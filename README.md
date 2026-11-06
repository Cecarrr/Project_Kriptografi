# CryptVault

Aplikasi desktop penyimpanan dokumen aman (Tugas Akhir Kriptografi). Detail desain ada di master-file.

## Setup (PowerShell)
```powershell
mkdir wheels                      # taruh dlib-*.whl di sini
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python check_env.py
python main.py
```

## Struktur dan pemilik modul
| Folder | Isi | Pemilik |
|---|---|---|
| cryptvault/core/keys.py | Argon2id, HKDF, KeySet | A |
| cryptvault/core/crypto.py | Vigenere, ChaCha20, AES, SHA-256 | B |
| cryptvault/auth/ | dongle, face, login, registrasi | A |
| cryptvault/storage/ | SQLite, dokumen, catatan | B |
| cryptvault/stego/ | LSB PNG | A |
| cryptvault/chain/ | blockchain + proof-of-work | B |
| cryptvault/ui/ | tampilan (login_view, stego_view: A; dashboard_view: B) | A / B |
| cryptvault/config.py, errors.py | konstanta dan exception | bersama |

## Aturan kontrak
1. Tanda tangan fungsi (nama, parameter, tipe, exception) di stub adalah kontrak. Mau ubah? Kabari partner dulu, lalu ubah stub-nya di commit terpisah.
2. Arah dependensi: `ui -> auth/storage/stego/chain -> core`. UI tidak meng-import `core.*` langsung.
3. `Session` (dari `auth/login.py`) adalah satu-satunya objek yang dibawa antar modul; ia memuat `KeySet`.
4. Kesalahan dilaporkan lewat exception di `errors.py`, bukan return code.
5. Konstanta ada di `config.py`.
6. Jangan commit: `dongle.key`, `data/`, `.venv/` (sudah di `.gitignore`).

## Git
- `main` selalu bisa dijalankan. Kerja di branch per modul (`feat/auth`, `feat/storage`, `feat/chain`, ...), merge lewat Pull Request kecil dan sering.
- Pesan commit singkat dan jelas, mis. `auth: implement find_dongle`.
