"""Face recognition. Pemilik: Anggota A.

Frame = numpy array RGB (H, W, 3). Konversi dari BGR OpenCV dilakukan di sini.
Encoding = 128 float64 -> diserialisasi ke bytes (enc.tobytes()) sebelum dienkripsi.
"""
from __future__ import annotations

import cv2
import face_recognition
import numpy as np

from brankas import config
from brankas.errors import BrankasError, InvalidInput, NoFaceDetected


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


def encode_face(frame: np.ndarray) -> np.ndarray:
    """Encoding satu wajah. Melempar NoFaceDetected bila tidak ada wajah."""
    encodings = face_recognition.face_encodings(frame)
    if not encodings:
        raise NoFaceDetected("Tidak ada wajah yang terdeteksi pada gambar")
    return encodings[0].astype(np.float64)


def enroll(frames: list[np.ndarray]) -> bytes:
    """Dari beberapa frame hasilkan encoding gabungan (rata-rata) dalam bentuk bytes.
    Tidak dinormalkan: encoding live pada verify() juga mentah, supaya jarak sebanding."""
    if not frames:
        raise InvalidInput("Dibutuhkan minimal satu frame untuk pendaftaran wajah")

    encs = [encode_face(f) for f in frames]
    return np.mean(encs, axis=0).astype(np.float64).tobytes()


def distance(frame: np.ndarray, stored: bytes) -> float:
    """Jarak Euclidean antara wajah di frame dan encoding tersimpan (makin kecil makin mirip).
    NoFaceDetected bila tidak ada wajah di frame."""
    current_enc = encode_face(frame)
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
