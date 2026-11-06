"""Face recognition. Pemilik: Anggota A.

Frame = numpy array RGB (H, W, 3). Konversi dari BGR OpenCV dilakukan di sini.
Encoding = 128 float64 -> diserialisasi ke bytes (enc.tobytes()) sebelum dienkripsi.
"""
import numpy as np


def capture_frame() -> np.ndarray:
    """Ambil satu frame dari webcam. Melempar BrankasError bila gagal."""
    raise NotImplementedError


def encode_face(frame: np.ndarray) -> np.ndarray:
    """Encoding satu wajah. Melempar NoFaceDetected bila tidak ada wajah."""
    raise NotImplementedError


def enroll(frames: list[np.ndarray]) -> bytes:
    """Dari beberapa frame hasilkan encoding gabungan (rata-rata) dalam bentuk bytes."""
    raise NotImplementedError


def verify(frame: np.ndarray, stored: bytes, tolerance: float | None = None) -> bool:
    """Bandingkan wajah di frame dengan encoding tersimpan (bytes dari enroll)."""
    raise NotImplementedError
