"""Peluncur uji DashboardView TANPA dongle/wajah/login (hanya untuk pengembangan).

Memakai database dan vault terpisah di data/dev/ dan kunci tetap, jadi data uji
tidak bercampur dengan data asli dan tetap bisa dibuka setelah aplikasi ditutup.

Jalankan:  python dev_dashboard.py
"""
import hashlib
from types import SimpleNamespace

import customtkinter as ctk

from brankas import config

config.DB_PATH = config.DATA_DIR / "dev" / "dev.db"
config.VAULT_DIR = config.DATA_DIR / "dev" / "vault"

from brankas.core import keys          # noqa: E402
from brankas.storage import db         # noqa: E402
from brankas.ui.dashboard_view import DashboardView  # noqa: E402


def make_dev_session() -> SimpleNamespace:
    with db.transaction() as conn:
        row = db.get_user_by_dongle(conn, "dev-dongle")
        user_id = row["id"] if row else db.create_user(
            conn, "dev", "-", b"dev-salt-123456", "dev-dongle", b"-")
    master = hashlib.sha256(b"brankas-dev-master").digest()
    return SimpleNamespace(user_id=user_id, username="dev", keys=keys.derive_keyset(master))


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    root.title("Brankas (mode uji dashboard)")
    root.geometry("960x640")
    DashboardView(root, make_dev_session(), on_logout=root.destroy).pack(fill="both", expand=True)
    root.mainloop()
