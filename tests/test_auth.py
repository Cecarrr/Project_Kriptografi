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
        config.DB_PATH = self.orig_db
        os.environ.pop("BRANKAS_DEV_DONGLE_DIR", None)
        login.reset_lockouts()
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
                login.register("alice", "password2", str(self.dongle_dir), [FRAME])

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
                login.register("alice", "pw", str(self.dongle_dir), [FRAME])
        self.assertFalse((self.dongle_dir / config.DONGLE_FILENAME).exists())

    def test_register_db_failure_removes_new_dongle(self):
        with patch("brankas.auth.face.encode_face", return_value=VEC_ALICE), \
             patch("brankas.auth.login.db.create_user", side_effect=UserExists("x")):
            with self.assertRaises(UserExists):
                login.register("alice", "pw", str(self.dongle_dir), [FRAME])
        self.assertFalse((self.dongle_dir / config.DONGLE_FILENAME).exists())

    def test_invalid_register_inputs(self):
        with self.assertRaises(InvalidInput):
            login.register("", "pass", str(self.dongle_dir), [FRAME])
        with self.assertRaises(InvalidInput):
            login.register("user", "", str(self.dongle_dir), [FRAME])
        with self.assertRaises(InvalidInput):
            login.register("user", "pass", str(self.dongle_dir), [])


if __name__ == "__main__":
    unittest.main()
