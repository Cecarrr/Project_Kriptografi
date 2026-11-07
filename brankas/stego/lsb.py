"""Steganografi LSB pada PNG. Pemilik: Anggota A.

Payload di dalam gambar: MAGIC (4 B) || panjang (4 B, big-endian) || data.
"""
from __future__ import annotations

from pathlib import Path
import struct
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from brankas.core import crypto
from brankas.errors import (
    InvalidInput,
    ItemNotFound,
    StegoCapacityError,
    StegoNotFound,
    UnsupportedFileType,
)

if TYPE_CHECKING:
    from brankas.auth.login import Session

MAGIC: bytes = b"BRKS"
HEADER_LEN: int = 8  # 4 B MAGIC + 4 B length (uint32 big-endian)
HEADER_BITS: int = HEADER_LEN * 8


# ---- tingkat rendah (tidak tahu soal enkripsi) ----
def capacity_bytes(png_path: Path) -> int:
    """Berapa byte payload yang muat (setelah header)."""
    p = Path(png_path)
    if not p.is_file():
        raise ItemNotFound(f"Berkas tidak ditemukan: {p}")
    if p.suffix.lower() != ".png":
        raise UnsupportedFileType(f"Format file harus PNG (.png), bukan: {p.suffix}")

    try:
        with Image.open(p) as img:
            if img.format != "PNG":
                raise UnsupportedFileType(f"Format gambar bukan PNG: {img.format}")
            width, height = img.size
    except UnsupportedFileType:
        raise
    except Exception as e:
        raise UnsupportedFileType(f"Gagal membuka gambar PNG: {e}") from e

    total_bits = width * height * 3
    total_bytes = total_bits // 8
    return max(0, total_bytes - HEADER_LEN)


def embed(cover_path: Path, payload: bytes, out_path: Path) -> None:
    """Sisipkan payload ke LSB kanal RGB. Simpan sebagai PNG.
    StegoCapacityError bila tidak muat; UnsupportedFileType bila bukan PNG.
    """
    cover_p = Path(cover_path)
    out_p = Path(out_path)

    if not cover_p.is_file():
        raise ItemNotFound(f"Berkas cover tidak ditemukan: {cover_p}")
    if cover_p.suffix.lower() != ".png":
        raise UnsupportedFileType(f"Format file cover harus .png, bukan: {cover_p.suffix}")
    if out_p.suffix.lower() != ".png":
        raise UnsupportedFileType(f"Format file keluaran harus .png, bukan: {out_p.suffix}")

    try:
        with Image.open(cover_p) as img:
            if img.format != "PNG":
                raise UnsupportedFileType(f"Format file cover bukan PNG: {img.format}")
            if img.mode != "RGB":
                img = img.convert("RGB")
            arr = np.array(img, dtype=np.uint8)
    except UnsupportedFileType:
        raise
    except Exception as e:
        raise UnsupportedFileType(f"Gagal memuat cover PNG: {e}") from e

    flat = arr.reshape(-1)
    total_available_bytes = len(flat) // 8
    max_payload = max(0, total_available_bytes - HEADER_LEN)
    if len(payload) > max_payload:
        raise StegoCapacityError(
            f"Ukuran data ({len(payload)} B) melebihi kapasitas gambar ({max_payload} B)"
        )

    # Susun paket: MAGIC || length || payload
    header = MAGIC + struct.pack(">I", len(payload))
    data_to_embed = header + payload
    bits = np.unpackbits(np.frombuffer(data_to_embed, dtype=np.uint8))

    n_bits = len(bits)
    flat[:n_bits] = (flat[:n_bits] & 0xFE) | bits

    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_img = Image.fromarray(arr, mode="RGB")
    out_img.save(out_p, format="PNG")


def extract(png_path: Path) -> bytes:
    """Ambil payload. StegoNotFound bila MAGIC tidak ada."""
    p = Path(png_path)
    if not p.is_file():
        raise ItemNotFound(f"Berkas tidak ditemukan: {p}")
    if p.suffix.lower() != ".png":
        raise UnsupportedFileType(f"Format file harus .png, bukan: {p.suffix}")

    try:
        with Image.open(p) as img:
            if img.format != "PNG":
                raise UnsupportedFileType(f"Format berkas bukan PNG: {img.format}")
            if img.mode != "RGB":
                img = img.convert("RGB")
            arr = np.array(img, dtype=np.uint8)
    except UnsupportedFileType:
        raise
    except Exception as e:
        raise UnsupportedFileType(f"Gagal memuat gambar PNG: {e}") from e

    flat = arr.reshape(-1)
    if len(flat) < HEADER_BITS:
        raise StegoNotFound("Gambar terlalu kecil untuk memuat data steganografi")

    header_bits = flat[:HEADER_BITS] & 1
    header_bytes = np.packbits(header_bits).tobytes()

    magic = header_bytes[:4]
    if magic != MAGIC:
        raise StegoNotFound("MAGIC steganografi tidak ditemukan pada gambar ini")

    payload_len = struct.unpack(">I", header_bytes[4:8])[0]
    total_needed_bits = HEADER_BITS + (payload_len * 8)
    if total_needed_bits > len(flat):
        raise StegoNotFound("Header panjang payload tidak valid atau data gambar rusak")

    payload_bits = flat[HEADER_BITS:total_needed_bits] & 1
    return np.packbits(payload_bits).tobytes()


# ---- tingkat tinggi (dipanggil UI) ----
def hide_note(session: Session, cover_path: Path, note: str, out_path: Path) -> None:
    """crypto.encrypt_text(note) lalu embed."""
    if not note.strip():
        raise InvalidInput("Catatan yang akan disembunyikan tidak boleh kosong")

    encrypted_blob = crypto.encrypt_text(note, session.keys)
    embed(cover_path, encrypted_blob, out_path)


def reveal_note(session: Session, png_path: Path) -> str:
    """extract lalu crypto.decrypt_text."""
    payload = extract(png_path)
    return crypto.decrypt_text(payload, session.keys)
