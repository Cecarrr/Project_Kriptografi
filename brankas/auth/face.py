"""Face recognition. Pemilik: Anggota A.

Frame = numpy array RGB (H, W, 3). Konversi dari BGR OpenCV dilakukan di sini.
Encoding = 128 float64 -> diserialisasi ke bytes (enc.tobytes()) sebelum dienkripsi.

Pemilihan wajah: bila ada beberapa wajah di frame, dipakai yang TERBESAR (bukan yang pertama terdeteksi).
Wajah terlalu kecil ditolak, dan bila ada wajah kedua dengan ukuran mirip, frame ditolak sebagai ambigu.
"""
from __future__ import annotations

import cv2
import face_recognition
import numpy as np

from brankas import config
from brankas.errors import AmbiguousFace, BrankasError, InvalidInput, NoFaceDetected


def capture_frame() -> np.ndarray:
    """Ambil satu frame dari webcam. Melempar BrankasError bila gagal."""
    cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cam.isOpened():
        cam = cv2.VideoCapture(0)
    if not cam.isOpened():
        raise BrankasError("Webcam tidak dapat dibuka (kamera tidak terhubung atau sedang dipakai)")
    try:
        ok, frame = cam.read()
    finally:
        cam.release()

    if not ok or frame is None:
        raise BrankasError("Gagal mengambil frame dari webcam")

    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def _area(loc: tuple[int, int, int, int]) -> int:
    top, right, bottom, left = loc          # format face_recognition
    return max(0, bottom - top) * max(0, right - left)


def pick_face(locations: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    """Pilih wajah utama dari daftar kotak (top, right, bottom, left).
    NoFaceDetected bila kosong / terlalu kecil; AmbiguousFace bila ada wajah kedua berukuran mirip."""
    if not locations:
        raise NoFaceDetected("Tidak ada wajah yang terdeteksi pada gambar")
    ranked = sorted(locations, key=_area, reverse=True)
    main = ranked[0]
    height = main[2] - main[0]
    if height < config.FACE_MIN_SIZE_PX:
        raise NoFaceDetected(
            f"Wajah terlalu kecil di frame ({height} px, minimal {config.FACE_MIN_SIZE_PX} px). Dekatkan wajah ke kamera."
        )
    if len(ranked) > 1 and _area(ranked[1]) >= config.FACE_AMBIGUITY_RATIO * _area(main):
        raise AmbiguousFace("Terdeteksi lebih dari satu wajah dengan ukuran mirip. Pastikan hanya satu orang di depan kamera.")
    return main


def encode_face(frame: np.ndarray, num_jitters: int | None = None) -> np.ndarray:
    """Encoding wajah utama. NoFaceDetected / AmbiguousFace bila tidak ada wajah yang layak dipakai."""
    if num_jitters is None:
        num_jitters = config.FACE_JITTERS_LOGIN
    loc = pick_face(face_recognition.face_locations(frame))
    encodings = face_recognition.face_encodings(
        frame, known_face_locations=[loc], num_jitters=num_jitters, model=config.FACE_LANDMARK_MODEL
    )
    if not encodings:
        raise NoFaceDetected("Tidak ada wajah yang terdeteksi pada gambar")
    return encodings[0].astype(np.float64)


def enroll(frames: list[np.ndarray]) -> bytes:
    """Dari beberapa frame hasilkan encoding gabungan (rata-rata) dalam bentuk bytes.
    Tidak dinormalkan: encoding live pada verify() juga mentah, supaya jarak sebanding.
    InvalidInput bila sampel saling berjauhan (mis. orang berbeda terekam di tengah pendaftaran)."""
    if not frames:
        raise InvalidInput("Dibutuhkan minimal satu frame untuk pendaftaran wajah")

    encs = [encode_face(f, num_jitters=config.FACE_JITTERS_ENROLL) for f in frames]
    if len(encs) > 1:
        spread = max(float(np.linalg.norm(a - b)) for i, a in enumerate(encs) for b in encs[i + 1:])
        if spread > config.FACE_ENROLL_MAX_SPREAD:
            raise InvalidInput(
                f"Sampel wajah tidak konsisten (selisih {spread:.2f} > {config.FACE_ENROLL_MAX_SPREAD}). "
                "Pastikan orang yang sama dan pencahayaan cukup, lalu ulangi pengambilan sampel."
            )
    return np.mean(encs, axis=0).astype(np.float64).tobytes()


def distance(frame: np.ndarray, stored: bytes) -> float:
    """Jarak Euclidean antara wajah di frame dan encoding tersimpan (makin kecil makin mirip).
    NoFaceDetected / AmbiguousFace bila tidak ada wajah yang layak di frame."""
    current_enc = encode_face(frame, num_jitters=config.FACE_JITTERS_LOGIN)
    stored_enc = np.frombuffer(stored, dtype=np.float64)
    if len(stored_enc) != 128:
        raise BrankasError("Format data encoding wajah tersimpan tidak valid")
    return float(np.linalg.norm(current_enc - stored_enc))


def verify(frame: np.ndarray, stored: bytes, tolerance: float | None = None) -> bool:
    """Bandingkan wajah di frame dengan encoding tersimpan (bytes dari enroll)."""
    if tolerance is None:
        tolerance = config.FACE_TOLERANCE
    try:
        return distance(frame, stored) <= tolerance
    except NoFaceDetected:
        return False
