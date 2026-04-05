import os
import aiomysql

async def setup_db(pool):
    """Run schema.sql to ensure tables exist."""
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    if not os.path.exists(schema_path):
        return
        
    with open(schema_path, 'r') as f:
        sql = f.read()
        
    statements = [s.strip() for s in sql.split(';') if s.strip()]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for statement in statements:
                await cur.execute(statement)

async def get_or_create_user(pool, user_id: int, username: str, first_name: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Check user
            await cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            user = await cur.fetchone()
            
            if not user:
                await cur.execute(
                    "INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s)",
                    (user_id, username, first_name)
                )
                await cur.execute(
                    "INSERT INTO mood (user_id, score, last_reason) VALUES (%s, 0, 'New user')",
                    (user_id,)
                )

async def get_user_id_by_username(pool, name_or_username: str):
    """"Get a user's ID by their username or first_name (case insensitive)."""
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            clean_name = name_or_username[1:] if name_or_username.startswith('@') else name_or_username
            
            # 1. Try username
            await cur.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(%s)", (clean_name,))
            res = await cur.fetchone()
            if res:
                return res['id']
                
            # 2. Try first_name
            await cur.execute("SELECT id FROM users WHERE LOWER(first_name) = LOWER(%s)", (clean_name,))
            res = await cur.fetchone()
            if res:
                return res['id']
                
            return None

async def get_mood(pool, user_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT score, last_reason, updated_at FROM mood WHERE user_id = %s", (user_id,))
            return await cur.fetchone()

async def update_mood(pool, user_id: int, new_score: int, reason: str, score_change: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE mood SET score = %s, last_reason = %s WHERE user_id = %s",
                (new_score, reason, user_id)
            )
            await cur.execute(
                "INSERT INTO mood_log (user_id, score_change, reason) VALUES (%s, %s, %s)",
                (user_id, score_change, reason)
            )

async def get_inactive_users(pool):
    """Get users with score > 0 who haven't been active for 3+ days."""
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT user_id, score FROM mood WHERE score > 0 AND updated_at < DATE_SUB(NOW(), INTERVAL 3 DAY)"
            )
            return await cur.fetchall()

async def log_conversation(pool, user_id: int, role: str, message: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO conversations (user_id, role, message) VALUES (%s, %s, %s)",
                (user_id, role, message)
            )

async def get_recent_conversations(pool, user_id: int, limit: int = 10):
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT role, message FROM conversations WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            results = await cur.fetchall()
            return list(reversed(results))  # Return in chronological order

async def save_group_message(pool, group_id: int, user_id: int, username: str, message: str):
    """Save a group message and prune old ones beyond 100 per group."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_conversations (group_id, user_id, username, message) VALUES (%s, %s, %s, %s)",
                (group_id, user_id, username, message)
            )
            # Keep only last 100 messages per group
            await cur.execute(
                """DELETE FROM group_conversations
                   WHERE group_id = %s AND id NOT IN (
                       SELECT id FROM (
                           SELECT id FROM group_conversations
                           WHERE group_id = %s ORDER BY created_at DESC LIMIT 100
                       ) AS sub
                   )""",
                (group_id, group_id)
            )

async def get_group_context(pool, group_id: int, limit: int = 20):
    """Get the last N messages from a group in chronological order."""
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT username, message FROM group_conversations
                   WHERE group_id = %s ORDER BY created_at DESC LIMIT %s""",
                (group_id, limit)
            )
            results = await cur.fetchall()
            return list(reversed(results))

