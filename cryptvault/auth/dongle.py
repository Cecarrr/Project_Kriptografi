"""Dongle USB. Pemilik: Anggota A."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DongleInfo:
    drive: str          # mis. "E:\\"
    serial: str         # serial volume, hex 8 digit
    serial_hash: str    # SHA-256(serial), yang disimpan di tabel users
    key: bytes          # isi dongle.key (32 B)


def find_dongle() -> DongleInfo | None:
    """Cari flashdisk removable yang berisi dongle.key. None bila tidak ada."""
    raise NotImplementedError


def provision_dongle(drive: str) -> DongleInfo:
    """Registrasi: tulis dongle.key (32 B acak) ke drive, kembalikan DongleInfo."""
    raise NotImplementedError


def is_present(info: DongleInfo) -> bool:
    """Dipanggil berkala oleh UI (config.DONGLE_CHECK_INTERVAL_S) untuk kunci otomatis."""
    raise NotImplementedError
