"""Alur login 3 lapis + registrasi. Pemilik: Anggota A.

Session adalah satu-satunya objek yang dibawa UI dan modul storage.
UI tidak boleh meng-import brankas.core.* langsung.
"""
from dataclasses import dataclass

import numpy as np

from brankas.auth.dongle import DongleInfo
from brankas.core.keys import KeySet


@dataclass
class Session:
    user_id: int
    username: str
    keys: KeySet
    dongle: DongleInfo


class LoginFlow:
    """Panggil berurutan: step_dongle -> step_face -> step_password.
    Setiap step melempar subclass BrankasError bila gagal."""

    def step_dongle(self) -> DongleInfo:
        """Cari dongle, cocokkan serial dengan DB (mengenali user).
        DongleNotFound / DongleMismatch."""
        raise NotImplementedError

    def step_face(self, frame: np.ndarray) -> bool:
        """Dekripsi encoding dengan derive_face_key(dongle.key), lalu face.verify.
        Mengembalikan True/False; batas percobaan (FACE_MAX_ATTEMPTS) dijaga UI."""
        raise NotImplementedError

    def step_password(self, password: str) -> Session:
        """verify_password lalu derive master key & KeySet. WrongPassword bila salah."""
        raise NotImplementedError


def register(username: str, password: str, drive: str,
             face_frames: list[np.ndarray]) -> Session:
    """Registrasi akun baru: provision dongle, enroll wajah, simpan user. UserExists bila duplikat."""
    raise NotImplementedError
