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
    UserExists,
    WrongPassword,
)
from brankas.storage import db


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

    def tearDown(self):
        config.DB_PATH = self.orig_db
        os.environ.pop("BRANKAS_DEV_DONGLE_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

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

    def test_face_enroll_and_verify(self):
        mock_vec = np.ones(128, dtype=np.float64) / np.sqrt(128)
        with patch("brankas.auth.face.encode_face", return_value=mock_vec):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            stored = face.enroll([frame, frame])
            self.assertEqual(len(stored), 1024)
            self.assertTrue(face.verify(frame, stored))

    def test_full_register_and_login_flow(self):
        mock_vec = np.ones(128, dtype=np.float64) / np.sqrt(128)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        with patch("brankas.auth.face.encode_face", return_value=mock_vec):
            # 1. Registrasi
            session = login.register(
                username="alice",
                password="password-rahasia",
                drive=str(self.dongle_dir),
                face_frames=[frame],
            )
            self.assertEqual(session.username, "alice")
            self.assertIsNotNone(session.keys)

            # Registrasi ulang dengan username yang sama harus gagal
            with self.assertRaises(UserExists):
                login.register(
                    username="alice",
                    password="password2",
                    drive=str(self.dongle_dir),
                    face_frames=[frame],
                )

            # 2. Login Flow Sukses
            flow = login.LoginFlow()
            d_info = flow.step_dongle()
            self.assertEqual(flow.recognized_username, "alice")

            face_ok = flow.step_face(frame)
            self.assertTrue(face_ok)

            logged_session = flow.step_password("password-rahasia")
            self.assertEqual(logged_session.username, "alice")
            self.assertEqual(logged_session.keys.k_file, session.keys.k_file)

            # 3. Login Flow Password Salah
            flow_wrong_pw = login.LoginFlow()
            flow_wrong_pw.step_dongle()
            flow_wrong_pw.step_face(frame)
            with self.assertRaises(WrongPassword):
                flow_wrong_pw.step_password("password-salah")

    def test_face_mismatch_during_login(self):
        vec_alice = np.ones(128, dtype=np.float64) / np.sqrt(128)
        vec_bob = -np.ones(128, dtype=np.float64) / np.sqrt(128)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        with patch("brankas.auth.face.encode_face", return_value=vec_alice):
            login.register(
                username="alice",
                password="password-rahasia",
                drive=str(self.dongle_dir),
                face_frames=[frame],
            )

        with patch("brankas.auth.face.encode_face", return_value=vec_bob):
            flow = login.LoginFlow()
            flow.step_dongle()
            matched = flow.step_face(frame)
            self.assertFalse(matched)
            with self.assertRaises(BrankasError):
                flow.step_password("password-rahasia")

    def test_invalid_register_inputs(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        with self.assertRaises(InvalidInput):
            login.register("", "pass", str(self.dongle_dir), [frame])
        with self.assertRaises(InvalidInput):
            login.register("user", "", str(self.dongle_dir), [frame])
        with self.assertRaises(InvalidInput):
            login.register("user", "pass", str(self.dongle_dir), [])


if __name__ == "__main__":
    unittest.main()
