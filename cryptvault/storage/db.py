"""Skema dan akses SQLite. Pemilik: Anggota B (tabel users: koordinasi dengan A)."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,          -- Argon2id
    salt_kdf BLOB NOT NULL,               -- salt untuk derive_pw_key
    dongle_serial_hash TEXT UNIQUE NOT NULL,
    face_enc BLOB NOT NULL,               -- AES-GCM(k_face)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,                  -- UUID
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename_enc BLOB NOT NULL,           -- AES-GCM(k_db)
    meta_enc BLOB NOT NULL,               -- AES-GCM(k_db): tipe, ukuran
    stored_path TEXT NOT NULL,            -- relatif terhadap VAULT_DIR
    cipher_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    content_enc BLOB NOT NULL,            -- Vigenere + ChaCha20
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chain (
    idx INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,                 -- GENESIS / UPLOAD / DELETE
    doc_id TEXT NOT NULL,
    doc_hash TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    nonce INTEGER NOT NULL,
    hash TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """Buka koneksi ke config.DB_PATH (buat folder bila belum ada), row_factory=sqlite3.Row,
    PRAGMA foreign_keys=ON."""
    raise NotImplementedError


def init_db(conn: sqlite3.Connection) -> None:
    """Jalankan SCHEMA."""
    raise NotImplementedError


# ---- users (dipakai auth/login.py) ----
def create_user(conn, username: str, password_hash: str, salt_kdf: bytes,
                dongle_serial_hash: str, face_enc: bytes) -> int:
    """Kembalikan user_id. Melempar errors.UserExists bila username/dongle sudah ada."""
    raise NotImplementedError


def get_user_by_dongle(conn, dongle_serial_hash: str) -> sqlite3.Row | None:
    raise NotImplementedError
