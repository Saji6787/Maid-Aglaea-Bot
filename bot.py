import asyncio
import random
import re
import json
import logging
import os
import io
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz
import aiomysql
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from google import genai
from google.genai import types as genai_types
from mistralai.client import Mistral

# ================= KONFIGURASI & ENV =================
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
else:
    load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
DEFAULT_TZ = pytz.timezone("Asia/Jakarta")

if not TELEGRAM_TOKEN:
    print("❌ TELEGRAM_TOKEN belum terisi di .env")
    exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Inisialisasi Bot & Dispatcher (HANYA SEKALI!)
bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
mistral_client = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None

# Cache info bot agar tidak get_me terus menerus
bot_info_cache = {"id": None, "username": None}

# ================= MYSQL POOL =================
DB_CONFIG = {
    'host': os.getenv("MYSQL_HOST", "localhost"),
    'port': int(os.getenv("MYSQL_PORT", 3306)),
    'user': os.getenv("MYSQL_USER"),
    'password': os.getenv("MYSQL_PASSWORD"),
    'db': os.getenv("MYSQL_DB"),
    'charset': 'utf8mb4',
    'autocommit': True,
    'cursorclass': aiomysql.cursors.DictCursor
}
pool = None

async def init_db_pool():
    global pool
    try:
        pool = await aiomysql.create_pool(**DB_CONFIG, minsize=1, maxsize=5)
        logging.info("✅ MySQL Connection Pool berhasil dibuat")
    except Exception as e:
        logging.warning(f"⚠️ Gagal koneksi ke MySQL: {e}. Fitur Reminder dinonaktifkan sementara.")
        pool = None

async def close_db_pool():
    global pool
    if pool:
        try:
            pool.close()
            try:
                await pool.wait_closed()
                logging.info("🔒 MySQL Pool ditutup")
            except RuntimeError as e:
                if "bound to a different event loop" in str(e):
                    logging.warning("⚠️ MySQL Pool ditutup (event loop cleanup)")
                else:
                    raise
        except Exception as e:
            logging.error(f"❌ Error menutup pool: {e}")
        finally:
            pool = None

# ================= GAME LOBBY STATE =================
game_lobbies = {}  # chat_id -> {"players": [user_id], "game_type": "wordchain"}
active_games = {}  # chat_id -> GameSession
pending_aglaea_tasks = {}  # (chat_id, user_id) -> asyncio.Task

# ================= BACKGROUND WORKER =================
async def reminder_worker(bot: Bot):
    logging.info("⏰ Reminder Worker Dimulai...")
    while True:
        try:
            if not pool:
                await asyncio.sleep(60)
                continue

            now_utc = datetime.now(pytz.UTC)
            now_local = now_utc.astimezone(DEFAULT_TZ)
            current_date_str = now_local.strftime("%Y-%m-%d %H:%M:%S")

            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "SELECT r.id, r.user_id, r.note, t.deadline_at "
                        "FROM reminders_aglaea r "
                        "LEFT JOIN tasks t ON r.task_id = t.id "
                        "WHERE r.is_sent = 0 AND r.remind_at <= %s",
                        (current_date_str,)
                    )
                    rows = await cur.fetchall()

                    for row in rows:
                        try:
                            # New structured format (User Request)
                            reminder_text = (
                                "[ !!! ] <b>Pengingat</b> [ !!! ]\n"
                                f"{row['note']}\n"
                            )
                            
                            if row.get('deadline_at'):
                                deadline_dt = row['deadline_at']
                                # Handle naive datetime from MySQL (assume UTC)
                                if deadline_dt.tzinfo is None:
                                    deadline_dt = pytz.UTC.localize(deadline_dt)
                                deadline_local = deadline_dt.astimezone(DEFAULT_TZ)
                                deadline_str = deadline_local.strftime("%d %b %Y, %H:%M WIB")
                                reminder_text += f"Deadline: {deadline_str}\n"

                            natural_comments = [
                                "Tuan, jangan sampai lupa ya. Saya sudah catat ini sebelumnya.",
                                "Permisi tuan, sudah waktunya untuk hal ini dilakukan.",
                                "Sekadar pengingat buat tuan, jangan ditunda-tunda ya.",
                                "Tuan, catatan ini sudah waktunya. Mohon diperhatikan.",
                                "Jangan sampai kelewat ya tuan, nanti repot lho.",
                                "Saya hanya menjalankan tugas untuk mengingatkan tuan soal ini.",
                                "Sudah masuk jadwalnya nih tuan. Semangat ya!",
                                "Tuan, ini sudah waktunya. Jangan lupa diselesaikan ya.",
                                "Izin mengingatkan tuan, hal ini sudah harus dilakukan."
                            ]
                            comment = random.choice(natural_comments)
                            reminder_text += f"\n{comment}"

                            await bot.send_message(
                                chat_id=row['user_id'],
                                text=reminder_text
                            )
                            # Langsung hapus reminder setelah berhasil dikirim
                            await cur.execute("DELETE FROM reminders_aglaea WHERE id = %s", (row['id'],))
                        except Exception as e:
                            if "Forbidden" in str(e):
                                logging.warning(f"⚠️ User {row['user_id']} belum PC bot/memblokir. Reminder ID {row['id']} dibatalkan.")
                                await cur.execute("UPDATE reminders_aglaea SET is_sent = 2 WHERE id = %s", (row['id'],)) # 2 = Failed/Forbidden
                            else:
                                logging.error(f"❌ Error kirim reminder ke {row['user_id']}: {e}")
                    
                    # Cleanup reminder yang gagal dikirim (Forbidden) setelah 1 hari
                    await cur.execute("DELETE FROM reminders_aglaea WHERE is_sent = 2 AND created_at < NOW() - INTERVAL 1 DAY")
        except Exception as e:
            if "(1146," in str(e): # Table doesn't exist
                logging.warning("⚠️ Tabel reminders_aglaea belum dibuat. Worker standby...")
                await asyncio.sleep(300) # Sleep longer if table missing
            else:
                logging.error(f"❌ Worker error: {e}")
                await asyncio.sleep(60)
        
        await asyncio.sleep(60)


# ================= GEMINI AI CONFIG =================
AVAILABLE_MODELS = {
    #"image": {
        #"id": "imagen-3.0-generate-001",  # ✅ Model Imagen yang benar
        #"name": "🎨 Imagen 3 (Image)",
        #"desc": "Generate gambar dari teks",
        #"limits": "Berbagai limit tergantung tier",
        #"best_for": ["gambar", "foto", "ilustrasi", "art"]
    #},
    "flash_lite": {
        "id": "gemini-2.5-flash-lite",
        "name": "⚡ Flash Lite (Text)",
        "desc": "Cepat & efisien untuk chat biasa",
        "limits": "30 request/hari, 20 RPM",
        "best_for": ["chat", "Q&A", "terjemahan", "ringkasan"]
    },
    "flash": {
        "id": "gemini-2.5-flash",
        "name": "🧠 Flash (Text Advanced)",
        "desc": "Lebih pintar untuk task kompleks",
        "limits": "20 request/hari, 5 RPM",
        "best_for": ["analisis", "coding", "reasoning"]
    },
    "mistral_nemo": {
        "id": "open-mistral-nemo",
        "name": "🌊 Mistral NeMo",
        "desc": "Cepat dan tangguh",
        "limits": "Tergantung limit Mistral",
        "best_for": ["chat", "pertanyaan umum", "roleplay"]
    },
    "mistral_large": {
        "id": "mistral-large-latest",
        "name": "🌪️ Mistral Large",
        "desc": "Kuat untuk logika kompleks",
        "limits": "Tergantung limit Mistral",
        "best_for": ["coding", "analisis", "bahasa"]
    }
}

DEFAULT_MODEL = {"image": "image", "text": "mistral_large"}

class UserPreferences:
    def __init__(self):
        self._prefs = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: int, request_type: str = "text") -> str:
        async with self._lock:
            prefs = self._prefs.get(user_id, {})
            if prefs.get("auto_detect", True):
                return DEFAULT_MODEL.get(request_type, "flash_lite")
            return prefs.get("model", DEFAULT_MODEL.get(request_type, "flash_lite"))

    async def set(self, user_id: int, model_key: str):
        async with self._lock:
            if user_id not in self._prefs:
                self._prefs[user_id] = {}
            self._prefs[user_id]["model"] = model_key
            self._prefs[user_id]["auto_detect"] = False

    async def reset(self, user_id: int):
        async with self._lock:
            if user_id in self._prefs:
                self._prefs[user_id]["auto_detect"] = True

    async def get_info(self, user_id: int) -> dict:
        async with self._lock:
            prefs = self._prefs.get(user_id, {})
            is_auto = prefs.get("auto_detect", True)
            model_key = prefs.get("model", DEFAULT_MODEL["text"])
            return {"auto": is_auto, "model": AVAILABLE_MODELS.get(model_key, {}), "model_key": model_key}

user_prefs = UserPreferences()

class QuotaManager:
    def __init__(self, max_images_per_day=2):
        self.max_images_per_day = max_images_per_day
        self.image_count = 0
        self.last_reset_date = datetime.now().date()
        self.user_cooldowns = {}
        self._lock = asyncio.Lock()

    async def check_and_reset(self):
        today = datetime.now().date()
        if today > self.last_reset_date:
            async with self._lock:
                if today > self.last_reset_date:
                    self.image_count = 0
                    self.last_reset_date = today
                    logging.info("🔄 Daily quota reset")

    async def can_generate_image(self):
        await self.check_and_reset()
        return self.image_count < self.max_images_per_day

    async def increment_image_count(self):
        async with self._lock:
            self.image_count += 1
            return max(0, self.max_images_per_day - self.image_count)

    async def get_remaining_quota(self):
        await self.check_and_reset()
        return max(0, self.max_images_per_day - self.image_count)

    def add_user_cooldown(self, user_id, seconds=60):
        self.user_cooldowns[user_id] = datetime.now() + timedelta(seconds=seconds)

    def is_on_cooldown(self, user_id):
        if user_id not in self.user_cooldowns:
            return False
        if datetime.now() < self.user_cooldowns[user_id]:
            return True
        del self.user_cooldowns[user_id]
        return False

quota_manager = QuotaManager(max_images_per_day=2)

# ================= HELPER FUNCTIONS =================
def is_image_request(text):
    # Fitur generate gambar sedang dinonaktifkan
    return False  # Selalu return False

def get_model_keyboard(user_id: int, current_model: str = None) -> InlineKeyboardMarkup:
    keyboard = []
    
    # 1. Cek apakah model 'image' tersedia di AVAILABLE_MODELS
    if "image" in AVAILABLE_MODELS:
        img_model = AVAILABLE_MODELS["image"]
        keyboard.append([InlineKeyboardButton(
            text=f"{'✅ ' if current_model == 'image' else ''}{img_model['name']}",
            callback_data=f"set_model:image"
        )])

    # 2. Tambahkan tombol untuk model Text
    text_models = ["flash_lite", "flash", "mistral_nemo", "mistral_large"]
    for model_key in text_models:
        if model_key in AVAILABLE_MODELS:
            keyboard.append([InlineKeyboardButton(
                text=f"{'✅ ' if current_model == model_key else ''}{AVAILABLE_MODELS[model_key]['name']}",
                callback_data=f"set_model:{model_key}"
            )])

    # 3. Tombol Auto-Detect & Tutup
    keyboard.append([
        InlineKeyboardButton(text="🔄 Auto-Detect", callback_data="set_model:auto"),
        InlineKeyboardButton(text="❌ Tutup", callback_data="close_models")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_model_info_text(model_key: str) -> str:
    model = AVAILABLE_MODELS.get(model_key)
    if not model: return "Model tidak ditemukan."
    return f"<b>{model['name']}</b>\n\n📝 {model['desc']}\n📊 Limit: {model['limits']}\n🎯 Cocok untuk: {', '.join(model['best_for'])}"

async def generate_with_model(model_key: str, prompt: str, response_type: str = "text"):
    model_config = AVAILABLE_MODELS.get(model_key)
    if not model_config:
        raise ValueError(f"Model {model_key} tidak tersedia")
    
    if "mistral" in model_key or "mistral" in model_config["id"]:
        if not mistral_client:
            raise ValueError("MISTRAL_API_KEY belum dikonfigurasi di .env")
        response = await mistral_client.chat.complete_async(
            model=model_config["id"],
            messages=[{"role": "user", "content": f"Jawab dengan bahasa Indonesia yang santai, gaul, dan tidak baku sewajarnya teman chat. {prompt}"}]
        )
        return response.choices[0].message.content

    if response_type == "image":
        response = genai_client.models.generate_content(
            model=model_config["id"],
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_modalities=["IMAGE"])
        )
        return response
    else:
        response = genai_client.models.generate_content(
            model=model_config["id"],
            contents=f"Jawab dengan bahasa Indonesia yang santai, gaul, dan tidak baku sewajarnya teman chat. {prompt}",
            config=genai_types.GenerateContentConfig(max_output_tokens=1000, temperature=0.7)
        )
        return response.text

# ================= COMMAND HANDLERS =================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    bot_info = await bot.get_me()
    await message.reply(
        f"👋 <b>Halo! Saya {bot_info.first_name}.</b>\n\n"
        f"Saya adalah bot multi-fungsi yang dilengkapi AI Gemini dan Game.\n\n"
        f"Gunakan /pothelp untuk melihat daftar lengkap fitur saya! 🚀"
    )

@dp.message(Command("riwayat"))
async def cmd_riwayat(message: types.Message):
    if not pool:
        await message.reply("Database belum terkonfigurasi.")
        return
        
    user_id = message.from_user.id
    now_local = datetime.now(DEFAULT_TZ)
    today_str = now_local.strftime("%Y-%m-%d")

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT amount, description FROM expenses WHERE user_id = %s AND date = %s ORDER BY id ASC",
                (user_id, today_str)
            )
            rows = await cur.fetchall()

            if not rows:
                await message.reply("belum ada pengeluaran hari ini")
                return

            reply_text = "pengeluaran hari ini:\n"
            for row in rows:
                reply_text += f"{row['description']} — Rp{int(row['amount']):,}\n".replace(',', '.')
            
            await message.reply(reply_text.strip())

@dp.message(Command("convertmoney"))
async def cmd_convertmoney(message: types.Message):
    # Regex to parse: /convertmoney 500rb Rupiah to Dollar
    # Match: (amount) (from_curr) to (to_curr)
    match = re.search(r'/convertmoney\s+([\d.,]+[a-z]*)\s+([a-z\s]+)\s+to\s+([a-z\s]+)', message.text, re.IGNORECASE)
    if not match:
        await message.reply("Format salah. Contoh: <code>/convertmoney 100rb Rupiah to Dollar</code>")
        return

    amount_str = match.group(1)
    from_curr_name = match.group(2).strip()
    to_curr_name = match.group(3).strip()
    
    await message.reply("Mohon tunggu sebentar...")
    
    from aglaea.currency import parse_amount, get_iso_code, fetch_currency_data, format_currency
    
    amount = parse_amount(amount_str)
    from_iso = get_iso_code(from_curr_name) or from_curr_name.upper()
    to_iso = get_iso_code(to_curr_name) or to_curr_name.upper()
    
    try:
        data, err = await fetch_currency_data(amount, from_iso, to_iso)
        if err:
            await message.answer(f"❌ Error: {err}")
            return
        
        res_text = (
            f"💰 <b>Konversi Mata Uang</b>\n"
            f"💵 {format_currency(amount, from_iso)} ➔ <b>{format_currency(data['result'], to_iso)}</b>\n"
            f"📊 Rate: 1 {from_iso} = {data['rate']:.4f} {to_iso}\n"
            f"📈 Trend: {data['trend']}\n"
            f"📅 Data per: {data['date']}"
        )
        await message.answer(res_text)
    except Exception as e:
        await message.answer(f"❌ Terjadi kesalahan: {str(e)}")

@dp.message(Command("features", "help", "fitur"))
async def cmd_features(message: types.Message):
    bot_info = await bot.get_me()
    username = bot_info.username

    features_text = (
        f"🤖 <b>Daftar Fitur Lengkap Bot @{username}</b>\n\n"
        
        f"🧠 <b>1. AI & Chat (Aglaea)</b>\n"
        f"• Ngobrol: Langsung chat atau reply pesan Aglaea\n"
        f"• Mention: <code>@{username} [prompt]</code> (Grup)\n"
        f"• <code>/models</code> — Pilih model AI\n"
        f"• 🔄 Auto-Detect — Deteksi model otomatis\n\n"
        
        f"⏰ <b>2. AI Reminder</b>\n"
        f"• Cara pakai: <i>'Agy nanti ingetin jam 3 buat kuliah'</i>\n"
        f"• Daftar/Hapus: <i>'lihat jadwal gue'</i> atau <i>'batalin pengingat mandi'</i>\n"
        f"• ⚡ AI otomatis konversi waktu relatif\n\n"

        f"💸 <b>3. Catat Pengeluaran</b>\n"
        f"• Cara pakai: <i>'Agy catat beli bensin 25rb'</i>\n"
        f"• Riwayat: <code>/riwayat</code> atau <i>'kemarin jajan apa saja'</i>\n\n"

        f"📝 <b>4. Catatan & Deadline (Tasks)</b>\n"
        f"• Tambah: <i>'Agy, tugas matematika deadline Senin. Ingetin hari Sabtu jam 9 pagi ya.'</i>\n"
        f"• Flexible: <i>'Ingetin jam 9, 12, 3, dan 6 sore.'</i>\n"
        f"• Kelola: <i>'Daftar tugas'</i> & <i>'Selesaikan nomor 1'</i>\n\n"
        
        f"🎮 <b>5. Game: Sambung Kata</b>\n"
        f"• /games — Mulai permainan (Max 2 Player)\n"
        f"• ❤️ Sistem HP & Timer 45 detik\n"
        f"• 📜 AI Narrator & Lore unik tiap kata\n\n"
        
        f"💰 <b>6. Cek Kurs & Mata Uang</b>\n"
        f"• Cara pakai: <i>'Agy, 100rb rupiah ke dollar berapa?'</i>\n"
        f"• Command: <code>/convertmoney 50rb IDR to USD</code>\n"
        f"• 📈 Informasi kenaikan/penurunan harga\n\n"
        
        f"💡 <b>Panduan Penggunaan</b>\n"
        f"• Di grup: Wajib mention bot <code>@{username}</code>\n"
        f"• Di private chat: Langsung ketik prompt/command\n\n"
        
        f"🔧 <i>Powered by Mistral AI Function Calling & MariaDB</i>"
    )
    await message.reply(features_text)

@dp.message(Command("models", "model", "settings"))
async def cmd_models(message: types.Message):
    user_id = message.from_user.id
    prefs = await user_prefs.get_info(user_id)
    current = prefs["model_key"] if not prefs["auto"] else "auto"
    text = (
        "⚙️ <b>[Pilih Model AI]</b>\n\n"
        f"🔄 Status: <b>{'Auto-Detect' if prefs['auto'] else 'Manual'}</b>\n"
        f"📦 Model aktif: <b>{prefs['model'].get('name', 'Flash Lite')}</b>\n\n"
        "Pilih model di bawah ini:"
    )
    await message.reply(text, reply_markup=get_model_keyboard(user_id, current))

@dp.message(Command("quota", "status"))
async def cmd_quota(message: types.Message):
    remaining = await quota_manager.get_remaining_quota()
    reset_time = datetime.combine(quota_manager.last_reset_date + timedelta(days=1), datetime.min.time())
    await message.reply(
        "📊 <b>Status Quota Harian</b>\n\n"
        f"🖼️ <b>Gambar:</b> {remaining}/{quota_manager.max_images_per_day} tersisa\n"
        f"🔄 <b>Reset:</b> {reset_time.strftime('%d %b %Y, %H:%M WIB')}\n\n"
        "💡 Gunakan <code>/models</code> untuk ganti model"
    )

# ================= CALLBACK HANDLERS =================
@dp.callback_query(F.data.startswith("set_model:"))
async def handle_model_selection(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    action = callback.data.split(":")[1]
    if action == "auto":
        await user_prefs.reset(user_id)
        response_text = "✅ <b>Mode Auto-Detect diaktifkan!</b>\n\nBot akan otomatis memilih model berdasarkan permintaanmu."
    elif action in AVAILABLE_MODELS:
        await user_prefs.set(user_id, action)
        model_name = AVAILABLE_MODELS[action]["name"]
        response_text = f"✅ <b>Model diubah ke {model_name}</b>\n\n{get_model_info_text(action)}"
    else:
        response_text = "❌ Model tidak valid."

    prefs = await user_prefs.get_info(user_id)
    current = prefs["model_key"] if not prefs["auto"] else "auto"
    await callback.message.edit_text(response_text, reply_markup=get_model_keyboard(user_id, current), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "close_models")
async def handle_close_models(callback: types.CallbackQuery):
    try:
        # Coba hapus langsung jika message accessible
        await callback.message.delete()
    except AttributeError:
        # Fallback jika message bertipe InaccessibleMessage
        await bot.delete_message(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("exp:"))
async def handle_expense_pagination(callback: types.CallbackQuery):
    try:
        parts = callback.data.split(":")
        page = int(parts[1])
        year = int(parts[2])
        month = int(parts[3])
        
        from aglaea.tools import get_monthly_expenses
        from aglaea.handlers import send_monthly_expense_page
        
        user_id = callback.from_user.id
        res_json = await get_monthly_expenses(pool, user_id, year, month)
        monthly_data = json.loads(res_json)
        
        await send_monthly_expense_page(callback, monthly_data, page=page)
    except Exception as e:
        await callback.answer(f"Error: {str(e)}", show_alert=True)

# ================= MENTION & GAME MESSAGE HANDLER =================
from aglaea.handlers import handle_aglaea_message

@dp.message(~F.text.startswith('/'))
async def handle_mentions(message: types.Message):
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Private chat → Aglaea handles everything
    if message.chat.type == "private":
        # Log immediately so history is accurate even if timer is cancelled
        from aglaea.db import log_conversation
        if pool:
            try:
                await log_conversation(pool, user_id, "user", text)
            except Exception:
                pass

        # But first, check if it's a game move
        if chat_id in active_games and user_id in active_games[chat_id].players:
            if " " not in text:
                await active_games[chat_id].process_move(user_id, text)
                return
        
        # Debounce/Anti-Spam logic
        user_key = (chat_id, user_id)
        if user_key in pending_aglaea_tasks:
            pending_aglaea_tasks[user_key].cancel()
            
        async def _delayed_aglaea():
            try:
                await asyncio.sleep(1) # Tunggu cuma 1 detik agar responsif
                await handle_aglaea_message(message, pool)
            except asyncio.CancelledError:
                # Task dibatalkan karena ada pesan baru, abaikan
                pass
            finally:
                if pending_aglaea_tasks.get(user_key) == task:
                    del pending_aglaea_tasks[user_key]
        
        task = asyncio.create_task(_delayed_aglaea())
        pending_aglaea_tasks[user_key] = task
        return

    # Group / supergroup
    if chat_id in active_games and user_id in active_games[chat_id].players:
        if " " not in text:
            await active_games[chat_id].process_move(user_id, text)
            return

    # Gunakan cache bot info
    bot_id = bot_info_cache["id"]
    bot_username = bot_info_cache["username"]

    # Log debug untuk melacak pesan grup yang masuk
    logging.info(f"📩 [Group {chat_id}] Message from {message.from_user.username or message.from_user.id}: {text[:50]}...")

    # Save to group context
    username = message.from_user.username or message.from_user.first_name or "User"
    from aglaea.db import save_group_message
    if pool:
        try:
            await save_group_message(pool, chat_id, user_id, username, text[:500])
        except Exception as e:
            logging.warning(f"Failed to save group message: {e}")

    mentioned = False
    is_reply_to_me = False
    
    if message.reply_to_message and bot_id and message.reply_to_message.from_user.id == bot_id:
        is_reply_to_me = True
        logging.info(f"🎯 Message is a reply to bot (is_reply_to_me=True)")

    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned_text = text[entity.offset : entity.offset + entity.length]
                if bot_username and mentioned_text.lower() == f"@{bot_username}":
                    mentioned = True
                    logging.info(f"🎯 Bot mentioned via @{bot_username} (mentioned=True)")
                    break
            elif entity.type == "text_mention" and entity.user:
                if bot_id and entity.user.id == bot_id:
                    mentioned = True
                    logging.info("🎯 Bot mentioned via text_mention (mentioned=True)")
                    break

    if not (mentioned or is_reply_to_me):
        return

    # Group @mention or reply → Aglaea handles it with debounce
    user_key = (chat_id, user_id)
    if user_key in pending_aglaea_tasks:
        pending_aglaea_tasks[user_key].cancel()
        
    async def _delayed_aglaea_group():
        try:
            await asyncio.sleep(2) # Group debounce dikurangi juga
            await handle_aglaea_message(message, pool, bot_username=bot_username)
        except asyncio.CancelledError:
            pass
        finally:
            if pending_aglaea_tasks.get(user_key) == task:
                del pending_aglaea_tasks[user_key]
                
    task = asyncio.create_task(_delayed_aglaea_group())
    pending_aglaea_tasks[user_key] = task
    return


# (main execution block moved to the end of file to ensure all handlers are registered first)

# ================= GAME CONFIG =================
GAME_MAX_HP = 3
GAME_TIMEOUT_SEC = 45

class GameSession:
    def __init__(self, chat_id, players_dict, bot):
        self.chat_id = chat_id
        self.players_dict = players_dict # {user_id: name}
        self.players = list(players_dict.keys())
        self.bot = bot
        
        self.hp = {p: GAME_MAX_HP for p in self.players}
        self.current_turn = random.choice(self.players) # Siapa yang mulai
        
        self.history = [] # List kata yang sudah dipakai
        self.last_word = None
        self.last_letter = None
        
        self.timer_task = None
        self.is_active = True

    def get_tag(self, user_id):
        name = self.players_dict.get(user_id, str(user_id))
        return f'<a href="tg://user?id={user_id}">{name}</a>'

    async def _call_ai_with_fallback(self, user_id, prompt):
        model_key = await user_prefs.get(user_id, "text")
        model_config = AVAILABLE_MODELS.get(model_key, AVAILABLE_MODELS["flash_lite"])
        model_id = model_config["id"]
        
        class PseudoResponse:
            def __init__(self, text):
                self.text = text

        try:
            if "mistral" in model_id:
                if not mistral_client: raise Exception("Mistral Client unset")
                resp = await mistral_client.chat.complete_async(model=model_id, messages=[{"role": "user", "content": prompt}])
                return PseudoResponse(resp.choices[0].message.content)
            return genai_client.models.generate_content(model=model_id, contents=prompt)
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "resource_exhausted" in err_str or "rate limit" in err_str:
                fallback_key = "mistral_nemo" if model_key == "mistral_large" else "flash_lite"
                if fallback_key in AVAILABLE_MODELS:
                    fallback_config = AVAILABLE_MODELS[fallback_key]
                    await self.bot.send_message(self.chat_id, f"⚠️ Model <b>{model_config['name']}</b> limit harian!\n🔄 Sesi gamemu dialihkan otomatis ke <b>{fallback_config['name']}</b>.")
                    await user_prefs.set(user_id, fallback_key)
                    if "mistral" in fallback_config["id"]:
                        resp = await mistral_client.chat.complete_async(model=fallback_config["id"], messages=[{"role": "user", "content": prompt}])
                        return PseudoResponse(resp.choices[0].message.content)
                    return genai_client.models.generate_content(model=fallback_config["id"], contents=prompt)
            raise e

    async def start(self):
        """Mulai game dengan kata awal acak"""
        first_words = ["Sinar", "Bulan", "Matahari", "Langit", "Bumi", "Awan", "Api", "Air"]
        start_word = random.choice(first_words)
        
        self.last_word = start_word.lower()
        self.last_letter = self.last_word[-1]
        self.history.append(self.last_word)
        
        msg = f"🎮 <b>GAME DIMULAI!</b>\n\n"
        msg += f"👥 Pemain: {self.get_tag(self.players[0])} vs {self.get_tag(self.players[1])}\n"
        msg += f"❤️ HP: {GAME_MAX_HP}\n"
        msg += f"⏱️ Waktu: {GAME_TIMEOUT_SEC} detik/giliran\n\n"
        msg += f" Kata Pertama: <b>{start_word}</b>\n"
        msg += f"👉 {self.get_tag(self.current_turn)}, giliranmu! (Kirim kata berawalan '{self.last_letter}')"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Akhiri Game", callback_data=f"gc:stop:{self.chat_id}")]])
        await self.bot.send_message(self.chat_id, msg, reply_markup=kb)
        self.timer_task = asyncio.create_task(self._start_timer())

    async def process_move(self, user_id, word):
        if not self.is_active: return

        # 1. Validasi Giliran
        if user_id != self.current_turn:
            await self.bot.send_message(self.chat_id, "🚫 Bukan giliranmu!")
            return

        # 2. Validasi Huruf
        if not word.lower().startswith(self.last_letter):
            await self.bot.send_message(self.chat_id, f"❌ **Salah!** Kata harus berawalan huruf '{self.last_letter}'.")
            await self._penalty(user_id, "Pelanggaran aturan huruf")
            return

        # 3. Validasi Duplikat
        if word.lower() in self.history:
            await self.bot.send_message(self.chat_id, "❌ **Kata sudah dipakai!** Konsepnya sudah hilang dari dunia ini.")
            await self._penalty(user_id, "Menggunakan konsep yang hilang")
            return

        # Reset timer jika valid
        if self.timer_task:
            self.timer_task.cancel()
        
        self.timer_task = asyncio.create_task(self._start_timer())
        self.history.append(word.lower())
        
        # 4. Proses AI & Database
        waiting_msg = await self.bot.send_message(
            self.chat_id,
            f"⏳ Menyiapkan mantra untuk <b>'{word}'</b>, mohon tunggu sebentar..."
        )
        await self._handle_ai_logic(user_id, word, waiting_msg)

    async def _handle_ai_logic(self, user_id, word, waiting_msg=None):
        prev_word = self.last_word
        opponent = [p for p in self.players if p != user_id][0]
        
        # Cek Database Cache
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT data FROM game_word_cache WHERE word = %s", (word.lower(),))
                cached = await cur.fetchone()

        lore = ""
        damage = 1
        
        # --- JIKA ADA DI CACHE ---
        if cached:
            data = json.loads(cached['data'])
            tags = data.get('tags', [])
            base_damage = data.get('damage', 1)
            
            # Kita minta AI bikin narasi BARU berdasarkan tag yang sudah ada (agar variatif)
            prompt_narrate = f"""
                Role: Game Master / Narrator.
                Task: Deskripsikan hilangnya konsep '{word}' dari dunia permainan secara rasional.
                Context: 
                - Tag elemen kata ini adalah: {tags}.
                - Kata sebelumnya adalah '{prev_word}'.
                - Kata ini memberikan efek damage sebesar {base_damage} kepada lawan.
                
                Output: 
                1. Awali kalimat pertama persis dengan "Kata {word.capitalize()} dihilangkan! Sekarang konsep {word.lower()} hilang dari dunia."
                2. Jelaskan efek nyata dan harafiah pada kehidupan manusia atau sistem dunia karena kehilangan '{word}' (MAKSIMAL 2 KALIMAT). Dilarang keras memakai gaya bahasa puitis/dongeng/majas berlebihan!
            """
            ai_response = await self._call_ai_with_fallback(user_id, prompt_narrate)
            lore = ai_response.text
            damage = base_damage

        # --- JIKA BELUM ADA DI CACHE ---
        else:
            # Minta AI Analisis & Buat Data
            prompt_analyze = f"""
                Role: Game Master / AI Creator.
                Task: Analisis kata '{word}' yang disambungkan setelah '{prev_word}'.
                
                Tentukan:
                1. Validasi (boolean): false JIKA '{word}' BUKAN kata bahasa Indonesia ATAU merupakan kata kasar/kotor/umpatan. Evaluasinya true jika sah SFW.
                2. Tags (array JSON) elemen/konsep kata ini (misal: ["api", "panas", "kebakaran"]).
                3. Damage: Berikan angka 0 atau 1. Berikan angka 1 HANYA JIKA kata '{word}' adalah sesuatu yang secara alamiah sangat mematikan atau destruktif (misal: racun, meteor, bencana, pedang). Jika kata biasa tak berbahaya (misal: tas, apel, bulan), MAKA WAJIB bernilai 0.
                4. Lore: Awali persis dengan kalimat "Kata {word.capitalize()} dihilangkan! Sekarang konsep {word.lower()} hilang dari dunia." Setelah itu, sampaikan efek rasionalnya bagi peradaban tanpa menggunakan bahasa puitis (contoh: Manusia sekarang kerepotan membawa barang...). MAKSIMAL 2 KALIMAT.
                
                Return format HARUS JSON seperti ini:
                {{
                    "valid": true,
                    "tags": ["tag1", "tag2"],
                    "damage": 0,
                    "lore": "Kata {word.capitalize()} dihilangkan! Manusia sekarang tidak tahu..."
                }}
            """
            ai_response = await self._call_ai_with_fallback(user_id, prompt_analyze)
            
            # Parsing JSON Response
            try:
                # Cari bagian JSON di response text
                json_str = re.search(r'\{.*\}', ai_response.text, re.DOTALL).group(0)
                data = json.loads(json_str)
                
                if not data.get("valid", True):
                    if waiting_msg:
                        try:
                            await waiting_msg.delete()
                        except Exception:
                            pass
                    self.history.remove(word.lower())
                    await self.bot.send_message(self.chat_id, f"🚫 <b>Kata Ditolak oleh Dewa Game!</b>\nKata '{word}' kasar atau bukan bahasa Indonesia yang valid!")
                    await self._penalty(user_id, "Kata terlarang/tidak valid")
                    return

                tags = data.get('tags', [])
                damage = data.get('damage', 0)
                lore = data.get('lore', "Dunia kembali bergetar.")
                
                # Simpan ke Database
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "INSERT INTO game_word_cache (word, data) VALUES (%s, %s)",
                            (word.lower(), json.dumps(data))
                        )
                        
            except Exception as e:
                logging.error(f"Error parsing AI JSON: {e}")
                lore = "Dunia bergetar saat konsep itu hilang."
                damage = 1

        # 5. Terapkan Damage & Update HP
        self.hp[opponent] -= damage
        self.last_word = word.lower()
        self.last_letter = self.last_word[-1]
        self.current_turn = opponent
        
        # Kirim Narasi ke User
        result_msg = f"✨ <b>'{word}' telah diucapkan!</b>\n\n"
        result_msg += f"📜 <b>Narator Game:</b>\n{lore}\n\n"
        if damage > 0:
            result_msg += f"💥 <b>Damage {damage} diterima {self.get_tag(opponent)}!</b>\n"
        else:
            result_msg += f"🛡️ <b>Tanpa efek damage.</b>\n"
        result_msg += f"❤️ HP {self.get_tag(opponent)}: {self.hp[opponent]}\n"
        result_msg += f"❤️ HP {self.get_tag(user_id)}: {self.hp[user_id]}\n\n"
        result_msg += f"👉 {self.get_tag(self.current_turn)}, giliranmu! (Awalan '{self.last_letter}')"
        if waiting_msg:
            try:
                await waiting_msg.delete()
            except Exception:
                pass
                
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Akhiri Game", callback_data=f"gc:stop:{self.chat_id}")]])
        await self.bot.send_message(self.chat_id, result_msg, reply_markup=kb)
        
        # Cek Game Over
        if self.hp[opponent] <= 0:
            await self.end_game(user_id)

    async def _penalty(self, user_id, reason):
        """Kurangi HP karena error/tidak jawab"""
        self.hp[user_id] -= 1
        
        msg = f"⚠️ <b>Pelanggaran:</b> {reason}.\n"
        msg += f"❤️ HP berkurang! Sisa HP {self.get_tag(user_id)}: {self.hp[user_id]}\n\n"
        msg += f"👉 Silakan jawab lagi dengan benar, {self.get_tag(user_id)}! (Awalan '{self.last_letter}')"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Akhiri Game", callback_data=f"gc:stop:{self.chat_id}")]])
        await self.bot.send_message(self.chat_id, msg, reply_markup=kb)
        
        if self.hp[user_id] <= 0:
            winner = [p for p in self.players if p != user_id][0]
            await self.end_game(winner)

    async def _start_timer(self):
        """Timer 45 Detik"""
        try:
            await asyncio.sleep(GAME_TIMEOUT_SEC)
            if self.is_active and self.current_turn:
                await self._penalty(self.current_turn, "Waktu Habis (45 detik)")
        except asyncio.CancelledError:
            pass

    async def end_game(self, winner):
        self.is_active = False
        if self.timer_task:
            self.timer_task.cancel()
            
        msg = f"🏆 <b>GAME SELESAI!</b>\n\n"
        msg += f"👑 <b>Pemenang: {self.get_tag(winner)}</b>\n\n"
        msg += "👏 Terima kasih telah bermain. Game telah direset."
        
        await self.bot.send_message(self.chat_id, msg)
        # Hapus sesi game dari memory global
        if self.chat_id in active_games:
            del active_games[self.chat_id]


# ================= GAME HELPER =================
async def start_word_chain_game(chat_id, players):
    game = GameSession(chat_id, players, bot)
    active_games[chat_id] = game
    await game.start()

# ================= GAME COMMAND & MENU =================
@dp.message(Command("games"))
async def cmd_games(message: types.Message):
    if message.chat.type == "private":
        await message.reply("❌ Game ini khusus dimainkan di Grup/Supergroup!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Start", callback_data="gc:lobby:wordchain")],
        [InlineKeyboardButton(text="📜 Rules", callback_data="gc:rules:wordchain")],
        [InlineKeyboardButton(text="❌ Batalkan", callback_data="gc:cancel:wordchain")]
    ])
    await message.answer(
        "🎮 <b>Game: Sambung Kata</b>\n\n"
        "⚔️ 2 Player | ❤️ 3 HP | ⏱️ 45s/giliran\n"
        "📖 AI Narrator + Database Lore Cache\n\n"
        "Pilih aksi di bawah:",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("gc:lobby:"))
async def cb_game_lobby(callback: types.CallbackQuery):
    game_type = callback.data.split(":")[2]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Start", callback_data=f"gc:start:{game_type}")],
        [InlineKeyboardButton(text="📜 Rules", callback_data=f"gc:rules:{game_type}")],
        [InlineKeyboardButton(text="❌ Batalkan", callback_data=f"gc:cancel:{game_type}")]
    ])
    await callback.message.edit_text(
        "🎮 <b>Game: Sambung Kata</b>\n\n"
        "⚔️ 2 Player | ❤️ 3 HP | ⏱️ 45s/giliran\n"
        "📖 AI Narrator + Database Lore Cache\n\n"
        "Pilih aksi di bawah:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("gc:rules:"))
async def cb_game_rules(callback: types.CallbackQuery):
    rules_text = (
        "📜 <b>RULES SAMBUNG KATA</b>\n\n"
        "👥 Max 2 pemain per sesi.\n"
        "❤️ Setiap pemain punya 3 HP.\n"
        "⏱️ Waktu jawab: 45 detik/giliran.\n"
        "🔤 Huruf terakhir kata sebelumnya = huruf pertama kata jawaban.\n"
        "🚫 Kata tidak boleh diulang dalam 1 sesi.\n"
        "📖 AI berperan sebagai Narrator/Dewa Game.\n"
        "💾 Database menyimpan 'Lore' & 'Power' tiap kata.\n\n"
        "🏁 <b>Game Over</b> jika HP = 0. Pemenang adalah yang tersisa!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Kembali", callback_data="gc:lobby:wordchain")
    ]])
    await callback.message.edit_text(rules_text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("gc:start:"))
async def cb_game_start(callback: types.CallbackQuery):
    game_type = callback.data.split(":")[2]
    chat_id = callback.message.chat.id
    
    # Buat lobby jika belum ada
    if chat_id not in game_lobbies:
        game_lobbies[chat_id] = {"players": {}, "game_type": game_type}
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✋ Join Game", callback_data=f"gc:join:{game_type}")],
        [InlineKeyboardButton(text="❌ Batalkan", callback_data=f"gc:cancel:{game_type}")]
    ])
    
    await callback.message.edit_text(
        "⏳ <b>Lobby Game: Sambung Kata</b>\n"
        f"👥 Pemain bergabung: {len(game_lobbies[chat_id]['players'])}/2\n\n"
        "Tekan tombol di bawah untuk bergabung!\n"
        "Game akan dimulai otomatis saat slot penuh.",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("gc:join:"))
async def cb_game_join(callback: types.CallbackQuery):
    game_type = callback.data.split(":")[2]
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    
    if chat_id not in game_lobbies:
        await callback.answer("❌ Lobby tidak ditemukan. Ketik /games ulang.", show_alert=True)
        return
        
    lobby = game_lobbies[chat_id]
    
    if user_id in lobby["players"]:
        await callback.answer("⚠️ Kamu sudah join!", show_alert=True)
        return
        
    if len(lobby["players"]) >= 2:
        await callback.answer("🚫 Lobby sudah penuh. Tunggu game selesai.", show_alert=True)
        return
        
    lobby["players"][user_id] = username
    count = len(lobby["players"])
    
    if count < 2:
        # Masih menunggu pemain ke-2
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✋ Join Game", callback_data=f"gc:join:{game_type}")
        ]])
        await callback.message.edit_text(
            f"⏳ <b>Lobby Game: Sambung Kata</b>\n"
            f"✅ {username} bergabung!\n"
            f"👥 Pemain: {count}/2\n\n"
            "Menunggu pemain ke-2 untuk memulai...",
            reply_markup=kb
        )
    else:
        # Slot penuh -> Mulai Game
        await callback.message.edit_text("🚀 <b>Game Dimulai!</b>\nMenyiapkan arena...")
        # Panggil fungsi start game yang sudah kamu buat sebelumnya
        await start_word_chain_game(chat_id, lobby["players"])
        # Hapus lobby dari memori
        del game_lobbies[chat_id]
        
    await callback.answer()

@dp.callback_query(F.data.startswith("gc:cancel:"))
async def cb_game_cancel(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id in game_lobbies:
        del game_lobbies[chat_id]
        
    try:
        await callback.message.delete()
    except Exception:
        await bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
        
    await callback.answer("❌ Menu dibatalkan", show_alert=True)

@dp.callback_query(F.data.startswith("gc:stop:"))
async def cb_game_stop(callback: types.CallbackQuery):
    chat_id = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    if chat_id in active_games:
        game = active_games[chat_id]
        if user_id in game.players:
            if game.timer_task:
                 game.timer_task.cancel()
            del active_games[chat_id]
            game.is_active = False
            
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.message.reply(f"🛑 <b>Game dihentikan paksa oleh <a href='tg://user?id={user_id}'>{callback.from_user.first_name}</a>.</b>")
            await callback.answer("Game dihentikan.")
            return
        await callback.answer("❌ Kamu bukan pemain di game ini!", show_alert=True)
    else:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer("Game sudah tidak aktif.")

# ================= AGLAEA DB =================
from aglaea.decay import decay_worker
from aglaea.db import setup_db

# ================= MAIN =================
async def main():
    await init_db_pool()
    if pool:
        try:
            await setup_db(pool)
            logging.info("✅ Aglaea Database Schema Initialized")
        except Exception as e:
            logging.warning(f"⚠️ Aglaea DB setup (non-fatal, tabel mungkin sudah ada): {e}")
    aglaea_decay_task = None
    reminder_task = None
    if pool:
        aglaea_decay_task = asyncio.create_task(decay_worker(pool))
        reminder_task = asyncio.create_task(reminder_worker(bot))
    
    me = await bot.get_me()
    bot_info_cache["id"] = me.id
    bot_info_cache["username"] = me.username.lower()
    
    print(f"\n🚀 Bot @{me.username} ONLINE!")
    print(f"   Mode: Multi-Model Selector")
    print(f"   Daily Image Quota: {quota_manager.max_images_per_day}/hari\n")
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logging.info("🛑 Shutdown signal received")
    finally:
        if aglaea_decay_task and not aglaea_decay_task.done():
            aglaea_decay_task.cancel()
            try:
                await aglaea_decay_task
            except asyncio.CancelledError:
                pass
        if reminder_task and not reminder_task.done():
            reminder_task.cancel()
            try:
                await reminder_task
            except asyncio.CancelledError:
                pass
        
        await close_db_pool()
        await bot.session.close()
        logging.info("👋 Bot shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())