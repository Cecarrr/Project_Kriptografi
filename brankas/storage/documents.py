"""CRUD dokumen. Pemilik: Anggota B.

Setiap add/delete mencatat blok lewat brankas.chain.blockchain.add_block
di dalam transaksi yang sama dengan perubahan tabel documents.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from brankas import config
from brankas.chain import blockchain
from brankas.core import crypto
from brankas.errors import DecryptionError, FileTooLarge, ItemNotFound, UnsupportedFileType
from brankas.storage import db

if TYPE_CHECKING:   # hanya untuk anotasi; hindari impor melingkar dengan auth.login
    from brankas.auth.login import Session


@dataclass
class DocInfo:
    id: str
    filename: str      # sudah didekripsi
    file_type: str     # ekstensi, mis. ".png"
    size: int          # byte, file asli
    created_at: str


def _get_owned(conn, session: Session, doc_id: str):
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ? AND user_id = ?", (doc_id, session.user_id)
    ).fetchone()
    if row is None:
        raise ItemNotFound("Dokumen tidak ditemukan")
    return row


def add_document(session: Session, src_path: Path) -> DocInfo:
    """Validasi ekstensi & ukuran (FileTooLarge / UnsupportedFileType), enkripsi AES-GCM,
    tulis ke VAULT_DIR/<uuid>.enc, simpan metadata terenkripsi, catat blok UPLOAD."""
    src = Path(src_path)
    if not src.is_file():
        raise ItemNotFound("File sumber tidak ditemukan")
    ext = src.suffix.lower()
    if ext not in config.ALLOWED_DOC_EXT:
        raise UnsupportedFileType(f"Jenis file {ext or '(tanpa ekstensi)'} tidak didukung")
    size = src.stat().st_size
    if size > config.MAX_FILE_BYTES:
        raise FileTooLarge(f"Ukuran file melebihi batas {config.MAX_FILE_BYTES // (1024 * 1024)} MB")

    keys = session.keys
    blob = crypto.encrypt_file(src.read_bytes(), keys)
    doc_id = str(uuid.uuid4())
    stored_path = f"{doc_id}.enc"
    cipher_hash = crypto.sha256_hex(blob)
    filename_enc = crypto.encrypt_field(src.name, keys)
    meta_enc = crypto.encrypt_field(json.dumps({"type": ext, "size": size}), keys)

    config.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    target = config.VAULT_DIR / stored_path
    target.write_bytes(blob)
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO documents (id, user_id, filename_enc, meta_enc, stored_path, cipher_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, session.user_id, filename_enc, meta_enc, stored_path, cipher_hash),
            )
            blockchain.add_block(conn, session.user_id, "UPLOAD", doc_id, cipher_hash)
            created_at = conn.execute(
                "SELECT created_at FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()["created_at"]
    except BaseException:
        target.unlink(missing_ok=True)   # jangan tinggalkan file yatim bila DB/chain gagal
        raise
    return DocInfo(doc_id, src.name, ext, size, created_at)


def list_documents(session: Session) -> list[DocInfo]:
    """Hanya dokumen milik session.user_id, terbaru di atas."""
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE user_id = ? ORDER BY rowid DESC", (session.user_id,)
        ).fetchall()
    result = []
    for r in rows:
        try:
            name = crypto.decrypt_field(r["filename_enc"], session.keys).decode("utf-8")
            meta = json.loads(crypto.decrypt_field(r["meta_enc"], session.keys))
            result.append(DocInfo(r["id"], name, meta["type"], meta["size"], r["created_at"]))
        except (DecryptionError, ValueError, KeyError):
            result.append(DocInfo(r["id"], "(gagal didekripsi)", "", 0, r["created_at"]))
    return result


def export_document(session: Session, doc_id: str, dest_path: Path) -> None:
    """Dekripsi dan tulis ke dest_path. DecryptionError bila file rusak/kunci salah."""
    with db.transaction() as conn:
        row = _get_owned(conn, session, doc_id)
    path = config.VAULT_DIR / row["stored_path"]
    if not path.is_file():
        raise ItemNotFound("File terenkripsi hilang dari vault")
    data = crypto.decrypt_file(path.read_bytes(), session.keys)
    Path(dest_path).write_bytes(data)


def delete_document(session: Session, doc_id: str) -> None:
    """Hapus file .enc dan baris DB, catat blok DELETE."""
    with db.transaction() as conn:
        row = _get_owned(conn, session, doc_id)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        blockchain.add_block(conn, session.user_id, "DELETE", doc_id, row["cipher_sha256"])
    (config.VAULT_DIR / row["stored_path"]).unlink(missing_ok=True)   # setelah commit
