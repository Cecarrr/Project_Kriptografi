# Perubahan Tahap 1

Semua perubahan di bawah tidak mengubah format data (berkas `.enc`, kolom basis data, muatan stego), jadi
data uji lama tetap bisa dibuka. Satu-satunya perubahan skema: tabel baru `lockouts`, dibuat otomatis oleh
`init_db` pada basis data yang sudah ada.

| # | Perubahan | Berkas utama |
| --- | --- | --- |
| 1 | `_guard` di steganografi: error apa pun (bukan hanya `BrankasError`) menjadi dialog dan label status, tidak crash. Juga `report_callback_exception` global di `app.py`, dan penangkap error di langkah dongle/password/registrasi pada `login_view`. | `ui/stego_view.py`, `ui/app.py`, `ui/login_view.py` |
| 2 | Penghapusan kunci eksplisit: `Session.lock()` melepas `KeySet` dan `DongleInfo`, `keys`/`dongle` lalu melempar `SessionLocked`. Dipanggil saat logout, dongle dicabut (SEBELUM dialog peringatan), dan aplikasi ditutup. Widget dibersihkan (`wipe_sensitive`): daftar dokumen, isi catatan, hasil stego, clipboard bila pernah disalin dari aplikasi. `LoginFlow.clear()` dan kolom password dikosongkan saat layar login dihancurkan. | `auth/login.py`, `ui/*` |
| 3 | Kebijakan password minimal 8 karakter (`config.PASSWORD_MIN_LENGTH`), ditegakkan di backend (`login.register` -> `InvalidInput`) dan di form dengan petunjuk langsung. Akun lama dengan password lebih pendek tetap bisa login. | `auth/login.py`, `ui/login_view.py` |
| 4 | Validasi `stored_path`: hanya nama berkas biasa `*.enc`, tanpa `..`, `/`, `\`, atau drive, dan hasil resolve harus tepat di dalam `VAULT_DIR` (`storage/vault.py`). Dipakai di unduh, hapus, dan verifikasi rantai. Hapus memvalidasi SEBELUM mengubah DB sehingga `unlink` tidak bisa keluar dari vault. | `storage/vault.py`, `storage/documents.py`, `chain/blockchain.py` |
| 5 | Verifikasi blockchain otomatis saat dashboard dibuka (thread terpisah agar UI tidak membeku). Banner hijau bila valid, banner merah penuh dengan tombol "Lihat detail" bila gagal, juga bila verifikasi tidak dapat dijalankan. | `ui/dashboard_view.py` |
| 6 | Lockout tahan restart: status kunci disimpan di tabel `lockouts` per pengguna dan jenis (`face:<id>`, `password:<id>`) dengan waktu epoch. Sisa waktu dibatasi paling lama durasi kunci supaya jam sistem yang diubah tidak mengunci selamanya. | `auth/login.py`, `storage/db.py` |
| 7 | Daftar blok di tab Blockchain hanya milik pengguna yang login (`list_blocks(conn, user_id)`); blok genesis disembunyikan. Verifikasi tetap memeriksa seluruh rantai. Jumlah blok total tidak lagi ditampilkan karena membocorkan jumlah aksi akun lain. | `chain/blockchain.py`, `ui/dashboard_view.py` |
| 8 | Log aplikasi (`data/logs/brankas.log`, berputar). Mencatat peristiwa, bukan rahasia. | `applog.py` dan pemanggilnya |
| 9 | Daftar uji manual. | `docs/DAFTAR_UJI_MANUAL.md` |

## Hal yang perlu diketahui

- **`Session` bukan lagi dataclass.** `keys` dan `dongle` kini properti. Kode yang hanya membaca `session.keys`,
  `session.user_id`, dan `session.username` tidak perlu diubah.
- **Penghapusan kunci bersifat best effort.** `bytes` Python tidak bisa ditimpa dengan nol. `lock()` melepas
  semua referensi yang dipegang aplikasi lalu memanggil `gc.collect()`, tetapi salinan di dalam pustaka kripto
  atau memori yang belum dipakai ulang bisa saja masih ada. Tulis begitu di laporan.
- **Lockout bergantung pada jam sistem.** Mengubah jam komputer ke belakang tidak memperpanjang kunci
  (dibatasi), tetapi memajukan jam bisa mempercepat berakhirnya kunci. Penyerang dengan akses ke berkas DB juga
  bisa menghapus tabel `lockouts`; lockout ini melindungi dari percobaan lewat antarmuka, bukan dari akses berkas.
- **Banner merah palsu:** menaikkan `POW_DIFFICULTY` setelah ada data membuat blok lama gagal verifikasi
  (sudah tercatat di `blockchain.py`). Jangan ubah nilainya setelah data demo dibuat.
- **Tes:** `test_auth.py` disesuaikan (password uji diperpanjang, `tearDown` mereset lockout sebelum `DB_PATH`
  dikembalikan) dan ditambah tes kebijakan password, penguncian sesi, dan lockout persisten. `test_storage.py`
  ditambah tes `stored_path`, filter rantai per pengguna, dan helper lockout.
