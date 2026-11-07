"""Jendela utama dan perpindahan layar. Pemilik: bersama (B memegang dashboard)."""
from __future__ import annotations

from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from brankas import config
from brankas.auth import dongle
from brankas.ui.dashboard_view import DashboardView
from brankas.ui.login_view import LoginView

if TYPE_CHECKING:
    from brankas.auth.login import Session


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
    app.title("Brankas - Sistem Penyimpanan Dokumen Aman")
    app.geometry("1000x700")
    if dongle.dev_dir() is not None:   # peringatan agar mode dev tidak terbawa ke demo
        app.title("Brankas [MODE DEV DONGLE - JANGAN DIPAKAI SAAT DEMO]")

    current_frame: ctk.CTkFrame | None = None
    dongle_poll_id: str | None = None

    def cancel_dongle_poll() -> None:
        nonlocal dongle_poll_id
        if dongle_poll_id is not None:
            try:
                app.after_cancel(dongle_poll_id)
            except Exception:
                pass
            dongle_poll_id = None

    def show_login() -> None:
        nonlocal current_frame
        cancel_dongle_poll()

        if current_frame is not None:
            current_frame.destroy()

        login_view = LoginView(app, on_login_success=show_dashboard)
        login_view.pack(fill="both", expand=True)
        current_frame = login_view

    def show_dashboard(session: Session) -> None:
        nonlocal current_frame, dongle_poll_id
        cancel_dongle_poll()

        if current_frame is not None:
            current_frame.destroy()

        dashboard_view = DashboardView(app, session=session, on_logout=show_login)
        dashboard_view.pack(fill="both", expand=True)
        current_frame = dashboard_view

        # Pengawasan berkala dongle USB (kunci otomatis jika dicabut)
        def poll_dongle() -> None:
            nonlocal dongle_poll_id
            if current_frame is not dashboard_view:
                return

            if not dongle.is_present(session.dongle):
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

    show_login()
    app.mainloop()
