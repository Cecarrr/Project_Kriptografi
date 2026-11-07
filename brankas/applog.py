"""Log aplikasi sederhana. TIDAK PERNAH mencatat rahasia.

Aturan isi log (dipatuhi semua pemanggil):
- Boleh : peristiwa (login berhasil/gagal, dongle dicabut, unggah/hapus dokumen), ID dokumen, jumlah,
          jarak wajah, hasil verifikasi blockchain, nama kelas error.
- Jangan: password, isi dongle.key, kunci/subkunci, isi catatan, nama file asli dokumen (nama file
          disimpan terenkripsi di basis data, jadi tidak boleh bocor lewat log), encoding wajah.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from brankas import config

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def get_logger(name: str) -> logging.Logger:
    """Logger di bawah namespace 'brankas' (mis. get_logger('login') -> 'brankas.login')."""
    return logging.getLogger(f"brankas.{name}")


def setup_logging() -> None:
    """Pasang handler berkas berputar di config.LOG_DIR. Aman dipanggil berulang.
    Bila folder log tidak bisa dibuat, aplikasi tetap jalan tanpa log berkas."""
    global _configured
    if _configured:
        return
    root = logging.getLogger("brankas")
    root.setLevel(logging.INFO)
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            config.LOG_DIR / "brankas.log",
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    except OSError:
        pass
    _configured = True
