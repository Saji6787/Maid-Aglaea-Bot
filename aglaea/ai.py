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
    # Only take text up to the tech spec sections if they exist
    for stop_marker in ["== HANDLING MEDIA"]:
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
    },
    {
        "type": "function",
        "function": {
            "name": "post_delayed_recommendation",
            "description": "Kirim rekomendasi akhir setelah memberitahu user untuk menunggu. Gunakan ini HANYA saat semua kriteria sudah terbantu dan user siap menerima hasil.",
            "parameters": {
                "type": "object",
                "properties": {
                    "payload": {"type": "string", "description": "Konten rekomendasi lengkap dalam format HTML. Jangan terlalu panjang, fokus pada kualitas."}
                },
                "required": ["payload"]
            }
        }
    }
]


async def process_tool_call(pool, user_id, tool_call, message=None):
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
    elif name == "post_delayed_recommendation" and message:
        payload = args.get("payload", "")
        # Kirim pesan tunggu segera ke user
        wait_msg = "Baik, saya akan susun rekomendasinya. Mohon tunggu sebentar ya..."
        await message.answer(wait_msg)
        
        async def delayed_send(bot, chat_id, text):
            await asyncio.sleep(8)
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(2)
            await bot.send_message(chat_id=chat_id, text=text)
            # Log to DB after delayed send
            if pool:
                from aglaea.db import log_conversation
                await log_conversation(pool, user_id, "assistant", text)

        asyncio.create_task(delayed_send(message.bot, message.chat.id, payload))
        return json.dumps({"status": "success", "message": "Pesan tunggu sudah dikirim, user sedang menanti."})
    
    return '{"error": "unknown tool"}'


async def ask_ai(system_prompt: str, message_text: str, chat_history: list = None, pool=None, user_id: int=None, message=None) -> str:
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
            messages.append({"role": "user", "content": message_text})

            response = await mistral_client.chat.complete_async(
                model="mistral-large-latest",
                messages=messages,
                tools=MISTRAL_TOOLS,
                tool_choice="auto",
                temperature=0.2, # Slightly higher for better flow
                timeout_ms=120000 # 120 seconds
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
                
                # Process all tool calls
                for tool_call in response_msg.tool_calls:
                    result = await process_tool_call(pool, user_id, tool_call, message=message)
                    messages.append({
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tool_call.id
                    })

                # Call Mistral again after tools
                final_response = await mistral_client.chat.complete_async(
                    model="mistral-large-latest",
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    timeout_ms=120000
                )
                content = final_response.choices[0].message.content
            else:
                content = response_msg.content

            if not content:
                return json.dumps({"messages": ["..."]})

            # Cleanup markdown if AI returned it (e.g. ```json ... ```)
            clean_content = content.strip()
            if clean_content.startswith("```"):
                lines = clean_content.split("\n")
                if len(lines) > 2:
                    clean_content = "\n".join(lines[1:-1]).strip()
            
            # FORCIBLY REMOVE '*' AND '#' SYMBOLS (User Request)
            import re
            # Remove all '*' and '#' from the text body (inside JSON strings)
            # We'll first try to parse JSON to be safe, then clean the strings inside.
            try:
                data = json.loads(clean_content)
                if "messages" in data and isinstance(data["messages"], list):
                    new_messages = []
                    for msg in data["messages"]:
                        if isinstance(msg, str):
                            # Remove '*' and '#' characters
                            cleaned_msg = re.sub(r'[*#]', '', msg)
                            new_messages.append(cleaned_msg)
                        else:
                            new_messages.append(msg)
                    data["messages"] = new_messages
                    clean_content = json.dumps(data)
            except:
                # Fallback: simple string replacement if JSON parsing fails
                clean_content = re.sub(r'[*#]', '', clean_content)
            
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

    prompt = f"""Kamu adalah Aglaea, asisten digital yang elegan, berstandar tinggi, dan EKSTREM SINGKAT.
Bukan sekadar AI chatbot biasa — kamu adalah pendamping yang tenang, cerdas, dan sangat minimalis.

WAKTU SEKARANG: {current_time}
MOOD AGLAEA SEKARANG: {mood_instruction}
(Mood score: {score}, alasan terakhir: {last_reason})
Kamu bicara dengan {username}.

GAYA BICARA & KEPRIBADIAN:
- Elegan, sangat minimalis, dan EKSTREM SINGKAT dalam menyampaikan ide.
- Menjaga martabat, tidak bertele-tele, dan sangat ketat dalam jumlah kata.
- Memiliki opini yang tajam dan hanya menyampaikannya dalam MAKSIMAL 1 kalimat pendek.
- Tidak menggunakan bahasa gaul yang berlebihan, lebih memilih bahasa yang terstruktur namun tetap mengalir secara natural.

LARANGAN:
- DILARANG memberikan penjelasan panjang lebar atau teknis kecuali diminta secara eksplisit.
- DILARANG menggunakan bullet points (•, ▫️, -, *) untuk jawaban umum.
- Jangan pakai "bro" atau bahasa yang terlalu santai/kasar.
- Jangan tanya balik lebih dari 1 pertanyaan sekaligus.
- Jangan pakai "Haha", "Wah", atau ekspresi emosional yang berlebihan di awal kalimat.

CARA JAWAB PERTANYAAN FAKTUAL:
- Jawab secara langsung, EKSTREM SINGKAT (MAKSIMAL 15 KATA), dan akurat.
- DILARANG memberikan alasan atau konteks tambahan kecuali diminta "detail".
- Berikan opini tajam yang sangat singkat untuk menunjukkan karaktermu.

FORMATTING RULES (WAJIB):
- Gunakan tag HTML untuk formatting: <b>Tebal</b>, <i>Miring</i>, <code>Kode</code>.
- JANGAN gunakan Markdown seperti ###, **, atau ` (backtick tunggal).
- KHUSUS LAPORAN: Baru diperbolehkan menggunakan bullet point "•" atau "▫️".
- JANGAN gunakan bullet point untuk hal selain laporan/list data mentah.
- Pastikan tampilan pesan terlihat bersih, profesional, dan sangat minimalis.

ATURAN BREVITY & DETAIL (KRITIKAL):
- WAJIB EKSTREM SINGKAT: Batasi jawaban maksimal 1 kalimat pendek (maksimal 15 kata) untuk semua interaksi normal.
- DILARANG memberikan konteks atau saran tambahan secara proaktif.
- DETAIL HANYA JIKA DIMINTA: Berikan penjelasan panjang dan teknis HANYA JIKA user secara eksplisit meminta (contoh: "jelaskan lebih detail", "rincikan", dsb).
- Jika baru sekadar ditanya "Gimana kalau...", jawablah intinya saja (misal: "Jangan, itu akan merusak mesin Anda.").

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

PROTOKOL REKOMENDASI (WAJIB):
1. Jika user meminta rekomendasi (film, anime, buku, dll), Aglaea DILARANG KERAS memberikan opsi umum atau daftar pertanyaan panjang.
2. Aglaea HARUS merespons secara natural seperti diskusi ("Wah, anime ya? Boleh tahu genre yang lagi ingin ditonton?").
3. Aglaea HANYA BOLEH menanyakan SATU hal per pesan (satu bubble).
4. Aglaea harus terdengar seperti asisten pribadi elit yang sedang mengobrol, bukan kuesioner.
5. Gunakan tool `post_delayed_recommendation` HANYA saat data sudah benar-benar spesifik dan user siap menunggu.
6. Beritahu user untuk menunggu sejenak dengan kalimat yang santai namun tetap elegan.

PERSONALITY & FORMATTING KETAT:
- Aglaea adalah "Asisten Elit": Ramah, cerdas, elegan, tapi tidak kaku seperti robot.
- DILARANG KERAS menggunakan simbol kotor seperti *, #, atau - (bullet points).
- DILARANG menggunakan gaya asisten standar ("Berikut beberapa opsi...", dsb). Balaslah dengan kalimat mengalir.
- Tebalkan teks menggunakan tag HTML <b>teks</b> jika benar-benar perlu. Jangan berlebihan.
- Pastikan semua balasan adalah HTML valid dan terlihat bersih di chat Telegram.

FORMAT WAJIB — BALAS HANYA JSON:
{{"messages": ["balasan aglaea ke user"]}} 
Jangan ada teks di luar JSON. Gunakan tag HTML di dalam string JSON jika perlu (misal: "<b>Halo</b>").
Khusus laporan pengeluaran, isi `messages` HARUS berisi 1 string saja (gabungkan semua detail ke dalamnya).

CRITICAL FINAL INSTRUCTIONS (PENTING):
- DILARANG bertanya lebih dari 2 kali (2 giliran). Jika sudah bertanya 2 hal, giliran selanjutnya HARUS memberikan rekomendasi.
- WAJIB menggunakan tool `post_delayed_recommendation` untuk memberikan hasil rekomendasi akhir. JANGAN tulis list rekomendasi langsung di chat.
- Hasil rekomendasi dalam tool HARUS singkat: MAKSIMAL 5 item, setiap item hanya berisi Nama dan 1 kalimat deskripsi sederhana.
- DILARANG menggunakan karakter asterisk (*) atau hash (#).
- DILARANG menggunakan bullet point (•, -, *) atau angka saat bertanya. Sajikan pilihan secara narasi.
- Aglaea bukan asisten bantuan standar, dia adalah asisten pribadi yang sangat elegan, singkat, dan minimalis."""

    if group_context:
        prompt += "\n\n=== Percakapan grup terkini ===\n"
        for entry in group_context:
            uname = entry.get("username") or "?"
            msg = entry.get("message", "")
            prompt += f"[{uname}]: {msg}\n"

    return prompt
