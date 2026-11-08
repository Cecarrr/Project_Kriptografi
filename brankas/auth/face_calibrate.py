"""Kalibrasi ambang wajah (FACE_TOLERANCE). Jalankan dari root repo:  python face_calibrate.py

Memakai pengaturan face.py yang sama dengan aplikasi (model landmark, jitter, pemilihan wajah terbesar).
Orang ke-1 = pemilik akun: FACE_ENROLL_SAMPLES foto pertamanya dipakai mendaftar (seperti registrasi),
foto sisanya menjadi data "orang sama". Foto orang ke-2 dan seterusnya menjadi data "orang berbeda";
ajak teman satu angkatan / saudara yang mirip untuk hasil yang realistis.
Tips: ambil foto dalam kondisi berbeda (terang, redup, sedikit menoleh, jam berbeda).
Foto tidak disimpan ke disk."""
from __future__ import annotations

import statistics

from brankas import config
from brankas.auth import face
from brankas.errors import BrankasError, InvalidInput


def _stats(name: str, values: list[float]) -> None:
    if not values:
        print(f"  {name}: (tidak ada data)")
        return
    print(f"  {name}: n={len(values)}  min={min(values):.3f}  rata-rata={statistics.mean(values):.3f}  "
          f"maks={max(values):.3f}")


def report(genuine: list[float], impostor: list[float]) -> None:
    print("\n=== Hasil ===")
    _stats("Orang sama   ", genuine)
    _stats("Orang berbeda", impostor)
    print("\n  ambang   FRR (pemilik ditolak)   FAR (orang lain diterima)")
    for t in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        frr = 100 * sum(d > t for d in genuine) / len(genuine) if genuine else float("nan")
        far = 100 * sum(d <= t for d in impostor) / len(impostor) if impostor else float("nan")
        mark = "  <- saat ini" if abs(t - config.FACE_TOLERANCE) < 1e-9 else ""
        print(f"  {t:.2f}     {frr:6.1f}%                 {far:6.1f}%{mark}")
    if genuine and impostor:
        hi_g, lo_i = max(genuine), min(impostor)
        if hi_g < lo_i:
            print(f"\n  Terpisah bersih: usulan ambang ~{(hi_g + lo_i) / 2:.2f} (celah {lo_i - hi_g:.2f}).")
        else:
            print(f"\n  TUMPANG TINDIH: orang sama sampai {hi_g:.3f}, orang berbeda mulai {lo_i:.3f}. "
                  "Tidak ada ambang tunggal yang sempurna; turunkan ambang (prioritaskan FAR), "
                  "perbaiki cahaya/jarak kamera, atau naikkan jitter.")
    print("\n  Catatan: sampel kecil. Makin banyak foto dan makin beragam kondisi, makin bisa dipercaya.")


def _collect(label: str, shots: int) -> list:
    frames = []
    while len(frames) < shots:
        input(f"[{label}] Enter untuk foto {len(frames) + 1}/{shots} (ubah posisi/cahaya sedikit)...")
        try:
            frame = face.capture_frame()
            face.encode_face(frame)          # pastikan wajah layak sebelum disimpan
        except BrankasError as e:
            print(f"   ✖ {e}")
            continue
        frames.append(frame)
        print("   ✔ tercatat")
    return frames


def main() -> None:
    n_people = int(input("Jumlah orang (min 2, orang ke-1 = pemilik akun): ") or 2)
    shots = int(input("Foto per orang (disarankan 12): ") or 12)
    owner_shots = max(shots, config.FACE_ENROLL_SAMPLES + 3)

    owner_frames = _collect(input("Nama orang ke-1 (pemilik): ").strip() or "pemilik", owner_shots)
    try:
        stored = face.enroll(owner_frames[: config.FACE_ENROLL_SAMPLES])
    except InvalidInput as e:
        raise SystemExit(f"Pendaftaran pemilik gagal: {e}")
    genuine = [face.distance(f, stored) for f in owner_frames[config.FACE_ENROLL_SAMPLES:]]

    impostor: list[float] = []
    for i in range(2, n_people + 1):
        label = input(f"Nama orang ke-{i}: ").strip() or f"orang{i}"
        impostor += [face.distance(f, stored) for f in _collect(label, shots)]

    report(genuine, impostor)


if __name__ == "__main__":
    main()
