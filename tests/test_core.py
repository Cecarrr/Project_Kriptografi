"""Tes inti kripto. Jalankan dari root repo:  python -m unittest discover -v"""
import os
import unittest

from brankas.core import crypto, keys
from brankas.errors import DecryptionError


def make_keyset() -> keys.KeySet:
    return keys.derive_keyset(os.urandom(32))


class TestVigenere(unittest.TestCase):
    def test_known_vector(self):
        self.assertEqual(crypto.vigenere_encrypt(b"abc", b"\x01\x02"), b"bdd")

    def test_roundtrip_all_bytes(self):
        data, key = bytes(range(256)) * 3, b"kunci-rahasia"
        self.assertEqual(crypto.vigenere_decrypt(crypto.vigenere_encrypt(data, key), key), data)

    def test_empty_key(self):
        with self.assertRaises(ValueError):
            crypto.vigenere_encrypt(b"x", b"")


class TestAead(unittest.TestCase):
    def test_aes_and_chacha_roundtrip(self):
        key, data = os.urandom(32), os.urandom(5000)
        self.assertEqual(crypto.aes_decrypt(crypto.aes_encrypt(data, key), key), data)
        self.assertEqual(crypto.chacha_decrypt(crypto.chacha_encrypt(data, key), key), data)

    def test_empty_data(self):
        key = os.urandom(32)
        self.assertEqual(crypto.aes_decrypt(crypto.aes_encrypt(b"", key), key), b"")

    def test_nonce_random(self):
        key, data = os.urandom(32), b"sama"
        self.assertNotEqual(crypto.aes_encrypt(data, key), crypto.aes_encrypt(data, key))

    def test_wrong_key(self):
        blob = crypto.aes_encrypt(b"rahasia", os.urandom(32))
        with self.assertRaises(DecryptionError):
            crypto.aes_decrypt(blob, os.urandom(32))

    def test_tamper_detected(self):
        key = os.urandom(32)
        for enc, dec in ((crypto.aes_encrypt, crypto.aes_decrypt),
                         (crypto.chacha_encrypt, crypto.chacha_decrypt)):
            blob = bytearray(enc(b"data penting", key))
            blob[-1] ^= 0x01
            with self.assertRaises(DecryptionError):
                dec(bytes(blob), key)

    def test_too_short(self):
        with self.assertRaises(DecryptionError):
            crypto.aes_decrypt(b"pendek", os.urandom(32))

    def test_bad_key_length_is_valueerror(self):
        with self.assertRaises(ValueError):
            crypto.aes_encrypt(b"x", b"kunci-pendek")


class TestHighLevel(unittest.TestCase):
    def setUp(self):
        self.ks = make_keyset()

    def test_text_unicode(self):
        teks = "Halo Brankas! Catatan rahasia 123 \u00e9\u00e8 \u4f60\u597d \U0001f512"
        blob = crypto.encrypt_text(teks, self.ks)
        self.assertEqual(crypto.decrypt_text(blob, self.ks), teks)
        self.assertNotIn(b"Halo", blob)

    def test_text_wrong_keyset(self):
        blob = crypto.encrypt_text("rahasia", self.ks)
        with self.assertRaises(DecryptionError):
            crypto.decrypt_text(blob, make_keyset())

    def test_file_roundtrip_1mb(self):
        data = os.urandom(1024 * 1024)
        self.assertEqual(crypto.decrypt_file(crypto.encrypt_file(data, self.ks), self.ks), data)

    def test_field_str_and_bytes(self):
        self.assertEqual(crypto.decrypt_field(crypto.encrypt_field("laporan.docx", self.ks), self.ks),
                         b"laporan.docx")
        self.assertEqual(crypto.decrypt_field(crypto.encrypt_field(b"\x00\x01", self.ks), self.ks),
                         b"\x00\x01")

    def test_text_and_file_use_different_keys(self):
        # blob teks tidak boleh bisa dibuka sebagai file (kunci & algoritma berbeda)
        blob = crypto.encrypt_text("x", self.ks)
        with self.assertRaises(DecryptionError):
            crypto.decrypt_file(blob, self.ks)

    def test_sha256(self):
        self.assertEqual(crypto.sha256_hex(b"abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class TestKeys(unittest.TestCase):
    def test_keyset_deterministic_and_distinct(self):
        master = os.urandom(32)
        a, b = keys.derive_keyset(master), keys.derive_keyset(master)
        self.assertEqual(a, b)
        subs = {a.k_text, a.k_file, a.k_db, a.k_stego}
        self.assertEqual(len(subs), 4)
        self.assertEqual(len(a.vigenere_key), 16)
        self.assertNotIn(a.k_text.hex(), repr(a))   # kunci tidak bocor di repr

    def test_master_depends_on_both_inputs(self):
        pw, dg = os.urandom(32), os.urandom(32)
        m = keys.derive_master_key(pw, dg)
        self.assertEqual(m, keys.derive_master_key(pw, dg))
        self.assertNotEqual(m, keys.derive_master_key(os.urandom(32), dg))
        self.assertNotEqual(m, keys.derive_master_key(pw, os.urandom(32)))

    def test_face_key(self):
        dg = os.urandom(32)
        self.assertEqual(keys.derive_face_key(dg), keys.derive_face_key(dg))
        self.assertNotEqual(keys.derive_face_key(dg), keys.derive_keyset(dg).k_db)

    def test_password_hash(self):
        h = keys.hash_password("rahasia-123")
        self.assertTrue(keys.verify_password(h, "rahasia-123"))
        self.assertFalse(keys.verify_password(h, "salah"))
        self.assertFalse(keys.verify_password("bukan-hash", "rahasia-123"))

    def test_pw_key(self):
        salt = keys.new_salt()
        k = keys.derive_pw_key("rahasia-123", salt)
        self.assertEqual(len(k), 32)
        self.assertEqual(k, keys.derive_pw_key("rahasia-123", salt))
        self.assertNotEqual(k, keys.derive_pw_key("rahasia-124", salt))
        self.assertNotEqual(k, keys.derive_pw_key("rahasia-123", keys.new_salt()))

    def test_full_chain(self):
        """password + dongle -> keyset -> enkripsi -> password salah gagal."""
        salt, dongle = keys.new_salt(), os.urandom(32)
        ks = keys.derive_keyset(keys.derive_master_key(keys.derive_pw_key("benar", salt), dongle))
        blob = crypto.encrypt_text("isi catatan", ks)
        ks2 = keys.derive_keyset(keys.derive_master_key(keys.derive_pw_key("benar", salt), dongle))
        self.assertEqual(crypto.decrypt_text(blob, ks2), "isi catatan")
        bad = keys.derive_keyset(keys.derive_master_key(keys.derive_pw_key("salah", salt), dongle))
        with self.assertRaises(DecryptionError):
            crypto.decrypt_text(blob, bad)


if __name__ == "__main__":
    unittest.main()
