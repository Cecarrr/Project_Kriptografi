"""Manajemen kunci. Pemilik: Anggota A.

Alur:  k_pw = Argon2id(password, salt_kdf)
       master_key = HKDF-SHA256(k_pw || dongle_key)
       subkunci   = HKDF(master_key, info=label)
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class KeySet:
    k_text: bytes        # 32 B, ChaCha20-Poly1305 (teks)
    k_file: bytes        # 32 B, AES-256-GCM (file)
    k_db: bytes          # 32 B, AES-256-GCM (field basis data)
    k_stego: bytes       # 32 B, cadangan untuk steganografi
    vigenere_key: bytes  # 16 B, kunci Vigenere level byte


def new_salt(n: int = 16) -> bytes:
    """Salt acak (os.urandom)."""
    raise NotImplementedError


def hash_password(password: str) -> str:
    """Hash Argon2id (string siap simpan di tabel users.password_hash)."""
    raise NotImplementedError


def verify_password(password_hash: str, password: str) -> bool:
    """True bila cocok. Jangan melempar exception untuk password salah."""
    raise NotImplementedError


def derive_pw_key(password: str, salt_kdf: bytes) -> bytes:
    """Argon2id raw (32 B) dari password. Salt BERBEDA dari salt hash password."""
    raise NotImplementedError


def derive_master_key(pw_key: bytes, dongle_key: bytes) -> bytes:
    """HKDF-SHA256(pw_key || dongle_key) -> 32 B."""
    raise NotImplementedError


def derive_keyset(master_key: bytes) -> KeySet:
    """Turunkan semua subkunci dengan label HKDF berbeda."""
    raise NotImplementedError


def derive_face_key(dongle_key: bytes) -> bytes:
    """HKDF(dongle_key, info=b'face') -> 32 B. Untuk enkripsi encoding wajah
    (dipakai SEBELUM password diketahui)."""
    raise NotImplementedError
