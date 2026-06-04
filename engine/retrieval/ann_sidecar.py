from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

ANN_BACKEND_NAME = "hashed-simhash-sqlite"
ANN_BACKEND_VERSION = "hashed-simhash-sqlite-v1"
ANN_SCHEMA_VERSION = "1"
_VECTOR_DIMS = 96
_SIMHASH_BITS = 64
_BAND_BITS = 8
_FULL_SCAN_SCOPE_LIMIT = 2048
_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[idx : idx + n] for idx in range(len(normalized) - n + 1)}


def _hashed_slot(feature: str, dims: int) -> tuple[int, float]:
    digest = hashlib.sha256(feature.encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % dims
    sign = 1.0 if digest[8] & 1 else -1.0
    return index, sign


def _normalize_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0.0:
        return values
    return [value / norm for value in values]


def _vectorize_text(text: str, *, dims: int = _VECTOR_DIMS) -> list[float]:
    tokens = _tokenize(text)
    vector = [0.0] * dims
    token_counts: dict[str, int] = {}
    for token in tokens:
        token_counts[token] = token_counts.get(token, 0) + 1
    bigram_counts: dict[str, int] = {}
    for left, right in zip(tokens, tokens[1:]):
        key = f"{left}|{right}"
        bigram_counts[key] = bigram_counts.get(key, 0) + 1

    for token, count in token_counts.items():
        weight = 1.25 + min(float(count - 1), 2.0) * 0.20
        if len(token) >= 6:
            weight += 0.20
        index, sign = _hashed_slot(f"t:{token}", dims)
        vector[index] += sign * weight

    for bigram, count in bigram_counts.items():
        weight = 1.00 + min(float(count - 1), 1.0) * 0.15
        index, sign = _hashed_slot(f"b:{bigram}", dims)
        vector[index] += sign * weight

    for trigram in _char_ngrams(text):
        index, sign = _hashed_slot(f"c:{trigram}", dims)
        vector[index] += sign * 0.16

    return _normalize_vector(vector)


def _signature_hex(vector: list[float], *, bits: int = _SIMHASH_BITS) -> str:
    bit_count = max(1, min(bits, len(vector)))
    out = 0
    for idx in range(bit_count):
        if vector[idx] >= 0.0:
            out |= 1 << idx
    width = max(1, math.ceil(bit_count / 4))
    return f"{out:0{width}x}"


def _band_values(signature_hex: str, *, bits: int = _SIMHASH_BITS, band_bits: int = _BAND_BITS) -> list[str]:
    value = int(signature_hex or "0", 16)
    mask = (1 << band_bits) - 1
    out: list[str] = []
    for idx in range(max(1, bits // band_bits)):
        out.append(f"{(value >> (idx * band_bits)) & mask:0{max(1, math.ceil(band_bits / 4))}x}")
    return out


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


@dataclass(slots=True)
class AnnSidecarDocument:
    atom_id: str
    canonical_text: str


@dataclass(slots=True)
class AnnQueryResult:
    candidate_ids: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    used: bool = False
    fallback_reason: str = ""
    store_fingerprint: str = ""
    backend_version: str = ANN_BACKEND_VERSION

    def __post_init__(self) -> None:
        self.candidate_ids = [str(item) for item in list(self.candidate_ids or []) if str(item).strip()]
        self.latency_ms = max(0.0, float(self.latency_ms or 0.0))
        self.used = bool(self.used)
        self.fallback_reason = str(self.fallback_reason or "")
        self.store_fingerprint = str(self.store_fingerprint or "")
        self.backend_version = str(self.backend_version or ANN_BACKEND_VERSION)


@dataclass(slots=True)
class RetrievalAnnTelemetry:
    enabled: bool = False
    used: bool = False
    candidate_count: int = 0
    latency_ms: float = 0.0
    fallback_reason: str = ""
    store_fingerprint: str = ""
    backend_version: str = ""

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.used = bool(self.used)
        self.candidate_count = max(0, int(self.candidate_count or 0))
        self.latency_ms = max(0.0, float(self.latency_ms or 0.0))
        self.fallback_reason = str(self.fallback_reason or "")
        self.store_fingerprint = str(self.store_fingerprint or "")
        self.backend_version = str(self.backend_version or "")


class AnnSidecar:
    """Local sqlite-backed vector sidecar for bounded candidate generation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    atom_id TEXT PRIMARY KEY,
                    vector_json TEXT NOT NULL,
                    signature_hex TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bands (
                    atom_id TEXT NOT NULL,
                    band_index INTEGER NOT NULL,
                    band_value TEXT NOT NULL,
                    PRIMARY KEY (atom_id, band_index)
                );
                CREATE INDEX IF NOT EXISTS idx_bands_lookup ON bands(band_index, band_value);
                """
            )

    def metadata(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        conn = self._connect()
        try:
            self._init_schema(conn)
            rows = conn.execute("SELECT key, value FROM metadata").fetchall()
            return {str(row["key"]): str(row["value"]) for row in rows}
        finally:
            conn.close()

    def is_current(self, *, store_fingerprint: str) -> bool:
        metadata = self.metadata()
        return self._validation_reason(metadata, store_fingerprint=store_fingerprint) == ""

    def rebuild(self, *, documents: list[AnnSidecarDocument], store_fingerprint: str) -> None:
        conn = self._connect()
        try:
            self._init_schema(conn)
            rows: list[tuple[str, str, str]] = []
            band_rows: list[tuple[str, int, str]] = []
            for document in documents:
                atom_id = str(document.atom_id or "").strip()
                if not atom_id:
                    continue
                vector = _vectorize_text(document.canonical_text)
                signature_hex = _signature_hex(vector)
                rows.append((atom_id, json.dumps(vector), signature_hex))
                for band_index, band_value in enumerate(_band_values(signature_hex)):
                    band_rows.append((atom_id, band_index, band_value))
            metadata_rows = {
                "backend_name": ANN_BACKEND_NAME,
                "backend_version": ANN_BACKEND_VERSION,
                "schema_version": ANN_SCHEMA_VERSION,
                "store_fingerprint": str(store_fingerprint or ""),
                "vector_dims": str(_VECTOR_DIMS),
                "simhash_bits": str(_SIMHASH_BITS),
                "band_bits": str(_BAND_BITS),
            }
            with conn:
                conn.execute("DELETE FROM metadata")
                conn.execute("DELETE FROM documents")
                conn.execute("DELETE FROM bands")
                conn.executemany(
                    "INSERT INTO metadata(key, value) VALUES(?, ?)",
                    list(metadata_rows.items()),
                )
                conn.executemany(
                    "INSERT INTO documents(atom_id, vector_json, signature_hex) VALUES(?, ?, ?)",
                    rows,
                )
                conn.executemany(
                    "INSERT INTO bands(atom_id, band_index, band_value) VALUES(?, ?, ?)",
                    band_rows,
                )
        finally:
            conn.close()

    def query(
        self,
        *,
        query_text: str,
        scope_ids: set[str],
        store_fingerprint: str,
        limit: int,
        max_latency_ms: float,
    ) -> AnnQueryResult:
        started = time.perf_counter()
        metadata = self.metadata()
        reason = self._validation_reason(metadata, store_fingerprint=store_fingerprint)
        if reason:
            return AnnQueryResult(
                candidate_ids=[],
                latency_ms=(time.perf_counter() - started) * 1000.0,
                used=False,
                fallback_reason=reason,
                store_fingerprint=str(store_fingerprint or ""),
                backend_version=str(metadata.get("backend_version") or ANN_BACKEND_VERSION),
            )
        if limit <= 0 or not scope_ids:
            return AnnQueryResult(
                candidate_ids=[],
                latency_ms=(time.perf_counter() - started) * 1000.0,
                used=True,
                store_fingerprint=str(store_fingerprint or ""),
                backend_version=str(metadata.get("backend_version") or ANN_BACKEND_VERSION),
            )

        query_vector = _vectorize_text(query_text)
        query_signature = _signature_hex(query_vector)
        conn = self._connect()
        try:
            self._init_schema(conn)
            candidate_rows: list[sqlite3.Row]
            if len(scope_ids) <= _FULL_SCAN_SCOPE_LIMIT:
                candidate_rows = self._load_rows(conn, scope_ids)
            else:
                shortlist_ids = self._band_shortlist(conn, query_signature, scope_ids=scope_ids, limit=max(limit * 16, 64))
                candidate_rows = self._load_rows(conn, shortlist_ids)
            if (time.perf_counter() - started) * 1000.0 > float(max_latency_ms):
                return AnnQueryResult(
                    candidate_ids=[],
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    used=False,
                    fallback_reason="timeout",
                    store_fingerprint=str(store_fingerprint or ""),
                    backend_version=str(metadata.get("backend_version") or ANN_BACKEND_VERSION),
                )

            scored: list[tuple[float, str]] = []
            for row in candidate_rows:
                atom_id = str(row["atom_id"])
                vector = [float(value) for value in json.loads(str(row["vector_json"]))]
                score = _cosine_similarity(query_vector, vector)
                if score <= 0.0:
                    continue
                scored.append((score, atom_id))
            scored.sort(key=lambda item: (-item[0], item[1]))
            candidate_ids = [atom_id for _score, atom_id in scored[: max(1, int(limit))]]
            return AnnQueryResult(
                candidate_ids=candidate_ids,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                used=True,
                store_fingerprint=str(store_fingerprint or ""),
                backend_version=str(metadata.get("backend_version") or ANN_BACKEND_VERSION),
            )
        finally:
            conn.close()

    def _validation_reason(self, metadata: dict[str, str], *, store_fingerprint: str) -> str:
        if not metadata:
            return "sidecar_missing"
        required_keys = {
            "backend_name",
            "backend_version",
            "schema_version",
            "store_fingerprint",
            "vector_dims",
            "simhash_bits",
            "band_bits",
        }
        if any(not str(metadata.get(key) or "").strip() for key in required_keys):
            return "incomplete_metadata"
        if metadata.get("backend_name") != ANN_BACKEND_NAME:
            return "backend_mismatch"
        if metadata.get("backend_version") != ANN_BACKEND_VERSION:
            return "backend_mismatch"
        if metadata.get("schema_version") != ANN_SCHEMA_VERSION:
            return "backend_mismatch"
        if metadata.get("store_fingerprint") != str(store_fingerprint or ""):
            return "fingerprint_mismatch"
        return ""

    def _load_rows(self, conn: sqlite3.Connection, atom_ids: set[str]) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        ordered = [str(item) for item in sorted(set(atom_ids)) if str(item).strip()]
        if not ordered:
            return rows
        for start in range(0, len(ordered), 500):
            chunk = ordered[start : start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            rows.extend(
                conn.execute(
                    f"SELECT atom_id, vector_json, signature_hex FROM documents WHERE atom_id IN ({placeholders})",
                    chunk,
                ).fetchall()
            )
        return rows

    def _band_shortlist(
        self,
        conn: sqlite3.Connection,
        query_signature: str,
        *,
        scope_ids: set[str],
        limit: int,
    ) -> set[str]:
        counts: dict[str, int] = {}
        scope = {str(item) for item in scope_ids if str(item).strip()}
        for band_index, band_value in enumerate(_band_values(query_signature)):
            rows = conn.execute(
                "SELECT atom_id FROM bands WHERE band_index = ? AND band_value = ?",
                (band_index, band_value),
            ).fetchall()
            for row in rows:
                atom_id = str(row["atom_id"])
                if atom_id not in scope:
                    continue
                counts[atom_id] = counts.get(atom_id, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return {atom_id for atom_id, _count in ranked[: max(1, int(limit))]}
