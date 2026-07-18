from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from ..contracts import AtomType, CandidateAtom, NormalizedTurn, contract_to_dict, source_ref_from_dict
from .store import (
    AtomStatus,
    AtomStore,
    ContradictionEdge,
    EventType,
    MemoryAtom,
    ProvenanceEvent,
    RawContextTurn,
    RecognitionRecord,
    half_life_days_for_atom_type,
)

SCHEMA_VERSION = 3


class SqliteProvenanceLedger:
    """Append-only provenance ledger backed by sqlite."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock, *, batch_active: callable) -> None:
        self._conn = conn
        self._lock = lock
        self._batch_active = batch_active

    def append(self, event: ProvenanceEvent) -> None:
        source_refs_json = json.dumps([contract_to_dict(ref) for ref in event.source_refs], ensure_ascii=False)
        metadata_json = json.dumps(dict(event.metadata), ensure_ascii=False)
        with self._lock:
            if self._batch_active():
                self._conn.execute(
                    """
                    INSERT INTO provenance_events (
                        event_id, event_type, atom_id, timestamp, source_refs_json, reason, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type.value,
                        event.atom_id,
                        event.timestamp.isoformat(),
                        source_refs_json,
                        event.reason,
                        metadata_json,
                    ),
                )
            else:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO provenance_events (
                            event_id, event_type, atom_id, timestamp, source_refs_json, reason, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            event.event_type.value,
                            event.atom_id,
                            event.timestamp.isoformat(),
                            source_refs_json,
                            event.reason,
                            metadata_json,
                        ),
                    )

    def all_events(self) -> list[ProvenanceEvent]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, event_type, atom_id, timestamp, source_refs_json, reason, metadata_json
                FROM provenance_events
                ORDER BY seq ASC
                """
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def events_for_atom(self, atom_id: str) -> list[ProvenanceEvent]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, event_type, atom_id, timestamp, source_refs_json, reason, metadata_json
                FROM provenance_events
                WHERE atom_id = ?
                ORDER BY seq ASC
                """,
                (atom_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ProvenanceEvent:
        source_refs = [source_ref_from_dict(item) for item in json.loads(row["source_refs_json"] or "[]")]
        metadata = {str(key): str(value) for key, value in json.loads(row["metadata_json"] or "{}").items()}
        return ProvenanceEvent(
            event_id=str(row["event_id"]),
            event_type=EventType(str(row["event_type"])),
            atom_id=str(row["atom_id"]),
            timestamp=datetime.fromisoformat(str(row["timestamp"])),
            source_refs=source_refs,
            reason=str(row["reason"]),
            metadata=metadata,
        )


class SqliteAtomStore:
    """Sqlite-backed atom repository with append-only provenance and conflict graph."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        salience_half_life_days: int = 180,
    ) -> None:
        if salience_half_life_days <= 0:
            raise ValueError("salience_half_life_days must be > 0")
        self.salience_half_life_days = salience_half_life_days
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_scope_id = f"sqlite-atom-store:{self.db_path.resolve()}"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._batch_depth = 0
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._ensure_runtime_control_schema()
        self.ledger = SqliteProvenanceLedger(self._conn, self._lock, batch_active=lambda: self._batch_depth > 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def backup_to(self, target_path: str | Path) -> Path:
        """Create a transactionally consistent SQLite backup without copying live WAL files."""
        target = Path(target_path).expanduser().resolve()
        source = self.db_path.expanduser().resolve()
        if target == source:
            raise ValueError("backup target must differ from the live store")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(str(target)) as destination:
            self._conn.backup(destination)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

    def schema_version(self) -> int:
        with self._lock:
            row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    @contextmanager
    def _write_scope(self):
        if self._batch_depth > 0:
            yield
            return
        with self._conn:
            yield

    @contextmanager
    def write_batch(self):
        with self._lock:
            outermost = self._batch_depth == 0
            if outermost:
                self._conn.execute("BEGIN")
            self._batch_depth += 1
            try:
                yield
            except Exception:
                self._batch_depth -= 1
                if outermost:
                    self._conn.rollback()
                raise
            else:
                self._batch_depth -= 1
                if outermost:
                    self._conn.commit()

    def _init_schema(self) -> None:
        version = self.schema_version()
        if version == 0:
            self._create_schema_v2()
            with self._conn:
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version == 1:
            self._migrate_1_to_2()
            self._migrate_2_to_3()
            with self._conn:
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version == 2:
            self._migrate_2_to_3()
            with self._conn:
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            raise RuntimeError(f"unsupported schema version: {version}")
        self._ensure_raw_context_schema()
        self._ensure_mutation_review_schema()

    def _create_schema_v2(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS atoms (
                    atom_id TEXT PRIMARY KEY,
                    atom_type TEXT NOT NULL,
                    canonical_text TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    salience REAL NOT NULL,
                    salience_half_life_days INTEGER NOT NULL,
                    last_reinforced_at TEXT,
                    support_count INTEGER NOT NULL,
                    contradiction_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    version_of TEXT,
                    tombstoned_at TEXT,
                    purge_after TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS provenance_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    atom_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conflicts (
                    left_atom_id TEXT NOT NULL,
                    right_atom_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    PRIMARY KEY (left_atom_id, right_atom_id)
                );

                CREATE TABLE IF NOT EXISTS recognition_events (
                    event_id TEXT PRIMARY KEY,
                    atom_id TEXT NOT NULL,
                    recognized INTEGER NOT NULL,
                    score REAL NOT NULL,
                    query_text TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shared_language_keys (
                    key_id TEXT PRIMARY KEY,
                    phrase TEXT NOT NULL,
                    phrase_norm TEXT NOT NULL UNIQUE,
                    aliases_json TEXT NOT NULL,
                    domains_json TEXT NOT NULL,
                    support_count INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    confidence REAL NOT NULL,
                    curated INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shared_language_links (
                    key_id TEXT NOT NULL,
                    atom_id TEXT NOT NULL,
                    PRIMARY KEY (key_id, atom_id)
                );

                CREATE INDEX IF NOT EXISTS idx_atoms_status ON atoms(status);
                CREATE INDEX IF NOT EXISTS idx_atoms_updated_at ON atoms(updated_at);
                CREATE INDEX IF NOT EXISTS idx_events_atom ON provenance_events(atom_id);
                CREATE INDEX IF NOT EXISTS idx_conflicts_left ON conflicts(left_atom_id);
                CREATE INDEX IF NOT EXISTS idx_slk_phrase_norm ON shared_language_keys(phrase_norm);
                """
            )
        self._ensure_raw_context_schema()
        self._ensure_raw_context_schema()

    def _migrate_1_to_2(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS recognition_events (
                    event_id TEXT PRIMARY KEY,
                    atom_id TEXT NOT NULL,
                    recognized INTEGER NOT NULL,
                    score REAL NOT NULL,
                    query_text TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )

    def _migrate_2_to_3(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS shared_language_keys (
                    key_id TEXT PRIMARY KEY,
                    phrase TEXT NOT NULL,
                    phrase_norm TEXT NOT NULL UNIQUE,
                    aliases_json TEXT NOT NULL,
                    domains_json TEXT NOT NULL,
                    support_count INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    confidence REAL NOT NULL,
                    curated INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shared_language_links (
                    key_id TEXT NOT NULL,
                    atom_id TEXT NOT NULL,
                    PRIMARY KEY (key_id, atom_id)
                );

                CREATE INDEX IF NOT EXISTS idx_slk_phrase_norm ON shared_language_keys(phrase_norm);
                """
            )
        self._ensure_raw_context_schema()

    def _ensure_raw_context_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_context_turns (
                    turn_key TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    conversation_id TEXT,
                    message_id TEXT,
                    sequence_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    quote_text TEXT NOT NULL,
                    timestamp TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_raw_context_source_seq ON raw_context_turns(source_id, sequence_index);
                CREATE INDEX IF NOT EXISTS idx_raw_context_source_msg ON raw_context_turns(source_id, message_id);
                """
            )

    def _ensure_mutation_review_schema(self) -> None:
        """Install durable reviewer-controlled mutation state in the atom database."""

        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mutation_review_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    target_atom_id TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    replacement_candidate_json TEXT,
                    retention_days INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_by TEXT,
                    reviewer TEXT,
                    reviewed_at TEXT,
                    applied_atom_id TEXT,
                    apply_identity TEXT,
                    applied_at TEXT,
                    refresh_pending INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS mutation_review_audit_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    proposal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT,
                    timestamp TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mutation_review_bridge_state (
                    proposal_id TEXT PRIMARY KEY,
                    provisional_record_id TEXT NOT NULL,
                    applied_atom_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    bridge_sync_pending INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_mutation_review_status
                    ON mutation_review_proposals(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_mutation_review_bridge_provisional
                    ON mutation_review_bridge_state(provisional_record_id);
                """
            )

    def _ensure_runtime_control_schema(self) -> None:
        """Create or validate protected, store-stable integration signing state."""

        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_control'"
            ).fetchone()
            if exists is None:
                with self._conn:
                    self._conn.execute(
                        "CREATE TABLE runtime_control (control_key TEXT PRIMARY KEY, control_value TEXT NOT NULL)"
                    )
                    self._conn.executemany(
                        "INSERT INTO runtime_control(control_key, control_value) VALUES (?, ?)",
                        (
                            ("store_uuid", str(uuid4())),
                            ("signing_key_hex", secrets.token_hex(32)),
                            ("signing_key_id", f"key_{uuid4().hex[:16]}"),
                        ),
                    )
            rows = {
                str(row["control_key"]): str(row["control_value"])
                for row in self._conn.execute(
                    "SELECT control_key, control_value FROM runtime_control"
                ).fetchall()
            }
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        try:
            key = bytes.fromhex(rows["signing_key_hex"])
        except (KeyError, ValueError) as exc:
            raise RuntimeError("CONTROL_KEY_UNAVAILABLE") from exc
        if len(key) != 32 or not rows.get("store_uuid") or not rows.get("signing_key_id"):
            raise RuntimeError("CONTROL_KEY_UNAVAILABLE")

    def runtime_control_identity(self) -> dict[str, str]:
        with self._lock:
            rows = {
                str(row["control_key"]): str(row["control_value"])
                for row in self._conn.execute(
                    "SELECT control_key, control_value FROM runtime_control WHERE control_key IN ('store_uuid', 'signing_key_id')"
                ).fetchall()
            }
        if not rows.get("store_uuid") or not rows.get("signing_key_id"):
            raise RuntimeError("CONTROL_KEY_UNAVAILABLE")
        return rows

    def runtime_signing_key(self) -> bytes:
        with self._lock:
            row = self._conn.execute(
                "SELECT control_value FROM runtime_control WHERE control_key='signing_key_hex'"
            ).fetchone()
        if row is None:
            raise RuntimeError("CONTROL_KEY_UNAVAILABLE")
        try:
            key = bytes.fromhex(str(row[0]))
        except ValueError as exc:
            raise RuntimeError("CONTROL_KEY_UNAVAILABLE") from exc
        if len(key) != 32:
            raise RuntimeError("CONTROL_KEY_UNAVAILABLE")
        return key

    def rotate_runtime_signing_key(self) -> dict[str, str]:
        """Rotate the store-local signing key while the caller owns offline store access."""
        key_id = f"key_{uuid4().hex[:16]}"
        key_hex = secrets.token_hex(32)
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE runtime_control SET control_value=? WHERE control_key='signing_key_hex'",
                (key_hex,),
            )
            self._conn.execute(
                "UPDATE runtime_control SET control_value=? WHERE control_key='signing_key_id'",
                (key_id,),
            )
        return self.runtime_control_identity()

    def mutation_review_create(self, record: dict[str, Any]) -> dict[str, Any]:
        """Persist a proposed mutation without changing atom or review truth."""

        with self._lock, self._write_scope():
            self._conn.execute(
                """
                INSERT INTO mutation_review_proposals (
                    proposal_id, action, target_atom_id, reason_code, created_at, status,
                    replacement_candidate_json, retention_days, metadata_json, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["proposal_id"], record["action"], record["target_atom_id"], record["reason_code"],
                    record["created_at"], record["status"], record.get("replacement_candidate_json"),
                    int(record["retention_days"]), record["metadata_json"], record.get("created_by"),
                ),
            )
            self._mutation_review_audit(record["proposal_id"], "PROPOSED", record.get("created_by"), {})
        return self.mutation_review_get(str(record["proposal_id"]))

    def mutation_review_get(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM mutation_review_proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        return {key: row[key] for key in row.keys()}

    def mutation_review_list(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mutation_review_proposals ORDER BY created_at ASC, proposal_id ASC"
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def mutation_review_resolve(
        self,
        proposal_id: str,
        *,
        decision: str,
        actor_id: str,
        rejection_reason: str = "",
        apply: bool = False,
    ) -> dict[str, Any]:
        """Resolve/apply a proposal atomically; callers map conflicts to their public contract."""

        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if not actor_id.strip():
            raise ValueError("actor_id is required")
        if apply and decision != "approve":
            raise ValueError("reject decisions cannot apply")

        with self._lock, self.write_batch():
            row = self.mutation_review_get(proposal_id)
            status = str(row["status"])
            persisted_decision = "approve" if status in {"approved", "applied"} else "reject" if status == "rejected" else ""
            if persisted_decision and persisted_decision != decision:
                return {"decision_conflict": persisted_decision, "proposal": row}
            if status == "pending":
                metadata = json.loads(str(row["metadata_json"]))
                if decision == "reject":
                    metadata["rejection_reason"] = rejection_reason
                now = self._now().isoformat()
                next_status = "approved" if decision == "approve" else "rejected"
                self._conn.execute(
                    """
                    UPDATE mutation_review_proposals
                    SET status = ?, reviewer = ?, reviewed_at = ?, metadata_json = ?
                    WHERE proposal_id = ?
                    """,
                    (next_status, actor_id, now, json.dumps(metadata, ensure_ascii=False), proposal_id),
                )
                self._mutation_review_audit(proposal_id, "APPROVED" if decision == "approve" else "REJECTED", actor_id, {})
                row = self.mutation_review_get(proposal_id)

            if not apply:
                return {"proposal": self.mutation_review_get(proposal_id)}
            if str(row["status"]) == "applied":
                return {"proposal": self.mutation_review_get(proposal_id)}

            applied_atom_id = self._mutation_review_apply_atom(row, actor_id)
            now = self._now().isoformat()
            apply_identity = f"mra_{sha256(proposal_id.encode('utf-8')).hexdigest()[:24]}"
            self._conn.execute(
                """
                UPDATE mutation_review_proposals
                SET status = 'applied', applied_atom_id = ?, apply_identity = ?, applied_at = ?
                WHERE proposal_id = ?
                """,
                (applied_atom_id, apply_identity, now, proposal_id),
            )
            self._mutation_review_audit(
                proposal_id, "APPLIED", actor_id, {"applied_atom_id": applied_atom_id, "apply_identity": apply_identity}
            )
            metadata = json.loads(str(row["metadata_json"]))
            provisional_record_id = str(metadata.get("provisional_record_id") or "").strip()
            if provisional_record_id:
                self._conn.execute(
                    """
                    INSERT INTO mutation_review_bridge_state (
                        proposal_id, provisional_record_id, applied_atom_id, actor_id, applied_at, bridge_sync_pending
                    ) VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(proposal_id) DO NOTHING
                    """,
                    (proposal_id, provisional_record_id, applied_atom_id, actor_id, now),
                )
                self._mutation_review_audit(
                    proposal_id, "BRIDGE_SUPPRESSED", actor_id, {"provisional_record_id": provisional_record_id}
                )
            return {"proposal": self.mutation_review_get(proposal_id)}

    def _mutation_review_apply_atom(self, row: dict[str, Any], actor_id: str) -> str:
        action = str(row["action"])
        proposal_id = str(row["proposal_id"])
        reason = f"proposal:{proposal_id}"
        if action == "PROPOSE_DELETE":
            self.tombstone_atom(str(row["target_atom_id"]), reason=reason, retention_days=int(row["retention_days"]))
            return str(row["target_atom_id"])
        candidate_payload = json.loads(str(row["replacement_candidate_json"] or "{}"))
        candidate = CandidateAtom(
            candidate_id=str(candidate_payload["candidate_id"]),
            atom_type=AtomType(str(candidate_payload["atom_type"])),
            canonical_text=str(candidate_payload["canonical_text"]),
            source_refs=[source_ref_from_dict(item) for item in candidate_payload["source_refs"]],
            entities=[str(item) for item in candidate_payload.get("entities") or []],
            topics=[str(item) for item in candidate_payload.get("topics") or []],
            confidence=float(candidate_payload["confidence"]),
            salience=float(candidate_payload["salience"]),
        )
        stable_atom_id = f"mem_mra_{sha256(proposal_id.encode('utf-8')).hexdigest()[:24]}"
        if action == "PROPOSE_CREATE":
            return self.add_candidate(candidate, reason=reason, atom_id=stable_atom_id).atom_id
        if action == "PROPOSE_EDIT":
            return self.supersede_atom(
                str(row["target_atom_id"]), candidate, reason=reason, replacement_atom_id=stable_atom_id
            ).atom_id
        raise ValueError(f"unsupported mutation action: {action}")

    def _mutation_review_audit(
        self, proposal_id: str, event_type: str, actor_id: str | None, metadata: dict[str, str]
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO mutation_review_audit_events (event_id, proposal_id, event_type, actor_id, timestamp, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"mra_evt_{uuid4().hex}", proposal_id, event_type, actor_id, self._now().isoformat(), json.dumps(metadata)),
        )

    def mutation_review_mark_refresh_pending(self, proposal_id: str) -> None:
        with self._lock, self._write_scope():
            self._conn.execute(
                "UPDATE mutation_review_proposals SET refresh_pending = 1 WHERE proposal_id = ?", (proposal_id,)
            )
            self._mutation_review_audit(proposal_id, "REFRESH_PENDING", None, {})

    def mutation_bridge_state(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM mutation_review_bridge_state WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        result = {key: row[key] for key in row.keys()}
        result["bridge_sync_pending"] = bool(result["bridge_sync_pending"])
        return result

    def is_provisional_bridge_suppressed(self, provisional_record_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM mutation_review_bridge_state WHERE provisional_record_id = ? LIMIT 1",
                (provisional_record_id,),
            ).fetchone()
        return row is not None

    def mutation_bridge_mark_reconciled(self, proposal_id: str) -> None:
        with self._lock, self._write_scope():
            self._conn.execute(
                "UPDATE mutation_review_bridge_state SET bridge_sync_pending = 0 WHERE proposal_id = ?", (proposal_id,)
            )
            self._mutation_review_audit(proposal_id, "BRIDGE_RECONCILED", None, {})

    def _row_to_atom(self, row: sqlite3.Row) -> MemoryAtom:
        source_refs = [source_ref_from_dict(item) for item in json.loads(row["source_refs_json"] or "[]")]
        entities = [str(item) for item in json.loads(row["entities_json"] or "[]")]
        topics = [str(item) for item in json.loads(row["topics_json"] or "[]")]
        return MemoryAtom(
            atom_id=str(row["atom_id"]),
            atom_type=AtomType(str(row["atom_type"])),
            canonical_text=str(row["canonical_text"]),
            source_refs=source_refs,
            entities=entities,
            topics=topics,
            confidence=float(row["confidence"]),
            salience=float(row["salience"]),
            salience_half_life_days=int(row["salience_half_life_days"]),
            last_reinforced_at=datetime.fromisoformat(row["last_reinforced_at"]) if row["last_reinforced_at"] else None,
            support_count=int(row["support_count"]),
            contradiction_count=int(row["contradiction_count"]),
            status=AtomStatus(str(row["status"])),
            version_of=str(row["version_of"]) if row["version_of"] else None,
            tombstoned_at=datetime.fromisoformat(row["tombstoned_at"]) if row["tombstoned_at"] else None,
            purge_after=datetime.fromisoformat(row["purge_after"]) if row["purge_after"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _row_to_recognition(row: sqlite3.Row) -> RecognitionRecord:
        return RecognitionRecord(
            event_id=str(row["event_id"]),
            atom_id=str(row["atom_id"]),
            recognized=bool(int(row["recognized"])),
            score=float(row["score"]),
            query_text=str(row["query_text"]),
            timestamp=datetime.fromisoformat(str(row["timestamp"])),
        )

    def add_candidate(
        self,
        candidate: CandidateAtom,
        *,
        reason: str = "extractor_add",
        atom_id: str | None = None,
    ) -> MemoryAtom:
        now = self._now()
        key = AtomStore._dedupe_key(
            atom_type=candidate.atom_type,
            canonical_text=candidate.canonical_text,
            entities=candidate.entities,
            topics=candidate.topics,
        )
        with self._lock, self._write_scope():
            if atom_id:
                persisted = self._conn.execute("SELECT * FROM atoms WHERE atom_id = ?", (atom_id,)).fetchone()
                if persisted is not None:
                    return self._row_to_atom(persisted)
            row = self._conn.execute("SELECT atom_id FROM atoms WHERE dedupe_key = ?", (key,)).fetchone()
            if row is None:
                atom = MemoryAtom(
                    atom_id=atom_id or f"mem_{uuid4().hex}",
                    atom_type=candidate.atom_type,
                    canonical_text=candidate.canonical_text.strip(),
                    source_refs=list(candidate.source_refs),
                    entities=list(candidate.entities),
                    topics=list(candidate.topics),
                    confidence=candidate.confidence,
                    salience=candidate.salience,
                    salience_half_life_days=half_life_days_for_atom_type(
                        base_half_life_days=self.salience_half_life_days,
                        atom_type=candidate.atom_type,
                    ),
                    last_reinforced_at=now,
                    created_at=now,
                    updated_at=now,
                )
                self._conn.execute(
                    """
                    INSERT INTO atoms (
                        atom_id, atom_type, canonical_text, source_refs_json, entities_json, topics_json,
                        confidence, salience, salience_half_life_days, last_reinforced_at, support_count,
                        contradiction_count, status, version_of, tombstoned_at, purge_after, created_at, updated_at, dedupe_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        atom.atom_id,
                        atom.atom_type.value,
                        atom.canonical_text,
                        json.dumps([contract_to_dict(ref) for ref in atom.source_refs], ensure_ascii=False),
                        json.dumps(atom.entities, ensure_ascii=False),
                        json.dumps(atom.topics, ensure_ascii=False),
                        atom.confidence,
                        atom.salience,
                        atom.salience_half_life_days,
                        atom.last_reinforced_at.isoformat() if atom.last_reinforced_at else None,
                        atom.support_count,
                        atom.contradiction_count,
                        atom.status.value,
                        atom.version_of,
                        atom.tombstoned_at.isoformat() if atom.tombstoned_at else None,
                        atom.purge_after.isoformat() if atom.purge_after else None,
                        atom.created_at.isoformat(),
                        atom.updated_at.isoformat(),
                        key,
                    ),
                )
                self.ledger.append(
                    ProvenanceEvent(
                        event_id=f"evt_{uuid4().hex}",
                        event_type=EventType.ADD,
                        atom_id=atom.atom_id,
                        timestamp=now,
                        source_refs=list(candidate.source_refs),
                        reason=reason,
                    )
                )
                return atom

            existing_row = self._conn.execute("SELECT * FROM atoms WHERE atom_id = ?", (str(row["atom_id"]),)).fetchone()
            if existing_row is None:
                raise KeyError(str(row["atom_id"]))
            atom = self._row_to_atom(existing_row)
            atom.source_refs.extend(candidate.source_refs)
            atom.support_count += 1
            atom.last_reinforced_at = now
            atom.updated_at = now
            atom.confidence = max(atom.confidence, candidate.confidence)
            atom.salience = max(atom.salience, candidate.salience)
            self._conn.execute(
                """
                UPDATE atoms
                SET source_refs_json = ?, support_count = ?, last_reinforced_at = ?, updated_at = ?, confidence = ?, salience = ?
                WHERE atom_id = ?
                """,
                (
                    json.dumps([contract_to_dict(ref) for ref in atom.source_refs], ensure_ascii=False),
                    atom.support_count,
                    atom.last_reinforced_at.isoformat() if atom.last_reinforced_at else None,
                    atom.updated_at.isoformat(),
                    atom.confidence,
                    atom.salience,
                    atom.atom_id,
                ),
            )
            self.ledger.append(
                ProvenanceEvent(
                    event_id=f"evt_{uuid4().hex}",
                    event_type=EventType.REINFORCE,
                    atom_id=atom.atom_id,
                    timestamp=now,
                    source_refs=list(candidate.source_refs),
                    reason=reason,
                )
            )
            return atom

    def get_atom(self, atom_id: str) -> MemoryAtom:
        with self._lock:
            row = self._conn.execute("SELECT * FROM atoms WHERE atom_id = ?", (atom_id,)).fetchone()
        if row is None:
            raise KeyError(atom_id)
        return self._row_to_atom(row)

    def list_atoms(self) -> list[MemoryAtom]:
        with self._lock:
            # Use indexed ordering to avoid temp-sort failures on large stores.
            rows = self._conn.execute("SELECT * FROM atoms ORDER BY updated_at ASC").fetchall()
        return [self._row_to_atom(row) for row in rows]

    def record_raw_turn(self, turn: NormalizedTurn) -> RawContextTurn:
        source_id = str(turn.source_id or "").strip()
        message_id = str(turn.message_id or "").strip() or None
        sequence_index = int(turn.sequence_index if turn.sequence_index is not None else 0)
        turn_key = f"{source_id}|{message_id or ''}|{sequence_index}"
        record = RawContextTurn(
            source_id=source_id,
            conversation_id=str(turn.conversation_id or "").strip() or None,
            message_id=message_id,
            sequence_index=sequence_index,
            role=str(turn.role or "").strip().lower(),
            quote_text=str(turn.quote_text if turn.quote_text is not None else turn.text),
            timestamp=turn.timestamp,
        )
        with self._lock, self._write_scope():
            self._conn.execute(
                """
                INSERT INTO raw_context_turns (
                    turn_key, source_id, conversation_id, message_id, sequence_index, role, quote_text, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(turn_key) DO UPDATE SET
                    conversation_id = excluded.conversation_id,
                    message_id = excluded.message_id,
                    sequence_index = excluded.sequence_index,
                    role = excluded.role,
                    quote_text = excluded.quote_text,
                    timestamp = excluded.timestamp
                """,
                (
                    turn_key,
                    record.source_id,
                    record.conversation_id,
                    record.message_id,
                    record.sequence_index,
                    record.role,
                    record.quote_text,
                    record.timestamp.isoformat() if record.timestamp else None,
                ),
            )
        return record

    def fetch_raw_context_slice(
        self,
        source_id: str,
        *,
        message_id: str | None = None,
        sequence_index: int | None = None,
        before: int = 1,
        after: int = 1,
        max_turns: int = 3,
        max_chars: int = 1200,
    ) -> list[RawContextTurn]:
        source_key = str(source_id or "").strip()
        if not source_key:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT source_id, conversation_id, message_id, sequence_index, role, quote_text, timestamp
                FROM raw_context_turns
                WHERE source_id = ?
                ORDER BY sequence_index ASC
                """,
                (source_key,),
            ).fetchall()
        if not rows:
            return []
        turns = [
            RawContextTurn(
                source_id=str(row["source_id"]),
                conversation_id=str(row["conversation_id"] or "").strip() or None,
                message_id=str(row["message_id"] or "").strip() or None,
                sequence_index=int(row["sequence_index"]),
                role=str(row["role"]),
                quote_text=str(row["quote_text"]),
                timestamp=datetime.fromisoformat(str(row["timestamp"])) if row["timestamp"] else None,
            )
            for row in rows
        ]
        center = None
        target_message_id = str(message_id or "").strip() or None
        if target_message_id is not None:
            for idx, row in enumerate(turns):
                if row.message_id == target_message_id:
                    center = idx
                    break
        if center is None and sequence_index is not None:
            for idx, row in enumerate(turns):
                if row.sequence_index == int(sequence_index):
                    center = idx
                    break
        if center is None:
            return []
        start = max(0, center - max(0, int(before)))
        end = min(len(turns), center + max(0, int(after)) + 1)
        window = turns[start:end][: max(1, int(max_turns))]
        bounded: list[RawContextTurn] = []
        chars_used = 0
        budget = max(1, int(max_chars))
        for row in window:
            text = str(row.quote_text or "")
            remaining = budget - chars_used
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[: max(1, remaining - 1)].rstrip() + "…"
            bounded.append(
                RawContextTurn(
                    source_id=row.source_id,
                    conversation_id=row.conversation_id,
                    message_id=row.message_id,
                    sequence_index=row.sequence_index,
                    role=row.role,
                    quote_text=text,
                    timestamp=row.timestamp,
                )
            )
            chars_used += len(text)
        return bounded

    def supersede_atom(
        self,
        atom_id: str,
        replacement: CandidateAtom,
        *,
        reason: str = "manual_update",
        replacement_atom_id: str | None = None,
    ) -> MemoryAtom:
        old = self.get_atom(atom_id)
        replacement_key = AtomStore._dedupe_key(
            atom_type=replacement.atom_type,
            canonical_text=replacement.canonical_text,
            entities=replacement.entities,
            topics=replacement.topics,
        )
        with self._lock:
            target_key_row = self._conn.execute(
                "SELECT dedupe_key FROM atoms WHERE atom_id = ?",
                (old.atom_id,),
            ).fetchone()
        if target_key_row is not None and str(target_key_row["dedupe_key"]) == replacement_key:
            raise ValueError("replacement must differ from target")
        now = self._now()
        with self._lock, self._write_scope():
            self._conn.execute(
                "UPDATE atoms SET status = ?, updated_at = ? WHERE atom_id = ?",
                (AtomStatus.SUPERSEDED.value, now.isoformat(), old.atom_id),
            )
            replacement_atom = self.add_candidate(replacement, reason=reason, atom_id=replacement_atom_id)
            replacement_atom.version_of = old.atom_id
            replacement_atom.updated_at = self._now()
            self._conn.execute(
                "UPDATE atoms SET version_of = ?, updated_at = ? WHERE atom_id = ?",
                (replacement_atom.version_of, replacement_atom.updated_at.isoformat(), replacement_atom.atom_id),
            )
            self.ledger.append(
                ProvenanceEvent(
                    event_id=f"evt_{uuid4().hex}",
                    event_type=EventType.SUPERSEDE,
                    atom_id=old.atom_id,
                    timestamp=self._now(),
                    source_refs=list(replacement.source_refs),
                    reason=reason,
                    metadata={"replacement_atom_id": replacement_atom.atom_id},
                )
            )
        return replacement_atom

    def mark_conflict(self, left_atom_id: str, right_atom_id: str, *, reason: str) -> ContradictionEdge:
        if left_atom_id == right_atom_id:
            raise ValueError("conflict requires two distinct atom ids")
        left = self.get_atom(left_atom_id)
        right = self.get_atom(right_atom_id)
        now = self._now()
        with self._lock, self._write_scope():
            self._conn.execute(
                "UPDATE atoms SET status = ?, contradiction_count = contradiction_count + 1, updated_at = ? WHERE atom_id = ?",
                (AtomStatus.CONFLICTED.value, now.isoformat(), left.atom_id),
            )
            self._conn.execute(
                "UPDATE atoms SET status = ?, contradiction_count = contradiction_count + 1, updated_at = ? WHERE atom_id = ?",
                (AtomStatus.CONFLICTED.value, now.isoformat(), right.atom_id),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO conflicts (left_atom_id, right_atom_id, created_at, reason) VALUES (?, ?, ?, ?)",
                (left_atom_id, right_atom_id, now.isoformat(), reason),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO conflicts (left_atom_id, right_atom_id, created_at, reason) VALUES (?, ?, ?, ?)",
                (right_atom_id, left_atom_id, now.isoformat(), reason),
            )

        edge = ContradictionEdge(
            left_atom_id=left_atom_id,
            right_atom_id=right_atom_id,
            created_at=now,
            reason=reason,
        )
        self.ledger.append(
            ProvenanceEvent(
                event_id=f"evt_{uuid4().hex}",
                event_type=EventType.CONFLICT,
                atom_id=left_atom_id,
                timestamp=now,
                source_refs=[],
                reason=reason,
                metadata={"other_atom_id": right_atom_id},
            )
        )
        return edge

    def conflict_neighbors(self, atom_id: str) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT right_atom_id FROM conflicts WHERE left_atom_id = ? ORDER BY right_atom_id ASC",
                (atom_id,),
            ).fetchall()
        return {str(row["right_atom_id"]) for row in rows}

    def conflict_map(self) -> dict[str, set[str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT left_atom_id, right_atom_id FROM conflicts ORDER BY left_atom_id ASC, right_atom_id ASC"
            ).fetchall()
        graph: dict[str, set[str]] = {}
        for row in rows:
            left = str(row["left_atom_id"])
            right = str(row["right_atom_id"])
            graph.setdefault(left, set()).add(right)
        return graph

    def cache_scope(self) -> str:
        return self._cache_scope_id

    def cache_token(self) -> tuple[object, ...]:
        with self._lock:
            atom_row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS atom_count,
                    COALESCE(MAX(updated_at), '') AS atom_updated_at_max
                FROM atoms
                """
            ).fetchone()
            conflict_row = self._conn.execute("SELECT COUNT(*) AS conflict_count FROM conflicts").fetchone()
            shared_row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS shared_key_count,
                    COALESCE(MAX(updated_at), '') AS shared_updated_at_max
                FROM shared_language_keys
                """
            ).fetchone()
            provenance_row = self._conn.execute(
                "SELECT COUNT(*) AS provenance_count FROM provenance_events"
            ).fetchone()
            raw_context_row = self._conn.execute(
                "SELECT COUNT(*) AS raw_turn_count, COALESCE(MAX(sequence_index), -1) AS raw_turn_max_seq FROM raw_context_turns"
            ).fetchone()
        return (
            "sqlite-atom-store-cache-v2",
            self._cache_scope_id,
            int(atom_row["atom_count"] if atom_row is not None else 0),
            int(conflict_row["conflict_count"] if conflict_row is not None else 0),
            int(shared_row["shared_key_count"] if shared_row is not None else 0),
            str(atom_row["atom_updated_at_max"] if atom_row is not None else ""),
            str(shared_row["shared_updated_at_max"] if shared_row is not None else ""),
            int(raw_context_row["raw_turn_count"] if raw_context_row is not None else 0),
            int(raw_context_row["raw_turn_max_seq"] if raw_context_row is not None else -1),
            int(provenance_row["provenance_count"] if provenance_row is not None else 0),
        )

    def tombstone_atom(
        self,
        atom_id: str,
        *,
        reason: str,
        retention_days: int = 30,
    ) -> MemoryAtom:
        if retention_days < 0:
            raise ValueError("retention_days must be >= 0")
        atom = self.get_atom(atom_id)
        now = self._now()
        purge_after = now + timedelta(days=retention_days)
        with self._lock, self._write_scope():
            self._conn.execute(
                """
                UPDATE atoms
                SET status = ?, tombstoned_at = ?, purge_after = ?, updated_at = ?
                WHERE atom_id = ?
                """,
                (
                    AtomStatus.TOMBSTONED.value,
                    now.isoformat(),
                    purge_after.isoformat(),
                    now.isoformat(),
                    atom.atom_id,
                ),
            )
        self.ledger.append(
            ProvenanceEvent(
                event_id=f"evt_{uuid4().hex}",
                event_type=EventType.TOMBSTONE,
                atom_id=atom.atom_id,
                timestamp=now,
                source_refs=[],
                reason=reason,
                metadata={"retention_days": str(retention_days)},
            )
        )
        return self.get_atom(atom_id)

    def purge_due_atoms(self, *, now: Optional[datetime] = None) -> list[str]:
        as_of = now or self._now()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT atom_id
                FROM atoms
                WHERE status = ?
                  AND purge_after IS NOT NULL
                  AND purge_after <= ?
                ORDER BY atom_id ASC
                """,
                (AtomStatus.TOMBSTONED.value, as_of.isoformat()),
            ).fetchall()
        to_purge = [str(row["atom_id"]) for row in rows]
        if not to_purge:
            return []

        with self._lock, self._conn:
            for atom_id in to_purge:
                self._conn.execute("DELETE FROM conflicts WHERE left_atom_id = ? OR right_atom_id = ?", (atom_id, atom_id))
                self._conn.execute("DELETE FROM atoms WHERE atom_id = ?", (atom_id,))
                self.ledger.append(
                    ProvenanceEvent(
                        event_id=f"evt_{uuid4().hex}",
                        event_type=EventType.PURGE,
                        atom_id=atom_id,
                        timestamp=as_of,
                        source_refs=[],
                        reason="retention_elapsed",
                    )
                )
        return to_purge

    def upsert_shared_language_key(
        self,
        *,
        phrase: str,
        atom_ids: list[str],
        aliases: list[str] | None = None,
        domains: list[str] | None = None,
        support_count: int = 1,
        weight: float = 0.8,
        confidence: float = 0.8,
        curated: bool = False,
        key_id: str | None = None,
    ) -> dict[str, Any]:
        """Create/update shared-language key and enforce atom provenance links."""

        normalized = phrase.strip().lower()
        if not normalized:
            raise ValueError("phrase is required")
        linked_ids = sorted({str(item).strip() for item in atom_ids if str(item).strip()})
        if not linked_ids:
            raise ValueError("atom_ids is required")

        with self._lock:
            for atom_id in linked_ids:
                row = self._conn.execute("SELECT atom_id FROM atoms WHERE atom_id = ?", (atom_id,)).fetchone()
                if row is None:
                    raise ValueError(f"unknown atom ids: {atom_id}")

        now = self._now().isoformat()
        aliases_norm = sorted({item.strip() for item in (aliases or []) if item and item.strip()})
        domains_norm = sorted({item.strip().lower() for item in (domains or []) if item and item.strip()})

        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT key_id, created_at FROM shared_language_keys WHERE phrase_norm = ?",
                (normalized,),
            ).fetchone()
            resolved_key_id = str(existing["key_id"]) if existing is not None else (key_id or f"slk_{uuid4().hex[:12]}")
            created_at = str(existing["created_at"]) if existing is not None else now
            self._conn.execute(
                """
                INSERT INTO shared_language_keys (
                    key_id, phrase, phrase_norm, aliases_json, domains_json, support_count,
                    weight, confidence, curated, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_id) DO UPDATE SET
                    phrase = excluded.phrase,
                    phrase_norm = excluded.phrase_norm,
                    aliases_json = excluded.aliases_json,
                    domains_json = excluded.domains_json,
                    support_count = excluded.support_count,
                    weight = excluded.weight,
                    confidence = excluded.confidence,
                    curated = excluded.curated,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_key_id,
                    phrase.strip(),
                    normalized,
                    json.dumps(aliases_norm, ensure_ascii=False),
                    json.dumps(domains_norm, ensure_ascii=False),
                    max(1, int(support_count)),
                    max(0.0, min(1.0, float(weight))),
                    max(0.0, min(1.0, float(confidence))),
                    1 if curated else 0,
                    created_at,
                    now,
                ),
            )
            self._conn.execute("DELETE FROM shared_language_links WHERE key_id = ?", (resolved_key_id,))
            for atom_id in linked_ids:
                self._conn.execute(
                    "INSERT INTO shared_language_links (key_id, atom_id) VALUES (?, ?)",
                    (resolved_key_id, atom_id),
                )

        return {
            "key_id": resolved_key_id,
            "phrase": phrase.strip(),
            "atom_ids": linked_ids,
            "aliases": aliases_norm,
            "domains": domains_norm,
            "support_count": max(1, int(support_count)),
            "weight": max(0.0, min(1.0, float(weight))),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "curated": bool(curated),
            "created_at": created_at,
            "updated_at": now,
        }

    def list_shared_language_keys(self) -> list[dict[str, Any]]:
        """Return shared-language keys in stable order."""

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT key_id, phrase, aliases_json, domains_json, support_count, weight, confidence, curated, created_at, updated_at
                FROM shared_language_keys
                ORDER BY updated_at DESC, key_id ASC
                """
            ).fetchall()
            links = self._conn.execute(
                "SELECT key_id, atom_id FROM shared_language_links ORDER BY key_id ASC, atom_id ASC"
            ).fetchall()

        by_key: dict[str, list[str]] = {}
        for row in links:
            key_id = str(row["key_id"])
            by_key.setdefault(key_id, []).append(str(row["atom_id"]))

        payload: list[dict[str, Any]] = []
        for row in rows:
            key_id = str(row["key_id"])
            payload.append(
                {
                    "key_id": key_id,
                    "phrase": str(row["phrase"]),
                    "atom_ids": by_key.get(key_id, []),
                    "aliases": [str(item) for item in json.loads(row["aliases_json"] or "[]")],
                    "domains": [str(item) for item in json.loads(row["domains_json"] or "[]")],
                    "support_count": int(row["support_count"]),
                    "weight": float(row["weight"]),
                    "confidence": float(row["confidence"]),
                    "curated": bool(row["curated"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
            )
        return payload

    def record_recognition_event(
        self,
        *,
        atom_id: str,
        recognized: bool,
        score: float,
        query_text: str,
        timestamp: Optional[datetime] = None,
    ) -> RecognitionRecord:
        """Persist one recognition event for salience/decay feedback."""

        with self._lock:
            row = self._conn.execute("SELECT atom_id FROM atoms WHERE atom_id = ?", (atom_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown atom id: {atom_id}")

        event = RecognitionRecord(
            event_id=f"rec_{uuid4().hex}",
            atom_id=atom_id,
            recognized=bool(recognized),
            score=max(0.0, min(1.0, float(score))),
            query_text=str(query_text or "").strip(),
            timestamp=timestamp or self._now(),
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO recognition_events (
                    event_id, atom_id, recognized, score, query_text, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.atom_id,
                    1 if event.recognized else 0,
                    event.score,
                    event.query_text,
                    event.timestamp.isoformat(),
                ),
            )
        return event

    def list_recognition_events(
        self,
        *,
        atom_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[RecognitionRecord]:
        """Return recognition events ordered by timestamp ascending."""

        base_query = "SELECT event_id, atom_id, recognized, score, query_text, timestamp FROM recognition_events"
        params: list[Any] = []
        where_clause = ""
        if atom_id is not None:
            where_clause = " WHERE atom_id = ?"
            params.append(atom_id)
        if limit is not None and limit >= 0:
            query = f"{base_query}{where_clause} ORDER BY timestamp DESC LIMIT ?"
            params.append(int(limit))
            with self._lock:
                rows = self._conn.execute(query, tuple(params)).fetchall()
            rows = list(reversed(rows))
            return [self._row_to_recognition(row) for row in rows]
        query = f"{base_query}{where_clause} ORDER BY timestamp ASC"
        with self._lock:
            rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_recognition(row) for row in rows]

    def recognition_bias(self, atom_id: str, *, window: int = 16) -> float:
        """Return signed recognition bias in [-1, 1] for one atom."""

        events = self.list_recognition_events(atom_id=atom_id, limit=max(1, int(window)))
        if not events:
            return 0.0
        signed = [(event.score if event.recognized else -event.score) for event in events]
        return max(-1.0, min(1.0, sum(signed) / len(signed)))

    def recognition_stats(self) -> dict[str, float]:
        """Return aggregate recognition metrics for diagnostics surfaces."""

        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN recognized = 1 THEN 1 ELSE 0 END) AS yes_count
                FROM recognition_events
                """
            ).fetchone()
        total = int(row["total"] or 0)
        recognized = int(row["yes_count"] or 0)
        unrecognized = max(0, total - recognized)
        return {
            "events": float(total),
            "recognized": float(recognized),
            "unrecognized": float(unrecognized),
            "recognized_rate": (recognized / total) if total else 0.0,
        }
