"""Layar utama setelah login: dokumen (cari, urut, pratinjau), catatan, blockchain, log audit, inspektur.
Pemilik: Anggota B.

Pemakaian:
    view = DashboardView(master, session, on_logout=callback)
    view.pack(fill="both", expand=True)

Anggota A dapat menambah tab sendiri lewat view.tabview, mis.:
    tab = view.tabview.add("Steganografi")
    StegoView(tab, session).pack(fill="both", expand=True)
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Callable

import customtkinter as ctk

from brankas import config
from brankas.chain import blockchain
from brankas.errors import BrankasError
from brankas.storage import db, documents, notes, preview
from brankas.ui.audit_view import AuditView
from brankas.ui.inspector_view import InspectorView
from brankas.ui.stego_view import StegoView
from brankas.ui.widgets import (
    GREEN as _GREEN,
    MUTED as _MUTED,
    RED as _RED,
    apply_tree_style as _apply_tree_style,
    fmt_size as _fmt_size,
    fmt_time as _fmt_time,
    make_tree as _make_tree,
    set_text as _set_text,
)

if TYPE_CHECKING:
    from brankas.auth.login import Session

_GREEN = "#2e7d32"
_RED = "#c62828"


# ---------------------------------------------------------------- helper tampilan
def _fmt_time(value: str) -> str:
    """Waktu UTC dari DB/chain -> waktu lokal yang mudah dibaca."""
    try:
        if "T" in value:
            dt = datetime.fromisoformat(value)
        else:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return value


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _apply_tree_style() -> None:
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


def _make_tree(parent, columns, selectmode="browse", height=8):
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


def _set_text(box: ctk.CTkTextbox, text: str) -> None:
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("1.0", text)
    box.configure(state="disabled")
log = get_logger("dashboard")


# ---------------------------------------------------------------- tampilan utama
class DashboardView(ctk.CTkFrame):
    def __init__(self, master, session: Session, on_logout: Callable[[], None] | None = None,
                 **kwargs):
        super().__init__(master, **kwargs)
        self.session = session
        self.on_logout = on_logout
        self._notes: dict[str, notes.Note] = {}
        self._last_verify: blockchain.VerifyResult | None = None
        self._verify_queue: queue.Queue = queue.Queue()
        self._verify_poll_id: str | None = None
        self._docs: list[documents.DocInfo] = []          # cache daftar dokumen (nama sudah didekripsi)
        self._doc_sort: tuple[str, bool] = ("created", True)   # (kolom, menurun?)
        self._doc_query = ctk.StringVar(master=self)
        self._preview_image = None                         # referensi CTkImage agar tidak di-GC

        _apply_tree_style()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._build_docs_tab(self.tabview.add("Dokumen"))
        self._build_notes_tab(self.tabview.add("Catatan"))
        self._build_chain_tab(self.tabview.add("Blockchain"))
        stego_tab = self.tabview.add("Steganografi")
        self.stego_view = StegoView(stego_tab, self.session)
        self.stego_view.pack(fill="both", expand=True)
        self.audit_view = AuditView(self.tabview.add("Log Audit"), self.session, guard=self._guard)
        self.audit_view.pack(fill="both", expand=True)
        self.inspector_view = InspectorView(self.tabview.add("Inspektur"), self.session, guard=self._guard)
        self.inspector_view.pack(fill="both", expand=True)
        self.refresh_all()

    # ------------------------------------------------------------ utilitas
    @contextmanager
    def _guard(self, title: str = "Gagal"):
        """Tampilkan error sebagai dialog, jangan biarkan aplikasi crash."""
        try:
            yield
        except BrankasError as e:
            messagebox.showerror(title, str(e), parent=self.winfo_toplevel())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Kesalahan tak terduga", f"{type(e).__name__}: {e}",
                                 parent=self.winfo_toplevel())

    def wipe_sensitive(self) -> None:
        """Hapus data terdekripsi (daftar dokumen, isi catatan, hasil stego) dari widget.
        Dipanggil app.py sebelum layar ditutup saat logout / dongle dicabut."""
        try:
            self._notes = {}
            self._last_verify = None
            self.doc_tree.delete(*self.doc_tree.get_children())
            self.note_tree.delete(*self.note_tree.get_children())
            _set_text(self.note_view, "")
            self.note_input.delete("1.0", "end")
            self._docs = []
            self._doc_query.set("")
            self._close_preview()
            self.audit_view.wipe_sensitive()
            self.inspector_view.wipe_sensitive()
            self.stego_view.wipe_sensitive()
        except Exception:  # noqa: BLE001  (widget mungkin sudah dihancurkan)
            log.exception("gagal membersihkan widget dashboard")

    def destroy(self) -> None:
        if self._verify_poll_id is not None:
            try:
                self.after_cancel(self._verify_poll_id)
            except Exception:  # noqa: BLE001
                pass
            self._verify_poll_id = None
        super().destroy()

    def refresh_all(self) -> None:
        self._refresh_docs()
        self._refresh_notes()
        self._refresh_chain()
        self.audit_view.refresh()

    def _build_header(self) -> None:
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        ctk.CTkLabel(head, text="Brankas", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        if self.on_logout:
            ctk.CTkButton(head, text="Keluar", width=80, command=self.on_logout).pack(side="right")
        ctk.CTkLabel(head, text=f"Masuk sebagai {self.session.username}").pack(side="right", padx=12)

    # ------------------------------------------------------------ tab Dokumen
    def _build_docs_tab(self, tab) -> None:
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkButton(bar, text="Unggah", width=110, command=self._upload).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bar, text="Unduh", width=110, command=self._download).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Hapus", width=110, fg_color=_RED, hover_color="#8e1f1f",
                      command=self._delete_docs).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Segarkan", width=100, command=self._refresh_docs).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Pratinjau", width=110, command=self._preview).pack(side="left", padx=6)
        self.doc_status = ctk.CTkLabel(bar, text="", anchor="e")
        self.doc_status.pack(side="right")

        search = ctk.CTkFrame(tab, fg_color="transparent")
        search.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkEntry(search, textvariable=self._doc_query, placeholder_text="Cari nama file...").pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(search, text="Hapus pencarian", width=130, fg_color="transparent", border_width=1,
                      text_color=_MUTED, command=lambda: self._doc_query.set("")).pack(side="left", padx=(6, 0))
        self._doc_query.trace_add("write", lambda *_: self._render_docs())

        self._doc_titles = {"name": "Nama", "type": "Jenis", "size": "Ukuran", "created": "Ditambahkan"}
        frame, self.doc_tree = _make_tree(
            tab,
            [("name", "Nama", 320), ("type", "Jenis", 70), ("size", "Ukuran", 90), ("created", "Ditambahkan", 150)],
            selectmode="extended",
        )
        for cid in self._doc_titles:
            self.doc_tree.heading(cid, command=lambda c=cid: self._sort_docs_by(c))
        self.doc_tree.bind("<Double-1>", self._on_doc_double_click)
        self._doc_tree_frame = frame
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # panel pratinjau: dibuat tersembunyi, muncul di bawah daftar saat dipakai
        self.preview_frame = ctk.CTkFrame(tab)
        head = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        head.pack(fill="x", padx=8, pady=(6, 0))
        self.preview_title = ctk.CTkLabel(head, text="", anchor="w", font=ctk.CTkFont(weight="bold"))
        self.preview_title.pack(side="left")
        ctk.CTkButton(head, text="Tutup", width=70, command=self._close_preview).pack(side="right")
        ctk.CTkLabel(self.preview_frame, text="Didekripsi hanya di memori; tidak ada file yang ditulis ke disk.",
                     anchor="w", text_color=_MUTED, font=ctk.CTkFont(size=11)).pack(fill="x", padx=10)
        self.preview_body = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        self.preview_body.pack(fill="both", expand=True, padx=8, pady=(2, 8))

    # -- daftar: cari dan urut kolom (di memori; nama file sudah didekripsi)
    _DOC_SORT_KEYS = {
        "name": lambda d: d.filename.casefold(),
        "type": lambda d: (d.file_type, d.filename.casefold()),
        "size": lambda d: d.size,                 # angka, bukan teks "1.2 MB"
        "created": lambda d: d.created_at,        # "YYYY-MM-DD HH:MM:SS" urut benar sebagai teks
    }

    def _refresh_docs(self) -> None:
        with self._guard():
            self._docs = documents.list_documents(self.session)
            self._render_docs()

    def _render_docs(self) -> None:
        col, desc = self._doc_sort
        query = self._doc_query.get().strip().casefold()
        shown = [d for d in self._docs if query in d.filename.casefold()] if query else list(self._docs)
        shown.sort(key=self._DOC_SORT_KEYS[col], reverse=desc)    # sort stabil: urutan awal terjaga saat seri

        selected = set(self.doc_tree.selection())
        self.doc_tree.delete(*self.doc_tree.get_children())
        for d in shown:
            self.doc_tree.insert("", "end", iid=d.id,
                                 values=(d.filename, d.file_type, _fmt_size(d.size), _fmt_time(d.created_at)))
        keep = [d.id for d in shown if d.id in selected]
        if keep:
            self.doc_tree.selection_set(keep)
        for cid, title in self._doc_titles.items():
            arrow = (" \u25bc" if desc else " \u25b2") if cid == col else ""
            self.doc_tree.heading(cid, text=title + arrow)
        total = len(self._docs)
        self.doc_status.configure(text=f"{len(shown)} dari {total} dokumen" if query else f"{total} dokumen")

    def _sort_docs_by(self, col: str) -> None:
        cur, desc = self._doc_sort
        # klik kolom yang sama membalik arah; kolom baru: ukuran dan tanggal mulai dari terbesar/terbaru
        self._doc_sort = (col, not desc) if col == cur else (col, col in ("size", "created"))
        self._render_docs()

    # -- pratinjau di memori
    def _on_doc_double_click(self, event) -> None:
        if self.doc_tree.identify_region(event.x, event.y) == "cell":
            self._preview()

    def _preview(self) -> None:
        sel = self.doc_tree.selection()
        if len(sel) != 1:
            messagebox.showinfo("Pratinjau", "Pilih tepat satu dokumen.", parent=self.winfo_toplevel())
            return
        doc_id = sel[0]
        name = self.doc_tree.set(doc_id, "name")
        ext = self.doc_tree.set(doc_id, "type")
        with self._guard("Pratinjau"):
            data = documents.read_document(self.session, doc_id)
            self._show_preview(name, ext, data)
            self.audit_view.refresh()

    def _show_preview(self, name: str, ext: str, data: bytes) -> None:
        self._clear_preview_body()
        kind = preview.kind_of(ext)
        title = f"Pratinjau: {name}"
        if kind == "image":
            img, original = preview.load_image(data)
            self._preview_image = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            ctk.CTkLabel(self.preview_body, text="", image=self._preview_image).pack(pady=4)
            title += f"  ({original[0]}\u00d7{original[1]} px)"
        else:
            if kind == "text":
                text = preview.text_from_bytes(data)
            elif kind == "docx":
                text = preview.docx_to_text(data)
            else:
                text = f"Pratinjau belum tersedia untuk jenis file {ext or '(tanpa ekstensi)'}. Gunakan Unduh."
            box = ctk.CTkTextbox(self.preview_body, height=170, wrap="word", state="disabled")
            box.pack(fill="both", expand=True)
            _set_text(box, text)
        self.preview_title.configure(text=title)
        self.preview_frame.pack(side="bottom", fill="x", padx=8, pady=(0, 8), before=self._doc_tree_frame)

    def _clear_preview_body(self) -> None:
        # widget dibuat ulang tiap pratinjau: configure(image=None) pada CTkLabel bisa memicu TclError
        for child in self.preview_body.winfo_children():
            child.destroy()
        self._preview_image = None

    def _close_preview(self) -> None:
        self._clear_preview_body()
        self.preview_title.configure(text="")
        self.preview_frame.pack_forget()

    def _upload(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(config.ALLOWED_DOC_EXT))
        paths = filedialog.askopenfilenames(
            parent=self.winfo_toplevel(), title="Pilih file untuk diunggah",
            filetypes=[("Dokumen dan gambar", exts), ("Semua file", "*.*")],
        )
        if not paths:
            return
        failed = []
        for i, p in enumerate(paths, 1):
            self.doc_status.configure(text=f"Mengenkripsi {i}/{len(paths)}...")
            self.update_idletasks()
            try:
                documents.add_document(self.session, Path(p))
            except Exception as e:  # noqa: BLE001
                msg = str(e) if isinstance(e, BrankasError) else f"{type(e).__name__}: {e}"
                failed.append(f"{Path(p).name}: {msg}")
        self._refresh_docs()
        self._refresh_chain()
        if failed:
            messagebox.showwarning("Sebagian file gagal diunggah", "\n".join(failed),
                                   parent=self.winfo_toplevel())

    def _download(self) -> None:
        sel = self.doc_tree.selection()
        if len(sel) != 1:
            messagebox.showinfo("Unduh", "Pilih tepat satu dokumen.", parent=self.winfo_toplevel())
            return
        name = self.doc_tree.set(sel[0], "name")
        dest = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), title="Simpan dokumen sebagai",
            initialfile=name, defaultextension=Path(name).suffix,
        )
        if not dest:
            return
        with self._guard():
            documents.export_document(self.session, sel[0], Path(dest))
            self.audit_view.refresh()
            messagebox.showinfo("Unduh", "Dokumen berhasil didekripsi dan disimpan.",
                                parent=self.winfo_toplevel())

    def _delete_docs(self) -> None:
        sel = self.doc_tree.selection()
        if not sel:
            messagebox.showinfo("Hapus", "Pilih dokumen yang akan dihapus.", parent=self.winfo_toplevel())
            return
        if not messagebox.askyesno("Hapus dokumen", f"Hapus {len(sel)} dokumen? Tindakan ini tidak bisa dibatalkan.",
                                   parent=self.winfo_toplevel()):
            return
        with self._guard():
            for doc_id in sel:
                documents.delete_document(self.session, doc_id)
        self._refresh_docs()
        self._refresh_chain()

    # ------------------------------------------------------------ tab Catatan
    def _build_notes_tab(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(tab, text="Catatan baru (dienkripsi: Vigenère + ChaCha20-Poly1305)",
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=8)
        top.grid_columnconfigure(0, weight=1)
        self.note_input = ctk.CTkTextbox(top, height=80, wrap="word")
        self.note_input.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(top, text="Simpan\ncatatan", width=100, command=self._add_note).grid(
            row=0, column=1, padx=(8, 0), sticky="ns")

        frame, self.note_tree = _make_tree(tab, [("preview", "Isi", 420), ("created", "Dibuat", 150)], height=6)
        frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        self.note_tree.bind("<<TreeviewSelect>>", self._on_note_select)

        bottom = ctk.CTkFrame(tab, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        bottom.grid_columnconfigure(0, weight=1)
        self.note_view = ctk.CTkTextbox(bottom, height=90, wrap="word", state="disabled")
        self.note_view.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(bottom, text="Hapus\ncatatan", width=100, fg_color=_RED, hover_color="#8e1f1f",
                      command=self._delete_note).grid(row=0, column=1, padx=(8, 0), sticky="ns")

    def _refresh_notes(self) -> None:
        with self._guard():
            items = notes.list_notes(self.session)
            self._notes = {str(n.id): n for n in items}
            self.note_tree.delete(*self.note_tree.get_children())
            for n in items:
                preview = n.content.replace("\n", " ")
                if len(preview) > 80:
                    preview = preview[:80] + "\u2026"
                self.note_tree.insert("", "end", iid=str(n.id), values=(preview, _fmt_time(n.created_at)))
            _set_text(self.note_view, "")

    def _add_note(self) -> None:
        text = self.note_input.get("1.0", "end").strip()
        with self._guard():
            notes.add_note(self.session, text)
            self.note_input.delete("1.0", "end")
            self._refresh_notes()

    def _on_note_select(self, _event=None) -> None:
        sel = self.note_tree.selection()
        if sel and sel[0] in self._notes:
            _set_text(self.note_view, self._notes[sel[0]].content)

    def _delete_note(self) -> None:
        sel = self.note_tree.selection()
        if not sel:
            messagebox.showinfo("Hapus", "Pilih catatan yang akan dihapus.", parent=self.winfo_toplevel())
            return
        if not messagebox.askyesno("Hapus catatan", "Hapus catatan ini?", parent=self.winfo_toplevel()):
            return
        with self._guard():
            notes.delete_note(self.session, int(sel[0]))
            self._refresh_notes()

    # ------------------------------------------------------------ tab Blockchain
    def _build_chain_tab(self, tab) -> None:
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkButton(bar, text="Verifikasi rantai", width=150, command=self._verify_chain).pack(side="left")
        ctk.CTkButton(bar, text="Segarkan", width=100, command=self._refresh_chain).pack(side="left", padx=8)
        self.chain_status = ctk.CTkLabel(bar, text="Belum diverifikasi", anchor="w")
        self.chain_status.pack(side="left", padx=8)

        self.chain_problems = ctk.CTkTextbox(tab, height=70, wrap="word", state="disabled")
        self.chain_problems.pack(fill="x", padx=8, pady=4)

        frame, self.chain_tree = _make_tree(
            tab,
            [("idx", "#", 40), ("time", "Waktu", 140), ("action", "Aksi", 90), ("doc", "Dokumen", 100),
             ("hash", "Hash blok", 260)],
            height=8,
        )
        self.chain_tree.column("idx", stretch=False)
        self.chain_tree.column("hash", stretch=True)
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    def _refresh_chain(self) -> None:
        with self._guard():
            with db.transaction() as conn:
                blocks = blockchain.list_blocks(conn)
            self.chain_tree.delete(*self.chain_tree.get_children())
            for b in blocks:
                doc = b.doc_id[:8] if b.doc_id != "-" else "-"
                self.chain_tree.insert("", "end", values=(b.idx, _fmt_time(b.timestamp), b.action, doc,
                                                         b.hash[:24] + "\u2026"))

    def _verify_chain(self) -> None:
        with self._guard():
            with db.transaction() as conn:
                result = blockchain.verify_chain(conn, config.VAULT_DIR)
            if result.ok:
                self.chain_status.configure(
                    text=f"Rantai VALID ({result.checked_blocks} blok diperiksa)", text_color=_GREEN)
                _set_text(self.chain_problems, "")
            else:
                self.chain_status.configure(
                    text=f"DITEMUKAN {len(result.problems)} MASALAH ({result.checked_blocks} blok diperiksa)",
                    text_color=_RED)
                _set_text(self.chain_problems, "\n".join(result.problems))
