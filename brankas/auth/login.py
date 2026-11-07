"""Alur login 3 lapis + registrasi. Pemilik: Anggota A.

Session adalah satu-satunya objek yang dibawa UI dan modul storage.
UI tidak boleh meng-import brankas.core.* langsung.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from brankas import config
from brankas.auth import dongle, face
from brankas.auth.dongle import DongleInfo
from brankas.core import crypto, keys
from brankas.core.keys import KeySet
from brankas.errors import (
    BrankasError,
    DongleMismatch,
    DongleNotFound,
    InvalidInput,
    WrongPassword,
)
from brankas.storage import db


@dataclass
class Session:
    user_id: int
    username: str
    keys: KeySet
    dongle: DongleInfo


class LoginFlow:
    """Panggil berurutan: step_dongle -> step_face -> step_password.
    Setiap step melempar subclass BrankasError bila gagal."""

    def __init__(self) -> None:
        self._dongle_info: DongleInfo | None = None
        self._user_row: dict[str, Any] | None = None
        self._face_verified: bool = False

    @property
    def recognized_username(self) -> str | None:
        return self._user_row["username"] if self._user_row else None

    def step_dongle(self, custom_path: str | None = None) -> DongleInfo:
        """Cari dongle, cocokkan serial dengan DB (mengenali user).
        DongleNotFound / DongleMismatch."""
        if custom_path:
            p = Path(custom_path)
            key_file = p / config.DONGLE_FILENAME
            if not key_file.is_file():
                try:
                    for sub in p.iterdir():
                        if sub.is_dir() and (sub / config.DONGLE_FILENAME).is_file():
                            key_file = sub / config.DONGLE_FILENAME
                            break
                except Exception:
                    pass
            if not key_file.is_file():
                raise DongleNotFound(f"Berkas {config.DONGLE_FILENAME} tidak ditemukan di {custom_path}")

            mount = dongle._normalize_drive(custom_path)
            try:
                import win32api
                vol_info = win32api.GetVolumeInformation(mount)
                serial_val = vol_info[1] & 0xFFFFFFFF
                serial_str = f"{serial_val:08X}"
            except Exception:
                serial_str = "DEV00001"
            import hashlib
            serial_hash = hashlib.sha256(serial_str.encode("utf-8")).hexdigest()
            dongle_info = DongleInfo(drive=str(p), serial=serial_str, serial_hash=serial_hash, key=key_file.read_bytes())
        else:
            dongle_info = dongle.find_dongle()
            if not dongle_info:
                raise DongleNotFound("Flashdisk dongle tidak ditemukan. Pastikan flashdisk terpasang.")

        with db.transaction() as conn:
            row = db.get_user_by_dongle(conn, dongle_info.serial_hash)

        if not row:
            raise DongleMismatch("Dongle tidak dikenali atau belum terdaftar untuk pengguna manapun.")

        self._dongle_info = dongle_info
        self._user_row = dict(row)
        self._face_verified = False
        return dongle_info

    def step_face(self, frame: np.ndarray) -> bool:
        """Dekripsi encoding dengan derive_face_key(dongle.key), lalu face.verify.
        Mengembalikan True/False; batas percobaan (FACE_MAX_ATTEMPTS) dijaga UI."""
        if not self._dongle_info or not self._user_row:
            raise BrankasError("Harap hubungkan dan verifikasi dongle terlebih dahulu.")

        k_face = keys.derive_face_key(self._dongle_info.key)
        stored_face_bytes = crypto.aes_decrypt(self._user_row["face_enc"], k_face)

        matched = face.verify(frame, stored_face_bytes, tolerance=config.FACE_TOLERANCE)
        if matched:
            self._face_verified = True
        return matched

    def step_password(self, password: str) -> Session:
        """verify_password lalu derive master key & KeySet. WrongPassword bila salah."""
        if not self._dongle_info or not self._user_row:
            raise BrankasError("Harap selesaikan verifikasi dongle terlebih dahulu.")
        if not self._face_verified:
            raise BrankasError("Verifikasi wajah belum berhasil.")

        if not keys.verify_password(self._user_row["password_hash"], password):
            raise WrongPassword("Password salah.")

        pw_key = keys.derive_pw_key(password, self._user_row["salt_kdf"])
        master_key = keys.derive_master_key(pw_key, self._dongle_info.key)
        key_set = keys.derive_keyset(master_key)

        return Session(
            user_id=self._user_row["id"],
            username=self._user_row["username"],
            keys=key_set,
            dongle=self._dongle_info,
        )


def register(username: str, password: str, drive: str,
             face_frames: list[np.ndarray]) -> Session:
    """Registrasi akun baru: provision dongle, enroll wajah, simpan user. UserExists bila duplikat."""
    username = username.strip()
    if not username:
        raise InvalidInput("Username tidak boleh kosong")
    if not password:
        raise InvalidInput("Password tidak boleh kosong")
    if not face_frames:
        raise InvalidInput("Dibutuhkan minimal satu sampel wajah untuk registrasi")

    # Cek apakah username sudah ada sebelum mengubah dongle
    with db.transaction() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            from brankas.errors import UserExists
            raise UserExists(f"Username '{username}' sudah terdaftar")

    # 1. Provision dongle
    dongle_info = dongle.provision_dongle(drive)

    # 2. Enroll wajah
    face_bytes = face.enroll(face_frames)
    k_face = keys.derive_face_key(dongle_info.key)
    face_enc = crypto.aes_encrypt(face_bytes, k_face)

    # 3. Kunci dan password
    password_hash = keys.hash_password(password)
    salt_kdf = keys.new_salt()
    pw_key = keys.derive_pw_key(password, salt_kdf)
    master_key = keys.derive_master_key(pw_key, dongle_info.key)
    key_set = keys.derive_keyset(master_key)

    # 4. Simpan ke database
    with db.transaction() as conn:
        user_id = db.create_user(
            conn,
            username=username,
            password_hash=password_hash,
            salt_kdf=salt_kdf,
            dongle_serial_hash=dongle_info.serial_hash,
            face_enc=face_enc,
        )

    return Session(
        user_id=user_id,
        username=username,
        keys=key_set,
        dongle=dongle_info,
    )
