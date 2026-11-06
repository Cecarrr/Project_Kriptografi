"""Steganografi LSB pada PNG. Pemilik: Anggota A.

Payload di dalam gambar: MAGIC (4 B) || panjang (4 B, big-endian) || data.
"""
from pathlib import Path

from brankas.auth.login import Session


# ---- tingkat rendah (tidak tahu soal enkripsi) ----
def capacity_bytes(png_path: Path) -> int:
    """Berapa byte payload yang muat (setelah header)."""
    raise NotImplementedError


def embed(cover_path: Path, payload: bytes, out_path: Path) -> None:
    """Sisipkan payload ke LSB kanal RGB. Simpan sebagai PNG.
    StegoCapacityError bila tidak muat; UnsupportedFileType bila bukan PNG."""
    raise NotImplementedError


def extract(png_path: Path) -> bytes:
    """Ambil payload. StegoNotFound bila MAGIC tidak ada."""
    raise NotImplementedError


# ---- tingkat tinggi (dipanggil UI) ----
def hide_note(session: Session, cover_path: Path, note: str, out_path: Path) -> None:
    """crypto.encrypt_text(note) lalu embed."""
    raise NotImplementedError


def reveal_note(session: Session, png_path: Path) -> str:
    """extract lalu crypto.decrypt_text."""
    raise NotImplementedError
