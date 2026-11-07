"""Blockchain sederhana dengan proof-of-work. Pemilik: Anggota B.

hash = SHA-256 atas "idx|timestamp|user_id|action|doc_id|doc_hash|prev_hash|nonce".
Blok valid bila hash diawali '0' * config.POW_DIFFICULTY.

Catatan: menaikkan POW_DIFFICULTY setelah ada data akan membuat blok lama gagal verifikasi
(menurunkan tidak masalah).
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from brankas import config
from brankas.core.crypto import sha256_hex
from brankas.errors import UnsafePath
from brankas.storage.vault import safe_vault_path

GENESIS_PREV = "0" * 64
VALID_ACTIONS = ("UPLOAD", "DELETE")


@dataclass
class Block:
    idx: int
    timestamp: str
    user_id: int
    action: str        # GENESIS / UPLOAD / DELETE
    doc_id: str
    doc_hash: str
    prev_hash: str
    nonce: int
    hash: str


@dataclass
class VerifyResult:
    ok: bool
    checked_blocks: int
    problems: list[str]   # pesan per masalah, mis. "Blok 3: hash tidak cocok"


def compute_hash(block: Block) -> str:
    payload = "|".join(str(x) for x in (
        block.idx, block.timestamp, block.user_id, block.action,
        block.doc_id, block.doc_hash, block.prev_hash, block.nonce,
    ))
    return sha256_hex(payload.encode("utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mine(block: Block) -> Block:
    """Proof-of-work: cari nonce sampai hash diawali nol sebanyak POW_DIFFICULTY."""
    prefix = "0" * config.POW_DIFFICULTY
    nonce = 0
    while True:
        block.nonce = nonce
        digest = compute_hash(block)
        if digest.startswith(prefix):
            block.hash = digest
            return block
        nonce += 1


def _row_to_block(row) -> Block:
    return Block(row["idx"], row["timestamp"], row["user_id"], row["action"],
                 row["doc_id"], row["doc_hash"], row["prev_hash"], row["nonce"], row["hash"])


def _insert(conn, b: Block) -> None:
    conn.execute(
        "INSERT INTO chain (idx, timestamp, user_id, action, doc_id, doc_hash, prev_hash, nonce, hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (b.idx, b.timestamp, b.user_id, b.action, b.doc_id, b.doc_hash, b.prev_hash, b.nonce, b.hash),
    )


def _last_block(conn) -> Block | None:
    row = conn.execute("SELECT * FROM chain ORDER BY idx DESC LIMIT 1").fetchone()
    return _row_to_block(row) if row else None


def add_block(conn, user_id: int, action: str, doc_id: str, doc_hash: str) -> Block:
    """Buat blok genesis bila rantai kosong, lakukan mining, simpan ke tabel chain.
    Tidak melakukan commit: panggil di dalam db.transaction() bersama operasi dokumen."""
    if action not in VALID_ACTIONS:
        raise ValueError(f"action harus salah satu dari {VALID_ACTIONS}")
    last = _last_block(conn)
    if last is None:
        last = _mine(Block(0, _now(), 0, "GENESIS", "-", "-", GENESIS_PREV, 0, ""))
        _insert(conn, last)
    block = _mine(Block(last.idx + 1, _now(), user_id, action, doc_id, doc_hash, last.hash, 0, ""))
    _insert(conn, block)
    return block


def verify_chain(conn, vault_dir: Path) -> VerifyResult:
    """Hitung ulang hash tiap blok, cek prev_hash & PoW, dan cocokkan doc_hash blok UPLOAD
    dengan SHA-256 file .enc yang ada di vault_dir (untuk dokumen yang belum dihapus)."""
    problems: list[str] = []
    blocks = [_row_to_block(r) for r in conn.execute("SELECT * FROM chain ORDER BY idx")]
    prefix = "0" * config.POW_DIFFICULTY

    # --- integritas rantai ---
    prev = None
    for pos, b in enumerate(blocks):
        tag = f"Blok {b.idx}"
        if b.idx != pos:
            problems.append(f"{tag}: nomor urut tidak berurutan (seharusnya {pos})")
        if pos == 0:
            if b.action != "GENESIS":
                problems.append(f"{tag}: blok pertama bukan GENESIS")
            if b.prev_hash != GENESIS_PREV:
                problems.append(f"{tag}: prev_hash blok genesis tidak valid")
        else:
            if b.prev_hash != prev.hash:
                problems.append(f"{tag}: prev_hash tidak cocok dengan blok sebelumnya")
            if b.action not in VALID_ACTIONS:
                problems.append(f"{tag}: aksi tidak dikenal ({b.action})")
        if compute_hash(b) != b.hash:
            problems.append(f"{tag}: hash tidak cocok dengan isi blok (data diubah)")
        elif not b.hash.startswith(prefix):
            problems.append(f"{tag}: proof-of-work tidak terpenuhi")
        prev = b

    # --- kecocokan dengan dokumen ---
    uploads: dict[str, str] = {}
    deleted: set[str] = set()
    for b in blocks:
        if b.action == "UPLOAD":
            uploads[b.doc_id] = b.doc_hash
        elif b.action == "DELETE":
            if b.doc_id not in uploads:
                problems.append(f"Blok {b.idx}: DELETE untuk dokumen yang tidak pernah diunggah")
            elif uploads[b.doc_id] != b.doc_hash:
                problems.append(f"Blok {b.idx}: hash DELETE berbeda dari hash saat unggah")
            deleted.add(b.doc_id)

    docs = {r["id"]: r["stored_path"] for r in conn.execute("SELECT id, stored_path FROM documents")}
    for doc_id, expected in uploads.items():
        short = f"Dokumen {doc_id[:8]}"
        if doc_id in deleted:
            if doc_id in docs:
                problems.append(f"{short}: tercatat dihapus tetapi masih ada di basis data")
            continue
        if doc_id not in docs:
            problems.append(f"{short}: hilang dari basis data tanpa catatan DELETE")
            continue
        try:
            f = safe_vault_path(vault_dir, docs[doc_id])
        except UnsafePath as e:
            problems.append(f"{short}: {e}")
            continue
        if not f.is_file():
            problems.append(f"{short}: file terenkripsi hilang dari vault")
        elif sha256_hex(f.read_bytes()) != expected:
            problems.append(f"{short}: isi file berubah (hash tidak cocok dengan blockchain)")
    for doc_id in docs:
        if doc_id not in uploads:
            problems.append(f"Dokumen {doc_id[:8]}: ada di basis data tetapi tidak tercatat di blockchain")

    return VerifyResult(ok=not problems, checked_blocks=len(blocks), problems=problems)


def list_blocks(conn, user_id: int | None = None) -> list[Block]:
    """Blok urut dari genesis (untuk ditampilkan di UI).
    user_id=None: semua blok (dipakai verifikasi/tes). user_id diisi: hanya blok milik pengguna itu,
    sehingga UI tidak membocorkan jumlah dan waktu aksi akun lain (blok genesis ikut disembunyikan).
    Verifikasi (verify_chain) selalu memeriksa seluruh rantai, terlepas dari filter tampilan ini."""
    if user_id is None:
        rows = conn.execute("SELECT * FROM chain ORDER BY idx")
    else:
        rows = conn.execute("SELECT * FROM chain WHERE user_id = ? AND action != 'GENESIS' ORDER BY idx",
                            (user_id,))
    return [_row_to_block(r) for r in rows]
