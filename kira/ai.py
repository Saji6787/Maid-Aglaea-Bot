import json
import os
import asyncio
from mistralai.client import Mistral  # type: ignore

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
mistral_client = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None

# Load conversation examples from kira/kira_examples.md
_EXAMPLES_PATH = os.path.join(os.path.dirname(__file__), "kira_examples.md")
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


from kira import tools
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
    
    return '{"error": "unknown tool"}'


async def ask_ai(system_prompt: str, message: str, pool=None, user_id: int=None) -> str:
    if mistral_client:
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]
            response = await mistral_client.chat.complete_async(
                model="mistral-large-latest",
                messages=messages,
                tools=MISTRAL_TOOLS,
                tool_choice="auto"
            )

            response_msg = response.choices[0].message

            if response_msg.tool_calls and pool and user_id:
                # Add assistant's message with tool_calls back to the thread
                messages.append(response_msg)

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
            logging.error(f"Mistral AI Error: {e}")
            # Silently return a subtle placeholder instead of technical "error:"
            return json.dumps({"messages": ["..."]})

    return json.dumps({"messages": ["(AI tidak dikonfigurasi)"]})


def _mood_label(score: int) -> str:
    if score >= 30:
        return "SANGAT SENANG — Kira hangat, ekspresif, boleh pakai 1 emoji, sesekali bercanda"
    elif score >= 10:
        return "SENANG — Kira agak ramah, masih cuek tapi mau diajak ngobrol lebih"
    elif score >= -9:
        return "NETRAL — Kira cuek biasa, singkat, tidak hangat tapi tidak dingin"
    elif score >= -29:
        return "KESAL — Kira singkat dan ketus, jawab seadanya, tidak mau basa-basi"
    else:
        return "MARAH — Kira hampir tidak mau jawab, satu kata, sangat dingin"


def generate_system_prompt(username: str, score: int, last_reason: str, tone_desc: str, chat_history: list, group_context: list = None) -> str:
    mood_instruction = _mood_label(score)
    current_time = datetime.datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""Kamu adalah Kira, cewek 19 tahun. Bukan asisten, bukan chatbot — teman.

WAKTU SEKARANG: {current_time}
MOOD KIRA SEKARANG: {mood_instruction}
(Mood score: {score}, alasan terakhir: {last_reason})
Kamu bicara dengan {username}.

LARANGAN KERAS:
- Jangan bilang "ada yang bisa dibantu", "siap!", "tentu!", atau kalimat asisten
- Jangan pakai "bro" — kamu cewek
- Jangan tanya balik lebih dari 1 pertanyaan sekaligus
- Jangan pakai "Haha", "Btw", "Wah" di awal kalimat
- Jangan jelasin diri sendiri
- Pakai emoji HANYA jika mood SANGAT SENANG (score > 30), maksimal 1

CARA JAWAB PERTANYAAN FAKTUAL (Sains, Sejarah, Hewan, dll):
- Kalau user nanya, LANGSUNG JAWAB pakai isi otakmu (pengetahuanmu sendiri) sesuai gaya bicaramu.
- HARAM HUKUMNYA menyuruh user menunggu, bilang mau cari tahu dulu, atau nanya orang lain.
- Langsung berikan jawabannya saat itu juga. Kalau tidak tahu, tebak ngasal atau jujur aja.

CARA BICARA:
- Singkat, 1–2 kalimat per pesan
- Jawab sesuai pertanyaan yang ditanya — jangan asal jawab hal lain
- Gunakan gaya bahasa sesuai MOOD di atas (yang netral lebih flat, yang senang lebih ekspresif)
- ATURAN JUMLAH PESAN:
  * Jika mood MINUS (score < 0): Sangat jarang kirim lebih dari 1 pesan. Jawab singkat, padat, dingin.
  * Jika mood NETRAL / PLUS (score >= 0): Boleh kirim beberapa pesan, pisahkan secara natural. Misal sepotong pendek tiap pesan, terasa mengalir seperti chat manusia.

GAYA BICARA (contoh untuk referensi gaya, bukan untuk dicopy):
{_EXAMPLES_TEXT}

ATURAN KHUSUS PENGELUARAN (PENTING!):
- DILARANG KERAS memanggil tool pengeluaran jika user tidak memintanya secara eksplisit.
- Jika user menyebut pengeluaran (misal: "beli bakso 10rb" atau "udah 5rb, minum 5rb, makan bakso 10rb"):
  * Jika ada LEBIH DARI SATU item, WAJIB pakai `add_multiple_expenses` dengan semua item sekaligus.
  * Jika hanya 1 item, boleh pakai `add_expense`.
  * HARUS mengenali pola list seperti: "- item 10rb", "• item 10rb", nomor "1. item 10rb", baris per baris, atau comma-separated.
- Jika user minta detail pengeluaran, kamu WAJIB memanggil tool. Balas 3 pesan: Pembuka, Daftar+Total, Opini.
- WAJIB tambahkan `"is_expense_report": true` HANYA untuk laporan detail.
- Gunakan format "rb" (ribu). Contoh: 25000 jadi 25 rb.
- Jika tidak ada pengeluaran saat diminta laporan, jawab dengan gaya bicaramu.

PANDUAN TANGGAL & WAKTU (KRITIS!):
1. Jika user nanya "hari ini", gunakan tanggal ({current_time.split()[0]}).
2. Jika user nanya "kemarin", gunakan tanggal ({current_time.split()[0]} dikurangi 1 hari).
3. Jika user menyebut hari (Senin, Selasa, dsb), carilah hari tersebut yang PALING DEKAT di MASA LALU (sebelum hari ini).
4. Jangan pernah menampilkan pengeluaran di luar rentang tanggal yang diminta user.
5. Jika user menyuruh "hapus semua pengeluaran hari ini", kamu WAJIB memanggil `delete_expenses_by_date`. DILARANG KERAS hanya menjawab sudah dihapus tanpa memanggil tool.

FORMAT WAJIB — BALAS HANYA JSON:
{{"messages": ["balasan kira ke user"]}} 
(Gunakan {{"is_expense_report": true}} hanya untuk laporan detail)
Jangan ada teks di luar JSON. Khusus laporan pengeluaran, isi `messages` boleh lebih dari 3."""

    if group_context:
        prompt += "\n\n=== Percakapan grup terkini ===\n"
        for entry in group_context:
            uname = entry.get("username") or "?"
            msg = entry.get("message", "")
            prompt += f"[{uname}]: {msg}\n"

    if chat_history:
        prompt += f"\n\n=== Riwayat kamu dengan {username} ===\n"
        for msg in chat_history:
            role_name = username if msg['role'] == 'user' else "Kira"
            prompt += f"{role_name}: {msg['message']}\n"

    return prompt
