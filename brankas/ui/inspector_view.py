"""Tab Inspektur: peragaan tiap tahap super-enkripsi teks (Vigenere -> ChaCha20-Poly1305).
Pemilik: Anggota B.

Teks yang diketik di sini hanya diproses di memori untuk peragaan; tidak disimpan ke basis data.
Pemakaian:  InspectorView(tab, session, guard=dashboard._guard).pack(fill="both", expand=True)
"""
from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from brankas import inspector
from brankas.errors import DecryptionError
from brankas.ui.widgets import GREEN, MUTED, RED, set_text

_MONO = ("Consolas", 12)


def _hex(b: bytes, limit: int = 96) -> str:
    if not b:
        return "(kosong)"
    s = " ".join(f"{x:02x}" for x in b[:limit])
    return s + (f" … (+{len(b) - limit} B)" if len(b) > limit else "")


class InspectorView(ctk.CTkFrame):
    def __init__(self, master, session, guard, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.session = session
        self._guard = guard
        self._trace: inspector.TextTrace | None = None
        self._stage_text = ""

        ctk.CTkLabel(self, text="Sidik jari kunci sesi (8 byte SHA-256; kunci aslinya tidak ditampilkan)",
                     anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(fill="x", padx=12, pady=(8, 0))
        self.fp_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", font=ctk.CTkFont(*_MONO))
        self.fp_label.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(self, text="Teks untuk dienkripsi (hanya peragaan, tidak disimpan)", anchor="w").pack(
            fill="x", padx=12)
        self.text_in = ctk.CTkTextbox(self, height=56, wrap="word")
        self.text_in.pack(fill="x", padx=8, pady=(2, 4))

        acts = ctk.CTkFrame(self, fg_color="transparent")
        acts.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkButton(acts, text="Enkripsi & tampilkan tahapan", width=210, command=self._encrypt).pack(
            side="left", padx=(0, 6))
        ctk.CTkButton(acts, text="Dekripsi", width=110, command=self._decrypt_ok).pack(side="left", padx=6)
        ctk.CTkButton(acts, text="Rusak 1 bit lalu dekripsi", width=190, fg_color=RED, hover_color="#8e1f1f",
                      command=self._decrypt_flipped).pack(side="left", padx=6)
        self.result = ctk.CTkLabel(acts, text="", anchor="w", wraplength=400, justify="left")
        self.result.pack(side="left", padx=10)

        self.out = ctk.CTkTextbox(self, wrap="word", state="disabled", font=ctk.CTkFont(*_MONO))
        self.out.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._show_fingerprints()

    # ------------------------------------------------------------ tampilan
    def _show_fingerprints(self) -> None:
        with self._guard("Inspektur"):
            lines = [f"{name:<13}{fp}   ({n} B)" for name, fp, n in inspector.key_fingerprints(self.session)]
            self.fp_label.configure(text="\n".join(lines))

    def _show(self, extra: str = "") -> None:
        set_text(self.out, self._stage_text + (("\n\n" + extra) if extra else ""))

    def _verdict(self, ok: bool, text: str) -> None:
        self.result.configure(text=text, text_color=GREEN if ok else RED)

    # ------------------------------------------------------------ aksi
    def _encrypt(self) -> None:
        with self._guard("Inspektur"):
            t = inspector.trace_encrypt(self.session, self.text_in.get("1.0", "end").strip())
            self._trace = t
            self._stage_text = (
                f"TAHAP 1  Plaintext (UTF-8, {len(t.plaintext)} B)\n  {_hex(t.plaintext)}\n\n"
                f"TAHAP 2  Vigenère level byte, (b + k) mod 256, kunci 16 B ({len(t.vigenere_out)} B)\n"
                f"  {_hex(t.vigenere_out)}\n\n"
                f"TAHAP 3  ChaCha20-Poly1305\n"
                f"  nonce (12 B, acak tiap enkripsi) : {_hex(t.nonce)}\n"
                f"  ciphertext ({len(t.ciphertext)} B)               : {_hex(t.ciphertext)}\n"
                f"  tag Poly1305 (16 B)              : {_hex(t.tag)}\n\n"
                f"TAHAP 4  Blob tersimpan = nonce ‖ ciphertext ‖ tag "
                f"({len(t.blob)} B, tambahan {len(t.blob) - len(t.plaintext)} B)\n  {_hex(t.blob)}"
            )
            self._show()
            self._verdict(True, "Enkripsi selesai. Nonce baru tiap kali: enkripsi ulang teks yang sama "
                                "menghasilkan blob berbeda.")

    def _need_trace(self) -> inspector.TextTrace | None:
        if self._trace is None:
            messagebox.showinfo("Inspektur", "Enkripsi sebuah teks dulu.", parent=self.winfo_toplevel())
        return self._trace

    def _decrypt_ok(self) -> None:
        t = self._need_trace()
        if t is None:
            return
        with self._guard("Inspektur"):
            d = inspector.decrypt_trace(self.session, t.blob)
            self._show("BALIK  Buka ChaCha20-Poly1305 (tag valid) → Vigenère terbalik\n"
                       f"  setelah ChaCha20 : {_hex(d.vigenere_out)}\n"
                       f"  sama dengan tahap 2 : {d.vigenere_out == t.vigenere_out}\n"
                       f"  plaintext : {d.plaintext}")
            self._verdict(True, "✔ Dekripsi berhasil, teks kembali utuh.")

    def _decrypt_flipped(self) -> None:
        t = self._need_trace()
        if t is None:
            return
        with self._guard("Inspektur"):
            bad, pos, bit = inspector.flip_ciphertext_bit(t.blob)
            off = len(t.nonce) + pos
            note = (f"RUSAK  Bit ke-{bit} pada byte ke-{pos} ciphertext dibalik: "
                    f"{t.blob[off]:02x} → {bad[off]:02x}\n  {_hex(bad)}\n")
            try:
                inspector.decrypt_trace(self.session, bad)
            except DecryptionError:
                self._show(note + "  Hasil: DecryptionError. Tag Poly1305 tidak cocok, sehingga tidak ada "
                                  "plaintext yang dikeluarkan sama sekali.")
                self._verdict(False, "✘ Gagal: satu bit berubah, seluruh blob ditolak.")
                return
            self._show(note + "  Hasil: dekripsi lolos (tidak seharusnya terjadi).")
            self._verdict(False, "Peringatan: data rusak lolos verifikasi.")

    def wipe_sensitive(self) -> None:
        """Buang teks demo, hasil tahapan, dan sidik jari saat logout / dongle dicabut."""
        self._trace = None
        self._stage_text = ""
        self.text_in.delete("1.0", "end")
        set_text(self.out, "")
        self.result.configure(text="")
        self.fp_label.configure(text="")
