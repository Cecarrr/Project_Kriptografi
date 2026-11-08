"""Alur login 3 lapis + registrasi. Pemilik: Anggota A.

Session adalah satu-satunya objek yang dibawa UI dan modul storage.
UI tidak boleh meng-import brankas.core.* langsung.
"""
from __future__ import annotations

import time
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
    UserExists,
    WrongPassword,
)
from brankas.storage import db


@dataclass
class Session:
    user_id: int
    username: str
    keys: KeySet
    dongle: DongleInfo


class _Lockout:
    """Pembatas percobaan: setelah N kegagalan berturut-turut, terkunci beberapa detik.
    Berlaku selama proses berjalan (tidak bisa dihindari dengan membuka ulang kamera
    atau membuat LoginFlow baru)."""

    def __init__(self, max_attr: str, default_max: int, seconds_attr: str,
                 default_seconds: float, label: str) -> None:
        self._max_attr, self._default_max = max_attr, default_max
        self._seconds_attr, self._default_seconds = seconds_attr, default_seconds
        self._label = label
        self.failures = 0
        self.locked_until = 0.0

    def check(self) -> None:
        remaining = self.locked_until - time.monotonic()
        if remaining > 0:
            raise BrankasError(
                f"Terlalu banyak percobaan {self._label} yang gagal. "
                f"Coba lagi dalam {int(remaining) + 1} detik."
            )

    def fail(self) -> None:
        self.failures += 1
        if self.failures >= int(getattr(config, self._max_attr, self._default_max)):
            seconds = float(getattr(config, self._seconds_attr, self._default_seconds))
            self.locked_until = time.monotonic() + seconds
            self.failures = 0

    def ok(self) -> None:
        self.failures = 0
        self.locked_until = 0.0


_face_lock = _Lockout("FACE_MAX_ATTEMPTS", 3, "FACE_LOCKOUT_SECONDS", 30.0, "verifikasi wajah")
_password_lock = _Lockout("PASSWORD_MAX_ATTEMPTS", 5, "PASSWORD_LOCKOUT_SECONDS", 30.0, "password")


def reset_lockouts() -> None:
    """Hapus status kunci percobaan (dipakai tes)."""
    _face_lock.ok()
    _password_lock.ok()


class LoginFlow:
    """Panggil berurutan: step_dongle -> step_face -> step_password.
    Setiap step melempar subclass BrankasError bila gagal."""

    def __init__(self) -> None:
        self._dongle_info: DongleInfo | None = None
        self._user_row: dict[str, Any] | None = None
        self._face_verified: bool = False
        self.last_face_distance: float | None = None   # jarak wajah terakhir (untuk ditampilkan saat demo)

    @property
    def recognized_username(self) -> str | None:
        return self._user_row["username"] if self._user_row else None

    def step_dongle(self, custom_path: str | None = None) -> DongleInfo:
        """Cari dongle, cocokkan serial dengan DB (mengenali user).
        DongleNotFound / DongleMismatch."""
        if custom_path:
            dongle_info = dongle.load_dongle(custom_path)
        else:
            dongle_info = dongle.find_dongle()
            if not dongle_info:
                d = dongle.dev_dir()
                if d is not None:
                    raise DongleNotFound(
                        f"Berkas {config.DONGLE_FILENAME} tidak ditemukan di folder development ({d})."
                    )
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
        """Dekripsi encoding dengan derive_face_key(dongle.key), lalu bandingkan wajah.
        True/False untuk cocok/tidak. NoFaceDetected (tidak ada wajah di frame) dilempar ke UI
        dan TIDAK dihitung sebagai percobaan gagal. Setelah FACE_MAX_ATTEMPTS gagal berturut-turut,
        step ini terkunci FACE_LOCKOUT_SECONDS detik."""
        if not self._dongle_info or not self._user_row:
            raise BrankasError("Harap hubungkan dan verifikasi dongle terlebih dahulu.")
        _face_lock.check()

        k_face = keys.derive_face_key(self._dongle_info.key)
        stored_face_bytes = crypto.aes_decrypt(self._user_row["face_enc"], k_face)

        dist = face.distance(frame, stored_face_bytes)
        self.last_face_distance = dist
        matched = dist <= config.FACE_TOLERANCE
        if matched:
            self._face_verified = True
            _face_lock.ok()
        else:
            self._face_verified = False
            _face_lock.fail()
        return matched

    def step_password(self, password: str) -> Session:
        """verify_password lalu derive master key & KeySet. WrongPassword bila salah.
        Setelah PASSWORD_MAX_ATTEMPTS gagal berturut-turut, terkunci PASSWORD_LOCKOUT_SECONDS detik."""
        if not self._dongle_info or not self._user_row:
            raise BrankasError("Harap selesaikan verifikasi dongle terlebih dahulu.")
        if not self._face_verified:
            raise BrankasError("Verifikasi wajah belum berhasil.")
        _password_lock.check()

        if not keys.verify_password(self._user_row["password_hash"], password):
            _password_lock.fail()
            raise WrongPassword("Password salah.")
        _password_lock.ok()

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
    """Registrasi akun baru: enroll wajah, tulis dongle, simpan user. UserExists bila duplikat.

    Urutan sengaja dibuat aman: semua pemeriksaan dan langkah yang bisa gagal dilakukan SEBELUM
    dongle.key ditulis, dan dongle.key yang baru ditulis dihapus lagi bila penyimpanan gagal.
    dongle.key yang sudah ada tidak pernah ditimpa."""
    username = username.strip()
    if not username:
        raise InvalidInput("Username tidak boleh kosong")
    if not password:
        raise InvalidInput("Password tidak boleh kosong")
    if not face_frames:
        raise InvalidInput("Dibutuhkan minimal satu sampel wajah untuk registrasi")

    # 1. Pemeriksaan tanpa menulis apa pun
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise UserExists(f"Username '{username}' sudah terdaftar")
    serial_hash = dongle.preflight(drive)    # drive valid? removable? belum berisi dongle.key?
    with db.transaction() as conn:
        if db.get_user_by_dongle(conn, serial_hash):
            raise UserExists("Flashdisk ini sudah terdaftar untuk pengguna lain")

    # 2. Wajah (bisa gagal bila tidak ada wajah; belum ada yang tertulis)
    face_bytes = face.enroll(face_frames)

    # 3. Tulis dongle, lalu simpan; bersihkan dongle bila gagal
    dongle_info = dongle.provision_dongle(drive)
    try:
        k_face = keys.derive_face_key(dongle_info.key)
        face_enc = crypto.aes_encrypt(face_bytes, k_face)

        password_hash = keys.hash_password(password)
        salt_kdf = keys.new_salt()
        pw_key = keys.derive_pw_key(password, salt_kdf)
        master_key = keys.derive_master_key(pw_key, dongle_info.key)
        key_set = keys.derive_keyset(master_key)

        with db.transaction() as conn:
            user_id = db.create_user(
                conn,
                username=username,
                password_hash=password_hash,
                salt_kdf=salt_kdf,
                dongle_serial_hash=dongle_info.serial_hash,
                face_enc=face_enc,
            )
    except BaseException:
        dongle.discard_dongle(dongle_info)
        raise

    return Session(user_id=user_id, username=username, keys=key_set, dongle=dongle_info)
