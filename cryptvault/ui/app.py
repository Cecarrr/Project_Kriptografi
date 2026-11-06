"""Jendela utama dan perpindahan layar. Pemilik: bersama (B memegang dashboard)."""
import customtkinter as ctk


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ctk.CTk()
    app.title("CryptVault")
    app.geometry("900x600")
    # TODO: tampilkan LoginView; setelah sukses ganti ke DashboardView(session)
    ctk.CTkLabel(app, text="CryptVault - kerangka siap", font=("Segoe UI", 20)).pack(pady=40)
    app.mainloop()
