"""CRUD dokumen. Pemilik: Anggota B.

Setiap add/delete harus mencatat blok lewat cryptvault.chain.blockchain.add_block.
"""
from dataclasses import dataclass
from pathlib import Path

from cryptvault.auth.login import Session


@dataclass
class DocInfo:
    id: str
    filename: str      # sudah didekripsi
    file_type: str     # ekstensi, mis. ".png"
    size: int          # byte, file asli
    created_at: str


def add_document(session: Session, src_path: Path) -> DocInfo:
    """Validasi ekstensi & ukuran (FileTooLarge / UnsupportedFileType), enkripsi AES-GCM,
    tulis ke VAULT_DIR/<uuid>.enc, simpan metadata terenkripsi, catat blok UPLOAD."""
    raise NotImplementedError


def list_documents(session: Session) -> list[DocInfo]:
    """Hanya dokumen milik session.user_id."""
    raise NotImplementedError


def export_document(session: Session, doc_id: str, dest_path: Path) -> None:
    """Dekripsi dan tulis ke dest_path. DecryptionError bila file rusak/kunci salah."""
    raise NotImplementedError


def delete_document(session: Session, doc_id: str) -> None:
    """Hapus file .enc dan baris DB, catat blok DELETE."""
    raise NotImplementedError
