"""Tes backend: database, dokumen, catatan, blockchain.
Jalankan dari root repo:  python -m unittest discover -v
Tes memakai folder sementara, tidak menyentuh data/ asli."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from brankas import config
from brankas.chain import blockchain
from brankas.core import keys as kmod
from brankas.errors import (DecryptionError, FileTooLarge, InvalidInput, ItemNotFound,
                            UnsupportedFileType, UserExists)
from brankas.storage import db, documents, notes


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved = (config.DB_PATH, config.VAULT_DIR, config.POW_DIFFICULTY, config.MAX_FILE_BYTES)
        config.DB_PATH = self.tmp / "data" / "test.db"
        config.VAULT_DIR = self.tmp / "data" / "vault"
        config.POW_DIFFICULTY = 2   # cepat untuk tes
        with db.transaction() as conn:
            self.uid1 = db.create_user(conn, "anggota_a", "hash", os.urandom(16), "dongle-1", b"face1")
            self.uid2 = db.create_user(conn, "anggota_b", "hash", os.urandom(16), "dongle-2", b"face2")
        self.s1 = SimpleNamespace(user_id=self.uid1, keys=kmod.derive_keyset(os.urandom(32)))
        self.s2 = SimpleNamespace(user_id=self.uid2, keys=kmod.derive_keyset(os.urandom(32)))

    def tearDown(self):
        config.DB_PATH, config.VAULT_DIR, config.POW_DIFFICULTY, config.MAX_FILE_BYTES = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_file(self, name="rahasia-laporan.txt", data=b"isi dokumen sangat rahasia"):
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def verify(self):
        with db.transaction() as conn:
            return blockchain.verify_chain(conn, config.VAULT_DIR)


class TestDb(StorageTestCase):
    def test_init_idempotent(self):
        with db.transaction() as conn:
            db.init_db(conn)
            db.init_db(conn)

    def test_duplicate_user(self):
        with db.transaction() as conn:
            with self.assertRaises(UserExists):
                db.create_user(conn, "anggota_a", "h", b"s", "dongle-baru", b"f")
            with self.assertRaises(UserExists):
                db.create_user(conn, "orang_baru", "h", b"s", "dongle-1", b"f")

    def test_get_user_by_dongle(self):
        with db.transaction() as conn:
            self.assertEqual(db.get_user_by_dongle(conn, "dongle-2")["id"], self.uid2)
            self.assertIsNone(db.get_user_by_dongle(conn, "tidak-ada"))


class TestDocuments(StorageTestCase):
    def test_roundtrip(self):
        src = self.make_file()
        info = documents.add_document(self.s1, src)
        self.assertEqual(info.filename, "rahasia-laporan.txt")
        self.assertEqual(info.file_type, ".txt")
        self.assertEqual(info.size, src.stat().st_size)

        docs = documents.list_documents(self.s1)
        self.assertEqual([d.id for d in docs], [info.id])

        out = self.tmp / "hasil.txt"
        documents.export_document(self.s1, info.id, out)
        self.assertEqual(out.read_bytes(), src.read_bytes())

    def test_nothing_plaintext_on_disk(self):
        src = self.make_file(data=b"isi dokumen sangat rahasia")
        info = documents.add_document(self.s1, src)
        enc = (config.VAULT_DIR / f"{info.id}.enc").read_bytes()
        self.assertNotIn(b"sangat rahasia", enc)
        raw_db = config.DB_PATH.read_bytes()
        self.assertNotIn(b"rahasia-laporan", raw_db)

    def test_validation(self):
        with self.assertRaises(UnsupportedFileType):
            documents.add_document(self.s1, self.make_file("virus.exe"))
        config.MAX_FILE_BYTES = 10
        with self.assertRaises(FileTooLarge):
            documents.add_document(self.s1, self.make_file("besar.txt", b"x" * 11))
        with self.assertRaises(ItemNotFound):
            documents.add_document(self.s1, self.tmp / "tidak-ada.txt")

    def test_user_isolation(self):
        info = documents.add_document(self.s1, self.make_file())
        self.assertEqual(documents.list_documents(self.s2), [])
        with self.assertRaises(ItemNotFound):
            documents.export_document(self.s2, info.id, self.tmp / "x.txt")
        with self.assertRaises(ItemNotFound):
            documents.delete_document(self.s2, info.id)

    def test_wrong_keys_cannot_export(self):
        info = documents.add_document(self.s1, self.make_file())
        intruder = SimpleNamespace(user_id=self.uid1, keys=kmod.derive_keyset(os.urandom(32)))
        with self.assertRaises(DecryptionError):
            documents.export_document(intruder, info.id, self.tmp / "x.txt")

    def test_delete(self):
        info = documents.add_document(self.s1, self.make_file())
        documents.delete_document(self.s1, info.id)
        self.assertEqual(documents.list_documents(self.s1), [])
        self.assertFalse((config.VAULT_DIR / f"{info.id}.enc").exists())
        with db.transaction() as conn:
            actions = [r["action"] for r in conn.execute("SELECT action FROM chain ORDER BY idx")]
        self.assertEqual(actions, ["GENESIS", "UPLOAD", "DELETE"])
        self.assertTrue(self.verify().ok)

    def test_png_binary(self):
        data = os.urandom(5000)
        info = documents.add_document(self.s1, self.make_file("foto.png", data))
        out = self.tmp / "foto-keluar.png"
        documents.export_document(self.s1, info.id, out)
        self.assertEqual(out.read_bytes(), data)


class TestChain(StorageTestCase):
    def test_empty_chain_ok(self):
        r = self.verify()
        self.assertTrue(r.ok)
        self.assertEqual(r.checked_blocks, 0)

    def test_valid_chain_and_pow(self):
        documents.add_document(self.s1, self.make_file("a.txt"))
        documents.add_document(self.s2, self.make_file("b.txt"))
        r = self.verify()
        self.assertTrue(r.ok, r.problems)
        self.assertEqual(r.checked_blocks, 3)   # genesis + 2 upload
        with db.transaction() as conn:
            for row in conn.execute("SELECT hash FROM chain"):
                self.assertTrue(row["hash"].startswith("00"))

    def test_detect_block_tampering(self):
        documents.add_document(self.s1, self.make_file())
        with db.transaction() as conn:
            conn.execute("UPDATE chain SET doc_hash = 'palsu' WHERE idx = 1")
        r = self.verify()
        self.assertFalse(r.ok)
        self.assertTrue(any("Blok 1" in p for p in r.problems))

    def test_detect_broken_link(self):
        documents.add_document(self.s1, self.make_file("a.txt"))
        documents.add_document(self.s1, self.make_file("b.txt"))
        with db.transaction() as conn:
            conn.execute("UPDATE chain SET prev_hash = ? WHERE idx = 2", ("f" * 64,))
        self.assertFalse(self.verify().ok)

    def test_detect_modified_file(self):
        info = documents.add_document(self.s1, self.make_file())
        path = config.VAULT_DIR / f"{info.id}.enc"
        data = bytearray(path.read_bytes())
        data[-1] ^= 0x01
        path.write_bytes(bytes(data))
        r = self.verify()
        self.assertFalse(r.ok)
        self.assertTrue(any("isi file berubah" in p for p in r.problems))

    def test_detect_missing_file(self):
        info = documents.add_document(self.s1, self.make_file())
        (config.VAULT_DIR / f"{info.id}.enc").unlink()
        self.assertFalse(self.verify().ok)

    def test_detect_row_deleted_without_block(self):
        info = documents.add_document(self.s1, self.make_file())
        with db.transaction() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (info.id,))
        r = self.verify()
        self.assertFalse(r.ok)
        self.assertTrue(any("tanpa catatan DELETE" in p for p in r.problems))

    def test_bad_action(self):
        with db.transaction() as conn:
            with self.assertRaises(ValueError):
                blockchain.add_block(conn, 1, "HACK", "x", "y")

    def test_list_blocks(self):
        documents.add_document(self.s1, self.make_file())
        with db.transaction() as conn:
            blocks = blockchain.list_blocks(conn)
        self.assertEqual([b.action for b in blocks], ["GENESIS", "UPLOAD"])
        self.assertEqual([b.idx for b in blocks], [0, 1])


class TestNotes(StorageTestCase):
    def test_roundtrip_and_isolation(self):
        n = notes.add_note(self.s1, "Catatan rahasia: kode brankas 1234")
        self.assertEqual([x.content for x in notes.list_notes(self.s1)], [n.content])
        self.assertEqual(notes.list_notes(self.s2), [])
        self.assertNotIn(b"kode brankas", config.DB_PATH.read_bytes())

    def test_empty_note(self):
        with self.assertRaises(InvalidInput):
            notes.add_note(self.s1, "   ")

    def test_delete(self):
        n = notes.add_note(self.s1, "hapus aku")
        with self.assertRaises(ItemNotFound):
            notes.delete_note(self.s2, n.id)
        notes.delete_note(self.s1, n.id)
        self.assertEqual(notes.list_notes(self.s1), [])
        with self.assertRaises(ItemNotFound):
            notes.delete_note(self.s1, n.id)


if __name__ == "__main__":
    unittest.main()
