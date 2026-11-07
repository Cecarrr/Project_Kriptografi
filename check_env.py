"""Cek lingkungan Brankas. Jalankan di dalam venv:  python check_env.py"""
import sys

hasil = {"ok": 0, "gagal": 0, "peringatan": 0}


def cek(nama, fn, hint=None, wajib=True):
    try:
        info = fn()
        print(f"[OK]        {nama}" + (f" - {info}" if info else ""))
        hasil["ok"] += 1
    except Exception as e:
        label = "GAGAL" if wajib else "PERINGATAN"
        print(f"[{label}]".ljust(12) + f"{nama} - {type(e).__name__}: {e}")
        if hint:
            print(f"            saran: {hint}")
        hasil["gagal" if wajib else "peringatan"] += 1


def python_ver():
    return sys.version.split()[0]


def dlib_ver():
    import dlib
    return dlib.__version__


def face_models():
    import numpy as np
    import face_recognition
    gambar = np.zeros((100, 100, 3), dtype=np.uint8)
    # memaksa model landmark dan encoder dimuat
    face_recognition.face_encodings(gambar, known_face_locations=[(10, 90, 90, 10)])
    return "model wajah termuat"


def opencv_ver():
    import cv2
    return cv2.__version__


def webcam():
    import cv2
    cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cam.isOpened():
        raise RuntimeError("webcam tidak bisa dibuka (dipakai aplikasi lain atau izin kamera mati)")
    ok, frame = cam.read()
    cam.release()
    if not ok:
        raise RuntimeError("webcam terbuka tapi tidak ada frame")
    return f"frame {frame.shape[1]}x{frame.shape[0]}"


def pillow_ver():
    import PIL
    return PIL.__version__


def aes_chacha():
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
    data = b"uji enkripsi Brankas"
    for kelas in (AESGCM, ChaCha20Poly1305):
        kunci, nonce = kelas.generate_key(bit_length=256) if kelas is AESGCM else kelas.generate_key(), os.urandom(12)
        c = kelas(kunci)
        assert c.decrypt(nonce, c.encrypt(nonce, data, None), None) == data
    return "AES-256-GCM dan ChaCha20-Poly1305 bolak-balik OK"


def argon2_cek():
    from argon2 import PasswordHasher
    from argon2.low_level import hash_secret_raw, Type
    ph = PasswordHasher()
    h = ph.hash("password-uji")
    ph.verify(h, "password-uji")
    kunci = hash_secret_raw(b"password-uji", b"0123456789abcdef", time_cost=3,
                            memory_cost=65536, parallelism=2, hash_len=32, type=Type.ID)
    assert len(kunci) == 32
    return "Argon2id hash dan turunan kunci OK"


def ctk_ver():
    import tkinter as tk
    import customtkinter
    root = tk.Tk()
    root.destroy()
    return f"customtkinter {customtkinter.__version__}"


def sqlite_ver():
    import sqlite3
    return sqlite3.sqlite_version


def flashdisk():
    import psutil
    import win32api
    baris = []
    for p in psutil.disk_partitions(all=False):
        if not p.fstype:
            continue
        if "removable" in p.opts.lower():
            try:
                serial = win32api.GetVolumeInformation(p.mountpoint)[1] & 0xFFFFFFFF
                baris.append(f"{p.device} serial={serial:08X}")
            except Exception:
                pass
    return ", ".join(baris) if baris else "tidak ada flashdisk terdeteksi (colokkan untuk menguji)"


if __name__ == "__main__":
    print("== Cek lingkungan Brankas ==")
    cek("Python", python_ver)
    cek("dlib", dlib_ver, "pasang ulang wheel dlib di dalam venv ini")
    cek("face_recognition + model", face_models,
        'pip install "setuptools<81" (pkg_resources hilang di setuptools 81+)')
    cek("OpenCV", opencv_ver)
    cek("Webcam", webcam, "tutup aplikasi kamera lain, cek izin kamera Windows", wajib=False)
    cek("Pillow", pillow_ver)
    cek("Kripto (AES, ChaCha20)", aes_chacha)
    cek("Argon2id", argon2_cek)
    cek("CustomTkinter", ctk_ver)
    cek("SQLite", sqlite_ver)
    cek("Flashdisk dan serial", flashdisk, wajib=False)
    print(f"\nRingkasan: {hasil['ok']} OK, {hasil['gagal']} gagal, {hasil['peringatan']} peringatan")
    sys.exit(1 if hasil["gagal"] else 0)
