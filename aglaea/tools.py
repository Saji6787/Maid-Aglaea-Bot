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
                    "INSERT INTO reminders_aglaea (user_id, remind_at, note) VALUES (%s, %s, %s)",
                    (user_id, dt.strftime("%Y-%m-%d %H:%M:%S"), note)
                )
        return json.dumps({"status": "success", "message": f"Reminder set for {remind_at}"})
    except Exception as e:
        if "(1146," in str(e):
            return json.dumps({"error": "Tabel 'reminders_aglaea' belum dibuat. Silakan buat tabelnya di database terlebih dahulu."})
        logging.error(f"add_reminder error: {e}")
        return json.dumps({"error": str(e)})

async def delete_reminder(pool, reminder_id: int) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM reminders_aglaea WHERE id = %s", (reminder_id,))
                if cur.rowcount > 0:
                    return json.dumps({"status": "success", "message": "Reminder deleted"})
                return json.dumps({"status": "error", "message": "Reminder not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def list_reminders(pool, user_id: int) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT id, remind_at, note FROM reminders_aglaea WHERE user_id = %s AND is_sent = 0 ORDER BY remind_at ASC LIMIT 10", (user_id,))
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

async def delete_expenses_by_date(pool, user_id: int, date: str) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM expenses WHERE user_id = %s AND date = %s", (user_id, date))
                count = cur.rowcount
                return json.dumps({"status": "success", "message": f"Berhasil menghapus {count} catatan pengeluaran untuk tanggal {date}."})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def add_multiple_expenses(pool, user_id: int, expenses: list) -> str:
    """Insert multiple expenses at once. expenses = [{amount, description, date}, ...]"""
    try:
        if not expenses:
            return json.dumps({"error": "Daftar pengeluaran kosong"})
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for item in expenses:
                    await cur.execute(
                        "INSERT INTO expenses (user_id, amount, description, date) VALUES (%s, %s, %s, %s)",
                        (user_id, float(item["amount"]), item["description"], item["date"])
                    )
        total = sum(float(i["amount"]) for i in expenses)
        return json.dumps({"status": "success", "message": f"Berhasil mencatat {len(expenses)} pengeluaran. Total: {total}"})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def get_monthly_expenses(pool, user_id: int, year: int, month: int) -> str:
    """Return all expenses for a given month, plus previous month's total for comparison."""
    try:
        import calendar
        from datetime import date as date_type
        first_day = date_type(year, month, 1).strftime("%Y-%m-%d")
        last_day = date_type(year, month, calendar.monthrange(year, month)[1]).strftime("%Y-%m-%d")

        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_first = date_type(prev_year, prev_month, 1).strftime("%Y-%m-%d")
        prev_last = date_type(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1]).strftime("%Y-%m-%d")

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Current month
                await cur.execute(
                    "SELECT id, amount, description, date FROM expenses WHERE user_id = %s AND date >= %s AND date <= %s ORDER BY date ASC",
                    (user_id, first_day, last_day)
                )
                rows = await cur.fetchall()

                # Previous month total
                await cur.execute(
                    "SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE user_id = %s AND date >= %s AND date <= %s",
                    (user_id, prev_first, prev_last)
                )
                prev_row = await cur.fetchone()
                prev_total = float(prev_row["total"]) if prev_row else 0.0

        expenses = []
        total = 0.0
        DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"]
        for row in rows:
            d = row["date"]
            day_name = DAYS_ID[d.weekday()]
            month_name = MONTHS_ID[d.month - 1]
            date_str = f"{day_name}, {d.day:02d} {month_name} {d.year}"
            amount = float(row["amount"])
            total += amount
            expenses.append({
                "date_str": date_str,
                "description": row["description"],
                "amount": amount
            })

        return json.dumps({
            "expenses": expenses,
            "total": total,
            "prev_total": prev_total,
            "year": year,
            "month": month
        })
    except Exception as e:
        return json.dumps({"error": str(e)})

async def add_task(pool, user_id: int, content: str, deadline_at: str = None, reminders: list = []) -> str:
    """
    Tambah tugas baru.
    reminders = ["2026-04-05 14:00:00", ...]
    """
    try:
        deadline_dt = datetime.strptime(deadline_at, "%Y-%m-%d %H:%M:%S") if deadline_at else None
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 1. Insert task
                await cur.execute(
                    "INSERT INTO tasks (user_id, content, deadline_at) VALUES (%s, %s, %s)",
                    (user_id, content, deadline_dt)
                )
                task_id = cur.lastrowid
                
                # 2. Insert associated reminders
                for r_time in reminders:
                    try:
                        r_dt = datetime.strptime(r_time, "%Y-%m-%d %H:%M:%S")
                        await cur.execute(
                            "INSERT INTO reminders_aglaea (user_id, task_id, remind_at, note) VALUES (%s, %s, %s, %s)",
                            (user_id, task_id, r_dt, f"🔔 Pengingat Tugas: {content}")
                        )
                    except Exception as re:
                        logging.warning(f"Failed to add reminder for task {task_id}: {re}")
                
        return json.dumps({
            "status": "success", 
            "message": f"Tugas '{content}' berhasil disimpan" + (f" dengan deadline {deadline_at}" if deadline_at else "") + f". Terjadwal {len(reminders)} pengingat.",
            "task_id": task_id
        })
    except Exception as e:
        logging.error(f"add_task error: {e}")
        return json.dumps({"error": str(e)})

async def list_tasks(pool, user_id: int) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, content, deadline_at FROM tasks WHERE user_id = %s AND status = 'pending' ORDER BY created_at ASC",
                    (user_id,)
                )
                rows = await cur.fetchall()
                if not rows:
                    return json.dumps({"tasks": []})
                
                tasks = []
                for row in rows:
                    tasks.append({
                        "id": row['id'],
                        "content": row['content'],
                        "deadline": row['deadline_at'].strftime("%Y-%m-%d %H:%M:%S") if row['deadline_at'] else None
                    })
                return json.dumps({"tasks": tasks})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def complete_task(pool, task_id: int) -> str:
    """Selesaikan tugas (hapus dari database beserta pengingatnya)."""
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Get content for message
                await cur.execute("SELECT content FROM tasks WHERE id = %s", (task_id,))
                row = await cur.fetchone()
                if not row:
                    return json.dumps({"status": "error", "message": "Tugas tidak ditemukan"})
                
                content = row[0]
                # Delete task (reminders will be deleted via CASCADE)
                await cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
                
                return json.dumps({"status": "success", "message": f"Tugas '{content}' telah diselesaikan dan dihapus."})
    except Exception as e:
        return json.dumps({"error": str(e)})
