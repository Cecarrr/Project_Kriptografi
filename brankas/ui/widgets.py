"""Helper tampilan bersama (dipindahkan dari dashboard_view.py agar bisa dipakai tab lain tanpa
impor melingkar). Pemilik: Anggota B."""
from __future__ import annotations

from datetime import datetime, timezone
from tkinter import ttk

import customtkinter as ctk

GREEN = "#2e7d32"
RED = "#c62828"
MUTED = ("gray40", "gray70")


def fmt_time(value: str, seconds: bool = False) -> str:
    """Waktu UTC dari DB/chain -> waktu lokal yang mudah dibaca."""
    try:
        if "T" in value:
            dt = datetime.fromisoformat(value)
        else:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d-%m-%Y %H:%M:%S" if seconds else "%d-%m-%Y %H:%M")
    except ValueError:
        return value


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def apply_tree_style() -> None:
    dark = ctk.get_appearance_mode() == "Dark"
    bg, fg = ("#2b2b2b", "#dce4ee") if dark else ("#ffffff", "#1a1a1a")
    head_bg = "#1f1f1f" if dark else "#e5e5e5"
    style = ttk.Style()
    style.theme_use("default")
    style.configure("Brankas.Treeview", background=bg, foreground=fg, fieldbackground=bg,
                    rowheight=28, borderwidth=0)
    style.map("Brankas.Treeview", background=[("selected", "#1f538d")],
              foreground=[("selected", "#ffffff")])
    style.configure("Brankas.Treeview.Heading", background=head_bg, foreground=fg,
                    relief="flat", borderwidth=0)
    style.map("Brankas.Treeview.Heading", background=[("active", head_bg)])


def make_tree(parent, columns, selectmode="browse", height=8):
    """columns: [(id, judul, lebar), ...]. Kembalikan (frame, tree); kolom pertama melebar."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                        selectmode=selectmode, height=height, style="Brankas.Treeview")
    for cid, heading, width in columns:
        tree.heading(cid, text=heading, anchor="w")
        tree.column(cid, width=width, anchor="w", stretch=(cid == columns[0][0]))
    scroll = ctk.CTkScrollbar(frame, command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return frame, tree


def set_text(box: ctk.CTkTextbox, text: str) -> None:
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("1.0", text)
    box.configure(state="disabled")
