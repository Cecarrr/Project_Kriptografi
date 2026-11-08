"""Fasad untuk tab Inspektur: jejak tahap-demi-tahap super-enkripsi teks. Pemilik: Anggota B.

Hanya untuk demonstrasi: teks yang diketik pengguna diproses dengan pipeline yang SAMA dengan
crypto.encrypt_text (Vigenere -> ChaCha20-Poly1305), tetapi setiap tahap dikembalikan terpisah.
Tidak ada yang ditulis ke basis data. UI tidak meng-import brankas.core.* langsung, jadi UI memakai modul ini.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from brankas.core import crypto
from brankas.errors import DecryptionError, InvalidInput

if TYPE_CHECKING:
    from brankas.auth.login import Session

MAX_TRACE_BYTES = 4096


@dataclass(frozen=True)
class TextTrace:
    plaintext: bytes       # tahap 1: UTF-8
    vigenere_out: bytes    # tahap 2: setelah Vigenere (panjang sama)
    nonce: bytes           # tahap 3: 12 B acak
    ciphertext: bytes      #          ChaCha20 (panjang sama dengan plaintext)
    tag: bytes             #          Poly1305, 16 B
    blob: bytes            # tahap 4: nonce || ciphertext || tag (persis format simpanan)


@dataclass(frozen=True)
class DecryptTrace:
    vigenere_out: bytes    # hasil buka ChaCha20 (harus sama dengan tahap 2)
    plaintext: str


def key_fingerprints(session: Session) -> list[tuple[str, str, int]]:
    """[(nama, sidik jari, panjang kunci)]. Sidik jari = 8 byte pertama SHA-256 dari kunci, dalam hex
    berkelompok; tidak bisa dibalik menjadi kunci."""
    ks = session.keys
    items = (("k_text", ks.k_text), ("k_file", ks.k_file), ("k_db", ks.k_db),
             ("k_stego", ks.k_stego), ("vigenere_key", ks.vigenere_key))
    out = []
    for name, key in items:
        fp = crypto.sha256_hex(b"brankas/fingerprint|" + key)[:16]
        out.append((name, "-".join(fp[i:i + 4] for i in range(0, 16, 4)), len(key)))
    return out


def trace_encrypt(session: Session, text: str) -> TextTrace:
    data = text.encode("utf-8")
    if not data:
        raise InvalidInput("Teks tidak boleh kosong")
    if len(data) > MAX_TRACE_BYTES:
        raise InvalidInput(f"Teks demo maksimal {MAX_TRACE_BYTES} byte")
    ks = session.keys
    classic = crypto.vigenere_encrypt(data, ks.vigenere_key)
    blob = crypto.chacha_encrypt(classic, ks.k_text)
    n, t = crypto.NONCE_LEN, crypto.TAG_LEN
    return TextTrace(data, classic, blob[:n], blob[n:-t], blob[-t:], blob)


def decrypt_trace(session: Session, blob: bytes) -> DecryptTrace:
    """DecryptionError bila kunci salah atau blob diubah."""
    ks = session.keys
    classic = crypto.chacha_decrypt(blob, ks.k_text)
    try:
        text = crypto.vigenere_decrypt(classic, ks.vigenere_key).decode("utf-8")
    except UnicodeDecodeError:
        raise DecryptionError("Hasil dekripsi bukan teks UTF-8 yang valid") from None
    return DecryptTrace(classic, text)


def flip_ciphertext_bit(blob: bytes) -> tuple[bytes, int, int]:
    """Balik SATU bit acak di bagian ciphertext (bukan nonce/tag).
    Kembalian: (blob baru, indeks byte dalam ciphertext, nomor bit 0-7)."""
    n = len(blob) - crypto.NONCE_LEN - crypto.TAG_LEN
    if n <= 0:
        raise InvalidInput("Tidak ada ciphertext yang bisa dirusak")
    pos, bit = secrets.randbelow(n), secrets.randbelow(8)
    data = bytearray(blob)
    data[crypto.NONCE_LEN + pos] ^= 1 << bit
    return bytes(data), pos, bit
