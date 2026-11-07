"""Tes alur autentikasi Brankas (dongle, face, login, registrasi)."""
from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from brankas import config
from brankas.auth import dongle, face, login
from brankas.errors import (
    BrankasError,
    DongleMismatch,
    DongleNotFound,
    InvalidInput,
    NoFaceDetected,
    SessionLocked,
    UserExists,
    WrongPassword,
)
from brankas.storage import db

VEC_ALICE = np.ones(128, dtype=np.float64) / np.sqrt(128)
VEC_BOB = -np.ones(128, dtype=np.float64) / np.sqrt(128)
FRAME = np.zeros((100, 100, 3), dtype=np.uint8)


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test.db"
        self.dongle_dir = self.temp_dir / "usb_drive"
        self.dongle_dir.mkdir()

        # Alihkan DB dan Dev Dongle
        self.orig_db = config.DB_PATH
        config.DB_PATH = self.db_path
        os.environ["BRANKAS_DEV_DONGLE_DIR"] = str(self.dongle_dir)
        login.reset_lockouts()

    def tearDown(self):
        login.reset_lockouts()          # masih menunjuk DB sementara
        config.DB_PATH = self.orig_db
        os.environ.pop("BRANKAS_DEV_DONGLE_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def register_alice(self, drive=None):
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            return login.register("alice", "password-rahasia", drive or str(self.dongle_dir), [FRAME])

    # ---------------------------------------------------------------- dongle
    def test_dongle_provision_and_presence(self):
        info = dongle.provision_dongle(str(self.dongle_dir))
        self.assertEqual(len(info.key), 32)
        self.assertTrue((self.dongle_dir / config.DONGLE_FILENAME).is_file())
        self.assertTrue(dongle.is_present(info))

        found = dongle.find_dongle()
        self.assertIsNotNone(found)
        self.assertEqual(found.serial, info.serial)
        self.assertEqual(found.key, info.key)

    def test_dongle_not_found_when_empty(self):
        empty_dir = self.temp_dir / "empty_usb"
        empty_dir.mkdir()
        os.environ["BRANKAS_DEV_DONGLE_DIR"] = str(empty_dir)

        flow = login.LoginFlow()
        with self.assertRaises(DongleNotFound):
            flow.step_dongle()

    def test_dongle_mismatch_unregistered(self):
        dongle.provision_dongle(str(self.dongle_dir))
        flow = login.LoginFlow()
        with self.assertRaises(DongleMismatch):
            flow.step_dongle()

    def test_provision_never_overwrites_existing_key(self):
        info = dongle.provision_dongle(str(self.dongle_dir))
        with self.assertRaises(BrankasError):
            dongle.provision_dongle(str(self.dongle_dir))
        self.assertEqual((self.dongle_dir / config.DONGLE_FILENAME).read_bytes(), info.key)

    def test_is_present_false_after_removal(self):
        info = dongle.provision_dongle(str(self.dongle_dir))
        (self.dongle_dir / config.DONGLE_FILENAME).unlink()
        self.assertFalse(dongle.is_present(info))

    def test_is_present_false_if_key_changed(self):
        info = dongle.provision_dongle(str(self.dongle_dir))
        (self.dongle_dir / config.DONGLE_FILENAME).write_bytes(os.urandom(32))
        self.assertFalse(dongle.is_present(info))

    def test_non_removable_drive_rejected(self):
        # "C:\Windows" bukan flashdisk removable dan bukan folder dev
        with self.assertRaises(DongleNotFound):
            dongle.load_dongle("C:\\Windows")

    # ---------------------------------------------------------------- wajah
    def test_face_enroll_and_verify(self):
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            stored = face.enroll([FRAME, FRAME])
            self.assertEqual(len(stored), 1024)
            self.assertTrue(face.verify(FRAME, stored))
            self.assertAlmostEqual(face.distance(FRAME, stored), 0.0, places=6)

    def test_face_enroll_is_not_normalized(self):
        raw = VEC_ALICE * 0.8   # norma 0.8, bukan 1
        with patch("brankas.auth.face.encode_face", return_value=raw):
            stored = face.enroll([FRAME])
            self.assertTrue(np.allclose(np.frombuffer(stored, dtype=np.float64), raw))
            self.assertAlmostEqual(face.distance(FRAME, stored), 0.0, places=6)

    # ---------------------------------------------------------------- alur lengkap
    def test_full_register_and_login_flow(self):
        session = self.register_alice()
        self.assertEqual(session.username, "alice")
        self.assertIsNotNone(session.keys)

        # Registrasi ulang dengan username yang sama harus gagal
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            with self.assertRaises(UserExists):
                login.register("alice", "password-dua", str(self.dongle_dir), [FRAME])

        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            flow = login.LoginFlow()
            flow.step_dongle()
            self.assertEqual(flow.recognized_username, "alice")
            self.assertTrue(flow.step_face(FRAME))
            self.assertIsNotNone(flow.last_face_distance)

            logged_session = flow.step_password("password-rahasia")
            self.assertEqual(logged_session.username, "alice")
            self.assertEqual(logged_session.keys.k_file, session.keys.k_file)

            flow_wrong_pw = login.LoginFlow()
            flow_wrong_pw.step_dongle()
            flow_wrong_pw.step_face(FRAME)
            with self.assertRaises(WrongPassword):
                flow_wrong_pw.step_password("password-salah")

    def test_custom_path_login(self):
        self.register_alice()
        flow = login.LoginFlow()
        info = flow.step_dongle(custom_path=str(self.dongle_dir))   # dulu: NameError (Path)
        self.assertEqual(flow.recognized_username, "alice")
        self.assertEqual(info.serial, dongle.DEV_SERIAL)

    def test_face_mismatch_during_login(self):
        self.register_alice()
        with patch("brankas.auth.face.encode_face", return_value=VEC_BOB):
            flow = login.LoginFlow()
            flow.step_dongle()
            self.assertFalse(flow.step_face(FRAME))
            with self.assertRaises(BrankasError):
                flow.step_password("password-rahasia")

    def test_no_face_is_not_a_failed_attempt(self):
        self.register_alice()
        flow = login.LoginFlow()
        flow.step_dongle()
        with patch("brankas.auth.face.encode_face", side_effect=NoFaceDetected("kosong")):
            for _ in range(config.FACE_MAX_ATTEMPTS + 2):
                with self.assertRaises(NoFaceDetected):
                    flow.step_face(FRAME)
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            self.assertTrue(flow.step_face(FRAME))   # tidak terkunci

    def test_face_lockout_survives_new_flow(self):
        self.register_alice()
        with patch("brankas.auth.face.encode_face", return_value=VEC_BOB):
            flow = login.LoginFlow()
            flow.step_dongle()
            for _ in range(config.FACE_MAX_ATTEMPTS):
                self.assertFalse(flow.step_face(FRAME))
        # wajah yang benar pun ditolak selama terkunci, juga lewat LoginFlow baru
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            flow2 = login.LoginFlow()
            flow2.step_dongle()
            with self.assertRaises(BrankasError) as ctx:
                flow2.step_face(FRAME)
            self.assertIn("Terlalu banyak", str(ctx.exception))

    def test_password_lockout(self):
        self.register_alice()
        with patch.object(config, "PASSWORD_MAX_ATTEMPTS", 2, create=True), \
             patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            flow = login.LoginFlow()
            flow.step_dongle()
            flow.step_face(FRAME)
            for _ in range(2):
                with self.assertRaises(WrongPassword):
                    flow.step_password("salah")
            with self.assertRaises(BrankasError) as ctx:
                flow.step_password("password-rahasia")   # benar pun ditolak saat terkunci
            self.assertIn("Terlalu banyak", str(ctx.exception))

    # ---------------------------------------------------------------- registrasi aman
    def test_second_account_cannot_clobber_first_dongle(self):
        first = self.register_alice()
        key_before = (self.dongle_dir / config.DONGLE_FILENAME).read_bytes()
        with patch("brankas.auth.face.encode_face", return_value=VEC_BOB):
            with self.assertRaises(BrankasError):
                login.register("bob", "password-bob", str(self.dongle_dir), [FRAME])
        self.assertEqual((self.dongle_dir / config.DONGLE_FILENAME).read_bytes(), key_before)
        # akun pertama masih bisa masuk dan kuncinya sama
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            flow = login.LoginFlow()
            flow.step_dongle()
            flow.step_face(FRAME)
            self.assertEqual(flow.step_password("password-rahasia").keys.k_file, first.keys.k_file)

    def test_register_without_face_writes_no_dongle(self):
        with patch("brankas.auth.face.encode_face", side_effect=NoFaceDetected("kosong")):
            with self.assertRaises(NoFaceDetected):
                login.register("alice", "password-pw1", str(self.dongle_dir), [FRAME])
        self.assertFalse((self.dongle_dir / config.DONGLE_FILENAME).exists())

    def test_register_db_failure_removes_new_dongle(self):
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE), \
             patch("brankas.auth.login.db.create_user", side_effect=UserExists("x")):
            with self.assertRaises(UserExists):
                login.register("alice", "password-pw1", str(self.dongle_dir), [FRAME])
        self.assertFalse((self.dongle_dir / config.DONGLE_FILENAME).exists())

    def test_invalid_register_inputs(self):
        with self.assertRaises(InvalidInput):
            login.register("", "password-ok-1", str(self.dongle_dir), [FRAME])
        with self.assertRaises(InvalidInput):
            login.register("user", "", str(self.dongle_dir), [FRAME])
        with self.assertRaises(InvalidInput):
            login.register("user", "password-ok-1", str(self.dongle_dir), [])

    # ---------------------------------------------------------------- kebijakan password
    def test_password_policy(self):
        n = config.PASSWORD_MIN_LENGTH
        self.assertEqual(n, 8)
        self.assertIsNone(login.password_problem("x" * n))
        self.assertIsNone(login.password_problem("kata sandi yang panjang"))
        self.assertIn("kosong", login.password_problem(""))
        msg = login.password_problem("x" * (n - 1))
        self.assertIn("minimal 8", msg)
        self.assertIn("saat ini 7", msg)
        self.assertIn("spasi", login.password_problem(" " * n))

    def test_register_rejects_short_password_without_side_effects(self):
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            with self.assertRaises(InvalidInput) as ctx:
                login.register("alice", "pendek", str(self.dongle_dir), [FRAME])
        self.assertIn("minimal 8", str(ctx.exception))
        self.assertFalse((self.dongle_dir / config.DONGLE_FILENAME).exists())   # dongle tidak ditulis
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_register_accepts_exactly_min_length(self):
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            session = login.register("alice", "12345678", str(self.dongle_dir), [FRAME])   # tepat 8 karakter
        self.assertEqual(session.username, "alice")

    # ---------------------------------------------------------------- penguncian sesi
    def test_session_lock_releases_keys(self):
        session = self.register_alice()
        self.assertFalse(session.locked)
        self.assertEqual(len(session.keys.k_file), 32)
        self.assertEqual(len(session.dongle.key), 32)

        session.lock()
        self.assertTrue(session.locked)
        with self.assertRaises(SessionLocked):
            session.keys
        with self.assertRaises(SessionLocked):
            session.dongle
        session.lock()   # idempoten
        self.assertEqual(session.username, "alice")
        self.assertNotIn("k_file", repr(session))

    def test_locked_session_cannot_use_storage(self):
        from brankas.storage import notes
        session = self.register_alice()
        notes.add_note(session, "rahasia sebelum kunci")
        session.lock()
        with self.assertRaises(SessionLocked):
            notes.list_notes(session)
        with self.assertRaises(SessionLocked):
            notes.add_note(session, "tidak boleh")

    def test_login_flow_clear(self):
        self.register_alice()
        flow = login.LoginFlow()
        flow.step_dongle()
        self.assertEqual(flow.recognized_username, "alice")
        flow.clear()
        self.assertIsNone(flow.recognized_username)
        with self.assertRaises(BrankasError):
            flow.step_face(FRAME)
        with self.assertRaises(BrankasError):
            flow.step_password("password-rahasia")

    # ---------------------------------------------------------------- lockout tahan restart
    def test_lockout_is_stored_in_database(self):
        import time as _time
        self.register_alice()
        with patch("brankas.auth.face.encode_face", return_value=VEC_BOB):
            flow = login.LoginFlow()
            flow.step_dongle()
            for _ in range(config.FACE_MAX_ATTEMPTS):
                flow.step_face(FRAME)
        with db.transaction() as conn:
            uid = db.get_user_by_dongle(conn, dongle.find_dongle().serial_hash)["id"]
            failures, locked_until = db.get_lockout(conn, f"face:{uid}")
        self.assertEqual(failures, 0)                       # hitungan direset saat terkunci
        self.assertGreater(locked_until, _time.time())      # tapi waktu kunci tercatat di DB

    def test_lockout_survives_process_restart(self):
        """Simulasi restart: tidak ada status di memori yang tersisa; hanya isi DB yang menentukan."""
        self.register_alice()
        with patch("brankas.auth.face.encode_face", return_value=VEC_BOB):
            flow = login.LoginFlow()
            flow.step_dongle()
            for _ in range(config.FACE_MAX_ATTEMPTS):
                flow.step_face(FRAME)
        # "proses baru": objek pembatas dibuat ulang dari nol
        fresh = login._Lockout("face", "FACE_MAX_ATTEMPTS", 3, "FACE_LOCKOUT_SECONDS", 30.0, "verifikasi wajah")
        with db.transaction() as conn:
            uid = db.get_user_by_dongle(conn, dongle.find_dongle().serial_hash)["id"]
        with self.assertRaises(BrankasError) as ctx:
            fresh.check(uid)
        self.assertIn("Terlalu banyak", str(ctx.exception))

    def test_lockout_expires(self):
        import time as _time
        self.register_alice()
        with patch("brankas.auth.face.encode_face", return_value=VEC_BOB):
            flow = login.LoginFlow()
            flow.step_dongle()
            for _ in range(config.FACE_MAX_ATTEMPTS):
                flow.step_face(FRAME)
        later = _time.time() + config.FACE_LOCKOUT_SECONDS + 5
        with patch("brankas.auth.login.time.time", return_value=later), \
             patch("brankas.auth.face.encode_face", return_value=VEC_ALICE):
            self.assertTrue(flow.step_face(FRAME))

    def test_lockout_remaining_is_clamped(self):
        """Jam sistem yang dimajukan lalu dikembalikan tidak boleh mengunci lebih lama dari durasi kunci."""
        import time as _time
        lock = login._Lockout("face", "FACE_MAX_ATTEMPTS", 3, "FACE_LOCKOUT_SECONDS", 30.0, "verifikasi wajah")
        with db.transaction() as conn:
            db.set_lockout(conn, "face:7", 0, _time.time() + 100000)
        with self.assertRaises(BrankasError) as ctx:
            lock.check(7)
        detik = int(str(ctx.exception).split("dalam ")[1].split(" detik")[0])
        self.assertLessEqual(detik, int(config.FACE_LOCKOUT_SECONDS) + 1)

    def test_lockout_is_per_user(self):
        lock = login._Lockout("password", "PASSWORD_MAX_ATTEMPTS", 5, "PASSWORD_LOCKOUT_SECONDS", 30.0, "password")
        with patch.object(config, "PASSWORD_MAX_ATTEMPTS", 2):
            lock.fail(1)
            lock.fail(1)
            with self.assertRaises(BrankasError):
                lock.check(1)
            lock.check(2)   # pengguna lain tidak ikut terkunci
        lock.ok(1)
        lock.check(1)       # ok() membersihkan kunci

    def test_success_resets_failure_count(self):
        lock = login._Lockout("password", "PASSWORD_MAX_ATTEMPTS", 5, "PASSWORD_LOCKOUT_SECONDS", 30.0, "password")
        with patch.object(config, "PASSWORD_MAX_ATTEMPTS", 3):
            lock.fail(1)
            lock.fail(1)
            lock.ok(1)
            lock.fail(1)
            lock.fail(1)
            lock.check(1)   # baru 2 gagal berturut-turut setelah reset: belum terkunci


if __name__ == "__main__":
    unittest.main()
