"""Konstanta bersama. Ubah di sini, jangan hardcode di modul lain."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"          # di-gitignore
VAULT_DIR = DATA_DIR / "vault"        # file terenkripsi (.enc)
DB_PATH = DATA_DIR / "brankas.db"
LOG_DIR = DATA_DIR / "logs"           # berkas log aplikasi (tanpa rahasia)

# Dokumen
MAX_FILE_BYTES = 25 * 1024 * 1024
ALLOWED_DOC_EXT = {".txt", ".md", ".docx", ".doc", ".png", ".jpg", ".jpeg"}

# Dongle
DONGLE_FILENAME = "dongle.key"
DONGLE_KEY_BYTES = 32
DONGLE_CHECK_INTERVAL_S = 3

# Argon2id (sesuaikan setelah uji performa di laptop)
ARGON2_TIME_COST = 3
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_PARALLELISM = 2

# Kebijakan password
PASSWORD_MIN_LENGTH = 8

# Wajah
FACE_TOLERANCE = 0.5
FACE_ENROLL_SAMPLES = 3
FACE_MAX_ATTEMPTS = 3
FACE_LOCKOUT_SECONDS = 30.0
FACE_LANDMARK_MODEL = "large"     # "small" (5 titik, lebih cepat) atau "large" (68 titik, sedikit lebih akurat)
FACE_JITTERS_ENROLL = 10          # jitter saat pendaftaran (jarang dilakukan, boleh mahal)
FACE_JITTERS_LOGIN = 5            # jitter saat login (tiap jitter menambah waktu proses)
FACE_MIN_SIZE_PX = 110            # tinggi minimal kotak wajah di frame; PERKIRAAN, ukur di webcam Anda
FACE_AMBIGUITY_RATIO = 0.5        # wajah kedua >= rasio ini x luas wajah terbesar => ambigu, ditolak
FACE_ENROLL_MAX_SPREAD = 0.4      # jarak maksimal antar sampel pendaftaran; lebih besar => sampel tidak konsisten
SHOW_FACE_DISTANCE = True         # tampilkan jarak wajah di dialog kamera (untuk kalibrasi; matikan setelah demo siap)

# Penguncian percobaan password (disimpan di database, tahan restart aplikasi)
PASSWORD_MAX_ATTEMPTS = 5
PASSWORD_LOCKOUT_SECONDS = 30.0

# Log aplikasi
LOG_MAX_BYTES = 256 * 1024
LOG_BACKUP_COUNT = 3

# Blockchain
POW_DIFFICULTY = 4   # jumlah nol di awal hash; turunkan ke 3 bila lambat
