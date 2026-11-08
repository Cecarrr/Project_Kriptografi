"""Tab Log Audit: riwayat LOGIN / LOGOUT / UNDUH / PRATINJAU milik pengguna + verifikasi hash berantai.
Pemilik: Anggota B.

Pemakaian:  AuditView(tab, session, guard=dashboard._guard).pack(fill="both", expand=True)
refresh() dipanggil dashboard setelah aksi yang menambah log.
"""
from __future__ import annotations

import customtkinter as ctk

from brankas.storage import audit, db, documents
from brankas.ui.widgets import GREEN, MUTED, RED, fmt_time, make_tree, set_text

_ACTION_LABEL = {"LOGIN": "LOGIN", "LOGOUT": "LOGOUT", "UNDUH": "UNDUH", "PRATINJAU": "PRATINJAU"}


class AuditView(ctk.CTkFrame):
    def __init__(self, master, session, guard, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.session = session
        self._guard = guard

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkButton(bar, text="Segarkan", width=100, command=self.refresh).pack(side="left")
        self.status = ctk.CTkLabel(bar, text="", anchor="w")
        self.status.pack(side="left", padx=12)
        ctk.CTkLabel(self, text="Hanya menampilkan peristiwa akun Anda. Keluar (LOGOUT) baru terlihat setelah "
                                "masuk berikutnya. Verifikasi hash memeriksa seluruh log.",
                     anchor="w", justify="left", text_color=MUTED, font=ctk.CTkFont(size=11),
                     wraplength=720).pack(fill="x", padx=12)

        self.problems = ctk.CTkTextbox(self, height=60, wrap="word", state="disabled")
        self.problems.pack(fill="x", padx=8, pady=4)

        frame, self.tree = make_tree(
            self, [("idx", "#", 50), ("time", "Waktu", 150), ("action", "Aksi", 100), ("doc", "Dokumen", 320)],
            height=10,
        )
        self.tree.column("idx", stretch=False)
        self.tree.column("doc", stretch=True)
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    def refresh(self) -> None:
        with self._guard("Log audit"):
            with db.transaction() as conn:
                entries = audit.list_entries(conn, self.session.user_id)
                result = audit.verify_audit(conn)
            names = {d.id: d.filename for d in documents.list_documents(self.session)}

            self.tree.delete(*self.tree.get_children())
            for e in entries:
                if e.doc_id == "-":
                    doc = "-"
                elif e.doc_id in names:
                    doc = names[e.doc_id]
                else:
                    doc = f"{e.doc_id[:8]} (sudah dihapus)"
                self.tree.insert("", "end", values=(e.idx, fmt_time(e.timestamp, seconds=True),
                                                    _ACTION_LABEL.get(e.action, e.action), doc))
            if result.ok:
                self.status.configure(text=f"{len(entries)} peristiwa. Log berantai VALID", text_color=GREEN)
                set_text(self.problems, "")
            else:
                self.status.configure(text=f"{len(entries)} peristiwa. DITEMUKAN {len(result.problems)} MASALAH",
                                      text_color=RED)
                set_text(self.problems, "\n".join(result.problems))

    def wipe_sensitive(self) -> None:
        """Nama dokumen yang sudah didekripsi ikut dibuang saat logout / dongle dicabut."""
        self.tree.delete(*self.tree.get_children())
        set_text(self.problems, "")
        self.status.configure(text="")
