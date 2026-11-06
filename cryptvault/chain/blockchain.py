"""Blockchain sederhana dengan proof-of-work. Pemilik: Anggota B.

hash = SHA-256 atas "idx|timestamp|user_id|action|doc_id|doc_hash|prev_hash|nonce".
Blok valid bila hash diawali '0' * config.POW_DIFFICULTY.
"""
from dataclasses import dataclass
from pathlib import Path


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
    raise NotImplementedError


def add_block(conn, user_id: int, action: str, doc_id: str, doc_hash: str) -> Block:
    """Buat blok genesis bila rantai kosong, lakukan mining, simpan ke tabel chain."""
    raise NotImplementedError


def verify_chain(conn, vault_dir: Path) -> VerifyResult:
    """Hitung ulang hash tiap blok, cek prev_hash & PoW, dan cocokkan doc_hash blok UPLOAD
    dengan SHA-256 file .enc yang ada di vault_dir (untuk dokumen yang belum dihapus)."""
    raise NotImplementedError
