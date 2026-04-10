import json
import os
import asyncio
from mistralai.client import Mistral  # type: ignore

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
mistral_client = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None

# Load conversation examples from aglaea/aglaea_examples.md
_EXAMPLES_PATH = os.path.join(os.path.dirname(__file__), "aglaea_examples.md")
_PERSONA_DIR = os.path.join(os.path.dirname(__file__), "persona")
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
            "name": "convert_currency",
            "description": "Konversi mata uang menggunakan real-time API. Gunakan ini jika user ingin tahu nilai tukar uang. Contoh: '100rb rupiah ke dollar'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount_str": {
                        "type": "string",
                        "description": "Jumlah uang (contoh: '100rb', '500.000', '1 juta')"
                    },
                    "from_currency": {
                        "type": "string",
                        "description": "Mata uang asal (contoh: 'rupiah', 'USD', 'IDR')"
                    },
                    "to_currency": {
                        "type": "string",
                        "description": "Mata uang tujuan (contoh: 'dollar', 'EUR', 'JPY')"
                    }
                },
                "required": ["amount_str", "from_currency", "to_currency"]
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
    elif name == "convert_currency" and message:
        amount_str = args.get("amount_str")
        from_curr_name = args.get("from_currency")
        to_curr_name = args.get("to_currency")
        
        # Kirim pesan tunggu segera
        await message.answer("Mohon tunggu sebentar...")
        
        from aglaea.currency import parse_amount, get_iso_code, fetch_currency_data, format_currency
        
        amount = parse_amount(amount_str)
        from_iso = get_iso_code(from_curr_name) or from_curr_name.upper()
        to_iso = get_iso_code(to_curr_name) or to_curr_name.upper()
        
        try:
            data, err = await fetch_currency_data(amount, from_iso, to_iso)
            if err:
                return json.dumps({"error": err})
            
            res_text = (
                f"💰 <b>Konversi Mata Uang</b>\n"
                f"💵 {format_currency(amount, from_iso)} ➔ <b>{format_currency(data['result'], to_iso)}</b>\n"
                f"📊 Rate: 1 {from_iso} = {data['rate']:.4f} {to_iso}\n"
                f"📈 Trend: {data['trend']}\n"
                f"📅 Data per: {data['date']}"
            )
            await message.answer(res_text)
            return json.dumps({"status": "success", "message": "Konversi berhasil ditampilkan ke user."})
        except Exception as e:
            return json.dumps({"error": str(e)})
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


def generate_system_prompt(username: str, score: int, last_reason: str, tone_desc: str, group_context: list = None, persona_name: str = "aglaea") -> str:
    mood_instruction = _mood_label(score)
    current_time_obj = datetime.datetime.now(pytz.timezone("Asia/Jakarta"))
    current_time = current_time_obj.strftime("%Y-%m-%d %H:%M:%S")
    today = current_time_obj.strftime("%Y-%m-%d")

    # Load persona template
    persona_path = os.path.join(_PERSONA_DIR, f"{persona_name}.md")
    if os.path.exists(persona_path):
        with open(persona_path, "r") as f:
            template = f.read()
    else:
        # Fallback if persona file is missing
        template = "Kamu adalah Aglaea, asisten digital yang elegan.\nUser: {{username}}"

    # Format the template
    prompt = template.replace("{{username}}", username) \
                     .replace("{{score}}", str(score)) \
                     .replace("{{last_reason}}", last_reason) \
                     .replace("{{current_time}}", current_time) \
                     .replace("{{today}}", today) \
                     .replace("{{mood_instruction}}", mood_instruction) \
                     .replace("{{examples_text}}", _EXAMPLES_TEXT)

    if group_context:
        prompt += "\n\n=== Percakapan grup terkini ===\n"
        for entry in group_context:
            uname = entry.get("username") or "?"
            msg = entry.get("message", "")
            prompt += f"[{uname}]: {msg}\n"

    return prompt
