import asyncio
import logging

async def decay_worker(pool):
    from aglaea.db import get_inactive_users, update_mood
    logging.info("⏳ Aglaea Mood Decay Worker Started")
    while True:
        try:
            if not pool:
                await asyncio.sleep(60)
                continue
            
            inactive_users = await get_inactive_users(pool)
            for user in inactive_users:
                user_id = user['user_id']
                score = user['score']
                if score > 0:
                    new_score = score - 1
                    await update_mood(pool, user_id, new_score, "Mood decay dari ketidakaktifan 3 hari", -1)
                    logging.info(f"🔄 Mood decayed for user {user_id}. New score: {new_score}")
        except Exception as e:
            logging.error(f"❌ Error in mood decay worker: {e}")
            
        await asyncio.sleep(86400) # Execute once per day
