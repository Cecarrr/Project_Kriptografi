"""Primitif enkripsi. Pemilik: Anggota B.

Format semua blob AEAD:  nonce (12 B acak) || ciphertext+tag(16 B)
Semua fungsi dekripsi melempar errors.DecryptionError bila kunci salah / data rusak.
Kunci yang panjangnya salah adalah kesalahan pemrograman -> ValueError.
"""
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

from brankas.core.keys import KeySet
from brankas.errors import DecryptionError

NONCE_LEN = 12
TAG_LEN = 16
_KEY_LEN = 32


def _check_key(key: bytes) -> None:
    if len(key) != _KEY_LEN:
        raise ValueError("kunci harus 32 byte")


def _seal(cipher_cls, data: bytes, key: bytes) -> bytes:
    _check_key(key)
    nonce = os.urandom(NONCE_LEN)
    return nonce + cipher_cls(key).encrypt(nonce, data, None)


def _open(cipher_cls, blob: bytes, key: bytes) -> bytes:
    _check_key(key)
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise DecryptionError("Data terenkripsi terlalu pendek / rusak")
    nonce, body = blob[:NONCE_LEN], blob[NONCE_LEN:]
    try:
        return cipher_cls(key).decrypt(nonce, body, None)
    except InvalidTag:
        raise DecryptionError("Kunci salah atau data telah diubah") from None


# ---- primitif generik ----
def aes_encrypt(data: bytes, key: bytes) -> bytes:
    """AES-256-GCM."""
    return _seal(AESGCM, data, key)


def aes_decrypt(blob: bytes, key: bytes) -> bytes:
    return _open(AESGCM, blob, key)


def chacha_encrypt(data: bytes, key: bytes) -> bytes:
    """ChaCha20-Poly1305."""
    return _seal(ChaCha20Poly1305, data, key)


def chacha_decrypt(blob: bytes, key: bytes) -> bytes:
    return _open(ChaCha20Poly1305, blob, key)


def vigenere_encrypt(data: bytes, key: bytes) -> bytes:
    """Vigenere level byte: (b + k) mod 256."""
    if not key:
        raise ValueError("kunci Vigenere tidak boleh kosong")
    n = len(key)
    return bytes((b + key[i % n]) & 0xFF for i, b in enumerate(data))


def vigenere_decrypt(data: bytes, key: bytes) -> bytes:
    if not key:
        raise ValueError("kunci Vigenere tidak boleh kosong")
    n = len(key)
    return bytes((b - key[i % n]) & 0xFF for i, b in enumerate(data))


# ---- API tingkat tinggi (ini yang dipanggil modul lain) ----
def encrypt_text(text: str, keys: KeySet) -> bytes:
    """UTF-8 -> Vigenere(keys.vigenere_key) -> ChaCha20-Poly1305(keys.k_text)."""
    classic = vigenere_encrypt(text.encode("utf-8"), keys.vigenere_key)
    return chacha_encrypt(classic, keys.k_text)


def decrypt_text(blob: bytes, keys: KeySet) -> str:
    classic = chacha_decrypt(blob, keys.k_text)
    try:
        return vigenere_decrypt(classic, keys.vigenere_key).decode("utf-8")
    except UnicodeDecodeError:
        raise DecryptionError("Hasil dekripsi bukan teks UTF-8 yang valid") from None


def encrypt_file(data: bytes, keys: KeySet) -> bytes:
    """AES-256-GCM dengan keys.k_file."""
    return aes_encrypt(data, keys.k_file)


def decrypt_file(blob: bytes, keys: KeySet) -> bytes:
    return aes_decrypt(blob, keys.k_file)


def encrypt_field(value: bytes | str, keys: KeySet) -> bytes:
    """Field basis data (nama file, metadata): AES-256-GCM dengan keys.k_db."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return aes_encrypt(value, keys.k_db)


def decrypt_field(blob: bytes, keys: KeySet) -> bytes:
    return aes_decrypt(blob, keys.k_db)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
