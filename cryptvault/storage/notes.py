"""Catatan teks aman (super enkripsi). Pemilik: Anggota B."""
from dataclasses import dataclass

from cryptvault.auth.login import Session


@dataclass
class Note:
    id: int
    content: str       # sudah didekripsi
    created_at: str


def add_note(session: Session, text: str) -> Note:
    """crypto.encrypt_text -> tabel notes."""
    raise NotImplementedError


def list_notes(session: Session) -> list[Note]:
    raise NotImplementedError


def delete_note(session: Session, note_id: int) -> None:
    raise NotImplementedError
