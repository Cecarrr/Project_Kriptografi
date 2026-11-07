"""Tes modul steganografi LSB PNG. Jalankan: python -m unittest tests/test_stego.py"""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from brankas.core import keys
from brankas.errors import (
    DecryptionError,
    InvalidInput,
    ItemNotFound,
    StegoCapacityError,
    StegoNotFound,
    UnsupportedFileType,
)
from brankas.stego import lsb


class DummySession:
    def __init__(self, key_set):
        self.user_id = 1
        self.username = "tester"
        self.keys = key_set


class TestStegoLsb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        # Buat gambar PNG uji berukuran 60x60 RGB
        self.cover_path = self.temp_dir / "cover.png"
        img = Image.new("RGB", (60, 60), color=(120, 150, 180))
        img.save(self.cover_path, format="PNG")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_capacity_bytes(self):
        cap = lsb.capacity_bytes(self.cover_path)
        # 60 * 60 * 3 bits = 10800 bits = 1350 bytes. Dikurangi header 8 B = 1342 bytes
        self.assertEqual(cap, 1342)

    def test_capacity_non_existent(self):
        with self.assertRaises(ItemNotFound):
            lsb.capacity_bytes(self.temp_dir / "tidak_ada.png")

    def test_capacity_non_png(self):
        txt_file = self.temp_dir / "file.txt"
        txt_file.write_text("bukan gambar")
        with self.assertRaises(UnsupportedFileType):
            lsb.capacity_bytes(txt_file)

    def test_embed_and_extract_roundtrip(self):
        payload = b"Halo, ini rahasia kriptografi Brankas!" * 5
        out_path = self.temp_dir / "stego.png"

        lsb.embed(self.cover_path, payload, out_path)
        self.assertTrue(out_path.is_file())

        extracted = lsb.extract(out_path)
        self.assertEqual(extracted, payload)

    def test_embed_capacity_exceeded(self):
        # Cover kapasitas 1342 B, berikan data 2000 B
        too_big = b"X" * 2000
        out_path = self.temp_dir / "gagal.png"
        with self.assertRaises(StegoCapacityError):
            lsb.embed(self.cover_path, too_big, out_path)

    def test_extract_not_found_on_plain_image(self):
        with self.assertRaises(StegoNotFound):
            lsb.extract(self.cover_path)

    def test_hide_and_reveal_note(self):
        master_key = os.urandom(32)
        session = DummySession(keys.derive_keyset(master_key))

        secret_text = "Catatan super rahasia: password brankas adalah 123456!"
        stego_path = self.temp_dir / "note_stego.png"

        lsb.hide_note(session, self.cover_path, secret_text, stego_path)
        self.assertTrue(stego_path.is_file())

        revealed = lsb.reveal_note(session, stego_path)
        self.assertEqual(revealed, secret_text)

    def test_hide_empty_note(self):
        session = DummySession(keys.derive_keyset(os.urandom(32)))
        stego_path = self.temp_dir / "empty.png"
        with self.assertRaises(InvalidInput):
            lsb.hide_note(session, self.cover_path, "   ", stego_path)

    def test_reveal_wrong_session_key(self):
        session1 = DummySession(keys.derive_keyset(os.urandom(32)))
        session2 = DummySession(keys.derive_keyset(os.urandom(32)))

        stego_path = self.temp_dir / "note_stego.png"
        lsb.hide_note(session1, self.cover_path, "Pesan Rahasia", stego_path)

        with self.assertRaises(DecryptionError):
            lsb.reveal_note(session2, stego_path)


if __name__ == "__main__":
    unittest.main()

