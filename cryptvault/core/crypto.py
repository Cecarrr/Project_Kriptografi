"""Primitif enkripsi. Pemilik: Anggota B.

Format semua blob AEAD:  nonce (12 B acak) || ciphertext+tag
Semua fungsi dekripsi melempar errors.DecryptionError bila gagal.
"""
from cryptvault.core.keys import KeySet


# ---- primitif generik ----
def aes_encrypt(data: bytes, key: bytes) -> bytes:
    """AES-256-GCM."""
    raise NotImplementedError


def aes_decrypt(blob: bytes, key: bytes) -> bytes:
    raise NotImplementedError


def chacha_encrypt(data: bytes, key: bytes) -> bytes:
    """ChaCha20-Poly1305."""
    raise NotImplementedError


def chacha_decrypt(blob: bytes, key: bytes) -> bytes:
    raise NotImplementedError


def vigenere_encrypt(data: bytes, key: bytes) -> bytes:
    """Vigenere level byte: (b + k) mod 256."""
    raise NotImplementedError


def vigenere_decrypt(data: bytes, key: bytes) -> bytes:
    raise NotImplementedError


# ---- API tingkat tinggi (ini yang dipanggil modul lain) ----
def encrypt_text(text: str, keys: KeySet) -> bytes:
    """UTF-8 -> Vigenere(keys.vigenere_key) -> ChaCha20-Poly1305(keys.k_text)."""
    raise NotImplementedError


def decrypt_text(blob: bytes, keys: KeySet) -> str:
    raise NotImplementedError


def encrypt_file(data: bytes, keys: KeySet) -> bytes:
    """AES-256-GCM dengan keys.k_file."""
    raise NotImplementedError


def decrypt_file(blob: bytes, keys: KeySet) -> bytes:
    raise NotImplementedError


def encrypt_field(value: bytes | str, keys: KeySet) -> bytes:
    """Field basis data (nama file, metadata): AES-256-GCM dengan keys.k_db."""
    raise NotImplementedError


def decrypt_field(blob: bytes, keys: KeySet) -> bytes:
    raise NotImplementedError


def sha256_hex(data: bytes) -> str:
    raise NotImplementedError
