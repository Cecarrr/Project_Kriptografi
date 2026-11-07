"""Alur 3 langkah (dongle, wajah, password) dan registrasi dengan live camera preview. Pemilik: Anggota A."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import cv2
import customtkinter as ctk
import numpy as np
from PIL import Image

from brankas import config
from brankas.auth import dongle, face, login
from brankas.auth.login import LoginFlow, Session
from brankas.errors import BrankasError, NoFaceDetected

_COLOR_SUCCESS = "#2e7d32"
_COLOR_ERROR = "#c62828"
_COLOR_WARNING = "#f57c00"
_COLOR_MUTED = ("gray40", "gray70")


def _face_upload_allowed() -> bool:
    """Unggah foto wajah hanya untuk pengembangan (config.ALLOW_FACE_UPLOAD = True).
    Default mati: login harus memakai kamera langsung, bukan foto."""
    return bool(getattr(config, "ALLOW_FACE_UPLOAD", False))


def _read_image_to_rgb(path: Path) -> np.ndarray:
    im = cv2.imread(str(path))
    if im is None:
        raise BrankasError(f"Gagal membaca berkas gambar: {path.name}")
    return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)


# =========================================================================
# MODAL PREVIEW KAMERA (LIVE VIDEO + VERIFIKASI LANGSUNG)
# =========================================================================
class CameraPreviewDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        title: str,
        mode: str = "login",
        flow: LoginFlow | None = None,
        on_login_success_callback: Callable[[np.ndarray], None] | None = None,
        on_register_complete_callback: Callable[[list[np.ndarray]], None] | None = None,
        on_cancel_callback: Callable[[], None] | None = None,
        target_samples: int = 3,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.title(title)
        self.geometry("520x660")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self.mode = mode
        self.flow = flow
        self.on_login_success_callback = on_login_success_callback
        self.on_register_complete_callback = on_register_complete_callback
        self.on_cancel_callback = on_cancel_callback
        self.target_samples = target_samples

        self._samples: list[np.ndarray] = []
        self._current_frame: np.ndarray | None = None
        self._poll_id: str | None = None
        self._is_closing = False
        self._face_attempts = 0
        self._cancelled = False  # True jika user klik Batal

        # Buka kamera
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(0)

        if not self.cap.isOpened():
            messagebox.showerror(
                "Kamera Tidak Tersedia",
                "Kamera webcam tidak dapat dibuka (sedang dipakai aplikasi lain atau izin dinonaktifkan).\n\n"
                "Tutup aplikasi lain yang memakai kamera, lalu coba lagi.",
                parent=parent.winfo_toplevel(),
            )
            self.after(50, self.destroy)
            return

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._build_ui()
        self._start_stream()

    def _build_ui(self) -> None:
        # Header info
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(12, 6))

        title_text = "📸 Kamera Verifikasi Wajah" if self.mode == "login" else "📸 Pendaftaran Wajah Pengguna"
        ctk.CTkLabel(
            header_frame,
            text=title_text,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left")

        # Kartu Area Video
        video_card = ctk.CTkFrame(self, corner_radius=10)
        video_card.pack(fill="both", expand=True, padx=16, pady=6)

        self.label_preview = ctk.CTkLabel(
            video_card,
            text="Menghubungkan ke kamera webcam...",
            font=ctk.CTkFont(size=12),
            text_color=_COLOR_MUTED,
        )
        self.label_preview.pack(fill="both", expand=True, padx=8, pady=8)

        # Kartu Status Keterangan Berhasil / Gagal
        self.card_status = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray85", "#242424"))
        self.card_status.pack(fill="x", padx=16, pady=6)

        initial_status = (
            "Posisikan wajah Anda tegak lurus menghadap kamera, lalu klik 'Ambil Foto & Verifikasi'."
            if self.mode == "login"
            else f"Kumpulkan {self.target_samples} sampel foto wajah. Sampel: 0/{self.target_samples}"
        )

        self.label_status = ctk.CTkLabel(
            self.card_status,
            text=initial_status,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=_COLOR_MUTED,
            wraplength=460,
        )
        self.label_status.pack(padx=12, pady=10)

        # Action Bar (Tombol Aksi)
        action_bar = ctk.CTkFrame(self, fg_color="transparent")
        action_bar.pack(fill="x", padx=16, pady=(6, 8))

        btn_text = "📸 Ambil Foto & Verifikasi" if self.mode == "login" else "📸 Ambil Sampel Wajah"
        self.btn_capture = ctk.CTkButton(
            action_bar,
            text=btn_text,
            font=ctk.CTkFont(weight="bold", size=13),
            height=38,
            command=self._on_capture_click,
        )
        self.btn_capture.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Tombol Batal — menutup kamera tanpa mengirim hasil
        ctk.CTkButton(
            action_bar,
            text="✖ Batal",
            width=90,
            height=38,
            fg_color=_COLOR_ERROR,
            hover_color="#8e1f1f",
            command=self._on_cancel,
        ).pack(side="right")

        # Tombol Tutup (tanpa batal — hanya menutup window)
        ctk.CTkButton(
            action_bar,
            text="Tutup",
            width=90,
            height=38,
            fg_color="gray30",
            hover_color="gray20",
            command=self._on_close,
        ).pack(side="right", padx=(0, 8))

    def _start_stream(self) -> None:
        if self._is_closing or not self.cap or not self.cap.isOpened():
            return

        ret, frame_bgr = self.cap.read()
        if ret and frame_bgr is not None:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            self._current_frame = frame_rgb

            # Resize proporsional untuk preview (440x330)
            h, w, _ = frame_rgb.shape
            target_w = 440
            target_h = int(target_w * (h / w))
            pil_img = Image.fromarray(frame_rgb).resize((target_w, target_h), Image.Resampling.BILINEAR)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(target_w, target_h))
            self.label_preview.configure(image=ctk_img, text="")

        self._poll_id = self.after(33, self._start_stream)

    def _on_capture_click(self) -> None:
        if self._current_frame is None:
            return

        frame = self._current_frame.copy()

        if self.mode == "login":
            self._handle_login_capture(frame)
        else:
            self._handle_register_capture(frame)

    def _handle_login_capture(self, frame: np.ndarray) -> None:
        if not self.flow:
            return

        try:
            matched = self.flow.step_face(frame)
            if matched:
                self.label_status.configure(
                    text="✔ Wajah Cocok & Berhasil Terverifikasi! (Menutup kamera...)",
                    text_color=_COLOR_SUCCESS,
                )
                self.btn_capture.configure(state="disabled")
                if self.on_login_success_callback:
                    self.on_login_success_callback(frame)
                self.after(1200, self._on_close)
            else:
                self._face_attempts += 1
                sisa = config.FACE_MAX_ATTEMPTS - self._face_attempts
                if sisa <= 0:
                    self.label_status.configure(
                        text="❌ Batas percobaan verifikasi wajah telah habis!",
                        text_color=_COLOR_ERROR,
                    )
                    self.btn_capture.configure(state="disabled")
                    messagebox.showerror(
                        "Gagal", "Batas percobaan wajah habis. Silakan coba lagi nanti.", parent=self
                    )
                    self._on_close()
                else:
                    self.label_status.configure(
                        text=f"❌ Wajah Tidak Cocok! Sisa percobaan: {sisa}. Silakan arahkan wajah kembali.",
                        text_color=_COLOR_ERROR,
                    )
        except NoFaceDetected:
            self.label_status.configure(
                text="⚠️ Tidak ada wajah yang terdeteksi di kamera! Pastikan wajah Anda terlihat jelas.",
                text_color=_COLOR_WARNING,
            )
        except Exception as e:
            self.label_status.configure(
                text=f"❌ Terjadi kesalahan: {e}",
                text_color=_COLOR_ERROR,
            )

    def _handle_register_capture(self, frame: np.ndarray) -> None:
        try:
            face.encode_face(frame)
            self._samples.append(frame)
            n = len(self._samples)
            target = self.target_samples

            if n >= target:
                self.label_status.configure(
                    text=f"✔ Berhasil! {n}/{target} sampel wajah lengkap terkumpul. (Menutup kamera...)",
                    text_color=_COLOR_SUCCESS,
                )
                self.btn_capture.configure(state="disabled")
                if self.on_register_complete_callback:
                    self.on_register_complete_callback(self._samples)
                self.after(1200, self._on_close)
            else:
                self.label_status.configure(
                    text=f"✔ Sampel ke-{n} berhasil dicatat! Arahkan wajah sedikit berbeda lalu ambil sampel ke-{n+1}/{target}.",
                    text_color=_COLOR_SUCCESS,
                )
        except NoFaceDetected:
            self.label_status.configure(
                text="⚠️ Tidak ada wajah yang terdeteksi di kamera! Harap hadap kamera dengan pencahayaan cukup.",
                text_color=_COLOR_WARNING,
            )
        except Exception as e:
            self.label_status.configure(
                text=f"❌ Terjadi kesalahan: {e}",
                text_color=_COLOR_ERROR,
            )

    def _on_cancel(self) -> None:
        """Tutup kamera DAN beri tahu pemanggil bahwa user membatalkan."""
        self._cancelled = True
        if self.on_cancel_callback:
            self.on_cancel_callback()
        self._on_close()

    def _on_close(self) -> None:
        """Tutup kamera (tanpa memberi sinyal batal ke pemanggil)."""
        self._is_closing = True
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None

        try:
            self.destroy()
        except Exception:
            pass


# =========================================================================
# TAMPILAN LOGIN VIEW UTAMA
# =========================================================================
class LoginView(ctk.CTkFrame):
    def __init__(self, master, on_login_success: Callable[[Session], None], **kwargs):
        super().__init__(master, **kwargs)
        self.on_login_success = on_login_success

        # State alur login
        self.flow = LoginFlow()
        self._face_attempts = 0
        self._face_verified = False
        self._captured_face_frame: np.ndarray | None = None
        self._captured_face_thumb: ctk.CTkImage | None = None

        # State registrasi
        self._reg_face_frames: list[np.ndarray] = []

        self._build_ui()

    def _build_ui(self) -> None:
        # Header Aplikasi
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 8))

        ctk.CTkLabel(
            header,
            text="🔒 Brankas Kriptografi",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text="Autentikasi 3-Faktor: USB Dongle • Biometrik Wajah • Master Password",
            font=ctk.CTkFont(size=12),
            text_color=_COLOR_MUTED,
        ).pack(side="left", padx=16, pady=(6, 0))

        # Tabview Utama (Login / Registrasi)
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        tab_login = self.tabview.add("  Masuk ke Brankas  ")
        tab_register = self.tabview.add("  Daftar Akun Baru  ")

        self._build_login_tab(tab_login)
        self._build_register_tab(tab_register)

    # =========================================================================
    # TAB LOGIN (3-LANGKAH)
    # =========================================================================
    def _build_login_tab(self, tab) -> None:
        container = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # ---------------- Langkah 1: Dongle USB ----------------
        self.card_dongle = ctk.CTkFrame(container, corner_radius=10)
        self.card_dongle.pack(fill="x", padx=4, pady=6)

        d_header = ctk.CTkFrame(self.card_dongle, fg_color="transparent")
        d_header.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            d_header,
            text="Langkah 1: Periksa Dongle USB",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")

        self.btn_check_dongle = ctk.CTkButton(
            d_header,
            text="🔌 Periksa Dongle",
            width=150,
            command=self._do_step_dongle,
        )
        self.btn_check_dongle.pack(side="right")

        self.btn_browse_dongle = ctk.CTkButton(
            d_header,
            text="📁 Pilih Folder...",
            width=120,
            fg_color="gray30",
            command=self._do_browse_dongle,
        )
        self.btn_browse_dongle.pack(side="right", padx=6)

        self.label_dongle_status = ctk.CTkLabel(
            self.card_dongle,
            text="Silakan colokkan flashdisk dongle Anda, lalu klik 'Periksa Dongle'.",
            font=ctk.CTkFont(size=12),
            text_color=_COLOR_MUTED,
            anchor="w",
        )
        self.label_dongle_status.pack(fill="x", padx=14, pady=(0, 12))

        # ---------------- Langkah 2: Biometrik Wajah ----------------
        self.card_face = ctk.CTkFrame(container, corner_radius=10)
        self.card_face.pack(fill="x", padx=4, pady=6)

        f_header = ctk.CTkFrame(self.card_face, fg_color="transparent")
        f_header.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            f_header,
            text="Langkah 2: Verifikasi Wajah",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")

        self.btn_capture_face = ctk.CTkButton(
            f_header,
            text="📸 Buka Kamera Preview",
            width=180,
            state="disabled",
            command=self._open_camera_login,
        )
        self.btn_capture_face.pack(side="right")

        self.btn_upload_face = ctk.CTkButton(
            f_header,
            text="📁 Unggah Foto...",
            width=130,
            fg_color="gray30",
            state="disabled",
            command=self._do_upload_face,
        )
        if _face_upload_allowed():
            self.btn_upload_face.pack(side="right", padx=8)

        # Konten status wajah
        f_body = ctk.CTkFrame(self.card_face, fg_color="transparent")
        f_body.pack(fill="x", padx=14, pady=(0, 6))

        self.label_face_thumb = ctk.CTkLabel(f_body, text="")
        self.label_face_thumb.pack(side="left", padx=(0, 12))

        self.label_face_status = ctk.CTkLabel(
            f_body,
            text="Terkunci: Harap selesaikan Langkah 1 (Dongle) terlebih dahulu.",
            font=ctk.CTkFont(size=12),
            text_color=_COLOR_MUTED,
            anchor="w",
        )
        self.label_face_status.pack(side="left", fill="x", expand=True)

        # Baris tombol Batal Foto (hanya muncul setelah foto berhasil diambil)
        f_cancel_bar = ctk.CTkFrame(self.card_face, fg_color="transparent")
        f_cancel_bar.pack(fill="x", padx=14, pady=(0, 10))

        self.btn_cancel_face_login = ctk.CTkButton(
            f_cancel_bar,
            text="✖ Batal / Ulangi Foto Wajah",
            width=200,
            height=28,
            fg_color=_COLOR_ERROR,
            hover_color="#8e1f1f",
            font=ctk.CTkFont(size=11),
            state="disabled",
            command=self._cancel_face_login,
        )
        self.btn_cancel_face_login.pack(side="left")

        # ---------------- Langkah 3: Password Master ----------------
        self.card_pw = ctk.CTkFrame(container, corner_radius=10)
        self.card_pw.pack(fill="x", padx=4, pady=6)

        p_header = ctk.CTkFrame(self.card_pw, fg_color="transparent")
        p_header.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            p_header,
            text="Langkah 3: Masukkan Master Password",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")

        # Form password
        p_form = ctk.CTkFrame(self.card_pw, fg_color="transparent")
        p_form.pack(fill="x", padx=14, pady=(4, 12))

        self.entry_login_pw = ctk.CTkEntry(
            p_form,
            placeholder_text="Ketik master password akun Anda...",
            show="*",
            width=320,
            state="disabled",
        )
        self.entry_login_pw.pack(side="left", padx=(0, 10))
        self.entry_login_pw.bind("<Return>", lambda event: self._do_step_password())

        self.btn_submit_login = ctk.CTkButton(
            p_form,
            text="🔓 Buka Brankas",
            font=ctk.CTkFont(weight="bold"),
            width=160,
            state="disabled",
            command=self._do_step_password,
        )
        self.btn_submit_login.pack(side="left")

        self.label_pw_status = ctk.CTkLabel(
            self.card_pw,
            text="Terkunci: Harap selesaikan Langkah 2 (Verifikasi Wajah) terlebih dahulu.",
            font=ctk.CTkFont(size=12),
            text_color=_COLOR_MUTED,
            anchor="w",
        )
        self.label_pw_status.pack(fill="x", padx=14, pady=(0, 12))

    def _do_step_dongle(self) -> None:
        self._check_dongle_path(None)

    def _do_browse_dongle(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Lokasi Berkas dongle.key", parent=self.winfo_toplevel())
        if folder:
            self._check_dongle_path(folder)

    def _check_dongle_path(self, custom_path: str | None = None) -> None:
        try:
            d_info = self.flow.step_dongle(custom_path=custom_path)
            user = self.flow.recognized_username
            self.label_dongle_status.configure(
                text=f"✔ Dongle Terdeteksi di {d_info.drive} (Serial: {d_info.serial}) — Pengguna: {user}",
                text_color=_COLOR_SUCCESS,
            )
            # Aktifkan langkah 2
            self.btn_capture_face.configure(state="normal")
            self.btn_upload_face.configure(state="normal")
            self.label_face_status.configure(
                text="Silakan klik 'Buka Kamera Preview' untuk verifikasi wajah langsung.",
                text_color=_COLOR_MUTED,
            )
        except BrankasError as e:
            self.label_dongle_status.configure(text=f"❌ {e}", text_color=_COLOR_ERROR)
            messagebox.showerror("Dongle Tidak Ditemukan", str(e), parent=self.winfo_toplevel())

    def _open_camera_login(self) -> None:
        def on_success(frame: np.ndarray):
            self._apply_face_success(frame)

        def on_cancel():
            # User klik Batal di kamera — pastikan tombol upload & kamera kembali aktif
            self.label_face_status.configure(
                text="⚠️ Pengambilan foto dibatalkan. Silakan coba lagi.",
                text_color=_COLOR_WARNING,
            )

        CameraPreviewDialog(
            parent=self,
            title="Verifikasi Wajah Login",
            mode="login",
            flow=self.flow,
            on_login_success_callback=on_success,
            on_cancel_callback=on_cancel,
        )

    def _apply_face_success(self, frame: np.ndarray) -> None:
        self._face_verified = True
        self._captured_face_frame = frame

        pil_img = Image.fromarray(frame)
        pil_img.thumbnail((75, 75), Image.Resampling.LANCZOS)
        thumb = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
        self.label_face_thumb.configure(image=thumb, text="")

        self.label_face_status.configure(
            text="✔ Wajah Berhasil Terverifikasi!",
            text_color=_COLOR_SUCCESS,
        )
        # Kunci tombol kamera/upload & aktifkan tombol batal foto & langkah 3
        self.btn_capture_face.configure(state="disabled")
        self.btn_upload_face.configure(state="disabled")
        self.btn_cancel_face_login.configure(state="normal")
        self.entry_login_pw.configure(state="normal")
        self.btn_submit_login.configure(state="normal")
        self.entry_login_pw.focus_set()
        self.label_pw_status.configure(
            text="Silakan ketik master password akun Anda dan tekan Buka Brankas.",
            text_color=_COLOR_MUTED,
        )

    def _cancel_face_login(self) -> None:
        """Reset verifikasi wajah agar user bisa mengulang foto."""
        if not messagebox.askyesno(
            "Ulangi Foto Wajah",
            "Batalkan verifikasi wajah saat ini dan ulangi dari Langkah 2?",
            parent=self.winfo_toplevel(),
        ):
            return

        self._face_verified = False
        self._captured_face_frame = None
        self.flow._face_verified = False  # reset status di LoginFlow juga

        self.label_face_thumb.configure(image=None, text="")
        self.label_face_status.configure(
            text="Silakan klik 'Buka Kamera Preview' untuk verifikasi wajah ulang.",
            text_color=_COLOR_MUTED,
        )
        self.btn_capture_face.configure(state="normal")
        self.btn_upload_face.configure(state="normal")
        self.btn_cancel_face_login.configure(state="disabled")

        # Kunci kembali langkah 3
        self.entry_login_pw.delete(0, "end")
        self.entry_login_pw.configure(state="disabled")
        self.btn_submit_login.configure(state="disabled")
        self.label_pw_status.configure(
            text="Terkunci: Harap selesaikan Langkah 2 (Verifikasi Wajah) terlebih dahulu.",
            text_color=_COLOR_MUTED,
        )

    def _do_upload_face(self) -> None:
        if not _face_upload_allowed():
            return
        file_path = filedialog.askopenfilename(
            title="Pilih Berkas Foto Wajah",
            filetypes=[("Berkas Gambar", "*.jpg;*.jpeg;*.png")],
            parent=self.winfo_toplevel(),
        )
        if not file_path:
            # User tekan Cancel di dialog — tidak ada aksi
            return

        try:
            frame = _read_image_to_rgb(Path(file_path))
            matched = self.flow.step_face(frame)
            if matched:
                self._apply_face_success(frame)
            else:
                self._face_attempts += 1
                sisa = config.FACE_MAX_ATTEMPTS - self._face_attempts
                if sisa <= 0:
                    messagebox.showerror("Batas Habis", "Percobaan wajah habis. Alur login di-reset.", parent=self.winfo_toplevel())
                    self._reset_login_flow()
                else:
                    self.label_face_status.configure(
                        text=f"❌ Wajah tidak cocok! Sisa percobaan: {sisa}",
                        text_color=_COLOR_ERROR,
                    )
        except NoFaceDetected:
            messagebox.showwarning("Wajah Tidak Terdeteksi", "Tidak ada wajah pada foto yang diunggah.", parent=self.winfo_toplevel())
        except Exception as e:
            messagebox.showerror("Gagal Verifikasi", str(e), parent=self.winfo_toplevel())

    def _do_step_password(self) -> None:
        pw = self.entry_login_pw.get()
        if not pw:
            messagebox.showwarning("Peringatan", "Password tidak boleh kosong.", parent=self.winfo_toplevel())
            return

        try:
            session = self.flow.step_password(pw)
            self.label_pw_status.configure(text="✔ Password Cocok! Masuk ke Brankas...", text_color=_COLOR_SUCCESS)
            self.on_login_success(session)
        except BrankasError as e:
            self.label_pw_status.configure(text=f"❌ {e}", text_color=_COLOR_ERROR)
            messagebox.showerror("Login Gagal", str(e), parent=self.winfo_toplevel())

    def _reset_login_flow(self) -> None:
        self.flow = LoginFlow()
        self._face_attempts = 0
        self._face_verified = False
        self.btn_capture_face.configure(state="disabled")
        self.btn_upload_face.configure(state="disabled")
        self.btn_cancel_face_login.configure(state="disabled")
        self.entry_login_pw.delete(0, "end")
        self.entry_login_pw.configure(state="disabled")
        self.btn_submit_login.configure(state="disabled")
        self.label_dongle_status.configure(
            text="Silakan colokkan flashdisk dongle Anda, lalu klik 'Periksa Dongle'.",
            text_color=_COLOR_MUTED,
        )
        self.label_face_status.configure(
            text="Terkunci: Harap selesaikan Langkah 1 (Dongle) terlebih dahulu.",
            text_color=_COLOR_MUTED,
        )
        self.label_face_thumb.configure(image=None, text="")
        self.label_pw_status.configure(
            text="Terkunci: Harap selesaikan Langkah 2 (Verifikasi Wajah) terlebih dahulu.",
            text_color=_COLOR_MUTED,
        )

    # =========================================================================
    # TAB REGISTRASI PENGGUNA BARU
    # =========================================================================
    def _build_register_tab(self, tab) -> None:
        container = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        card = ctk.CTkFrame(container, corner_radius=10)
        card.pack(fill="both", expand=True, padx=4, pady=4)

        # 1. Kredensial
        ctk.CTkLabel(
            card,
            text="1. Informasi Akun",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))

        self.entry_reg_user = ctk.CTkEntry(card, placeholder_text="Username baru...", width=320)
        self.entry_reg_user.pack(anchor="w", padx=16, pady=4)

        self.entry_reg_pw1 = ctk.CTkEntry(card, placeholder_text="Master Password...", show="*", width=320)
        self.entry_reg_pw1.pack(anchor="w", padx=16, pady=4)

        self.entry_reg_pw2 = ctk.CTkEntry(card, placeholder_text="Ulangi Password...", show="*", width=320)
        self.entry_reg_pw2.pack(anchor="w", padx=16, pady=4)

        # 2. Pemilihan Drive Flashdisk
        ctk.CTkLabel(
            card,
            text="2. Lokasi Flashdisk Dongle",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))

        drive_bar = ctk.CTkFrame(card, fg_color="transparent")
        drive_bar.pack(fill="x", padx=16, pady=4)

        self.opt_drives = ctk.CTkOptionMenu(drive_bar, values=["(Pindai drive...)"], width=200)
        self.opt_drives.pack(side="left")

        ctk.CTkButton(
            drive_bar,
            text="🔄 Segarkan Drive",
            width=130,
            command=self._refresh_drives,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            drive_bar,
            text="📁 Pilih Folder Drive...",
            width=150,
            fg_color="gray30",
            command=self._browse_custom_drive,
        ).pack(side="left")

        self.label_drive_selected = ctk.CTkLabel(
            card,
            text="Pilih drive flashdisk yang akan dijadikan USB security dongle.",
            font=ctk.CTkFont(size=11),
            text_color=_COLOR_MUTED,
            anchor="w",
        )
        self.label_drive_selected.pack(fill="x", padx=16, pady=(2, 8))

        # 3. Pendaftaran Biometrik Wajah
        ctk.CTkLabel(
            card,
            text=f"3. Pendaftaran Wajah ({config.FACE_ENROLL_SAMPLES} Sampel)",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(10, 4))

        face_bar = ctk.CTkFrame(card, fg_color="transparent")
        face_bar.pack(fill="x", padx=16, pady=4)

        self.btn_reg_camera = ctk.CTkButton(
            face_bar,
            text="📸 Buka Kamera Preview",
            width=190,
            command=self._open_camera_register,
        )
        self.btn_reg_camera.pack(side="left")

        self.btn_reg_upload = ctk.CTkButton(
            face_bar,
            text="📁 Unggah Foto...",
            width=150,
            fg_color="gray30",
            command=self._reg_upload_sample,
        )
        if _face_upload_allowed():
            self.btn_reg_upload.pack(side="left", padx=8)

        # Tombol batal/reset foto registrasi
        self.btn_reg_cancel = ctk.CTkButton(
            face_bar,
            text="✖ Batal / Reset Foto",
            width=130,
            fg_color=_COLOR_ERROR,
            hover_color="#8e1f1f",
            command=self._reg_reset_samples,
        )
        self.btn_reg_cancel.pack(side="left")

        self.label_reg_samples = ctk.CTkLabel(
            card,
            text=f"Sampel terkumpul: 0 dari {config.FACE_ENROLL_SAMPLES}",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.label_reg_samples.pack(fill="x", padx=16, pady=(4, 14))

        # 4. Tombol Submit Registrasi
        ctk.CTkButton(
            card,
            text="✨ Daftarkan Akun & Buat Dongle",
            font=ctk.CTkFont(weight="bold", size=14),
            height=40,
            width=320,
            command=self._do_register,
        ).pack(anchor="w", padx=16, pady=(8, 16))

        self._refresh_drives()

    def _open_camera_register(self) -> None:
        def on_complete(samples: list[np.ndarray]):
            self._reg_face_frames = samples
            self._update_reg_samples_label()

        def on_cancel():
            # User membatalkan — jika sudah ada sampel sebelumnya, pertahankan
            n = len(self._reg_face_frames)
            if n > 0:
                self.label_reg_samples.configure(
                    text=f"⚠️ Dibatalkan. Sampel sebelumnya masih tersimpan: {n} dari {config.FACE_ENROLL_SAMPLES}",
                    text_color=_COLOR_WARNING,
                )
            else:
                self.label_reg_samples.configure(
                    text=f"⚠️ Pengambilan foto dibatalkan. Sampel terkumpul: 0 dari {config.FACE_ENROLL_SAMPLES}",
                    text_color=_COLOR_WARNING,
                )

        CameraPreviewDialog(
            parent=self,
            title="Pendaftaran Sampel Wajah",
            mode="register",
            target_samples=config.FACE_ENROLL_SAMPLES,
            on_register_complete_callback=on_complete,
            on_cancel_callback=on_cancel,
        )

    def _update_reg_samples_label(self) -> None:
        n = len(self._reg_face_frames)
        target = config.FACE_ENROLL_SAMPLES
        color = _COLOR_SUCCESS if n >= target else _COLOR_MUTED
        text = f"✔ Sampel terkumpul: {n} dari {target} (Lengkap!)" if n >= target else f"Sampel terkumpul: {n} dari {target}"
        self.label_reg_samples.configure(text=text, text_color=color)

    def _refresh_drives(self) -> None:
        removables = dongle.list_removable_drives()
        if removables:
            self.opt_drives.configure(values=removables)
            self.opt_drives.set(removables[0])
            self.label_drive_selected.configure(
                text=f"Drive terpilih: {removables[0]}",
                text_color=_COLOR_SUCCESS,
            )
        else:
            self.opt_drives.configure(values=["Tidak ada flashdisk terdeteksi"])
            self.opt_drives.set("Tidak ada flashdisk terdeteksi")
            self.label_drive_selected.configure(
                text="Tidak ada USB removable aktif. Colokkan flashdisk atau klik 'Pilih Folder Drive...'.",
                text_color=_COLOR_MUTED,
            )

    def _browse_custom_drive(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Drive / Folder Dongle", parent=self.winfo_toplevel())
        if folder:
            cur_vals = list(self.opt_drives.cget("values"))
            if folder not in cur_vals:
                cur_vals.insert(0, folder)
            self.opt_drives.configure(values=cur_vals)
            self.opt_drives.set(folder)
            self.label_drive_selected.configure(text=f"Drive terpilih: {folder}", text_color=_COLOR_SUCCESS)

    def _reg_upload_sample(self) -> None:
        if not _face_upload_allowed():
            return
        file_path = filedialog.askopenfilename(
            title="Pilih Foto Wajah Pengguna",
            filetypes=[("Berkas Gambar", "*.jpg;*.jpeg;*.png")],
            parent=self.winfo_toplevel(),
        )
        if not file_path:
            # User tekan Cancel di dialog — tidak ada aksi
            return
        try:
            frame = _read_image_to_rgb(Path(file_path))
            face.encode_face(frame)
            self._reg_face_frames.append(frame)
            self._update_reg_samples_label()
            messagebox.showinfo("Berhasil", f"Sampel wajah ke-{len(self._reg_face_frames)} berhasil ditambahkan!", parent=self.winfo_toplevel())
        except NoFaceDetected:
            messagebox.showwarning("Wajah Tidak Terdeteksi", "Tidak ada wajah pada foto yang dipilih.", parent=self.winfo_toplevel())
        except Exception as e:
            messagebox.showerror("Gagal Membaca File", str(e), parent=self.winfo_toplevel())

    def _reg_reset_samples(self) -> None:
        if not self._reg_face_frames:
            messagebox.showinfo("Informasi", "Belum ada sampel foto yang diambil.", parent=self.winfo_toplevel())
            return
        if messagebox.askyesno(
            "Reset Sampel Wajah",
            f"Batalkan dan hapus {len(self._reg_face_frames)} sampel wajah yang sudah dikumpulkan?",
            parent=self.winfo_toplevel(),
        ):
            self._reg_face_frames.clear()
            self._update_reg_samples_label()

    def _do_register(self) -> None:
        username = self.entry_reg_user.get().strip()
        pw1 = self.entry_reg_pw1.get()
        pw2 = self.entry_reg_pw2.get()
        drive = self.opt_drives.get()

        if not username:
            messagebox.showwarning("Peringatan", "Username tidak boleh kosong.", parent=self.winfo_toplevel())
            return
        if not pw1:
            messagebox.showwarning("Peringatan", "Password tidak boleh kosong.", parent=self.winfo_toplevel())
            return
        if pw1 != pw2:
            messagebox.showwarning("Peringatan", "Konfirmasi password tidak cocok.", parent=self.winfo_toplevel())
            return
        if not drive or drive.startswith("Tidak ada"):
            messagebox.showwarning("Peringatan", "Silakan pilih drive flashdisk dongle terlebih dahulu.", parent=self.winfo_toplevel())
            return
        if len(self._reg_face_frames) < config.FACE_ENROLL_SAMPLES:
            messagebox.showwarning(
                "Peringatan",
                f"Dibutuhkan minimal {config.FACE_ENROLL_SAMPLES} sampel wajah (saat ini baru {len(self._reg_face_frames)}).",
                parent=self.winfo_toplevel(),
            )
            return

        try:
            session = login.register(
                username=username,
                password=pw1,
                drive=drive,
                face_frames=self._reg_face_frames,
            )
            messagebox.showinfo(
                "Registrasi Berhasil",
                f"Akun '{username}' berhasil didaftarkan!\nKunci dongle telah ditulis ke drive {drive}.\n\nAnda akan otomatis masuk ke Brankas.",
                parent=self.winfo_toplevel(),
            )
            self.on_login_success(session)
        except BrankasError as e:
            messagebox.showerror("Registrasi Gagal", str(e), parent=self.winfo_toplevel())
