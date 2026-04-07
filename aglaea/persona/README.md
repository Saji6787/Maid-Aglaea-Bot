# Manajemen Kepribadian (Persona) Bot

Folder ini digunakan untuk menyimpan template kepribadian bot Aglaea. Anda dapat mengubah perilaku, gaya bicara, dan identitas bot dengan mengedit file di folder ini.

## File Utama
- **`aglaea.md`**: Persona default bot.

## Cara Mengubah Persona
1. Buka file `.md` di dalam folder ini (misalnya `aglaea.md`).
2. Masukkan instruksi sistem yang Anda inginkan.
3. Gunakan placeholder berikut agar data dinamis tetap terisi:
    - `{{username}}`: Nama user yang sedang diajak bicara.
    - `{{current_time}}`: Waktu saat ini (YYYY-MM-DD HH:MM:SS).
    - `{{today}}`: Tanggal hari ini (YYYY-MM-DD).
    - `{{score}}`: Skor mood bot.
    - `{{mood_instruction}}`: Deskripsi label mood (misal: "SENANG", "KESAL").
    - `{{last_reason}}`: Alasan terakhir mood berubah.
    - `{{examples_text}}`: Teks dari `aglaea_examples.md`.

## Menambah Persona Baru
Anda bisa membuat file baru (misal: `kazuha.md`) dan kemudian mengganti parameter `persona_name` di fungsi `generate_system_prompt` pada `aglaea/ai.py` jika ingin mengganti secara permanen.
