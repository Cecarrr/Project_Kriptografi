"""Sisipkan dan ekstrak catatan terenkripsi di gambar PNG. Pemilik: Anggota A."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk
from PIL import Image

from brankas.errors import BrankasError
from brankas.stego import lsb

if TYPE_CHECKING:
    from brankas.auth.login import Session

_COLOR_SUCCESS = "#2e7d32"
_COLOR_ERROR = "#c62828"
_COLOR_INFO = "#1f538d"
_COLOR_TEXT = ("gray10", "#DCE4EE")
_COLOR_MUTED = ("gray40", "gray70")


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class StegoView(ctk.CTkFrame):
    def __init__(self, master, session: Session, **kwargs):
        super().__init__(master, **kwargs)
        self.session = session
        self._cover_path: Path | None = None
        self._cover_thumb: ctk.CTkImage | None = None
        self._stego_path: Path | None = None
        self._stego_thumb: ctk.CTkImage | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.subtabs = ctk.CTkTabview(self)
        self.subtabs.pack(fill="both", expand=True, padx=8, pady=8)

        tab_embed = self.subtabs.add("  Sembunyikan Catatan (Embed)  ")
        tab_extract = self.subtabs.add("  Ekstrak Catatan (Reveal)  ")

        self._build_embed_tab(tab_embed)
        self._build_extract_tab(tab_extract)

    def _create_thumbnail(self, img_path: Path, max_size=(100, 75)) -> ctk.CTkImage | None:
        try:
            with Image.open(img_path) as im:
                thumb = im.copy()
                thumb.thumbnail(max_size, Image.Resampling.LANCZOS)
                w, h = thumb.size
                return ctk.CTkImage(light_image=thumb, dark_image=thumb, size=(w, h))
        except Exception:
            return None

    # =========================================================================
    # TAB 1: Sembunyikan Catatan (Embed)
    # =========================================================================
    def _build_embed_tab(self, tab) -> None:
        container = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=6, pady=6)

        # 1. Card Pilih Gambar Cover
        card_upload = ctk.CTkFrame(container, corner_radius=10)
        card_upload.pack(fill="x", padx=4, pady=(2, 8))

        header_frame = ctk.CTkFrame(card_upload, fg_color="transparent")
        header_frame.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            header_frame,
            text="1. Pilih Gambar Cover (PNG)",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            header_frame,
            text="📁 Pilih File PNG...",
            width=150,
            command=self._select_cover_image,
        ).pack(side="right")

        # Tombol Batal Upload Cover
        self.btn_cancel_cover = ctk.CTkButton(
            header_frame,
            text="✖ Batal",
            width=70,
            height=28,
            fg_color=_COLOR_ERROR,
            hover_color="#8e1f1f",
            font=ctk.CTkFont(size=11),
            state="disabled",
            command=self._cancel_cover_image,
        )
        self.btn_cancel_cover.pack(side="right", padx=6)

        # Box info status upload
        self.card_cover_status = ctk.CTkFrame(card_upload, fg_color=("gray85", "#242424"), corner_radius=8)
        self.card_cover_status.pack(fill="x", padx=12, pady=(0, 10))

        self.label_cover_thumb = ctk.CTkLabel(self.card_cover_status, text="")
        self.label_cover_thumb.pack(side="left", padx=(10, 12), pady=8)

        info_text_frame = ctk.CTkFrame(self.card_cover_status, fg_color="transparent")
        info_text_frame.pack(side="left", fill="both", expand=True, pady=8)

        self.label_cover_title = ctk.CTkLabel(
            info_text_frame,
            text="Belum ada gambar yang di-upload",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        self.label_cover_title.pack(anchor="w")

        self.label_cover_meta = ctk.CTkLabel(
            info_text_frame,
            text="Silakan klik tombol 'Pilih File PNG' untuk memilih gambar penampung.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        )
        self.label_cover_meta.pack(anchor="w", pady=(2, 0))

        # 2. Card Catatan Rahasia
        card_note = ctk.CTkFrame(container, corner_radius=10)
        card_note.pack(fill="both", expand=True, padx=4, pady=6)

        lbl_note_head = ctk.CTkLabel(
            card_note,
            text="2. Catatan Rahasia yang Akan Disembunyikan",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        lbl_note_head.pack(anchor="w", padx=12, pady=(10, 4))

        self.text_embed_note = ctk.CTkTextbox(card_note, height=130, wrap="word")
        self.text_embed_note.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.text_embed_note.bind("<KeyRelease>", self._update_embed_char_count)

        self.label_note_counter = ctk.CTkLabel(
            card_note,
            text="Panjang teks: 0 karakter",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="e",
        )
        self.label_note_counter.pack(fill="x", padx=14, pady=(0, 8))

        # 3. Card Aksi & Hasil
        card_action = ctk.CTkFrame(container, corner_radius=10)
        card_action.pack(fill="x", padx=4, pady=6)

        action_bar = ctk.CTkFrame(card_action, fg_color="transparent")
        action_bar.pack(fill="x", padx=12, pady=10)

        ctk.CTkButton(
            action_bar,
            text="🔒 Sembunyikan & Simpan PNG...",
            font=ctk.CTkFont(weight="bold"),
            width=230,
            height=36,
            command=self._execute_embed,
        ).pack(side="left")

        self.label_embed_result = ctk.CTkLabel(
            action_bar,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.label_embed_result.pack(side="left", padx=14, fill="x", expand=True)

    def _update_embed_char_count(self, event=None) -> None:
        text = self.text_embed_note.get("1.0", "end-1c")
        n_chars = len(text)
        n_bytes = len(text.encode("utf-8"))
        if self._cover_path:
            try:
                cap = lsb.capacity_bytes(self._cover_path)
                status_color = _COLOR_ERROR if n_bytes > cap else "gray"
                self.label_note_counter.configure(
                    text=f"Panjang teks: {n_chars:,} karakter ({_fmt_size(n_bytes)}) / Kapasitas gambar: {_fmt_size(cap)}",
                    text_color=status_color,
                )
                return
            except Exception:
                pass
        self.label_note_counter.configure(
            text=f"Panjang teks: {n_chars:,} karakter ({_fmt_size(n_bytes)})",
            text_color="gray",
        )

    def _select_cover_image(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Pilih Gambar Cover PNG",
            filetypes=[("Berkas PNG", "*.png")],
            parent=self.winfo_toplevel(),
        )
        if not file_path:
            return

        p = Path(file_path)
        try:
            cap = lsb.capacity_bytes(p)
            with Image.open(p) as img:
                dim_str = f"{img.width} × {img.height} px"
            filesize_str = _fmt_size(p.stat().st_size)

            self._cover_path = p
            self._cover_thumb = self._create_thumbnail(p)

            # Update tampilan sukses upload
            if self._cover_thumb:
                self.label_cover_thumb.configure(image=self._cover_thumb, text="")
            else:
                self.label_cover_thumb.configure(image=None, text="🖼️")

            self.label_cover_title.configure(
                text=f"✔ Berhasil Di-upload: {p.name}",
                text_color=_COLOR_SUCCESS,
            )
            self.label_cover_meta.configure(
                text=f"Dimensi: {dim_str}  |  Ukuran file: {filesize_str}  |  Daya tampung rahasia: {_fmt_size(cap)} ({cap:,} bytes)",
                text_color=_COLOR_MUTED,
            )
            self.btn_cancel_cover.configure(state="normal")
            self.label_embed_result.configure(text="")
            self._update_embed_char_count()

        except BrankasError as e:
            self._cover_path = None
            self._cover_thumb = None
            self.btn_cancel_cover.configure(state="disabled")
            self.label_cover_thumb.configure(image=None, text="⚠️")
            self.label_cover_title.configure(
                text=f"❌ Gagal Memuat: {p.name}",
                text_color=_COLOR_ERROR,
            )
            self.label_cover_meta.configure(text=str(e), text_color=_COLOR_ERROR)
            messagebox.showerror("Gambar Tidak Valid", str(e), parent=self.winfo_toplevel())

    def _cancel_cover_image(self) -> None:
        """Batalkan pemilihan gambar cover."""
        self._cover_path = None
        self._cover_thumb = None
        self.label_cover_thumb.configure(image=None, text="")
        self.label_cover_title.configure(
            text="Belum ada gambar yang di-upload",
            text_color=_COLOR_TEXT,
        )
        self.label_cover_meta.configure(
            text="Silakan klik tombol 'Pilih File PNG' untuk memilih gambar penampung.",
            text_color="gray",
        )
        self.btn_cancel_cover.configure(state="disabled")
        self.label_embed_result.configure(text="")
        self._update_embed_char_count()

    def _execute_embed(self) -> None:
        if not self._cover_path:
            messagebox.showwarning(
                "Peringatan", "Silakan pilih gambar cover PNG terlebih dahulu.", parent=self.winfo_toplevel()
            )
            return

        content = self.text_embed_note.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showwarning(
                "Peringatan", "Catatan rahasia tidak boleh kosong.", parent=self.winfo_toplevel()
            )
            return

        out_path_str = filedialog.asksaveasfilename(
            title="Simpan Gambar Berisi Rahasia",
            defaultextension=".png",
            filetypes=[("Berkas PNG", "*.png")],
            initialfile=f"stego_{self._cover_path.name}",
            parent=self.winfo_toplevel(),
        )
        if not out_path_str:
            return

        out_p = Path(out_path_str)
        try:
            lsb.hide_note(self.session, self._cover_path, content, out_p)
            self.label_embed_result.configure(
                text=f"✔ Berhasil disembunyikan ke: {out_p.name}",
                text_color=_COLOR_SUCCESS,
            )
            # Otomatis pre-load file stego ke tab Extract agar user tidak salah pilih file
            self._preload_stego_for_extract(out_p)
            if messagebox.askyesno(
                "Berhasil Menyimpan",
                f"Catatan rahasia berhasil dienkripsi dan disisipkan ke dalam gambar:\n{out_p}\n\n"
                "Buka tab Ekstrak untuk mencoba membacanya sekarang?",
                parent=self.winfo_toplevel(),
            ):
                self.subtabs.set("  Ekstrak Catatan (Reveal)  ")
        except BrankasError as e:
            self.label_embed_result.configure(text=f"❌ {e}", text_color=_COLOR_ERROR)
            messagebox.showerror("Gagal Menyembunyikan", str(e), parent=self.winfo_toplevel())

    # =========================================================================
    # TAB 2: Ekstrak Catatan (Reveal)
    # =========================================================================
    def _build_extract_tab(self, tab) -> None:
        container = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=6, pady=6)

        # 1. Card Pilih Gambar Stego
        card_upload = ctk.CTkFrame(container, corner_radius=10)
        card_upload.pack(fill="x", padx=4, pady=(2, 8))

        header_frame = ctk.CTkFrame(card_upload, fg_color="transparent")
        header_frame.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            header_frame,
            text="1. Pilih Gambar Stego (PNG)",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            header_frame,
            text="📁 Pilih File Stego...",
            width=150,
            command=self._select_stego_image,
        ).pack(side="right")

        # Tombol Batal Upload Stego
        self.btn_cancel_stego = ctk.CTkButton(
            header_frame,
            text="✖ Batal",
            width=70,
            height=28,
            fg_color=_COLOR_ERROR,
            hover_color="#8e1f1f",
            font=ctk.CTkFont(size=11),
            state="disabled",
            command=self._cancel_stego_image,
        )
        self.btn_cancel_stego.pack(side="right", padx=6)

        # Box info status upload stego
        self.card_stego_status = ctk.CTkFrame(card_upload, fg_color=("gray85", "#242424"), corner_radius=8)
        self.card_stego_status.pack(fill="x", padx=12, pady=(0, 10))

        self.label_stego_thumb = ctk.CTkLabel(self.card_stego_status, text="")
        self.label_stego_thumb.pack(side="left", padx=(10, 12), pady=8)

        info_text_frame = ctk.CTkFrame(self.card_stego_status, fg_color="transparent")
        info_text_frame.pack(side="left", fill="both", expand=True, pady=8)

        self.label_stego_title = ctk.CTkLabel(
            info_text_frame,
            text="Belum ada gambar stego yang di-upload",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        self.label_stego_title.pack(anchor="w")

        self.label_stego_meta = ctk.CTkLabel(
            info_text_frame,
            text="Pilih berkas PNG yang sebelumnya telah disisipi catatan rahasia.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        )
        self.label_stego_meta.pack(anchor="w", pady=(2, 0))

        # 2. Tombol Aksi Ekstrak
        card_action = ctk.CTkFrame(container, corner_radius=10)
        card_action.pack(fill="x", padx=4, pady=6)

        action_bar = ctk.CTkFrame(card_action, fg_color="transparent")
        action_bar.pack(fill="x", padx=12, pady=10)

        ctk.CTkButton(
            action_bar,
            text="🔓 Ekstrak & Dekripsi Catatan",
            font=ctk.CTkFont(weight="bold"),
            width=230,
            height=36,
            command=self._execute_extract,
        ).pack(side="left")

        self.label_extract_result = ctk.CTkLabel(
            action_bar,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.label_extract_result.pack(side="left", padx=14, fill="x", expand=True)

        # 3. Card Hasil Catatan
        card_result = ctk.CTkFrame(container, corner_radius=10)
        card_result.pack(fill="both", expand=True, padx=4, pady=6)

        result_header = ctk.CTkFrame(card_result, fg_color="transparent")
        result_header.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            result_header,
            text="2. Hasil Catatan Rahasia yang Terbaca",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            result_header,
            text="📋 Salin Catatan",
            width=110,
            command=self._copy_revealed_note,
        ).pack(side="right")

        self.text_extracted = ctk.CTkTextbox(card_result, height=130, wrap="word")
        self.text_extracted.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _preload_stego_for_extract(self, stego_path: Path) -> None:
        """Setelah embed berhasil, otomatis muat file stego ke tab Extract."""
        try:
            with Image.open(stego_path) as img:
                dim_str = f"{img.width} × {img.height} px"
            filesize_str = _fmt_size(stego_path.stat().st_size)

            self._stego_path = stego_path
            self._stego_thumb = self._create_thumbnail(stego_path)

            if self._stego_thumb:
                self.label_stego_thumb.configure(image=self._stego_thumb, text="")
            else:
                self.label_stego_thumb.configure(image=None, text="🖼️")

            self.label_stego_title.configure(
                text=f"✔ Siap Diekstrak: {stego_path.name}",
                text_color=_COLOR_SUCCESS,
            )
            self.label_stego_meta.configure(
                text=f"Dimensi: {dim_str}  |  Ukuran file: {filesize_str}  |  "
                     f"⚠️ Ini adalah file output dari embed — jangan ganti ke file lain!",
                text_color=_COLOR_MUTED,
            )
            self.btn_cancel_stego.configure(state="normal")
            self.label_extract_result.configure(text="")
            self.text_extracted.delete("1.0", "end")
        except Exception:
            pass  # Jika gagal pre-load, biarkan user pilih manual

    def _select_stego_image(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Pilih Gambar Stego PNG",
            filetypes=[("Berkas PNG", "*.png")],
            parent=self.winfo_toplevel(),
        )
        if not file_path:
            return

        p = Path(file_path)
        try:
            with Image.open(p) as img:
                dim_str = f"{img.width} × {img.height} px"
            filesize_str = _fmt_size(p.stat().st_size)

            self._stego_path = p
            self._stego_thumb = self._create_thumbnail(p)

            if self._stego_thumb:
                self.label_stego_thumb.configure(image=self._stego_thumb, text="")
            else:
                self.label_stego_thumb.configure(image=None, text="🖼️")

            self.label_stego_title.configure(
                text=f"✔ Berhasil Di-upload: {p.name}",
                text_color=_COLOR_SUCCESS,
            )
            self.label_stego_meta.configure(
                text=f"Dimensi: {dim_str}  |  Ukuran file: {filesize_str}  |  Siap untuk diekstrak.",
                text_color=_COLOR_MUTED,
            )
            self.btn_cancel_stego.configure(state="normal")
            self.label_extract_result.configure(text="")
            self.text_extracted.delete("1.0", "end")

        except Exception as e:
            self._stego_path = None
            self._stego_thumb = None
            self.btn_cancel_stego.configure(state="disabled")
            self.label_stego_thumb.configure(image=None, text="⚠️")
            self.label_stego_title.configure(
                text=f"❌ Gagal Memuat: {p.name}",
                text_color=_COLOR_ERROR,
            )
            self.label_stego_meta.configure(text=str(e), text_color=_COLOR_ERROR)
            messagebox.showerror("Gambar Tidak Valid", str(e), parent=self.winfo_toplevel())

    def _cancel_stego_image(self) -> None:
        """Batalkan pemilihan gambar stego."""
        self._stego_path = None
        self._stego_thumb = None
        self.label_stego_thumb.configure(image=None, text="")
        self.label_stego_title.configure(
            text="Belum ada gambar stego yang di-upload",
            text_color=_COLOR_TEXT,
        )
        self.label_stego_meta.configure(
            text="Pilih berkas PNG yang sebelumnya telah disisipi catatan rahasia.",
            text_color="gray",
        )
        self.btn_cancel_stego.configure(state="disabled")
        self.label_extract_result.configure(text="")
        self.text_extracted.delete("1.0", "end")

    def _execute_extract(self) -> None:
        if not self._stego_path:
            messagebox.showwarning(
                "Peringatan", "Silakan pilih berkas gambar stego PNG terlebih dahulu.", parent=self.winfo_toplevel()
            )
            return

        try:
            revealed = lsb.reveal_note(self.session, self._stego_path)
            self.text_extracted.delete("1.0", "end")
            self.text_extracted.insert("1.0", revealed)
            self.label_extract_result.configure(
                text=f"✔ Catatan berhasil diekstrak dari: {self._stego_path.name}",
                text_color=_COLOR_SUCCESS,
            )
        except BrankasError as e:
            self.text_extracted.delete("1.0", "end")
            self.label_extract_result.configure(text=f"❌ {e}", text_color=_COLOR_ERROR)
            messagebox.showerror("Gagal Mengekstrak", str(e), parent=self.winfo_toplevel())

    def _copy_revealed_note(self) -> None:
        text = self.text_extracted.get("1.0", "end-1c")
        if not text:
            messagebox.showinfo("Informasi", "Belum ada catatan yang dapat disalin.", parent=self.winfo_toplevel())
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Berhasil", "Catatan rahasia berhasil disalin ke clipboard!", parent=self.winfo_toplevel())
