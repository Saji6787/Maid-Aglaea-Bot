import json
import asyncio
from aiogram import types

from aglaea.db import get_or_create_user, get_mood, update_mood, log_conversation, get_recent_conversations, get_group_context, get_user_id_by_username
from aglaea.mood import calculate_mood_change, calculate_new_score, get_tone_description
from aglaea.ai import ask_ai, generate_system_prompt


async def handle_aglaea_message(message: types.Message, pool, bot_username: str = ""):
    """
    Main Aglaea handler — called directly from bot.py.
    pool can be None; all DB calls are wrapped in try/except.
    """
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    first_name = message.from_user.first_name or username

    current_score = 0
    last_reason = "Normal"

    if pool:
        try:
            await get_or_create_user(pool, user_id, username, first_name)
            mood_data = await get_mood(pool, user_id)
            if mood_data:
                current_score = mood_data.get("score", 0)
                last_reason = mood_data.get("last_reason", "Normal")
        except Exception as e:
            import logging
            logging.warning(f"Aglaea DB (get mood): {e}")

    change, reason = calculate_mood_change(message.text, current_score)
    new_score = current_score
    if change != 0:
        new_score = calculate_new_score(current_score, change)
        if pool:
            try:
                await update_mood(pool, user_id, new_score, reason, change)
            except Exception as e:
                import logging
                logging.warning(f"Aglaea DB (update mood): {e}")
        last_reason = reason

    tone_desc = get_tone_description(new_score)

    # Strip @mention from the text before sending to AI
    text_for_ai = message.text
    if bot_username and f"@{bot_username}" in text_for_ai.lower():
        text_for_ai = text_for_ai.replace(f"@{bot_username}", "").replace(f"@{bot_username.lower()}", "").strip()
    if not text_for_ai:
        text_for_ai = "(tanpa pesan)"

    history = []
    if pool:
        try:
            # Note: logging user message is now done immediately in bot.py
            history = await get_recent_conversations(pool, user_id, limit=20)
        except Exception as e:
            import logging
            logging.warning(f"Aglaea DB (conversation): {e}")

    group_context = []
    if pool and message.chat.type != "private":
        try:
            group_context = await get_group_context(pool, message.chat.id, limit=20)
        except Exception as e:
            import logging
            logging.warning(f"Aglaea DB (get group context): {e}")

    prompt = generate_system_prompt(first_name, new_score, last_reason, tone_desc, group_context)

    # Continuous typing indicator loop
    async def typing_loop():
        try:
            while True:
                await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(typing_loop())
    
    try:
        raw = await ask_ai(prompt, text_for_ai, chat_history=history, pool=pool, user_id=user_id, message=message)
        import logging
        logging.info(f"🤖 [User {user_id}] AI Response: {raw[:100]}...")
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    is_expense_report = False
    try:
        data = json.loads(raw)
        messages = data.get("messages", [raw])
        send_to_username = data.get("send_to_username")
        send_message = data.get("send_message")
        is_expense_report = data.get("is_expense_report", False)
    except json.JSONDecodeError:
        import logging
        logging.warning(f"⚠️ Failed to parse AI JSON response: {raw[:100]}...")
        messages = [raw]
        send_to_username = None
        send_message = None

    if send_to_username and send_message and pool:
        import logging
        logging.info(f"Aglaea attempting to send PM to user: '{send_to_username}'")
        # Check if the target user exists
        target_id = await get_user_id_by_username(pool, send_to_username)
        if target_id:
            logging.info(f"Target user found: {target_id}")
            try:
                await message.bot.send_message(chat_id=target_id, text=send_message)
                logging.info("PM successfully sent.")
                # Log it in the target's conversation
                await log_conversation(pool, target_id, "assistant", send_message)
            except Exception as e:
                logging.warning(f"Failed to send to target: {e}")
                if "Forbidden" in str(e):
                     messages = [f"Mohon maaf, sepertinya @{send_to_username} belum memulai percakapan dengan saya atau saya telah diblokir. Saya memerlukan inisialisasi percakapan terlebih dahulu."]
                else:
                     messages = [f"Gagal mengirim pesan ke @{send_to_username}: {e}"]
        else:
            logging.info(f"Target user '{send_to_username}' NOT found in DB.")
            # Overwrite Aglaea's reply based on requirements
            messages = [f"Identitas @{send_to_username} tidak ditemukan dalam catatan saya. Mohon instruksikan beliau untuk menghubungi saya terlebih dahulu."]

    messages = [m for m in messages if m and str(m).strip()]

    # Check for monthly expense report action
    monthly_data = None
    try:
        data_check = json.loads(raw)
        if data_check.get("action") == "monthly_expense_report":
            monthly_data = data_check.get("monthly_data")
    except Exception:
        pass

    if monthly_data:
        await send_monthly_expense_page(message, monthly_data, page=0)
        if pool:
            try:
                await log_conversation(pool, user_id, "assistant", "[Laporan pengeluaran bulanan]")
            except Exception:
                pass
        return

    # Mood-based message limit:
    # - Expense report: no limit
    # - Mood netral/plus (>= 0): tidak ada batas
    # - Mood minus (< 0): maksimal 3, AI sudah diarahkan untuk jarang kirim >1
    if not is_expense_report and new_score < 0:
        messages = messages[:3]

    if not messages:
        messages = ["..."]

    reply_to = message.message_id if message.chat.type != "private" else None

    for i, msg in enumerate(messages):
        if i > 0:
            await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
            await asyncio.sleep(0.8)
        await message.answer(str(msg), reply_to_message_id=reply_to)

        if pool:
            try:
                await log_conversation(pool, user_id, "assistant", str(msg))
            except Exception:
                pass


PAGE_SIZE = 15
MONTHS_ID_FULL = ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
                  "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

async def send_monthly_expense_page(message_or_callback, monthly_data, page: int = 0):
    """Render a paginated monthly expense list with Back/Next inline buttons."""
    from aiogram import types as tg_types
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    import json

    if isinstance(monthly_data, str):
        try:
            monthly_data = json.loads(monthly_data)
        except Exception:
            return

    expenses = monthly_data.get("expenses", [])
    total = monthly_data.get("total", 0)
    prev_total = monthly_data.get("prev_total", 0)
    year = monthly_data.get("year", "")
    month = monthly_data.get("month", "")
    month_name = MONTHS_ID_FULL[month - 1] if month else ""

    total_pages = max(1, (len(expenses) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    items = expenses[start:start + PAGE_SIZE]

    lines = [f"[Pengeluaran {month_name} {year} — Hal. {page + 1}/{total_pages}]"]
    for i, item in enumerate(items, start=start + 1):
        amount = int(item["amount"]) if item["amount"] == int(item["amount"]) else item["amount"]
        lines.append(f"{i}. {item['date_str']} — Rp {amount:,}".replace(",", ".") + f" ({item['description']})")

    text = "\n".join(lines)

    # Pagination buttons
    buttons = []
    data_prefix = f"expense_page:{json.dumps({'d': monthly_data, 'uid': getattr(getattr(message_or_callback, 'from_user', None), 'id', 0)})}"
    if page > 0:
        buttons.append(InlineKeyboardButton(text="◀ Prev", callback_data=f"exp:{page - 1}:{year}:{month}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton(text="Next ▶", callback_data=f"exp:{page + 1}:{year}:{month}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None

    # Build summary message
    diff = total - prev_total
    if diff > 0:
        comparison = f"Pengeluaran bulan ini lebih besar Rp {int(diff):,} ketimbang bulan lalu."
    elif diff < 0:
        comparison = f"Pengeluaran bulan ini lebih kecil Rp {int(abs(diff)):,} dari bulan lalu."
    else:
        comparison = "Pengeluaran bulan ini sama dengan bulan lalu."
    comparison = comparison.replace(",", ".")

    summary = f"[Total {month_name} {year}: Rp {int(total):,}]\n{comparison}".replace(",", ".")

    if isinstance(message_or_callback, tg_types.CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=kb)
        await message_or_callback.answer()
        await message_or_callback.message.answer(summary)
    else:
        await message_or_callback.answer(text, reply_markup=kb)
        await asyncio.sleep(0.5)
        await message_or_callback.answer(summary)
