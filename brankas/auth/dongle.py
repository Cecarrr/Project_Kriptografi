"""Dongle USB. Pemilik: Anggota A."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

import psutil
import win32api
import win32file

from brankas import config
from brankas.errors import BrankasError, DongleNotFound


@dataclass(frozen=True)
class DongleInfo:
    drive: str          # mis. "E:\\"
    serial: str         # serial volume, hex 8 digit
    serial_hash: str    # SHA-256(serial), yang disimpan di tabel users
    key: bytes          # isi dongle.key (32 B)


def _normalize_drive(drive: str) -> str:
    s = str(drive)
    if not s.endswith("\\") and not s.endswith("/"):
        s += "\\"
    return s


def list_removable_drives() -> list[str]:
    """Daftar mountpoint drive removable yang aktif dan memiliki media."""
    drives = []
    for p in psutil.disk_partitions(all=False):
        if not p.fstype:  # Abaikan slot card reader kosong tanpa media
            continue
        mount = _normalize_drive(p.mountpoint)
        is_removable = "removable" in p.opts.lower()
        if not is_removable:
            try:
                is_removable = (win32file.GetDriveType(mount) == win32file.DRIVE_REMOVABLE)
            except Exception:
                pass
        if not is_removable:
            continue

        try:
            win32api.GetVolumeInformation(mount)
            if mount not in drives:
                drives.append(mount)
        except Exception:
            continue
    return drives


def find_dongle() -> DongleInfo | None:
    """Cari flashdisk removable yang berisi dongle.key. None bila tidak ada."""
    # 1. Cek folder dev / override pengujian bila disetel di environment
    dev_dir = os.environ.get("BRANKAS_DEV_DONGLE_DIR")
    if dev_dir:
        dev_path = Path(dev_dir)
        key_path = dev_path / config.DONGLE_FILENAME
        if key_path.is_file():
            key_data = key_path.read_bytes()
            if len(key_data) == config.DONGLE_KEY_BYTES:
                serial_str = "DEV00001"
                serial_hash = hashlib.sha256(serial_str.encode("utf-8")).hexdigest()
                return DongleInfo(drive=str(dev_path), serial=serial_str,
                                  serial_hash=serial_hash, key=key_data)

    # 2. Pindai partisi disk removable
    for p in psutil.disk_partitions(all=False):
        if not p.fstype:  # Abaikan slot tanpa media
            continue
        mount = _normalize_drive(p.mountpoint)
        is_removable = "removable" in p.opts.lower()
        if not is_removable:
            try:
                is_removable = (win32file.GetDriveType(mount) == win32file.DRIVE_REMOVABLE)
            except Exception:
                pass
        if not is_removable:
            continue

        try:
            key_file = Path(mount) / config.DONGLE_FILENAME
            if not key_file.is_file():
                # Cek di subfolder satu tingkat (mis. jika flashdisk memiliki folder seperti 'USB DRIVE')
                for sub in Path(mount).iterdir():
                    try:
                        if sub.is_dir():
                            cand = sub / config.DONGLE_FILENAME
                            if cand.is_file():
                                key_file = cand
                                break
                    except Exception:
                        continue

            if not key_file.is_file():
                continue

            key_data = key_file.read_bytes()
            if len(key_data) != config.DONGLE_KEY_BYTES:
                continue

            vol_info = win32api.GetVolumeInformation(mount)
            serial_val = vol_info[1] & 0xFFFFFFFF
            serial_str = f"{serial_val:08X}"
            serial_hash = hashlib.sha256(serial_str.encode("utf-8")).hexdigest()
            return DongleInfo(drive=mount, serial=serial_str,
                              serial_hash=serial_hash, key=key_data)
        except Exception:
            continue

    return None


def provision_dongle(drive: str) -> DongleInfo:
    """Registrasi: tulis dongle.key (32 B acak) ke drive, kembalikan DongleInfo."""
    drive_p = Path(drive)
    if not drive_p.exists():
        raise DongleNotFound(f"Drive/lokasi {drive} tidak ditemukan")

    mount = _normalize_drive(drive)
    try:
        vol_info = win32api.GetVolumeInformation(mount)
        serial_val = vol_info[1] & 0xFFFFFFFF
        serial_str = f"{serial_val:08X}"
    except Exception as e:
        if os.environ.get("BRANKAS_DEV_DONGLE_DIR"):
            serial_str = "DEV00001"
        else:
            raise DongleNotFound(f"Gagal membaca serial volume pada {drive}: {e}") from e

    serial_hash = hashlib.sha256(serial_str.encode("utf-8")).hexdigest()
    key_bytes = os.urandom(config.DONGLE_KEY_BYTES)
    key_path = drive_p / config.DONGLE_FILENAME

    try:
        key_path.write_bytes(key_bytes)
        # Tulis salinan ke root drive jika pengguna memilih subfolder di dalam flashdisk
        root_key_path = Path(mount) / config.DONGLE_FILENAME
        if root_key_path != key_path:
            try:
                root_key_path.write_bytes(key_bytes)
            except Exception:
                pass
    except Exception as e:
        raise BrankasError(f"Gagal menulis {config.DONGLE_FILENAME} ke {drive}: {e}") from e

    return DongleInfo(drive=mount, serial=serial_str, serial_hash=serial_hash, key=key_bytes)


def is_present(info: DongleInfo) -> bool:
    """Dipanggil berkala oleh UI (config.DONGLE_CHECK_INTERVAL_S) untuk kunci otomatis."""
    if os.environ.get("BRANKAS_DEV_DONGLE_DIR"):
        return (Path(info.drive) / config.DONGLE_FILENAME).is_file()

    mount = _normalize_drive(info.drive)
    try:
        vol_info = win32api.GetVolumeInformation(mount)
        serial_val = vol_info[1] & 0xFFFFFFFF
        serial_str = f"{serial_val:08X}"
        if serial_str != info.serial:
            return False
    except Exception:
        return False

    key_file = Path(mount) / config.DONGLE_FILENAME
    if key_file.is_file():
        return True

    # Cek jika ada di subfolder
    try:
        for sub in Path(mount).iterdir():
            try:
                if sub.is_dir() and (sub / config.DONGLE_FILENAME).is_file():
                    return True
            except Exception:
                continue
    except Exception:
        pass

    return False
