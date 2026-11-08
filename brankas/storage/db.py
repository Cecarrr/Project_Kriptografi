"""Skema dan akses SQLite. Pemilik: Anggota B (tabel users: koordinasi dengan A).

Pola pemakaian yang dianjurkan (commit/rollback/close otomatis, skema dibuat bila belum ada):

    with db.transaction() as conn:
        ...
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from brankas import config
from brankas.errors import UserExists

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
CREATE TABLE IF NOT EXISTS audit (
    idx INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,                 -- GENESIS / LOGIN / LOGOUT / UNDUH / PRATINJAU
    doc_id TEXT NOT NULL,                 -- "-" bila tidak terkait dokumen
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL                    -- SHA-256 berantai, tanpa proof-of-work
);
CREATE TABLE IF NOT EXISTS lockouts (
    key TEXT PRIMARY KEY,                 -- mis. "face:3" / "password:3" (jenis:user_id)
    failures INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0  -- waktu epoch (detik); 0 = tidak terkunci
);
"""


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Buka koneksi ke config.DB_PATH (buat folder bila belum ada), row_factory=sqlite3.Row,
    PRAGMA foreign_keys=ON. Pemanggil wajib menutup koneksi (atau pakai transaction())."""
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Jalankan SCHEMA (aman dipanggil berulang)."""
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def transaction(db_path: str | Path | None = None):
    """connect + init_db, lalu commit bila sukses / rollback bila error, dan selalu close."""
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- users (dipakai auth/login.py) ----
def create_user(conn, username: str, password_hash: str, salt_kdf: bytes,
                dongle_serial_hash: str, face_enc: bytes) -> int:
    """Kembalikan user_id (sudah di-commit). Melempar errors.UserExists bila username/dongle sudah ada."""
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, salt_kdf, dongle_serial_hash, face_enc) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, salt_kdf, dongle_serial_hash, face_enc),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        raise UserExists("Username atau dongle ini sudah terdaftar") from None
    conn.commit()
    return cur.lastrowid


def get_user_by_dongle(conn, dongle_serial_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE dongle_serial_hash = ?", (dongle_serial_hash,)
    ).fetchone()


def get_user(conn, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
