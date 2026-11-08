# Master File: Brankas

*Tugas Akhir Kriptografi · Aplikasi penyimpanan dokumen aman · Draft 1, 6 November 2026 *

## 1. Ringkasan

Brankas adalah aplikasi desktop (Python) untuk menyimpan dokumen dan catatan secara aman. Aplikasi hanya bisa dibuka lewat tiga lapis autentikasi berurutan: dongle USB, wajah (face recognition), dan password. Semua data dienkripsi sebelum disimpan, dan riwayat dokumen dicatat dalam blockchain sederhana agar perubahan bisa diverifikasi.

Pemenuhan kriteria tugas:

| Kriteria | Pemenuhan di Brankas |
| --- | --- |
| Login biometrik dan hanya hidup dengan dongle | Face recognition via webcam + USB flash drive sebagai dongle |
| Login memakai algoritma kriptografi | Argon2id untuk password, kunci turunan dari password + dongle |
| Pesan teks dienkripsi dengan super enkripsi | Vigenère (klasik) lalu ChaCha20-Poly1305 (modern) |
| File dienkripsi dengan kriptografi berbeda dari teks | AES-256-GCM |
| Pesan penting dienkripsi di basis data | Nama file, metadata, dan catatan terenkripsi di SQLite |
| Pesan gambar diamankan dengan steganografi | LSB pada gambar PNG |
| Aset penting diamankan dengan blockchain sederhana | Rantai blok berisi hash dokumen, dengan proof-of-work |

## 2. Tim dan jadwal

- Tim 2 orang (Anggota A dan Anggota B), sama-sama Windows, VS Code, Git dan GitHub.
- Batas pengumpulan: tersisa 2 hari 21 jam per 6 November 2026.
- Jadwal presentasi diacak (bisa minggu pertama, tengah, atau terakhir), jadi aplikasi harus siap didemokan kapan saja.
- Dosen tidak menetapkan bahasa pemrograman maupun template laporan.

Usulan pembagian tugas:

| Anggota | Modul |
| --- | --- |
| A | Dongle, face recognition, registrasi dan login, turunan kunci, steganografi |
| B | Inti kripto (Vigenère, ChaCha20, AES), basis data, dokumen dan catatan, blockchain, jendela utama |
| Bersama | Setup repo, kontrak antarmuka antar modul, integrasi, pengujian, laporan |

## 3. Cakupan fitur

Termasuk:

- Multi-user sederhana: setiap akun terikat satu dongle. Akun baru didaftarkan dengan dongle, wajah, dan password. Tidak ada peran admin.
- Dokumen: unggah, unduh, daftar, hapus. Jenis file teks (txt, md, docx) dan gambar (png, jpg). Batas 25 MB per file, sehingga file bisa dibaca utuh ke memori dan dienkripsi sekali jalan tanpa chunking.
- Catatan teks aman (memenuhi kriteria pesan teks).
- Steganografi: sisipkan dan ekstrak catatan rahasia di gambar PNG.
- Verifikasi blockchain: tombol cek integritas riwayat dokumen.
- Aplikasi terkunci otomatis bila dongle dicabut.

Tidak termasuk: berbagi dokumen, peran admin, pemulihan akun bila dongle hilang. Liveness check (deteksi kedipan) hanya bonus bila waktu tersisa.

## 4. Arsitektur

Tiga lapisan: antarmuka (CustomTkinter), layanan (auth, crypto, storage, stego, chain), dan penyimpanan (SQLite + folder `vault/` berisi file terenkripsi).

```
Brankas/
  main.py
  ui/              # jendela login, registrasi, dashboard, steganografi
  core/
    crypto.py      # Vigenère, ChaCha20, AES, helper AEAD
    keys.py        # Argon2id, HKDF, turunan subkunci
  auth/
    dongle.py      # deteksi flashdisk, baca dongle.key, cek serial
    face.py        # webcam, encoding wajah, pencocokan
    login.py       # alur 3 lapis, registrasi
  storage/
    db.py          # skema dan akses SQLite
    documents.py   # unggah, unduh, daftar, hapus
    notes.py       # catatan teks aman
  stego/lsb.py     # sisip dan ekstrak LSB
  chain/blockchain.py
  vault/           # file .enc (tidak di-commit)
```

## 5. Alur login

1. Aplikasi dibuka: cari flashdisk removable yang berisi `dongle.key`, cocokkan serial dengan akun terdaftar. Dari sini akun dikenali.
2. Wajah: ambil gambar webcam, bandingkan dengan encoding wajah terdaftar. Encoding disimpan terenkripsi dengan kunci turunan dari dongle (karena password belum dimasukkan pada tahap ini).
3. Password: verifikasi dengan Argon2id, lalu turunkan master key.
4. Sesi aktif. Sebuah thread mengecek dongle tiap beberapa detik; bila dicabut, sesi dikunci dan kunci dihapus dari memori.

Gagal di satu tahap berarti kembali ke awal. Wajah diberi beberapa kesempatan sebelum diulang dari tahap 1.

## 6. Algoritma dan manajemen kunci

| Kebutuhan | Algoritma | Library |
| --- | --- | --- |
| Hash password | Argon2id | argon2-cffi |
| Turunan kunci | Argon2id (raw) + HKDF-SHA256 | argon2-cffi, cryptography |
| Pesan teks | Vigenère (level byte) lalu ChaCha20-Poly1305 | kode sendiri, cryptography |
| File | AES-256-GCM | cryptography |
| Field di basis data | AES-256-GCM, subkunci khusus, helper yang sama dengan file | cryptography |
| Encoding wajah | AES-256-GCM, kunci dari dongle | cryptography |
| Pesan steganografi | Memakai ulang fungsi enkripsi teks | kode yang sudah ada |
| Integritas riwayat | SHA-256 + proof-of-work | hashlib |

Alur kunci:

- `dongle.key`: 32 byte acak, dibuat saat registrasi, disimpan di flashdisk.
- `k_pw` = Argon2id(password, salt\_kdf).
- `master_key` = HKDF-SHA256(k\_pw ‖ dongle\_key).
- Subkunci `k_text`, `k_file`, `k_db`, `k_stego` diturunkan dari `master_key` dengan label HKDF berbeda, satu fungsi untuk semuanya.
- `k_face` = HKDF(dongle\_key, "face").
- Semua enkripsi AEAD memakai nonce acak 12 byte yang disimpan di depan ciphertext.
- Vigenère bekerja pada byte (mod 256) agar semua karakter didukung. Kuncinya diambil dari 16 byte subkunci `k_text`. Urutan: plaintext → Vigenère → ChaCha20-Poly1305.
- Parameter awal Argon2id: time\_cost 3, memory 64 MiB, parallelism 2, disesuaikan setelah uji di laptop.

## 7. Basis data (SQLite)

| Tabel | Kolom |
| --- | --- |
| users | id, username, password\_hash (Argon2id), salt\_kdf, dongle\_serial\_hash, face\_enc (terenkripsi), created\_at |
| documents | id (UUID), user\_id, filename\_enc, meta\_enc (tipe dan ukuran), stored\_path, cipher\_sha256, created\_at |
| notes | id, user\_id, content\_enc (Vigenère + ChaCha20), created\_at |
| chain | idx, timestamp, user\_id, action, doc\_id, doc\_hash, prev\_hash, nonce, hash |

## 8. Steganografi

- Metode LSB pada gambar PNG (lossless), 1 bit per kanal RGB.
- Payload: penanda (magic) + panjang 4 byte + catatan rahasia yang sudah dienkripsi.
- Cek kapasitas gambar sebelum menyisipkan; tolak bila pesan terlalu besar.
- Hasil disimpan sebagai dokumen gambar di vault. Ekstraksi membaca bit, membuang header, lalu mendekripsi.

## 9. Blockchain sederhana

- Blok berisi: idx, timestamp, user\_id, action (UPLOAD atau DELETE), doc\_id, doc\_hash (SHA-256 file terenkripsi), prev\_hash, nonce, hash.
- Hash blok = SHA-256 atas seluruh isi blok.
- Proof-of-work: cari nonce sampai hash diawali "0000" (difficulty 4, turunkan ke 3 bila terasa lambat).
- Ada blok genesis. Tidak ada jaringan terdistribusi.
- Verifikasi: hitung ulang hash tiap blok, cek prev\_hash, lalu cocokkan doc\_hash dengan hash file di disk untuk mendeteksi file yang diubah.

## 10. Alat dan teknologi

| Alat | Fungsi |
| --- | --- |
| Python 3.10 atau 3.11 | Bahasa utama (paling kompatibel dengan dlib di Windows) |
| CustomTkinter | Antarmuka. Daftar dokumen memakai ttk.Treeview |
| face\_recognition (dlib), opencv-python | Wajah dan webcam. Cadangan: OpenCV saja |
| Pillow, numpy | Steganografi LSB |
| cryptography, argon2-cffi | AES, ChaCha20, HKDF, Argon2id |
| pywin32 / psutil | Deteksi flashdisk dan serial di Windows |
| SQLite (sqlite3) | Basis data; DB Browser for SQLite untuk inspeksi |
| VS Code, Git, GitHub | Pengembangan dan kolaborasi (branch per modul) |
| venv + requirements.txt | Lingkungan yang sama di kedua laptop |
| draw.io | Diagram arsitektur untuk laporan |

Jangan commit: `dongle.key`, file `.db`, dan folder `vault/`.

## 11. Rencana kerja

- **Hari 1**: setup repo dan venv (pasang dlib dan face\_recognition lebih dulu), sepakati nama fungsi antarmuka antar modul, helper kripto, skema DB, prototipe deteksi dongle dan wajah.
- **Hari 2**: login 3 lapis dan registrasi end-to-end, CRUD dokumen, catatan, steganografi, blockchain.
- **Hari 3**: integrasi, UI, pengujian, laporan dan diagram, video demo cadangan, sisakan waktu buffer. Liveness check hanya bila semuanya sudah stabil.

Urutan prioritas bila waktu mepet: login, dokumen, catatan, blockchain, steganografi, bonus.

## 12. Risiko dan mitigasi

| Risiko | Mitigasi |
| --- | --- |
| dlib gagal terpasang | Dicoba paling awal; cadangan memakai OpenCV |
| Akurasi wajah turun saat cahaya berubah | Daftarkan 3 sampai 5 foto di kondisi berbeda, atur threshold, uji sebelum presentasi |
| Serial flashdisk kosong atau kembar | Uji kedua flashdisk sejak awal; bila bermasalah, andalkan `dongle.key` |
| Dongle hilang atau rusak berarti data tak terbuka | Disengaja sebagai fitur keamanan; simpan salinan `dongle.key` untuk demo |
| Webcam bermasalah saat presentasi | Siapkan video demo |
| Waktu mepet | Ikuti urutan prioritas di bagian 11 |

## 13. Keputusan yang masih terbuka

- Format laporan dan jadwal presentasi (menunggu informasi).
- Parameter Argon2id final setelah uji performa.
