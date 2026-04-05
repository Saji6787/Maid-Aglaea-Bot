import json
import asyncio
from aiogram import types

from kira.db import get_or_create_user, get_mood, update_mood, log_conversation, get_recent_conversations, get_group_context, get_user_id_by_username
from kira.mood import calculate_mood_change, calculate_new_score, get_tone_description
from kira.ai import ask_ai, generate_system_prompt


async def handle_kira_message(message: types.Message, pool, bot_username: str = ""):
    """
    Main Kira handler — called directly from bot.py.
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
            logging.warning(f"Kira DB (get mood): {e}")

    change, reason = calculate_mood_change(message.text, current_score)
    new_score = current_score
    if change != 0:
        new_score = calculate_new_score(current_score, change)
        if pool:
            try:
                await update_mood(pool, user_id, new_score, reason, change)
            except Exception as e:
                import logging
                logging.warning(f"Kira DB (update mood): {e}")
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
            await log_conversation(pool, user_id, "user", text_for_ai)
            history = await get_recent_conversations(pool, user_id, limit=6)
        except Exception as e:
            import logging
            logging.warning(f"Kira DB (conversation): {e}")

    group_context = []
    if pool and message.chat.type != "private":
        try:
            group_context = await get_group_context(pool, message.chat.id, limit=20)
        except Exception as e:
            import logging
            logging.warning(f"Kira DB (get group context): {e}")

    prompt = generate_system_prompt(first_name, new_score, last_reason, tone_desc, history, group_context)

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    raw = await ask_ai(prompt, text_for_ai, pool=pool, user_id=user_id)

    try:
        data = json.loads(raw)
        messages = data.get("messages", [raw])
        send_to_username = data.get("send_to_username")
        send_message = data.get("send_message")
    except json.JSONDecodeError:
        messages = [raw]
        send_to_username = None
        send_message = None

    if send_to_username and send_message and pool:
        # Check if the target user exists
        target_id = await get_user_id_by_username(pool, send_to_username)
        if target_id:
            try:
                await message.bot.send_message(chat_id=target_id, text=send_message)
                # Log it in the target's conversation
                await log_conversation(pool, target_id, "assistant", send_message)
            except Exception as e:
                import logging
                logging.warning(f"Failed to send to target: {e}")
        else:
            # Overwrite Kira's reply based on requirements
            messages = [f"Itu si @{send_to_username} pc aku dulu. Programku blom jalan kalau belum dipc"]

    messages = [m for m in messages if m and str(m).strip()][:3]
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
