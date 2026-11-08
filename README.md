# Brankas

Aplikasi desktop (Python) untuk menyimpan dokumen dan catatan secara aman: dongle USB + wajah + password,
super enkripsi teks, AES-256-GCM untuk file, steganografi LSB, dan blockchain sederhana.
Detail rancangan ada di `docs/Master_File_Brankas.md`.

## Menjalankan
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Tes
Dari root repo:
```
python -m unittest discover -s tests -t . -v
```
Tes memakai folder sementara dan tidak menyentuh `data/` asli. Tes `test_auth.py` memerlukan Windows
(pywin32) karena `dongle.py` mengimpor `win32api`.

## Dokumen
- `docs/PERUBAHAN_TAHAP1.md` : daftar perubahan Tahap 1 beserta dampaknya.
- `docs/DAFTAR_UJI_MANUAL.md` : daftar uji manual untuk semua tombol di setiap layar.

## Log
Log aplikasi ada di `data/logs/brankas.log` (berputar, maks 3 cadangan). Log tidak berisi password, kunci,
isi catatan, atau nama file dokumen.
