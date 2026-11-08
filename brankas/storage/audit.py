"""Log audit berantai hash. Pemilik: Anggota B.

Mencatat peristiwa akses: LOGIN, LOGOUT, UNDUH, PRATINJAU. Terpisah dari tabel `chain` (blockchain
dokumen) agar login tidak memicu proof-of-work. Tiap entri memuat hash entri sebelumnya, jadi
mengubah atau menghapus entri di tengah log ketahuan oleh verify_audit().

Batas yang jujur: tanpa jangkar di luar basis data, entri yang dihapus dari UJUNG log tidak terdeteksi.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from brankas.core.crypto import sha256_hex

GENESIS_PREV = "0" * 64
ACTIONS = ("LOGIN", "LOGOUT", "UNDUH", "PRATINJAU")


@dataclass
class AuditEntry:
    idx: int
    timestamp: str
    user_id: int
    action: str        # GENESIS / LOGIN / LOGOUT / UNDUH / PRATINJAU
    doc_id: str        # "-" bila tidak terkait dokumen
    prev_hash: str
    hash: str


@dataclass
class AuditVerifyResult:
    ok: bool
    checked: int
    problems: list[str]


def compute_hash(e: AuditEntry) -> str:
    payload = "|".join(str(x) for x in (e.idx, e.timestamp, e.user_id, e.action, e.doc_id, e.prev_hash))
    return sha256_hex(payload.encode("utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(r) -> AuditEntry:
    return AuditEntry(r["idx"], r["timestamp"], r["user_id"], r["action"], r["doc_id"],
                      r["prev_hash"], r["hash"])


def _insert(conn, e: AuditEntry) -> None:
    conn.execute(
        "INSERT INTO audit (idx, timestamp, user_id, action, doc_id, prev_hash, hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (e.idx, e.timestamp, e.user_id, e.action, e.doc_id, e.prev_hash, e.hash),
    )


def _seal(idx: int, user_id: int, action: str, doc_id: str, prev_hash: str) -> AuditEntry:
    e = AuditEntry(idx, _now(), user_id, action, doc_id, prev_hash, "")
    e.hash = compute_hash(e)
    return e


def record(conn, user_id: int, action: str, doc_id: str = "-") -> AuditEntry:
    """Tambah satu entri (membuat genesis bila log kosong). Tidak commit: panggil di dalam
    db.transaction(). BEGIN IMMEDIATE mengunci penulisan supaya dua thread (mis. watcher dongle
    dan UI) tidak membaca prev_hash yang sama."""
    if action not in ACTIONS:
        raise ValueError(f"action harus salah satu dari {ACTIONS}")
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    last = conn.execute("SELECT * FROM audit ORDER BY idx DESC LIMIT 1").fetchone()
    if last is None:
        genesis = _seal(0, 0, "GENESIS", "-", GENESIS_PREV)
        _insert(conn, genesis)
        prev = genesis
    else:
        prev = _row(last)
    entry = _seal(prev.idx + 1, user_id, action, doc_id, prev.hash)
    _insert(conn, entry)
    return entry


def list_entries(conn, user_id: int) -> list[AuditEntry]:
    """Entri milik user_id, terbaru di atas. Genesis (user_id 0) dan entri akun lain tidak ikut,
    seperti list_blocks. verify_audit tetap memeriksa seluruh log."""
    rows = conn.execute("SELECT * FROM audit WHERE user_id = ? ORDER BY idx DESC", (user_id,))
    return [_row(r) for r in rows]


def verify_audit(conn) -> AuditVerifyResult:
    problems: list[str] = []
    entries = [_row(r) for r in conn.execute("SELECT * FROM audit ORDER BY idx")]
    prev: AuditEntry | None = None
    for pos, e in enumerate(entries):
        tag = f"Entri {e.idx}"
        if e.idx != pos:
            problems.append(f"{tag}: nomor urut tidak berurutan (seharusnya {pos})")
        if pos == 0:
            if e.action != "GENESIS":
                problems.append(f"{tag}: entri pertama bukan GENESIS")
            if e.prev_hash != GENESIS_PREV:
                problems.append(f"{tag}: prev_hash genesis tidak valid")
        else:
            if e.prev_hash != prev.hash:
                problems.append(f"{tag}: prev_hash tidak cocok dengan entri sebelumnya")
            if e.action not in ACTIONS:
                problems.append(f"{tag}: aksi tidak dikenal ({e.action})")
        if compute_hash(e) != e.hash:
            problems.append(f"{tag}: hash tidak cocok dengan isi entri (data diubah)")
        prev = e
    return AuditVerifyResult(ok=not problems, checked=len(entries), problems=problems)
