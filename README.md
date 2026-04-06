# [Aglaea Maid Assistant Bot]

Bot Telegram multi-fungsi yang ditenagai oleh AI (Gemini & Mistral), fitur pencatatan pengeluaran, pengingat otomatis, dan permainan berbasis teks.

## Fitur Utama:

- 🧠 **Aglaea AI**: Ngobrol dengan asisten menggunakan model Gemini atau Mistral.
- 💸 **Catat Pengeluaran**: Kelola keuangan harian dengan mudah lewat chat.
- ⏰ **AI Reminder**: Seting pengingat hanya dengan bahasa natural (contoh: "Agy, ingetin besok jam 8 pagi buat kuliah").
- 🎮 **Game Sambung Kata**: Permainan interaktif dengan narasi unik dari AI.
- 📝 **Manajemen Tugas**: Catat deadline dan tugas penting kamu.

## Persyaratan Sistem

- **Python**: Versi 3.10 atau lebih tinggi.
- **Database**: MySQL atau MariaDB.
- **Koneksi Internet**: Untuk akses API Telegram dan AI.

## Panduan Instalasi & Setup

### 1. Clone Repository
```bash
git clone https://github.com/Saji6787/Kiraa_PotBot.git
cd Kiraa_PotBot
```

### 2. Buat Virtual Environment (Opsional tapi Direkomendasikan)
```bash
python -m venv venv
source venv/bin/activate  # Untuk Linux/macOS
# venv\Scripts\activate  # Untuk Windows
```

### 3. Instal Dependensi
```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Environment Variables
Salin file `.env.example` menjadi `.env` dan isi token/API key yang diperlukan:
```bash
cp .env.example .env
```
Isi variabel berikut di dalam `.env`:
- `TELEGRAM_TOKEN`: Dapatkan dari [@BotFather](https://t.me/BotFather).
- `GEMINI_API_KEY`: Dapatkan dari [Google AI Studio](https://aistudio.google.com/).
- `MISTRAL_API_KEY`: Dapatkan dari [Mistral AI Console](https://console.mistral.ai/).
- Informasi Database (`MYSQL_HOST`, `MYSQL_USER`, dll).

### 5. Persiapan Database
Bot ini akan otomatis mencoba membuat tabel yang diperlukan saat dijalankan pertama kali. Pastikan kamu sudah membuat database kosong di MySQL/MariaDB sesuai dengan nama yang kamu isi di `.env`.

Jika ingin melakukan manual setup, kamu bisa menjalankan query di file `aglaea/schema.sql`.

## Cara Menjalankan Bot

Pastikan virtual environment sudah aktif, lalu jalankan:
```bash
python bot.py
```

## Penggunaan di Grup
- Bot harus diberikan akses sebagai Admin (atau setidaknya akses baca pesan).
- Gunakan mention `@{username_bot}` untuk berinteraksi dengan AI di dalam grup.

## Lisensi
Proyek ini dibuat untuk keperluan pribadi dan pembelajaran.
