"""Alur login 3 lapis + registrasi. Pemilik: Anggota A.

Session adalah satu-satunya objek yang dibawa UI dan modul storage.
UI tidak boleh meng-import brankas.core.* langsung.
"""
from __future__ import annotations

import gc
import time
from typing import Any

import numpy as np

from brankas import config
from brankas.applog import get_logger
from brankas.auth import dongle, face
from brankas.auth.dongle import DongleInfo
from brankas.core import crypto, keys
from brankas.core.keys import KeySet
from brankas.errors import (
    BrankasError,
    DecryptionError,
    DongleMismatch,
    DongleNotFound,
    InvalidInput,
    SessionLocked,
    UserExists,
    WrongPassword,
)
from brankas.storage import audit, db

log = get_logger("login")


def _audit_event(user_id: int, action: str) -> None:
    """Catat peristiwa sesi (LOGIN / LOGOUT) di log audit. Sengaja tidak melempar error: kegagalan
    mencatat tidak boleh menggagalkan login, dan lock() harus selalu berhasil melepas kunci."""
    try:
        with db.transaction() as conn:
            audit.record(conn, user_id, action)
    except Exception:  # noqa: BLE001
        log.exception("gagal mencatat log audit action=%s user=%s", action, user_id)


class Session:
    """Sesi pengguna yang sudah masuk. Membawa KeySet dan DongleInfo (berisi dongle.key).

    lock() dipanggil saat logout / dongle dicabut / aplikasi ditutup: referensi kunci dilepas dan
    semua akses berikutnya ke `keys` atau `dongle` melempar SessionLocked, sehingga tampilan yang
    masih menggenggam objek ini tidak bisa lagi mendekripsi apa pun.

    Catatan jujur: Python memakai bytes yang immutable, jadi kunci tidak bisa ditimpa dengan nol di
    memori. lock() melepas semua referensi yang kita pegang lalu memanggil gc.collect(); salinan
    yang sudah dibuat pustaka kripto bisa saja masih tertinggal sampai memori dipakai ulang (best effort).
    """

    def __init__(self, user_id: int, username: str, keys: KeySet, dongle: DongleInfo) -> None:
        self.user_id = user_id
        self.username = username
        self._keys: KeySet | None = keys
        self._dongle: DongleInfo | None = dongle

    @property
    def locked(self) -> bool:
        return self._keys is None

    @property
    def keys(self) -> KeySet:
        if self._keys is None:
            raise SessionLocked("Sesi sudah dikunci. Silakan masuk kembali.")
        return self._keys

    @property
    def dongle(self) -> DongleInfo:
        if self._dongle is None:
            raise SessionLocked("Sesi sudah dikunci. Silakan masuk kembali.")
        return self._dongle

    def lock(self) -> None:
        """Lepas kunci dari sesi. Aman dipanggil berulang."""
        was_locked = self.locked
        self._keys = None
        self._dongle = None
        gc.collect()
        if not was_locked:
            log.info("sesi dikunci user=%s", self.user_id)
            _audit_event(self.user_id, "LOGOUT")

    def __repr__(self) -> str:   # tidak pernah mencetak kunci
        return f"Session(user_id={self.user_id!r}, username={self.username!r}, locked={self.locked})"


def password_problem(password: str) -> str | None:
    """Kebijakan password. Kembalikan pesan masalah (bahasa Indonesia, siap ditampilkan) atau None bila lolos."""
    if not password:
        return "Password tidak boleh kosong."
    if len(password) < config.PASSWORD_MIN_LENGTH:
        return (f"Password terlalu pendek: minimal {config.PASSWORD_MIN_LENGTH} karakter "
                f"(saat ini {len(password)}).")
    if not password.strip():
        return "Password tidak boleh hanya berisi spasi."
    return None


class _Lockout:
    """Pembatas percobaan per pengguna: setelah N kegagalan berturut-turut, terkunci beberapa detik.
    Status disimpan di tabel `lockouts` (SQLite), jadi tidak hilang bila aplikasi ditutup dan dibuka
    lagi atau LoginFlow baru dibuat. Waktu memakai epoch (time.time()) supaya bermakna antar-proses;
    sisa waktu dibatasi paling lama durasi kunci, agar jam sistem yang diubah tidak mengunci selamanya."""

    def __init__(self, kind: str, max_attr: str, default_max: int, seconds_attr: str,
                 default_seconds: float, label: str) -> None:
        self._kind = kind
        self._max_attr, self._default_max = max_attr, default_max
        self._seconds_attr, self._default_seconds = seconds_attr, default_seconds
        self._label = label

    def _key(self, user_id: int) -> str:
        return f"{self._kind}:{user_id}"

    def _max(self) -> int:
        return int(getattr(config, self._max_attr, self._default_max))

    def _seconds(self) -> float:
        return float(getattr(config, self._seconds_attr, self._default_seconds))

    def check(self, user_id: int) -> None:
        with db.transaction() as conn:
            _, locked_until = db.get_lockout(conn, self._key(user_id))
        remaining = min(locked_until - time.time(), self._seconds())
        if remaining > 0:
            raise BrankasError(
                f"Terlalu banyak percobaan {self._label} yang gagal. "
                f"Coba lagi dalam {int(remaining) + 1} detik."
            )

    def fail(self, user_id: int) -> None:
        key = self._key(user_id)
        with db.transaction() as conn:
            failures, locked_until = db.get_lockout(conn, key)
            failures += 1
            if failures >= self._max():
                locked_until = time.time() + self._seconds()
                failures = 0
                log.warning("%s terkunci %.0f detik user=%s", self._label, self._seconds(), user_id)
            db.set_lockout(conn, key, failures, locked_until)

    def ok(self, user_id: int) -> None:
        with db.transaction() as conn:
            db.clear_lockout(conn, self._key(user_id))


_face_lock = _Lockout("face", "FACE_MAX_ATTEMPTS", 3, "FACE_LOCKOUT_SECONDS", 30.0, "verifikasi wajah")
_password_lock = _Lockout("password", "PASSWORD_MAX_ATTEMPTS", 5, "PASSWORD_LOCKOUT_SECONDS", 30.0, "password")


def reset_lockouts() -> None:
    """Hapus semua status kunci percobaan di basis data yang sedang aktif (dipakai tes / pemulihan darurat)."""
    with db.transaction() as conn:
        db.clear_all_lockouts(conn)


class LoginFlow:
    """Panggil berurutan: step_dongle -> step_face -> step_password.
    Setiap step melempar subclass BrankasError bila gagal."""

    def __init__(self) -> None:
        self._dongle_info: DongleInfo | None = None
        self._user_row: dict[str, Any] | None = None
        self._username: str | None = None
        self._face_verified: bool = False
        self.last_face_distance: float | None = None   # jarak wajah terakhir (untuk ditampilkan saat demo)

    @property
    def recognized_username(self) -> str | None:
        return self._username

    def clear(self) -> None:
        """Lepas dongle.key, baris pengguna, dan status wajah dari alur ini (dipanggil saat layar login ditutup)."""
        self._dongle_info = None
        self._user_row = None
        self._username = None
        self._face_verified = False
        self.last_face_distance = None

    def step_dongle(self, custom_path: str | None = None) -> DongleInfo:
        """Cari dongle, cocokkan serial dengan DB (mengenali user).
        DongleNotFound / DongleMismatch."""
        if custom_path:
            dongle_info = dongle.load_dongle(custom_path)
        else:
            dongle_info = dongle.find_dongle()
            if not dongle_info:
                log.info("login: flashdisk dongle tidak ditemukan")
                d = dongle.dev_dir()
                if d is not None:
                    raise DongleNotFound(
                        f"Berkas {config.DONGLE_FILENAME} tidak ditemukan di folder development ({d})."
                    )
                raise DongleNotFound("Flashdisk dongle tidak ditemukan. Pastikan flashdisk terpasang.")

        with db.transaction() as conn:
            row = db.get_user_by_dongle(conn, dongle_info.serial_hash)
        if not row:
            log.warning("login: dongle tidak terdaftar untuk pengguna manapun")
            raise DongleMismatch("Dongle tidak dikenali atau belum terdaftar untuk pengguna manapun.")

        # Username tersimpan terenkripsi dengan kunci dari dongle.key: dibuka sekarang, sebelum wajah/password.
        # dongle.key yang salah (serial sama tetapi isi berbeda) ketahuan di langkah ini, bukan di langkah wajah.
        try:
            username = crypto.aes_decrypt(
                row["username_enc"], keys.derive_username_key(dongle_info.key)
            ).decode("utf-8")
        except (DecryptionError, UnicodeDecodeError):
            log.warning("login: dongle.key tidak cocok dengan akun user=%s", row["id"])
            raise DongleMismatch("Isi dongle.key tidak cocok dengan akun yang terdaftar untuk flashdisk ini.") from None

        self._dongle_info = dongle_info
        self._user_row = dict(row)
        self._username = username
        self._face_verified = False
        log.info("login: dongle dikenali user=%s", self._user_row["id"])
        return dongle_info

    def step_face(self, frame: np.ndarray) -> bool:
        """Dekripsi encoding dengan derive_face_key(dongle.key), lalu bandingkan wajah.
        True/False untuk cocok/tidak. NoFaceDetected (tidak ada wajah di frame) dilempar ke UI
        dan TIDAK dihitung sebagai percobaan gagal. Setelah FACE_MAX_ATTEMPTS gagal berturut-turut,
        step ini terkunci FACE_LOCKOUT_SECONDS detik."""
        if not self._dongle_info or not self._user_row:
            raise BrankasError("Harap hubungkan dan verifikasi dongle terlebih dahulu.")
        uid = self._user_row["id"]
        _face_lock.check(uid)

        k_face = keys.derive_face_key(self._dongle_info.key)
        stored_face_bytes = crypto.aes_decrypt(self._user_row["face_enc"], k_face)

        dist = face.distance(frame, stored_face_bytes)
        self.last_face_distance = dist
        matched = dist <= config.FACE_TOLERANCE
        log.info("login: verifikasi wajah user=%s cocok=%s jarak=%.3f", uid, matched, dist)
        if matched:
            self._face_verified = True
            _face_lock.ok(uid)
        else:
            self._face_verified = False
            _face_lock.fail(uid)
        return matched

    def step_password(self, password: str) -> Session:
        """verify_password lalu derive master key & KeySet. WrongPassword bila salah.
        Setelah PASSWORD_MAX_ATTEMPTS gagal berturut-turut, terkunci PASSWORD_LOCKOUT_SECONDS detik."""
        if not self._dongle_info or not self._user_row:
            raise BrankasError("Harap selesaikan verifikasi dongle terlebih dahulu.")
        if not self._face_verified:
            raise BrankasError("Verifikasi wajah belum berhasil.")
        uid = self._user_row["id"]
        _password_lock.check(uid)

        if not keys.verify_password(self._user_row["password_hash"], password):
            _password_lock.fail(uid)
            log.warning("login: password salah user=%s", uid)
            raise WrongPassword("Password salah.")
        _password_lock.ok(uid)

        pw_key = keys.derive_pw_key(password, self._user_row["salt_kdf"])
        master_key = keys.derive_master_key(pw_key, self._dongle_info.key)
        key_set = keys.derive_keyset(master_key)

        log.info("login: berhasil user=%s", uid)
        session = Session(
            user_id=self._user_row["id"],
            username=self._username or "",
            keys=key_set,
            dongle=self._dongle_info,
        )
        _audit_event(uid, "LOGIN")
        return session


def register(username: str, password: str, drive: str,
             face_frames: list[np.ndarray]) -> Session:
    """Registrasi akun baru: enroll wajah, tulis dongle, simpan user. UserExists bila flashdisk sudah terdaftar.

    Urutan sengaja dibuat aman: semua pemeriksaan dan langkah yang bisa gagal dilakukan SEBELUM
    dongle.key ditulis, dan dongle.key yang baru ditulis dihapus lagi bila penyimpanan gagal.
    dongle.key yang sudah ada tidak pernah ditimpa."""
    username = username.strip()
    if not username:
        raise InvalidInput("Username tidak boleh kosong")
    problem = password_problem(password)
    if problem:
        raise InvalidInput(problem)
    if not face_frames:
        raise InvalidInput("Dibutuhkan minimal satu sampel wajah untuk registrasi")

    # 1. Pemeriksaan tanpa menulis apa pun
    # Username tidak perlu unik (disimpan terenkripsi; satu dongle = satu akun, dijaga lewat serial dongle).
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
        username_enc = crypto.aes_encrypt(username.encode("utf-8"), keys.derive_username_key(dongle_info.key))

        password_hash = keys.hash_password(password)
        salt_kdf = keys.new_salt()
        pw_key = keys.derive_pw_key(password, salt_kdf)
        master_key = keys.derive_master_key(pw_key, dongle_info.key)
        key_set = keys.derive_keyset(master_key)

        with db.transaction() as conn:
            user_id = db.create_user(
                conn,
                username_enc=username_enc,
                password_hash=password_hash,
                salt_kdf=salt_kdf,
                dongle_serial_hash=dongle_info.serial_hash,
                face_enc=face_enc,
            )
    except BaseException:
        dongle.discard_dongle(dongle_info)
        raise

    log.info("registrasi: akun baru user=%s", user_id)
    session = Session(user_id=user_id, username=username, keys=key_set, dongle=dongle_info)
    _audit_event(user_id, "LOGIN")   # registrasi langsung membuka sesi
    return session
