"""Manajemen kunci. Pemilik: Anggota A.

Alur:  pw_key     = Argon2id(password, salt_kdf)              (32 B)
       master_key = HKDF-SHA256(pw_key || dongle_key)         (32 B)
       subkunci   = HKDF-SHA256(master_key, info=label)

Catatan keamanan singkat:
- password_hash (untuk verifikasi login) dan pw_key (untuk kunci) memakai salt BERBEDA.
  Salt untuk hash dibuat otomatis oleh Argon2; salt_kdf dibuat lewat new_salt() dan
  disimpan di tabel users.
- Tanpa dongle_key, master_key tidak bisa dihitung walau password diketahui.
"""
import os
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from brankas import config

KEY_LEN = 32
VIGENERE_KEY_LEN = 16
SALT_LEN = 16

_hasher = PasswordHasher(
    time_cost=config.ARGON2_TIME_COST,
    memory_cost=config.ARGON2_MEMORY_KIB,
    parallelism=config.ARGON2_PARALLELISM,
)


@dataclass(frozen=True)
class KeySet:
    # repr=False supaya kunci tidak ikut tercetak di log / traceback
    k_text: bytes = field(repr=False)        # 32 B, ChaCha20-Poly1305 (teks)
    k_file: bytes = field(repr=False)        # 32 B, AES-256-GCM (file)
    k_db: bytes = field(repr=False)          # 32 B, AES-256-GCM (field basis data)
    k_stego: bytes = field(repr=False)       # 32 B, cadangan untuk steganografi
    vigenere_key: bytes = field(repr=False)  # 16 B, kunci Vigenere level byte


def new_salt(n: int = SALT_LEN) -> bytes:
    """Salt acak (os.urandom)."""
    return os.urandom(n)


def hash_password(password: str) -> str:
    """Hash Argon2id (string siap simpan di tabel users.password_hash)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True bila cocok. Tidak melempar exception untuk password salah / hash rusak."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def derive_pw_key(password: str, salt_kdf: bytes) -> bytes:
    """Argon2id raw (32 B) dari password. Salt BERBEDA dari salt hash password."""
    if len(salt_kdf) < 8:
        raise ValueError("salt_kdf minimal 8 byte")
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt_kdf,
        time_cost=config.ARGON2_TIME_COST,
        memory_cost=config.ARGON2_MEMORY_KIB,
        parallelism=config.ARGON2_PARALLELISM,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def _hkdf(key_material: bytes, info: bytes, length: int = KEY_LEN) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(key_material)


def derive_master_key(pw_key: bytes, dongle_key: bytes) -> bytes:
    """HKDF-SHA256(pw_key || dongle_key) -> 32 B."""
    if len(pw_key) != KEY_LEN or len(dongle_key) != config.DONGLE_KEY_BYTES:
        raise ValueError("panjang pw_key atau dongle_key tidak sesuai")
    return _hkdf(pw_key + dongle_key, b"brankas/master/v1")


def derive_keyset(master_key: bytes) -> KeySet:
    """Turunkan semua subkunci dengan label HKDF berbeda."""
    if len(master_key) != KEY_LEN:
        raise ValueError("master_key harus 32 byte")
    return KeySet(
        k_text=_hkdf(master_key, b"brankas/text/v1"),
        k_file=_hkdf(master_key, b"brankas/file/v1"),
        k_db=_hkdf(master_key, b"brankas/db/v1"),
        k_stego=_hkdf(master_key, b"brankas/stego/v1"),
        vigenere_key=_hkdf(master_key, b"brankas/vigenere/v1", VIGENERE_KEY_LEN),
    )


def derive_username_key(dongle_key: bytes) -> bytes:
    """HKDF(dongle_key, info=b'brankas/username/v1') -> 32 B. Untuk enkripsi username di tabel users
    (dibuka begitu dongle dikenali, sebelum wajah dan password)."""
    if len(dongle_key) != config.DONGLE_KEY_BYTES:
        raise ValueError("dongle_key harus 32 byte")
    return _hkdf(dongle_key, b"brankas/username/v1")


def derive_face_key(dongle_key: bytes) -> bytes:
    """HKDF(dongle_key, info=b'brankas/face/v1') -> 32 B. Untuk enkripsi encoding wajah
    (dipakai SEBELUM password diketahui)."""
    if len(dongle_key) != config.DONGLE_KEY_BYTES:
        raise ValueError("dongle_key harus 32 byte")
    return _hkdf(dongle_key, b"brankas/face/v1")
