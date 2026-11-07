"""Catatan teks aman (super enkripsi). Pemilik: Anggota B."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from brankas.applog import get_logger
from brankas.core import crypto
from brankas.errors import DecryptionError, InvalidInput, ItemNotFound
from brankas.storage import db

log = get_logger("notes")

if TYPE_CHECKING:
    from brankas.auth.login import Session


@dataclass
class Note:
    id: int
    content: str       # sudah didekripsi
    created_at: str


def add_note(session: Session, text: str) -> Note:
    """crypto.encrypt_text -> tabel notes."""
    if not text.strip():
        raise InvalidInput("Catatan tidak boleh kosong")
    blob = crypto.encrypt_text(text, session.keys)
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO notes (user_id, content_enc) VALUES (?, ?)", (session.user_id, blob)
        )
        created_at = conn.execute(
            "SELECT created_at FROM notes WHERE id = ?", (cur.lastrowid,)
        ).fetchone()["created_at"]
    log.info("tambah catatan id=%s user=%s panjang=%d", cur.lastrowid, session.user_id, len(text))
    return Note(cur.lastrowid, text, created_at)


def list_notes(session: Session) -> list[Note]:
    """Hanya catatan milik session.user_id, terbaru di atas."""
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE user_id = ? ORDER BY id DESC", (session.user_id,)
        ).fetchall()
    result = []
    for r in rows:
        try:
            content = crypto.decrypt_text(r["content_enc"], session.keys)
        except DecryptionError:
            content = "(gagal didekripsi)"
        result.append(Note(r["id"], content, r["created_at"]))
    return result


def delete_note(session: Session, note_id: int) -> None:
    with db.transaction() as conn:
        cur = conn.execute(
            "DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, session.user_id)
        )
        if cur.rowcount == 0:
            raise ItemNotFound("Catatan tidak ditemukan")
    log.info("hapus catatan id=%s user=%s", note_id, session.user_id)
