"""Akses aman ke folder vault. Pemilik: Anggota B.

stored_path berasal dari basis data, jadi diperlakukan sebagai input tidak tepercaya: bila baris DB
diubah (mis. menjadi "..\\..\\berkas-penting"), operasi baca/hapus tidak boleh keluar dari vault.
"""
from __future__ import annotations

import re
from pathlib import Path

from brankas.errors import UnsafePath

# Nama biasa berakhiran .enc: huruf/angka/_/- dan titik, harus diawali huruf/angka.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.enc$")


def validate_stored_name(name: object) -> str:
    """Pastikan `name` hanya nama berkas biasa (tanpa folder, '..', '/', '\\', atau drive)."""
    if not isinstance(name, str) or not name:
        raise UnsafePath("stored_path kosong atau bukan teks")
    if ".." in name or "/" in name or "\\" in name or ":" in name or "\x00" in name:
        raise UnsafePath("stored_path tidak aman (mengandung '..', pemisah folder, atau drive)")
    if not _NAME_RE.match(name):
        raise UnsafePath("stored_path tidak berupa nama berkas vault yang valid")
    return name


def safe_vault_path(vault_dir: Path | str, stored_path: object) -> Path:
    """Path absolut ke berkas di dalam vault_dir. UnsafePath bila stored_path mencoba keluar dari vault."""
    name = validate_stored_name(stored_path)
    root = Path(vault_dir).resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise UnsafePath("stored_path menunjuk ke luar folder vault")
    return target
