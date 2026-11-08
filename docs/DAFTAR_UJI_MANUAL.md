# Daftar Uji Manual Brankas

Centang setiap butir setelah diuji. Lakukan di laptop yang akan dipakai presentasi, dengan flashdisk dan webcam
yang sama. Pastikan variabel lingkungan `BRANKAS_DEV_DONGLE_DIR` TIDAK diset (judul jendela tidak boleh
bertuliskan "MODE DEV").

## 0. Persiapan
- [ ] `python -m unittest discover -s tests -t . -v` lulus semua
- [ ] `python main.py` membuka layar login tanpa error
- [ ] Dua flashdisk siap (satu kosong untuk registrasi, satu cadangan), tanpa `dongle.key` lama
- [ ] Folder `data/` lama dihapus bila ingin demo dari nol

## 1. Layar Login, tab "Daftar Akun Baru"
- [ ] Kolom username, password, ulangi password dapat diketik (password tersamar)
- [ ] Petunjuk password: kosong -> "minimal 8 karakter"; 3 huruf -> merah "terlalu pendek (saat ini 3)"; 8 huruf -> hijau
- [ ] Password 8 spasi ditolak; konfirmasi tidak cocok -> peringatan kuning dan dialog
- [ ] Tombol "Segarkan Drive": flashdisk muncul di daftar; dicabut lalu disegarkan -> "Tidak ada flashdisk terdeteksi"
- [ ] Tombol "Pilih Folder Drive...": memilih folder non-removable ditolak dengan pesan jelas
- [ ] Tombol "Buka Kamera Preview": video tampil; "Ambil Sampel Wajah" 3 kali; kamera menutup sendiri
- [ ] Tanpa wajah di kamera -> pesan kuning "Tidak ada wajah terdeteksi", sampel tidak bertambah
- [ ] "Batal" di dialog kamera -> sampel sebelumnya tetap; "Batal / Reset Foto" menghapus sampel
- [ ] Daftar dengan password pendek -> dialog "Password Tidak Memenuhi Syarat", `dongle.key` TIDAK tertulis di flashdisk
- [ ] Daftar dengan data lengkap -> dialog sukses, `dongle.key` (32 byte) ada di flashdisk, langsung masuk dashboard
- [ ] Daftar memakai flashdisk yang sudah berisi `dongle.key` -> ditolak, berkas lama tidak berubah
- [ ] Username yang sama didaftarkan lagi -> ditolak

## 2. Layar Login, tab "Masuk ke Brankas"
- [ ] Tanpa flashdisk: "Periksa Dongle" -> pesan "Flashdisk dongle tidak ditemukan"
- [ ] Flashdisk tanpa `dongle.key` atau tidak terdaftar -> pesan jelas, langkah 2 tetap terkunci
- [ ] "Pilih Folder..." menunjuk drive dongle -> dikenali
- [ ] Dongle benar -> langkah 2 aktif dan nama pengguna tampil
- [ ] Kamera: wajah salah -> sisa percobaan berkurang; setelah batas -> terkunci beberapa detik
- [ ] Setelah terkunci, TUTUP aplikasi lalu buka lagi -> wajah benar tetap ditolak sampai waktu kunci habis
- [ ] Wajah benar -> langkah 3 aktif; "Batal / Ulangi Foto Wajah" mengunci langkah 3 lagi
- [ ] Password salah 5 kali -> "Terlalu banyak percobaan password"; berlaku juga setelah restart
- [ ] Tekan Enter di kolom password sama dengan klik "Buka Brankas"
- [ ] Password benar -> dashboard terbuka; kolom password kosong bila kembali ke layar login

## 3. Dashboard: header dan banner integritas
- [ ] Judul "Masuk sebagai <username>" benar
- [ ] Saat dibuka tampil "Memeriksa integritas..." lalu hijau "Integritas blockchain dan vault terverifikasi"
- [ ] Ubah satu byte pada berkas `data/vault/*.enc` lalu login ulang -> banner MERAH dengan jumlah masalah
- [ ] Tombol "Lihat detail" pada banner merah membuka tab Blockchain dan menampilkan daftar masalah
- [ ] Kembalikan berkas (atau hapus data demo) -> banner kembali hijau
- [ ] Tombol "Keluar" kembali ke layar login

## 4. Tab Dokumen
- [ ] "Unggah": satu file txt/md/docx/png/jpg; banyak file sekaligus; status "Mengenkripsi i/n..."
- [ ] File .exe ditolak dan file > 25 MB ditolak, tercantum di dialog "Sebagian file gagal diunggah"
- [ ] Daftar menampilkan nama, jenis, ukuran, waktu; jumlah dokumen di kanan atas benar
- [ ] "Unduh" tanpa pilihan atau dengan banyak pilihan -> pesan "Pilih tepat satu dokumen"
- [ ] "Unduh" satu dokumen -> hasil identik dengan aslinya (bandingkan hash/isi)
- [ ] "Hapus" beberapa dokumen -> konfirmasi, daftar dan tab Blockchain ter-update
- [ ] "Segarkan" memuat ulang daftar
- [ ] Buka `data/brankas.db` dengan DB Browser: nama file dan metadata tidak terbaca; tidak ada nama asli di `data/vault`

## 4b. Keamanan jalur berkas
- [ ] Di DB Browser ubah `documents.stored_path` satu dokumen menjadi `..\..\sesuatu.enc` (pada salinan DB)
- [ ] Unduh dan Hapus dokumen itu -> dialog error "stored_path tidak aman", tidak ada berkas di luar vault yang terhapus
- [ ] Verifikasi rantai melaporkan dokumen itu sebagai masalah

## 5. Tab Catatan
- [ ] Simpan catatan (termasuk Unicode/emoji); catatan kosong ditolak
- [ ] Memilih baris menampilkan isi lengkap di kotak bawah
- [ ] "Hapus catatan" tanpa pilihan -> pesan; dengan pilihan -> konfirmasi lalu terhapus
- [ ] DB Browser: kolom `content_enc` tidak terbaca

## 6. Tab Blockchain
- [ ] "Verifikasi rantai" -> "Rantai VALID (seluruh blok diperiksa)" hijau
- [ ] Setelah merusak data (poin 3/4b) -> "DITEMUKAN n MASALAH" merah dan rincian di kotak
- [ ] Daftar blok hanya memuat blok akun yang login (bandingkan dengan akun kedua)
- [ ] "Segarkan" memuat ulang daftar

## 7. Tab Steganografi
- [ ] "Pilih File PNG..." dengan PNG valid -> thumbnail, dimensi, kapasitas tampil
- [ ] File JPG diganti ekstensi `.png` atau berkas rusak -> dialog "Gambar Tidak Valid", tidak crash
- [ ] Penghitung karakter memerah bila melebihi kapasitas
- [ ] "Sembunyikan & Simpan PNG..." tanpa cover/tanpa teks -> peringatan
- [ ] Teks lebih besar dari kapasitas -> dialog error kapasitas, label merah
- [ ] Embed sukses -> dialog dan tab Ekstrak terisi otomatis
- [ ] Ekstrak dari PNG biasa (tanpa rahasia) -> "MAGIC steganografi tidak ditemukan"
- [ ] Ekstrak dengan akun/password berbeda -> gagal dekripsi, tampil sebagai dialog
- [ ] "Salin Catatan" menyalin ke clipboard dan memberi tahu bahwa clipboard dibersihkan saat keluar
- [ ] "Batal" pada cover dan stego mengosongkan pilihan

## 8. Penguncian otomatis dan kunci
- [ ] Cabut flashdisk saat dashboard terbuka (tunggu <= 3 detik) -> dialog "Dongle Dicabut!" dan kembali ke login
- [ ] Layar di belakang dialog sudah kosong (daftar dokumen/catatan tidak terlihat)
- [ ] Setelah "Salin Catatan": logout lalu tempel di Notepad -> tidak berisi catatan
- [ ] Setelah logout, login ulang berjalan normal (dongle, wajah, password)
- [ ] Menutup jendela dengan tombol X tidak menimbulkan error

## 9. Kegagalan yang disengaja
- [ ] Webcam dicabut atau dipakai aplikasi lain -> dialog "Kamera Tidak Tersedia", aplikasi tetap hidup
- [ ] Cahaya redup / wajah tertutup -> pesan "Tidak ada wajah", bukan crash
- [ ] Flashdisk dicabut di tengah proses registrasi -> pesan error, tidak ada `dongle.key` setengah jadi
- [ ] Menghapus `data/` saat aplikasi tertutup lalu membuka lagi -> aplikasi membuat ulang DB dan tidak crash
- [ ] `data/logs/brankas.log` ada, berisi peristiwa login/unggah/hapus, dan TIDAK berisi password, kunci, isi catatan, atau nama file dokumen

## 10. Sebelum presentasi
- [ ] Video demo cadangan sudah direkam
- [ ] Salinan `dongle.key` disimpan terpisah (hanya untuk demo)
- [ ] Parameter Argon2id diuji di laptop presentasi (login terasa wajar)
- [ ] `POW_DIFFICULTY` tidak diubah setelah data demo dibuat
