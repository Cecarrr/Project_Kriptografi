"""Dongle USB. Pemilik: Anggota A.

Aturan keamanan:
- Dongle harus flashdisk removable (kecuali config.DONGLE_REQUIRE_REMOVABLE = False).
- dongle.key TIDAK PERNAH ditimpa: registrasi menolak flashdisk yang sudah berisi dongle.key,
  karena menimpanya berarti akun lama tidak bisa dibuka lagi selamanya.
- Mode dev (env BRANKAS_DEV_DONGLE_DIR) hanya untuk pengujian: dongle = isi folder itu saja
  (flashdisk asli diabaikan) dan serialnya tetap "DEV00001". JANGAN diset saat demo.
"""
from __future__ import annotations

import hashlib
import ntpath
import os
from dataclasses import dataclass
from pathlib import Path

import psutil
import win32api
import win32file

from brankas import config
from brankas.errors import BrankasError, DongleNotFound

DEV_SERIAL = "DEV00001"
_DEV_ENV = "BRANKAS_DEV_DONGLE_DIR"


@dataclass(frozen=True)
class DongleInfo:
    drive: str          # mis. "E:\\"
    serial: str         # serial volume, hex 8 digit
    serial_hash: str    # SHA-256(serial), yang disimpan di tabel users
    key: bytes          # isi dongle.key (32 B)


# ------------------------------------------------------------------ mode dev
def dev_dir() -> Path | None:
    """Folder dongle mode pengembangan; None bila env var tidak diset (kondisi normal)."""
    value = os.environ.get(_DEV_ENV)
    return Path(value) if value else None


def _in_dev_dir(path) -> bool:
    d = dev_dir()
    if d is None:
        return False
    try:
        Path(path).resolve().relative_to(d.resolve())
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ utilitas drive
def _normalize_drive(drive: str) -> str:
    s = str(drive)
    if not s.endswith("\\") and not s.endswith("/"):
        s += "\\"
    return s


def mount_root(path) -> str:
    """Root drive dari sebuah path (mis. 'E:\\Folder' -> 'E:\\'). Folder dev -> folder itu sendiri."""
    if _in_dev_dir(path):
        return str(dev_dir())
    drive = ntpath.splitdrive(os.fspath(path))[0]
    return _normalize_drive(drive or str(path))


def _hash_serial(serial: str) -> str:
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


def read_volume_serial(path) -> str:
    """Serial volume (hex 8 digit) dari drive tempat `path` berada."""
    if _in_dev_dir(path):
        return DEV_SERIAL
    root = mount_root(path)
    try:
        info = win32api.GetVolumeInformation(root)
    except Exception as e:  # noqa: BLE001
        raise DongleNotFound(f"Gagal membaca serial volume pada {root}: {e}") from e
    return f"{info[1] & 0xFFFFFFFF:08X}"


def _partition_is_removable(p) -> bool:
    if "removable" in p.opts.lower():
        return True
    try:
        return win32file.GetDriveType(_normalize_drive(p.mountpoint)) == win32file.DRIVE_REMOVABLE
    except Exception:  # noqa: BLE001
        return False


def list_removable_drives() -> list[str]:
    """Daftar mountpoint drive removable yang aktif dan memiliki media."""
    if dev_dir() is not None:
        return []  # Mode dev: terisolasi penuh, abaikan removable drives fisik
    drives: list[str] = []
    for p in psutil.disk_partitions(all=False):
        if not p.fstype:  # abaikan slot card reader kosong tanpa media
            continue
        if not _partition_is_removable(p):
            continue
        mount = _normalize_drive(p.mountpoint)
        try:
            win32api.GetVolumeInformation(mount)
        except Exception:  # noqa: BLE001
            continue
        if mount not in drives:
            drives.append(mount)
    return drives


def _require_removable(root: str) -> None:
    if _in_dev_dir(root) or not getattr(config, "DONGLE_REQUIRE_REMOVABLE", True):
        return
    allowed = {d.rstrip("\\/").lower() for d in list_removable_drives()}
    if root.rstrip("\\/").lower() not in allowed:
        raise DongleNotFound(
            f"{root} bukan flashdisk removable. Dongle harus berupa flashdisk USB "
            "(atur config.DONGLE_REQUIRE_REMOVABLE = False bila flashdisk Anda terdeteksi sebagai disk tetap)."
        )


# ------------------------------------------------------------------ berkas dongle.key
def _find_key_file(base: Path) -> Path | None:
    """dongle.key di root drive, atau di subfolder satu tingkat (mis. folder 'USB DRIVE')."""
    base = Path(base)
    direct = base / config.DONGLE_FILENAME
    if direct.is_file():
        return direct
    try:
        for sub in base.iterdir():
            try:
                cand = sub / config.DONGLE_FILENAME
                if sub.is_dir() and cand.is_file():
                    return cand
            except OSError:
                continue
    except OSError:
        pass
    return None


def _read_key(key_file: Path) -> bytes:
    data = key_file.read_bytes()
    if len(data) != config.DONGLE_KEY_BYTES:
        raise DongleNotFound(f"{key_file} bukan berkas dongle yang valid (ukuran salah)")
    return data


# ------------------------------------------------------------------ API publik
def load_dongle(path) -> DongleInfo:
    """Muat dongle dari drive/folder tertentu. Dipakai pencarian otomatis dan pilihan manual."""
    d = dev_dir()
    if d is not None and not _in_dev_dir(path):
        raise DongleNotFound(
            f"Mode development aktif: hanya folder development ({d}) yang dapat digunakan sebagai dongle."
        )
    root = mount_root(path)
    _require_removable(root)
    key_file = _find_key_file(Path(path)) or _find_key_file(Path(root))
    if key_file is None:
        raise DongleNotFound(f"Berkas {config.DONGLE_FILENAME} tidak ditemukan di {path}")
    key = _read_key(key_file)
    serial = read_volume_serial(root)
    return DongleInfo(drive=root, serial=serial, serial_hash=_hash_serial(serial), key=key)


def find_dongle() -> DongleInfo | None:
    """Cari flashdisk removable yang berisi dongle.key. None bila tidak ada."""
    d = dev_dir()
    if d is not None:   # mode dev: terisolasi, hanya folder dev yang diperiksa
        try:
            return load_dongle(d)
        except BrankasError:
            return None
    for mount in list_removable_drives():
        try:
            return load_dongle(mount)
        except BrankasError:
            continue
    return None


def preflight(drive: str) -> str:
    """Periksa drive untuk dijadikan dongle TANPA menulis apa pun. Mengembalikan serial_hash."""
    d = dev_dir()
    if d is not None and not _in_dev_dir(drive):
        raise BrankasError(
            f"Mode development aktif: registrasi dongle hanya diizinkan pada folder development ({d})."
        )
    if _in_dev_dir(drive):
        Path(drive).mkdir(parents=True, exist_ok=True)
    elif not Path(drive).exists():
        raise DongleNotFound(f"Drive/lokasi {drive} tidak ditemukan")
    root = mount_root(drive)
    _require_removable(root)
    existing = _find_key_file(Path(root))
    if existing is not None:
        raise BrankasError(
            f"{existing} sudah ada, jadi flashdisk ini sudah berisi dongle. Pakai flashdisk lain "
            "(menimpa dongle.key akan membuat akun lama tidak bisa dibuka lagi selamanya)."
        )
    return _hash_serial(read_volume_serial(root))


def provision_dongle(drive: str) -> DongleInfo:
    """Registrasi: tulis dongle.key (32 B acak) ke ROOT drive, kembalikan DongleInfo.
    Menolak bila dongle.key sudah ada (tidak pernah menimpa)."""
    d = dev_dir()
    if d is not None and not _in_dev_dir(drive):
        raise BrankasError(
            f"Mode development aktif: registrasi dongle hanya diizinkan pada folder development ({d})."
        )
    serial_hash = preflight(drive)
    root = mount_root(drive)
    serial = read_volume_serial(root)
    key = os.urandom(config.DONGLE_KEY_BYTES)
    key_path = Path(root) / config.DONGLE_FILENAME
    try:
        with open(key_path, "xb") as f:   # 'x' = gagal bila berkas sudah ada
            f.write(key)
    except FileExistsError:
        raise BrankasError(f"{key_path} sudah ada; dongle.key tidak boleh ditimpa") from None
    except OSError as e:
        raise BrankasError(f"Gagal menulis {config.DONGLE_FILENAME} ke {root}: {e}") from e
    return DongleInfo(drive=root, serial=serial, serial_hash=serial_hash, key=key)


def discard_dongle(info: DongleInfo) -> None:
    """Hapus dongle.key yang baru ditulis (hanya untuk membersihkan registrasi yang gagal)."""
    try:
        (Path(info.drive) / config.DONGLE_FILENAME).unlink(missing_ok=True)
    except OSError:
        pass


def is_present(info: DongleInfo) -> bool:
    """Dipanggil berkala oleh UI (config.DONGLE_CHECK_INTERVAL_S) untuk kunci otomatis.
    True hanya bila drive yang sama (serial sama) masih terpasang dan dongle.key-nya identik."""
    try:
        if read_volume_serial(info.drive) != info.serial:
            return False
        key_file = _find_key_file(Path(info.drive))
        return key_file is not None and key_file.read_bytes() == info.key
    except (BrankasError, OSError):
        return False
