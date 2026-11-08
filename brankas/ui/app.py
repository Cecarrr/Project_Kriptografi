"""Jendela utama dan perpindahan layar. Pemilik: bersama (B memegang dashboard)."""
from __future__ import annotations

from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from brankas import config
from brankas.applog import get_logger, setup_logging
from brankas.auth import dongle
from brankas.ui.dashboard_view import DashboardView
from brankas.ui.login_view import LoginView

if TYPE_CHECKING:
    from brankas.auth.login import Session

log = get_logger("app")


def run() -> None:
    setup_logging()
    log.info("aplikasi dimulai")

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
    app.title("Brankas - Sistem Penyimpanan Dokumen Aman")
    app.geometry("1000x700")
    if dongle.dev_dir() is not None:   # peringatan agar mode dev tidak terbawa ke demo
        app.title("Brankas [MODE DEV DONGLE - JANGAN DIPAKAI SAAT DEMO]")
        log.warning("MODE DEV DONGLE aktif (BRANKAS_DEV_DONGLE_DIR)")

    current_frame: ctk.CTkFrame | None = None
    current_session: Session | None = None
    dongle_poll_id: str | None = None

    def report_callback_exception(exc, val, tb) -> None:
        """Error tak terduga di callback Tk: catat di log dan tampilkan dialog (bukan hanya cetak ke konsol)."""
        log.error("kesalahan tak terduga di callback UI", exc_info=(exc, val, tb))
        try:
            messagebox.showerror("Kesalahan tak terduga", f"{exc.__name__}: {val}", parent=app)
        except Exception:  # noqa: BLE001
            pass

    app.report_callback_exception = report_callback_exception

    def cancel_dongle_poll() -> None:
        nonlocal dongle_poll_id
        if dongle_poll_id is not None:
            try:
                app.after_cancel(dongle_poll_id)
            except Exception:  # noqa: BLE001
                pass
            dongle_poll_id = None

    def lock_session() -> None:
        """Hapus data terdekripsi dari layar lalu kunci sesi (kunci dilepas dari memori, best effort)."""
        nonlocal current_session
        if current_frame is not None and hasattr(current_frame, "wipe_sensitive"):
            current_frame.wipe_sensitive()
        if current_session is not None:
            current_session.lock()
            current_session = None

    def show_login() -> None:
        nonlocal current_frame
        cancel_dongle_poll()
        lock_session()   # sebelum frame lama dihancurkan, supaya widget masih bisa dibersihkan

        if current_frame is not None:
            current_frame.destroy()

        login_view = LoginView(app, on_login_success=show_dashboard)
        login_view.pack(fill="both", expand=True)
        current_frame = login_view

    def show_dashboard(session: Session) -> None:
        nonlocal current_frame, current_session, dongle_poll_id
        cancel_dongle_poll()

        if current_frame is not None:
            current_frame.destroy()

        current_session = session
        dashboard_view = DashboardView(app, session=session, on_logout=show_login)
        dashboard_view.pack(fill="both", expand=True)
        current_frame = dashboard_view

        # Pengawasan berkala dongle USB (kunci otomatis jika dicabut)
        def poll_dongle() -> None:
            nonlocal dongle_poll_id
            if current_frame is not dashboard_view or session.locked:
                return

            if not dongle.is_present(session.dongle):
                log.warning("dongle dicabut, sesi dikunci otomatis user=%s", session.user_id)
                lock_session()   # kunci dulu SEBELUM dialog (dialog modal bisa tampil lama)
                messagebox.showwarning(
                    "Dongle Dicabut!",
                    "Flashdisk dongle telah dicabut dari perangkat!\n"
                    "Aplikasi dikunci secara otomatis demi keamanan data.",
                    parent=app,
                )
                show_login()
                return

            dongle_poll_id = app.after(
                int(config.DONGLE_CHECK_INTERVAL_S * 1000), poll_dongle
            )

        dongle_poll_id = app.after(
            int(config.DONGLE_CHECK_INTERVAL_S * 1000), poll_dongle
        )

    def on_close() -> None:
        log.info("aplikasi ditutup")
        cancel_dongle_poll()
        lock_session()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)

    show_login()
    app.mainloop()
