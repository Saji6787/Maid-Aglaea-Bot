import json
from datetime import datetime
import aiomysql
import logging

async def add_reminder(pool, user_id: int, remind_at: str, note: str) -> str:
    try:
        dt = datetime.strptime(remind_at, "%Y-%m-%d %H:%M:%S")
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO reminders_kira (user_id, remind_at, note) VALUES (%s, %s, %s)",
                    (user_id, dt.strftime("%Y-%m-%d %H:%M:%S"), note)
                )
        return json.dumps({"status": "success", "message": f"Reminder set for {remind_at}"})
    except Exception as e:
        if "(1146," in str(e):
            return json.dumps({"error": "Tabel 'reminders_kira' belum dibuat. Silakan buat tabelnya di database terlebih dahulu."})
        logging.error(f"add_reminder error: {e}")
        return json.dumps({"error": str(e)})

async def delete_reminder(pool, reminder_id: int) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM reminders_kira WHERE id = %s", (reminder_id,))
                if cur.rowcount > 0:
                    return json.dumps({"status": "success", "message": "Reminder deleted"})
                return json.dumps({"status": "error", "message": "Reminder not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def list_reminders(pool, user_id: int) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT id, remind_at, note FROM reminders_kira WHERE user_id = %s AND is_sent = 0 ORDER BY remind_at ASC LIMIT 10", (user_id,))
                rows = await cur.fetchall()
                if not rows:
                    return json.dumps({"reminders": []})
                # Convert datetime to string for JSON serialization
                reminders = []
                for row in rows:
                    reminders.append({
                        "id": row['id'],
                        "remind_at": row['remind_at'].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row['remind_at'], 'strftime') else str(row['remind_at']),
                        "note": row['note']
                    })
                return json.dumps({"reminders": reminders})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def add_expense(pool, user_id: int, amount: float, description: str, date: str) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO expenses (user_id, amount, description, date) VALUES (%s, %s, %s, %s)",
                    (user_id, amount, description, date)
                )
        return json.dumps({"status": "success", "message": "Expense added"})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def edit_expense(pool, expense_id: int, amount: float, description: str) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE expenses SET amount = %s, description = %s WHERE id = %s",
                    (amount, description, expense_id)
                )
                if cur.rowcount > 0:
                    return json.dumps({"status": "success", "message": "Expense updated"})
                return json.dumps({"status": "error", "message": "Expense not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def delete_expense(pool, expense_id: int) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
                if cur.rowcount > 0:
                    return json.dumps({"status": "success", "message": "Expense deleted"})
                return json.dumps({"status": "error", "message": "Expense not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def get_expenses(pool, user_id: int, date_from: str, date_to: str) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, amount, description, date FROM expenses WHERE user_id = %s AND date >= %s AND date <= %s ORDER BY date ASC",
                    (user_id, date_from, date_to)
                )
                rows = await cur.fetchall()
                if not rows:
                    return json.dumps({"expenses": []})
                expenses = []
                for row in rows:
                    expenses.append({
                        "id": row['id'],
                        "amount": float(row['amount']),
                        "description": row['description'],
                        "date": row['date'].strftime("%Y-%m-%d") if hasattr(row['date'], 'strftime') else str(row['date'])
                    })
                return json.dumps({"expenses": expenses})
    except Exception as e:
        return json.dumps({"error": str(e)})
