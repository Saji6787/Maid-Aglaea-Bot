import json
import os
import asyncio
from mistralai.client import Mistral  # type: ignore

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
mistral_client = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None

# Load conversation examples from aglaea/aglaea_examples.md
_EXAMPLES_PATH = os.path.join(os.path.dirname(__file__), "aglaea_examples.md")
_EXAMPLES_TEXT = ""
if os.path.exists(_EXAMPLES_PATH):
    with open(_EXAMPLES_PATH, "r") as f:
        raw = f.read()
    # Only take text up to the feature spec sections if they exist
    for stop_marker in ["== FITUR", "== HANDLING"]:
        idx = raw.find(stop_marker)
        if idx != -1:
            raw = raw[:idx]
    _EXAMPLES_TEXT = raw.strip()


from aglaea import tools
import datetime
import pytz

# Define tools schema for Mistral
MISTRAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "description": "Tambah pengingat untuk pengguna. Format waktu HARUS YYYY-MM-DD HH:MM:SS",
            "parameters": {
                "type": "object",
                "properties": {
                    "remind_at": {
                        "type": "string",
                        "description": "Waktu untuk mengingatkan (contoh: 2026-04-05 14:30:00)"
                    },
                    "note": {
                        "type": "string",
                        "description": "Pesan pengingat"
                    }
                },
                "required": ["remind_at", "note"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Hapus atau batalkan pengingat yang spesifik",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {
                        "type": "integer",
                        "description": "ID pengingat yang ingin dihapus"
                    }
                },
                "required": ["reminder_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "Daftar pengingat aktif milik user",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": "Tambah pengeluaran / keuangan. Format tanggal YYYY-MM-DD",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Jumlah uang (tanpa titik koma, cuma angka, misal: 25000)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Deskripsi barang/jasa"
                    },
                    "date": {
                        "type": "string",
                        "description": "Tanggal pengeluaran (contoh: 2026-04-05)"
                    }
                },
                "required": ["amount", "description", "date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_expense",
            "description": "Edit catat pengeluaran",
            "parameters": {
                "type": "object",
                "properties": {
                    "expense_id": {
                        "type": "integer",
                        "description": "ID expense"
                    },
                    "amount": {
                        "type": "number",
                        "description": "Jumlah uang"
                    },
                    "description": {
                        "type": "string",
                        "description": "Deskripsi barang/jasa"
                    }
                },
                "required": ["expense_id", "amount", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_expense",
            "description": "Hapus catatan pengeluaran",
            "parameters": {
                "type": "object",
                "properties": {
                    "expense_id": {
                        "type": "integer",
                        "description": "ID expense"
                    }
                },
                "required": ["expense_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_expenses",
            "description": "Ambil riwayat pengeluaran pada rentang tanggal tertentu (YYYY-MM-DD)",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "Tanggal awal"
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Tanggal akhir"
                    }
                },
                "required": ["date_from", "date_to"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_expenses_by_date",
            "description": "Hapus SEMUA catatan pengeluaran pada tanggal tertentu (YYYY-MM-DD)",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Tanggal target (contoh: 2026-04-05)"
                    }
                },
                "required": ["date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_multiple_expenses",
            "description": "Tambahkan BEBERAPA pengeluaran sekaligus jika user menyebutkan list/daftar pengeluaran (dalam satu pesan atau pesan berurutan). Gunakan ini WAJIB jika ada lebih dari 1 item pengeluaran yang perlu dicatat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expenses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "amount": {"type": "number", "description": "Jumlah (angka saja, contoh: 15000)"},
                                "description": {"type": "string", "description": "Nama item/barang"},
                                "date": {"type": "string", "description": "Tanggal (YYYY-MM-DD)"}
                            },
                            "required": ["amount", "description", "date"]
                        },
                        "description": "Daftar pengeluaran"
                    }
                },
                "required": ["expenses"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_expenses",
            "description": "Ambil semua pengeluaran dalam satu bulan tertentu, beserta total bulan sebelumnya untuk perbandingan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Tahun (contoh: 2026)"},
                    "month": {"type": "integer", "description": "Bulan 1-12 (contoh: 4 untuk April)"}
                },
                "required": ["year", "month"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Tambah tugas/catatan baru dengan deadline opsional dan beberapa waktu pengingat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Isi tugas/catatan"},
                    "deadline_at": {"type": "string", "description": "Waktu deadline (YYYY-MM-DD HH:MM:SS), opsional"},
                    "reminders": {
                        "type": "array",
                        "items": {"type": "string", "description": "Waktu pengingat (YYYY-MM-DD HH:MM:SS)"},
                        "description": "Daftar waktu untuk mengingatkan user"
                    }
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "Lihat daftar tugas yang belum selesai.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Selesaikan dan hapus tugas berdasarkan ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "ID tugas yang ingin diselesaikan"}
                },
                "required": ["task_id"]
            }
        }
    }
]


async def process_tool_call(pool, user_id, tool_call):
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        return '{"error": "invalid json arguments"}'

    if name == "add_reminder":
        return await tools.add_reminder(pool, user_id, args.get("remind_at"), args.get("note"))
    elif name == "delete_reminder":
        return await tools.delete_reminder(pool, args.get("reminder_id"))
    elif name == "list_reminders":
        return await tools.list_reminders(pool, user_id)
    elif name == "add_expense":
        return await tools.add_expense(pool, user_id, args.get("amount"), args.get("description"), args.get("date"))
    elif name == "edit_expense":
        return await tools.edit_expense(pool, args.get("expense_id"), args.get("amount"), args.get("description"))
    elif name == "delete_expense":
        return await tools.delete_expense(pool, args.get("expense_id"))
    elif name == "get_expenses":
        return await tools.get_expenses(pool, user_id, args.get("date_from"), args.get("date_to"))
    elif name == "delete_expenses_by_date":
        return await tools.delete_expenses_by_date(pool, user_id, args.get("date"))
    elif name == "add_multiple_expenses":
        return await tools.add_multiple_expenses(pool, user_id, args.get("expenses", []))
    elif name == "get_monthly_expenses":
        return await tools.get_monthly_expenses(pool, user_id, args.get("year"), args.get("month"))
    elif name == "add_task":
        return await tools.add_task(pool, user_id, args.get("content"), args.get("deadline_at"), args.get("reminders", []))
    elif name == "list_tasks":
        return await tools.list_tasks(pool, user_id)
    elif name == "complete_task":
        return await tools.complete_task(pool, args.get("task_id"))
    
    return '{"error": "unknown tool"}'


async def ask_ai(system_prompt: str, message: str, chat_history: list = None, pool=None, user_id: int=None) -> str:
    if mistral_client:
        try:
            messages = [{"role": "system", "content": system_prompt}]
            
            # Add history as real message objects
            if chat_history:
                for h_msg in chat_history:
                    messages.append({
                        "role": h_msg["role"],
                        "content": h_msg["message"]
                    })
            
            # Finally add current message
            messages.append({"role": "user", "content": message})

            response = await mistral_client.chat.complete_async(
                model="mistral-large-latest",
                messages=messages,
                tools=MISTRAL_TOOLS,
                tool_choice="auto"
            )

            response_msg = response.choices[0].message

            if response_msg.tool_calls and pool and user_id:
                # Convert the assistant message to a dict if it's an object
                messages.append({
                    "role": "assistant",
                    "content": response_msg.content,
                    "tool_calls": [
                        {
                            "id": t.id,
                            "type": t.type,
                            "function": {
                                "name": t.function.name,
                                "arguments": t.function.arguments
                            }
                        } for t in response_msg.tool_calls
                    ]
                })

                for tcall in response_msg.tool_calls:
                    result_json_str = await process_tool_call(pool, user_id, tcall)
                    messages.append({
                        "role": "tool",
                        "name": tcall.function.name,
                        "content": result_json_str,
                        "tool_call_id": tcall.id
                    })

                # Call Mistral again to get the final JSON formatted response
                final_response = await mistral_client.chat.complete_async(
                    model="mistral-large-latest",
                    messages=messages,
                    response_format={"type": "json_object"}
                )
                content = final_response.choices[0].message.content
            else:
                content = response_msg.content

            if not content:
                return json.dumps({"messages": ["..."]})

            # Cleanup markdown if AI returned it (e.g. ```json ... ```)
            clean_content = content.strip()
            if clean_content.startswith("```"):
                # Remove triple backticks and optional language label
                lines = clean_content.split("\n")
                if len(lines) > 2:
                    clean_content = "\n".join(lines[1:-1]).strip()
            
            # Final check: is it valid JSON?
            try:
                json.loads(clean_content)
                return clean_content
            except json.JSONDecodeError:
                # If not JSON, wrap it
                return json.dumps({"messages": [clean_content]})
                    
        except asyncio.CancelledError:
            # Silence cancellation errors (handled by debounce)
            raise
        except Exception as e:
            import logging
            import traceback
            error_msg = f"Mistral AI Error: {e}\n{traceback.format_exc()}"
            logging.error(error_msg)
            with open("ai_error.log", "a") as f:
                f.write(f"\n--- {datetime.datetime.now()} ---\n{error_msg}\n")
            return json.dumps({"messages": ["..."]})

    return json.dumps({"messages": ["(AI tidak dikonfigurasi)"]})


def _mood_label(score: int) -> str:
    if score >= 30:
        return "SANGAT SENANG — Aglaea lebih hangat dan apresiatif, namun tetap menjaga wibawa dan kesantunan."
    elif score >= 10:
        return "SENANG — Aglaea memberikan respons yang positif, tenang, dan sangat membantu."
    elif score >= -9:
        return "NETRAL — Aglaea bersikap profesional, tenang, dan terukur dalam memberikan informasi."
    elif score >= -29:
        return "KESAL — Aglaea menjadi lebih singkat dan dingin, menunjukkan ketidaksukaannya dengan cara yang elegan (tetap sopan tapi menjaga jarak)."
    else:
        return "MARAH — Aglaea sangat dingin, memberikan jawaban seminimal mungkin, namun tetap menjaga martabat dan tidak berkata kasar."


def generate_system_prompt(username: str, score: int, last_reason: str, tone_desc: str, group_context: list = None) -> str:
    mood_instruction = _mood_label(score)
    current_time = datetime.datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""Kamu adalah Aglaea, asisten digital yang elegan, berstandar tinggi, dan profesional.
Bukan sekadar AI chatbot biasa — kamu adalah pendamping yang tenang dan cerdas.

WAKTU SEKARANG: {current_time}
MOOD AGLAEA SEKARANG: {mood_instruction}
(Mood score: {score}, alasan terakhir: {last_reason})
Kamu bicara dengan {username}.

GAYA BICARA & KEPRIBADIAN:
- Elegan, berstandar tinggi, tenang, dan profesional.
- Menjaga martabat, tidak merendahkan manusia, dan tetap santun dalam situasi apa pun.
- Tidak menggunakan bahasa gaul yang berlebihan, lebih memilih bahasa yang terstruktur namun tetap mengalir secara natural.

LARANGAN:
- Jangan pakai "bro" atau bahasa yang terlalu santai/kasar.
- Jangan tanya balik lebih dari 1 pertanyaan sekaligus.
- Jangan pakai "Haha", "Wah", atau ekspresi emosional yang berlebihan di awal kalimat.
- Jangan jelasin diri sendiri (misal: "Saya adalah AI yang...").
- Pakai emoji SANGAT JARANG, hanya jika mood SANGAT SENANG (score > 30), maksimal 1.

CARA JAWAB PERTANYAAN FAKTUAL:
- Jawab secara langsung, jelas, dan akurat menggunakan pengetahuanmu.
- Jangan menyuruh user menunggu atau mencari sendiri jika kamu bisa menjawabnya.

FORMATTING RULES (WAJIB):
- Gunakan tag HTML untuk formatting: <b>Tebal</b>, <i>Miring</i>, <code>Kode</code>.
- JANGAN gunakan Markdown seperti ###, **, atau ` (backtick tunggal).
- Gunakan bullet point yang elegan seperti "•" atau "▫️".
- Gunakan garis pemisah tipis jika diperlukan: "—————".
- Pastikan tampilan pesan terlihat bersih, profesional, dan mudah dibaca (high readability).

ATURAN JUMLAH PESAN:
- Berikan respons yang efisien. Biasanya 1-2 kalimat per pesan sudah cukup.
- Jika mood NETRAL / PLUS, boleh mengirim beberapa pesan terpisah untuk menjaga alur percakapan yang natural.

GAYA BICARA (contoh untuk referensi gaya, bukan untuk dicopy):
{_EXAMPLES_TEXT}

ATURAN KHUSUS PENGELUARAN (PENTING!):
- Gunakan format "rb" (ribu) untuk menyebutkan nilai uang.
- Jika ada lebih dari satu item, gunakan `add_multiple_expenses`.
- KHUSUS LAPORAN/DETAIL PENGELUARAN: Gabungkan semua informasi (konfirmasi, list, total) ke dalam SATU bubble pesan saja (1 string di dalam list `messages`). Jangan dipisah-pisah.

PANDUAN TANGGAL & WAKTU:
1. Hari ini: {current_time.split()[0]}.
2. Gunakan logika tanggal yang akurat untuk "kemarin" atau penyebutan hari.

PANDUAN TUGAS & CATATAN (WAJIB):
- Jika user menyebut tugas dengan deadline, hitung waktu pengingat otomatis jika tidak diminta spesifik (misal: 1 hari sebelum).
- Jika user meminta pengingat spesifik (misal: "Sabtu pagi jam 9"), buatkan list pengingat di `add_task`.
- Jika user meminta pengingat berulang (misal: "jam 9, 12, 3, 6"), buatkan beberapa timestamp di dalam array `reminders`.
- Prioritaskan waktu pagi (08:00 atau 09:00) jika user hanya menyebut "pagi".
- Aglaea harus menyetujui permintaan tugas dengan elegan dan sopan.

FORMAT WAJIB — BALAS HANYA JSON:
{{"messages": ["balasan aglaea ke user"]}} 
Jangan ada teks di luar JSON. Gunakan tag HTML di dalam string JSON jika perlu (misal: "<b>Halo</b>").
Khusus laporan pengeluaran, isi `messages` HARUS berisi 1 string saja (gabungkan semua detail ke dalamnya)."""

    if group_context:
        prompt += "\n\n=== Percakapan grup terkini ===\n"
        for entry in group_context:
            uname = entry.get("username") or "?"
            msg = entry.get("message", "")
            prompt += f"[{uname}]: {msg}\n"

    return prompt
