"""Pratinjau dokumen di memori: ubah bytes hasil dekripsi menjadi teks atau gambar yang bisa
ditampilkan. Fungsi murni (tanpa widget dan tanpa menulis ke disk). Pemilik: Anggota B."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image

from brankas.errors import InvalidInput

TEXT_EXT = {".txt", ".md"}
DOCX_EXT = {".docx"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}

MAX_PREVIEW_CHARS = 100_000
_MAX_DOCX_XML = 20 * 1024 * 1024    # batas ukuran word/document.xml setelah dekompresi (anti zip-bomb)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def kind_of(ext: str) -> str:
    """'text' | 'docx' | 'image' | 'none' untuk ekstensi seperti '.png'."""
    ext = ext.lower()
    if ext in TEXT_EXT:
        return "text"
    if ext in DOCX_EXT:
        return "docx"
    if ext in IMAGE_EXT:
        return "image"
    return "none"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n… (dipotong: pratinjau hanya menampilkan {limit:,} karakter pertama)"


def text_from_bytes(data: bytes, limit: int = MAX_PREVIEW_CHARS) -> str:
    """Dekode UTF-8 (BOM diterima); byte yang tidak valid diganti, tidak melempar error."""
    return _clip(data.decode("utf-8-sig", errors="replace"), limit)


def docx_to_text(data: bytes, limit: int = MAX_PREVIEW_CHARS) -> str:
    """Teks polos dari .docx (paragraf, tab, baris baru). Tabel, gambar, dan format tidak ditampilkan."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > _MAX_DOCX_XML:
                raise InvalidInput("Isi dokumen .docx terlalu besar untuk dipratinjau")
            xml = z.read(info)
    except (zipfile.BadZipFile, KeyError):
        raise InvalidInput("File .docx tidak valid atau rusak") from None
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:   # document.xml sah tidak pernah memuat ini
        raise InvalidInput("Isi .docx ditolak: memuat deklarasi XML yang tidak diizinkan")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise InvalidInput("XML di dalam .docx rusak") from None

    paragraphs: list[str] = []
    total = 0
    for p in root.iter(f"{_W}p"):
        parts: list[str] = []
        for node in p.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        line = "".join(parts)
        paragraphs.append(line)
        total += len(line) + 1
        if total > limit:
            break
    return _clip("\n".join(paragraphs), limit)


def load_image(data: bytes, max_size: tuple[int, int] = (640, 360)) -> tuple[Image.Image, tuple[int, int]]:
    """(gambar RGB yang sudah diperkecil, ukuran asli). InvalidInput bila bukan gambar yang valid."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            original = img.size
            img.thumbnail(max_size)
            return img.convert("RGB"), original
    except (OSError, ValueError, Image.DecompressionBombError):
        raise InvalidInput("Gambar rusak atau tidak dapat ditampilkan") from None
