"""Tes tahap 2: log audit, pratinjau, inspektur, dan alur dokumen end-to-end.
Jalankan dari root repo:  python -m unittest discover -v
"""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from brankas import config, inspector
from brankas.core import crypto, keys
from brankas.errors import DecryptionError, InvalidInput
from brankas.storage import audit, db, documents, preview


def make_session(user_id: int = 1):
    return SimpleNamespace(user_id=user_id, username="uji", keys=keys.derive_keyset(os.urandom(32)))


class TempEnv(unittest.TestCase):
    """DB dan vault sementara; PoW diturunkan supaya tes cepat."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        for target, value in (("DB_PATH", root / "data" / "brankas.db"), ("VAULT_DIR", root / "vault"),
                              ("POW_DIFFICULTY", 1)):
            p = mock.patch.object(config, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.root = root


class TestAead(unittest.TestCase):
    def test_roundtrip(self):
        key = os.urandom(32)
        for enc, dec in ((crypto.aes_encrypt, crypto.aes_decrypt),
                         (crypto.chacha_encrypt, crypto.chacha_decrypt)):
            self.assertEqual(dec(enc(b"data", key), key), b"data")

    def test_wrong_key_or_tampered_blob_fails(self):
        key = os.urandom(32)
        for enc, dec in ((crypto.aes_encrypt, crypto.aes_decrypt),
                         (crypto.chacha_encrypt, crypto.chacha_decrypt)):
            blob = enc(b"data", key)
            with self.assertRaises(DecryptionError):
                dec(blob, os.urandom(32))
            tampered = bytearray(blob)
            tampered[-1] ^= 1
            with self.assertRaises(DecryptionError):
                dec(bytes(tampered), key)


class TestInspector(unittest.TestCase):
    def setUp(self):
        self.s = make_session()

    def test_trace_matches_encrypt_text_pipeline(self):
        t = inspector.trace_encrypt(self.s, "Halo Brankas \U0001f512")
        self.assertEqual(t.nonce + t.ciphertext + t.tag, t.blob)
        self.assertEqual(len(t.ciphertext), len(t.plaintext))
        self.assertEqual(crypto.decrypt_text(t.blob, self.s.keys), "Halo Brankas \U0001f512")
        self.assertEqual(crypto.vigenere_decrypt(t.vigenere_out, self.s.keys.vigenere_key), t.plaintext)

    def test_decrypt_trace(self):
        t = inspector.trace_encrypt(self.s, "rahasia")
        d = inspector.decrypt_trace(self.s, t.blob)
        self.assertEqual(d.plaintext, "rahasia")
        self.assertEqual(d.vigenere_out, t.vigenere_out)

    def test_flipped_bit_rejected(self):
        t = inspector.trace_encrypt(self.s, "rahasia")
        for _ in range(20):
            bad, pos, bit = inspector.flip_ciphertext_bit(t.blob)
            self.assertEqual(sum(a != b for a, b in zip(bad, t.blob)), 1)
            self.assertTrue(0 <= pos < len(t.ciphertext) and 0 <= bit < 8)
            with self.assertRaises(DecryptionError):
                inspector.decrypt_trace(self.s, bad)

    def test_input_limits(self):
        with self.assertRaises(InvalidInput):
            inspector.trace_encrypt(self.s, "")
        with self.assertRaises(InvalidInput):
            inspector.trace_encrypt(self.s, "x" * (inspector.MAX_TRACE_BYTES + 1))

    def test_fingerprints_distinct_and_no_key_leak(self):
        fps = inspector.key_fingerprints(self.s)
        self.assertEqual(len({fp for _, fp, _ in fps}), 5)
        ks = self.s.keys
        for _, fp, _ in fps:
            self.assertNotIn(fp.replace("-", ""), ks.k_text.hex() + ks.k_file.hex() + ks.vigenere_key.hex())


class TestAudit(TempEnv):
    def test_record_list_verify(self):
        with db.transaction() as conn:
            audit.record(conn, 1, "LOGIN")
            audit.record(conn, 2, "LOGIN")
            audit.record(conn, 1, "UNDUH", "doc-aaa")
            audit.record(conn, 1, "LOGOUT")
        with db.transaction() as conn:
            mine = audit.list_entries(conn, 1)
            self.assertEqual([e.action for e in mine], ["LOGOUT", "UNDUH", "LOGIN"])   # terbaru di atas
            self.assertEqual(len(audit.list_entries(conn, 2)), 1)
            res = audit.verify_audit(conn)
        self.assertTrue(res.ok, res.problems)
        self.assertEqual(res.checked, 5)   # genesis + 4

    def test_unknown_action(self):
        with db.transaction() as conn:
            with self.assertRaises(ValueError):
                audit.record(conn, 1, "HAPUS")

    def test_tamper_detected(self):
        with db.transaction() as conn:
            for _ in range(3):
                audit.record(conn, 1, "LOGIN")
        with db.transaction() as conn:
            conn.execute("UPDATE audit SET action = 'UNDUH' WHERE idx = 2")
        with db.transaction() as conn:
            res = audit.verify_audit(conn)
        self.assertFalse(res.ok)
        self.assertTrue(any("Entri 2" in p for p in res.problems))

    def test_deleted_middle_entry_detected(self):
        with db.transaction() as conn:
            for _ in range(4):
                audit.record(conn, 1, "LOGIN")
        with db.transaction() as conn:
            conn.execute("DELETE FROM audit WHERE idx = 2")
        with db.transaction() as conn:
            self.assertFalse(audit.verify_audit(conn).ok)

    def test_existing_db_gets_audit_table(self):
        """init_db memakai CREATE IF NOT EXISTS: DB lama tanpa tabel audit tidak perlu dihapus."""
        with db.transaction() as conn:
            conn.execute("DROP TABLE audit")
        with db.transaction() as conn:
            audit.record(conn, 1, "LOGIN")
            self.assertTrue(audit.verify_audit(conn).ok)


class TestPreview(unittest.TestCase):
    def _docx(self, body_xml: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml",
                       '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                       f'wordprocessingml/2006/main"><w:body>{body_xml}</w:body></w:document>')
        return buf.getvalue()

    def test_kind_of(self):
        self.assertEqual([preview.kind_of(e) for e in (".TXT", ".md", ".docx", ".PNG", ".jpg", ".pdf", "")],
                         ["text", "text", "docx", "image", "image", "none", "none"])

    def test_text(self):
        self.assertEqual(preview.text_from_bytes("\ufeffHalo é".encode("utf-8")), "Halo é")
        self.assertIn("\ufffd", preview.text_from_bytes(b"\xff\xfe abc"))
        clipped = preview.text_from_bytes(b"a" * 50, limit=10)
        self.assertTrue(clipped.startswith("a" * 10) and "dipotong" in clipped)

    def test_docx(self):
        data = self._docx("<w:p><w:r><w:t>Baris satu</w:t></w:r><w:r><w:tab/><w:t>kolom</w:t></w:r></w:p>"
                          "<w:p><w:r><w:t>Baris dua</w:t><w:br/><w:t>lanjut</w:t></w:r></w:p>")
        self.assertEqual(preview.docx_to_text(data), "Baris satu\tkolom\nBaris dua\nlanjut")

    def test_docx_invalid(self):
        for bad in (b"bukan zip", self._docx("<w:p>").replace(b"word/document.xml", b"word/lain.xml")):
            with self.assertRaises(InvalidInput):
                preview.docx_to_text(bad)

    def test_docx_rejects_entities(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
        with self.assertRaises(InvalidInput):
            preview.docx_to_text(buf.getvalue())

    def test_image(self):
        buf = io.BytesIO()
        Image.new("RGBA", (1600, 900), (10, 20, 30, 128)).save(buf, format="PNG")
        img, original = preview.load_image(buf.getvalue(), (640, 360))
        self.assertEqual(original, (1600, 900))
        self.assertLessEqual(img.size[0], 640)
        self.assertLessEqual(img.size[1], 360)
        self.assertEqual(img.mode, "RGB")
        with self.assertRaises(InvalidInput):
            preview.load_image(b"bukan gambar")


class TestDocumentsFlow(TempEnv):
    def setUp(self):
        super().setUp()
        with db.transaction() as conn:   # documents.user_id punya foreign key ke users
            uid = db.create_user(conn, b"u1", "hash", b"salt-salt", "serial-1", b"wajah")
            self.other_id = db.create_user(conn, b"u2", "hash", b"salt-salt", "serial-2", b"wajah")
        self.s = make_session(user_id=uid)
        self.src = self.root / "catatan.txt"
        self.src.write_text("isi rahasia", encoding="utf-8")

    def _actions(self):
        with db.transaction() as conn:
            return [(e.action, e.doc_id) for e in reversed(audit.list_entries(conn, self.s.user_id))]

    def test_read_document_in_memory_and_audited(self):
        doc = documents.add_document(self.s, self.src)
        files_before = sorted(p.name for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(documents.read_document(self.s, doc.id), b"isi rahasia")
        self.assertEqual(sorted(p.name for p in self.root.rglob("*") if p.is_file()), files_before)  # tak ada file baru
        self.assertEqual(self._actions(), [("PRATINJAU", doc.id)])

    def test_export_audited_and_other_user_blocked(self):
        doc = documents.add_document(self.s, self.src)
        out = self.root / "keluar.txt"
        documents.export_document(self.s, doc.id, out)
        self.assertEqual(out.read_bytes(), b"isi rahasia")
        self.assertEqual(self._actions(), [("UNDUH", doc.id)])
        other = make_session(user_id=self.other_id)
        with self.assertRaises(Exception):
            documents.read_document(other, doc.id)
        self.assertEqual(self._actions(), [("UNDUH", doc.id)])   # percobaan gagal tidak tercatat sebagai akses

    def test_wrong_key_not_audited(self):
        doc = documents.add_document(self.s, self.src)
        stranger = SimpleNamespace(user_id=self.s.user_id, username="x", keys=make_session().keys)
        with self.assertRaises(DecryptionError):
            documents.read_document(stranger, doc.id)
        self.assertEqual(self._actions(), [])

    def test_blockchain_untouched_by_audit(self):
        """Audit tidak boleh menambah blok di tabel chain (login tidak memicu mining)."""
        doc = documents.add_document(self.s, self.src)
        with db.transaction() as conn:
            before = conn.execute("SELECT COUNT(*) FROM chain").fetchone()[0]
        documents.read_document(self.s, doc.id)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chain").fetchone()[0], before)


if __name__ == "__main__":
    unittest.main()
