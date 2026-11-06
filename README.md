# Brankas

Aplikasi desktop penyimpanan dokumen yang aman (Tugas Akhir Kriptografi). Detail desain ada di master-file.

## Setup (Terminal VSCode)
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
| brankas/core/keys.py | Argon2id, HKDF, KeySet | A |
| brankas/core/crypto.py | Vigenere, ChaCha20, AES, SHA-256 | B |
| brankas/auth/ | dongle, face, login, registrasi | A |
| brankas/storage/ | SQLite, dokumen, catatan | B |
| brankas/stego/ | LSB PNG | A |
| brankas/chain/ | blockchain + proof-of-work | B |
| brankas/ui/ | tampilan (login_view, stego_view: A; dashboard_view: B) | A / B |
| brankas/config.py, errors.py | konstanta dan exception | A + B |

## Aturan kontrak
1. Tanda tangan fungsi (nama, parameter, tipe, exception) di stub adalah kontrak. Mau ubah? Kabari partner dulu, lalu ubah stub-nya di commit terpisah.
2. Arah dependensi: `ui -> auth/storage/stego/chain -> core`. UI tidak meng-import `core.*` langsung.
3. `Session` (dari `auth/login.py`) adalah satu-satunya objek yang dibawa antar modul; ia memuat `KeySet`.
4. Kesalahan dilaporkan lewat exception di `errors.py`, bukan return code.
5. Konstanta ada di `config.py`.
6. Jangan commit: `dongle.key`, `data/`, `.venv/` (sudah dicegah menggunakan `.gitignore`).
