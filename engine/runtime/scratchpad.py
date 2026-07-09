from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import quantiles
from typing import Any, Iterator

from ..config import WorkSessionScratchpadPolicy

SCRATCHPAD_ENTRY_KINDS = {"tool_result", "decision", "blocker", "task_state", "operator_note"}
SCRATCHPAD_STATUSES = {"active", "archived", "expired", "degraded"}
STRICT_SCOPE_MODE = "strict"
DEGRADED_SCOPE_MODE = "degraded"
DISABLED_SCOPE_MODE = "disabled"

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
LOGGER = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def estimate_context_tokens(payload: Any) -> int:
    """Deterministic token estimate for context-diet comparisons; not a billing tokenizer."""

    if payload is None:
        return 0
    if isinstance(payload, (dict, list, tuple)):
        text = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    else:
        text = str(payload or "")
    return len(_TOKEN_RE.findall(text))


def _p95(values: Sequence[float]) -> float:
    clean = sorted(max(0.0, float(value)) for value in values)
    if not clean:
        return 0.0
    if len(clean) == 1:
        return clean[0]
    return float(quantiles(clean, n=20, method="inclusive")[18])


def evaluate_context_diet_fixture(
    *,
    baseline_prompt: Any,
    scratchpad_assisted_prompt: Any,
    work_session_context: Mapping[str, Any],
    expected_resume_state: Mapping[str, Any],
    actual_resume_state: Mapping[str, Any],
    repeated_reread_steps: Sequence[Any] = (),
    false_memory_behavior_unchanged: bool,
    package_build_latencies_ms: Sequence[float] = (),
    latency_budget_ms: float | None = None,
) -> dict[str, Any]:
    """Evaluate a fixed long-session context-diet fixture without overclaiming savings."""

    baseline_tokens = estimate_context_tokens(baseline_prompt)
    assisted_tokens = estimate_context_tokens(scratchpad_assisted_prompt)
    injected_tokens = estimate_context_tokens(dict(work_session_context))
    p95_latency = _p95(package_build_latencies_ms)
    latency_within_budget = True if latency_budget_ms is None else p95_latency <= float(latency_budget_ms)
    resume_fidelity_pass = dict(expected_resume_state) == dict(actual_resume_state) and bool(
        false_memory_behavior_unchanged
    )
    fewer_prompt_tokens = assisted_tokens < baseline_tokens
    return {
        "observed_package_tokens": int(assisted_tokens),
        "observed_injected_tokens": int(injected_tokens),
        "hypothetical_prompt_tokens_replaced": max(0, int(baseline_tokens - assisted_tokens)),
        "repeat_reread_avoided_count": len(list(repeated_reread_steps)) if resume_fidelity_pass else 0,
        "resume_fidelity_pass": bool(resume_fidelity_pass),
        "baseline_prompt_tokens": int(baseline_tokens),
        "scratchpad_assisted_prompt_tokens": int(assisted_tokens),
        "fewer_prompt_tokens": bool(fewer_prompt_tokens),
        "p95_package_build_latency_ms": round(float(p95_latency), 3),
        "latency_budget_ms": None if latency_budget_ms is None else float(latency_budget_ms),
        "latency_within_budget": bool(latency_within_budget),
        "context_diet_fixture_pass": bool(fewer_prompt_tokens and resume_fidelity_pass and latency_within_budget),
    }


def _compact_text(text: str, *, max_chars: int) -> str:
    compact = " ".join(str(text or "").strip().split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "..."


def _safe_id(value: str, *, fallback: str) -> str:
    token = _SAFE_ID_RE.sub("_", str(value or "").strip()).strip("._-")
    return token[:96] or fallback


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalize_windows_local_path_text(value: str) -> str:
    text = str(value or "").strip()
    lower = text.lower()
    if lower.startswith("\\\\?\\unc\\"):
        return "\\\\" + text[8:]
    if len(text) >= 7 and lower.startswith("\\\\?\\") and text[4:6].endswith(":"):
        return text[4:]
    return text


def _drive_token(path: Path) -> str:
    drive = str(path.drive or "").casefold()
    if drive.startswith("\\\\?\\") and len(drive) >= 6 and drive[4:6].endswith(":"):
        return drive[4:]
    return drive


def _has_drive_change(candidate: Path, expected_drive: str) -> bool:
    drive = _drive_token(candidate)
    return bool(expected_drive and drive and drive != expected_drive)


def resolve_scratchpad_root(project_root: str | Path, runtime_state_root: str | Path | None = None) -> Path:
    """Resolve the project-local scratchpad root and fail closed on unsafe roots."""

    project = Path(_normalize_windows_local_path_text(str(project_root))).expanduser().resolve()
    runtime_boundary = (project / "runtime").resolve()
    runtime_root_raw = runtime_state_root or os.environ.get("MNO_RUNTIME_STATE_ROOT") or runtime_boundary
    runtime_root_text = _normalize_windows_local_path_text(str(runtime_root_raw or ""))
    if runtime_root_text.startswith("\\\\"):
        raise ValueError("scratchpad runtime root must not be a UNC path")
    runtime_root = Path(runtime_root_text).expanduser().resolve()
    expected_drive = _drive_token(project)
    if _has_drive_change(runtime_root, expected_drive):
        raise ValueError("scratchpad runtime root must stay on the project drive")
    if not _is_relative_to(runtime_root, runtime_boundary):
        raise ValueError("scratchpad runtime root must stay inside the project runtime boundary")
    root = (runtime_root / "scratchpads").resolve()
    if _has_drive_change(root, expected_drive):
        raise ValueError("scratchpad root must stay on the project drive")
    if str(root).startswith("\\\\"):
        raise ValueError("scratchpad root must not be a UNC path")
    if not _is_relative_to(root, runtime_boundary):
        raise ValueError("scratchpad root must stay inside the project runtime boundary")
    return root


@dataclass(frozen=True, slots=True)
class WorkSessionScope:
    scope_id: str
    project_id: str
    thread_id: str
    session_id: str
    workstream_key: str
    workstream_name: str
    runtime_store_fingerprint: str
    scope_mode: str
    status: str
    warnings: tuple[str, ...] = ()

    @property
    def can_inject(self) -> bool:
        return self.scope_mode == STRICT_SCOPE_MODE and self.status == "active"


@dataclass(frozen=True, slots=True)
class ScratchpadEntry:
    entry_id: str
    scope_id: str
    kind: str
    summary: str
    raw_ref: str
    raw_ref_sha256: str
    replaceability_score: float
    token_estimate: int
    status: str
    degraded: bool
    metadata: dict[str, Any]


def build_diagnostic_task_map(scope: WorkSessionScope, entries: Sequence[ScratchpadEntry]) -> dict[str, Any]:
    """Render deterministic diagnostics only; never synthesize with an LLM."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    unmapped_entries: list[str] = []
    known_ids = {str(entry.entry_id) for entry in entries}
    for entry in sorted(entries, key=lambda item: (item.kind, item.entry_id)):
        metadata = dict(entry.metadata or {})
        task_id = str(metadata.get("task_id") or "").strip()
        node_id = _safe_id(task_id or entry.entry_id, fallback=entry.entry_id)
        if not task_id:
            unmapped_entries.append(entry.entry_id)
        nodes.append(
            {
                "node_id": node_id,
                "entry_ids": [entry.entry_id],
                "kind": entry.kind,
                "status": entry.status,
                "summary": entry.summary,
                "mapped": bool(task_id),
                "degraded": bool(entry.degraded),
            }
        )
        depends_on = metadata.get("depends_on_entry_ids") or ()
        if isinstance(depends_on, str):
            depends_iter = [depends_on]
        elif isinstance(depends_on, Sequence):
            depends_iter = list(depends_on)
        else:
            depends_iter = []
        for dependency in depends_iter:
            source = str(dependency or "").strip()
            if source and source in known_ids:
                edges.append({"from_entry_id": source, "to_entry_id": entry.entry_id})
    return {
        "memory_layer": "scratchpad",
        "render_mode": "deterministic",
        "scope": {
            "scope_id": scope.scope_id,
            "project_id": scope.project_id,
            "thread_id": scope.thread_id,
            "session_id": scope.session_id,
            "workstream_key": scope.workstream_key,
            "scope_mode": scope.scope_mode,
        },
        "nodes": nodes,
        "edges": sorted(edges, key=lambda item: (item["from_entry_id"], item["to_entry_id"])),
        "unmapped_entries": sorted(unmapped_entries),
    }


def resolve_scope(
    *,
    project_id: str,
    thread_id: str,
    session_id: str,
    workstream_key: str,
    workstream_name: str = "",
    runtime_store_fingerprint: str,
) -> WorkSessionScope:
    warnings: list[str] = []
    project = str(project_id or "").strip()
    session = str(session_id or "").strip()
    thread = str(thread_id or "").strip()
    workstream = str(workstream_key or "").strip()
    fingerprint = str(runtime_store_fingerprint or "").strip()
    if not project or not session:
        return WorkSessionScope(
            scope_id="",
            project_id=project,
            thread_id=thread,
            session_id=session,
            workstream_key=workstream,
            workstream_name=str(workstream_name or workstream).strip(),
            runtime_store_fingerprint=fingerprint,
            scope_mode=DISABLED_SCOPE_MODE,
            status="degraded",
            warnings=("missing_project_or_session_identity",),
        )
    if not thread:
        warnings.append("missing_thread_id")
    if not workstream:
        warnings.append("missing_workstream_key")
    if not fingerprint:
        warnings.append("missing_runtime_store_fingerprint")
    scope_mode = DEGRADED_SCOPE_MODE if warnings else STRICT_SCOPE_MODE
    thread_for_id = thread or "thread_degraded"
    workstream_for_id = workstream or "workstream_degraded"
    fingerprint_for_id = fingerprint or "fingerprint_degraded"
    token = "|".join((project, thread_for_id, session, workstream_for_id, fingerprint_for_id))
    scope_id = "wps_" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
    return WorkSessionScope(
        scope_id=scope_id,
        project_id=project,
        thread_id=thread,
        session_id=session,
        workstream_key=workstream,
        workstream_name=str(workstream_name or workstream or "degraded").strip(),
        runtime_store_fingerprint=fingerprint,
        scope_mode=scope_mode,
        status="active" if scope_mode == STRICT_SCOPE_MODE else "degraded",
        warnings=tuple(warnings),
    )


def can_resume_scope(
    previous: WorkSessionScope,
    current: WorkSessionScope,
    *,
    explicit_resume: bool,
    policy: WorkSessionScratchpadPolicy,
) -> bool:
    if not (bool(explicit_resume) or bool(policy.resume_injection_enabled)):
        return False
    if previous.scope_mode != STRICT_SCOPE_MODE or current.scope_mode != STRICT_SCOPE_MODE:
        return False
    return (
        previous.project_id == current.project_id
        and previous.thread_id == current.thread_id
        and previous.workstream_key == current.workstream_key
        and previous.runtime_store_fingerprint == current.runtime_store_fingerprint
    )


class WorkSessionScratchpadStore:
    _SCHEMA_TABLES = frozenset({"scratchpad_scopes", "scratchpad_entries"})

    def __init__(
        self,
        *,
        project_root: str | Path,
        policy: WorkSessionScratchpadPolicy,
        runtime_state_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.policy = policy
        self.root = resolve_scratchpad_root(self.project_root, runtime_state_root)
        self.db_path = self.root / "scratchpads.sqlite3"
        self.refs_root = self.root / "refs"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.refs_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS scratchpad_scopes(
                  scope_id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL,
                  thread_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  workstream_key TEXT NOT NULL,
                  workstream_name TEXT NOT NULL,
                  runtime_store_fingerprint TEXT NOT NULL,
                  scope_mode TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  expires_at TEXT,
                  metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scratchpad_entries(
                  entry_id TEXT PRIMARY KEY,
                  scope_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  raw_ref TEXT NOT NULL DEFAULT '',
                  raw_ref_sha256 TEXT NOT NULL DEFAULT '',
                  source_turn_id TEXT NOT NULL DEFAULT '',
                  source_tool_call_id TEXT NOT NULL DEFAULT '',
                  ingress_kind TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  summary_mode TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  verified_raw_ref_present INTEGER NOT NULL DEFAULT 0,
                  replaceability_score REAL NOT NULL DEFAULT 0.0,
                  token_estimate INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL,
                  degraded INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  expires_at TEXT,
                  metadata_json TEXT NOT NULL,
                  dedupe_key TEXT NOT NULL,
                  FOREIGN KEY(scope_id) REFERENCES scratchpad_scopes(scope_id)
                );
                CREATE INDEX IF NOT EXISTS idx_scratchpad_entries_scope_created
                  ON scratchpad_entries(scope_id, created_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_scratchpad_entries_scope_dedupe
                  ON scratchpad_entries(scope_id, dedupe_key);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_scope(self, scope: WorkSessionScope, *, metadata: dict[str, Any] | None = None) -> None:
        if not scope.scope_id:
            return
        self.initialize()
        now = utc_now_iso()
        expires = (datetime.now(timezone.utc) + timedelta(days=int(self.policy.retention_days))).isoformat()
        meta = dict(metadata or {})
        if scope.warnings:
            meta["warnings"] = list(scope.warnings)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scratchpad_scopes(
                  scope_id, project_id, thread_id, session_id, workstream_key, workstream_name,
                  runtime_store_fingerprint, scope_mode, status, created_at, updated_at, expires_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                  workstream_name = excluded.workstream_name,
                  scope_mode = excluded.scope_mode,
                  status = excluded.status,
                  updated_at = excluded.updated_at,
                  expires_at = excluded.expires_at,
                  metadata_json = excluded.metadata_json
                """,
                (
                    scope.scope_id,
                    scope.project_id,
                    scope.thread_id,
                    scope.session_id,
                    scope.workstream_key,
                    scope.workstream_name,
                    scope.runtime_store_fingerprint,
                    scope.scope_mode,
                    scope.status,
                    now,
                    now,
                    expires,
                    _json_dumps(meta),
                ),
            )

    def add_entry(
        self,
        scope: WorkSessionScope,
        *,
        kind: str,
        summary: str = "",
        raw_content: str = "",
        source_turn_id: str = "",
        source_tool_call_id: str = "",
        ingress_kind: str = "explicit_metadata",
        source_kind: str = "work_state",
        summary_mode: str = "deterministic",
        created_by: str = "runtime",
        replaceability_score: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> ScratchpadEntry:
        if not scope.scope_id:
            raise ValueError("scratchpad scope is disabled")
        clean_kind = str(kind or "").strip()
        if clean_kind not in SCRATCHPAD_ENTRY_KINDS:
            raise ValueError(f"unsupported scratchpad entry kind: {kind}")
        score = max(0.0, min(1.0, float(replaceability_score or 0.0)))
        raw_text = str(raw_content or "")
        compact_summary = _compact_text(summary or raw_text, max_chars=700)
        if not compact_summary:
            raise ValueError("scratchpad summary or raw_content is required")
        dedupe_basis = "|".join((scope.scope_id, clean_kind, compact_summary, source_turn_id, source_tool_call_id))
        dedupe_key = hashlib.sha256(dedupe_basis.encode("utf-8")).hexdigest()
        entry_id = "sp_" + hashlib.sha256(f"{dedupe_key}|{scope.scope_id}".encode("utf-8")).hexdigest()[:32]
        degraded = False
        raw_ref = ""
        raw_sha = ""
        verified_raw = 0
        if raw_text:
            raw_bytes = raw_text.encode("utf-8")
            if len(raw_bytes) > int(self.policy.max_raw_ref_bytes):
                degraded = True
            else:
                try:
                    raw_ref, raw_sha = self._write_raw_ref(scope, entry_id, raw_bytes)
                    verified_raw = 1
                except Exception as exc:
                    LOGGER.warning("work-session scratchpad raw-ref write failed for entry %s: %s", entry_id, exc)
                    degraded = True
                    raw_ref = ""
                    raw_sha = ""
                    verified_raw = 0
        status = "degraded" if degraded else "active"
        now = utc_now_iso()
        expires = (datetime.now(timezone.utc) + timedelta(days=int(self.policy.retention_days))).isoformat()
        token_estimate = max(1, len(compact_summary.split()))
        self.upsert_scope(scope)
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scratchpad_entries(
                  entry_id, scope_id, kind, summary, raw_ref, raw_ref_sha256, source_turn_id,
                  source_tool_call_id, ingress_kind, source_kind, summary_mode, created_by,
                  verified_raw_ref_present, replaceability_score, token_estimate, status, degraded,
                  created_at, updated_at, expires_at, metadata_json, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_id, dedupe_key) DO UPDATE SET
                  summary = excluded.summary,
                  raw_ref = excluded.raw_ref,
                  raw_ref_sha256 = excluded.raw_ref_sha256,
                  verified_raw_ref_present = excluded.verified_raw_ref_present,
                  replaceability_score = excluded.replaceability_score,
                  token_estimate = excluded.token_estimate,
                  status = excluded.status,
                  degraded = excluded.degraded,
                  updated_at = excluded.updated_at,
                  expires_at = excluded.expires_at,
                  metadata_json = excluded.metadata_json
                """,
                (
                    entry_id,
                    scope.scope_id,
                    clean_kind,
                    compact_summary,
                    raw_ref,
                    raw_sha,
                    str(source_turn_id or ""),
                    str(source_tool_call_id or ""),
                    str(ingress_kind or "explicit_metadata"),
                    str(source_kind or "work_state"),
                    str(summary_mode or "deterministic"),
                    str(created_by or "runtime"),
                    verified_raw,
                    score,
                    token_estimate,
                    status,
                    1 if degraded else 0,
                    now,
                    now,
                    expires,
                    _json_dumps(dict(metadata or {})),
                    dedupe_key,
                ),
            )
        return ScratchpadEntry(
            entry_id=entry_id,
            scope_id=scope.scope_id,
            kind=clean_kind,
            summary=compact_summary,
            raw_ref=raw_ref,
            raw_ref_sha256=raw_sha,
            replaceability_score=score,
            token_estimate=token_estimate,
            status=status,
            degraded=degraded,
            metadata=dict(metadata or {}),
        )

    def _write_raw_ref(self, scope: WorkSessionScope, entry_id: str, raw_bytes: bytes) -> tuple[str, str]:
        scope_dir = (self.refs_root / _safe_id(scope.scope_id, fallback="scope")).resolve()
        if not _is_relative_to(scope_dir, self.refs_root.resolve()):
            raise ValueError("scratchpad raw ref escaped refs root")
        scope_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_id(entry_id, fallback="entry") + ".txt"
        target = (scope_dir / filename).resolve()
        if not _is_relative_to(target, scope_dir):
            raise ValueError("scratchpad raw ref escaped scope root")
        digest = hashlib.sha256(raw_bytes).hexdigest()
        target.write_bytes(raw_bytes)
        rel = target.relative_to(self.project_root).as_posix()
        return rel, digest

    def list_entries_for_injection(self, scope: WorkSessionScope) -> list[ScratchpadEntry]:
        if not scope.can_inject:
            return []
        self.initialize()
        min_score = float(self.policy.min_replaceability_score)
        limit = int(self.policy.max_entries_per_scope)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scratchpad_entries
                WHERE scope_id = ? AND status = 'active' AND replaceability_score >= ?
                ORDER BY created_at DESC, entry_id ASC
                LIMIT ?
                """,
                (scope.scope_id, min_score, limit),
            ).fetchall()
        out: list[ScratchpadEntry] = []
        for row in rows:
            out.append(
                ScratchpadEntry(
                    entry_id=str(row["entry_id"]),
                    scope_id=str(row["scope_id"]),
                    kind=str(row["kind"]),
                    summary=str(row["summary"]),
                    raw_ref=str(row["raw_ref"] or ""),
                    raw_ref_sha256=str(row["raw_ref_sha256"] or ""),
                    replaceability_score=float(row["replaceability_score"] or 0.0),
                    token_estimate=int(row["token_estimate"] or 0),
                    status=str(row["status"]),
                    degraded=bool(row["degraded"]),
                    metadata=json.loads(str(row["metadata_json"] or "{}")),
                )
            )
        return out

    def list_entries_for_resume_injection(self, scope: WorkSessionScope) -> list[ScratchpadEntry]:
        if not scope.can_inject:
            return []
        self.initialize()
        min_score = float(self.policy.min_replaceability_score)
        limit = int(self.policy.max_entries_per_scope)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.* FROM scratchpad_entries e
                JOIN scratchpad_scopes s ON s.scope_id = e.scope_id
                WHERE s.project_id = ?
                  AND s.thread_id = ?
                  AND s.workstream_key = ?
                  AND s.runtime_store_fingerprint = ?
                  AND s.scope_mode = 'strict'
                  AND s.status = 'active'
                  AND e.status = 'active'
                  AND e.replaceability_score >= ?
                ORDER BY e.created_at DESC, e.entry_id ASC
                LIMIT ?
                """,
                (
                    scope.project_id,
                    scope.thread_id,
                    scope.workstream_key,
                    scope.runtime_store_fingerprint,
                    min_score,
                    limit,
                ),
            ).fetchall()
        out: list[ScratchpadEntry] = []
        for row in rows:
            out.append(
                ScratchpadEntry(
                    entry_id=str(row["entry_id"]),
                    scope_id=str(row["scope_id"]),
                    kind=str(row["kind"]),
                    summary=str(row["summary"]),
                    raw_ref=str(row["raw_ref"] or ""),
                    raw_ref_sha256=str(row["raw_ref_sha256"] or ""),
                    replaceability_score=float(row["replaceability_score"] or 0.0),
                    token_estimate=int(row["token_estimate"] or 0),
                    status=str(row["status"]),
                    degraded=bool(row["degraded"]),
                    metadata=json.loads(str(row["metadata_json"] or "{}")),
                )
            )
        return out

    def list_entries_for_diagnostics(self, scope: WorkSessionScope) -> list[ScratchpadEntry]:
        if not scope.scope_id:
            return []
        self.initialize()
        limit = int(self.policy.max_entries_per_scope)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scratchpad_entries
                WHERE scope_id = ?
                ORDER BY created_at DESC, entry_id ASC
                LIMIT ?
                """,
                (scope.scope_id, limit),
            ).fetchall()
        out: list[ScratchpadEntry] = []
        for row in rows:
            out.append(
                ScratchpadEntry(
                    entry_id=str(row["entry_id"]),
                    scope_id=str(row["scope_id"]),
                    kind=str(row["kind"]),
                    summary=str(row["summary"]),
                    raw_ref=str(row["raw_ref"] or ""),
                    raw_ref_sha256=str(row["raw_ref_sha256"] or ""),
                    replaceability_score=float(row["replaceability_score"] or 0.0),
                    token_estimate=int(row["token_estimate"] or 0),
                    status=str(row["status"]),
                    degraded=bool(row["degraded"]),
                    metadata=json.loads(str(row["metadata_json"] or "{}")),
                )
            )
        return out

    def build_diagnostic_task_map(self, scope: WorkSessionScope) -> dict[str, Any]:
        return build_diagnostic_task_map(scope, self.list_entries_for_diagnostics(scope))

    def prune_expired(self, *, now: datetime | None = None) -> dict[str, int]:
        self.initialize()
        cutoff = (now or datetime.now(timezone.utc)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT entry_id, raw_ref FROM scratchpad_entries WHERE expires_at IS NOT NULL AND expires_at < ?",
                (cutoff,),
            ).fetchall()
            entry_ids = [str(row["entry_id"]) for row in rows]
            raw_refs = [str(row["raw_ref"] or "") for row in rows if str(row["raw_ref"] or "").strip()]
            conn.execute(
                "DELETE FROM scratchpad_entries WHERE expires_at IS NOT NULL AND expires_at < ?",
                (cutoff,),
            )
            scope_rows = conn.execute(
                """
                SELECT scope_id FROM scratchpad_scopes
                WHERE expires_at IS NOT NULL AND expires_at < ?
                  AND scope_id NOT IN (SELECT DISTINCT scope_id FROM scratchpad_entries)
                """,
                (cutoff,),
            ).fetchall()
            scope_ids = [str(row["scope_id"]) for row in scope_rows]
            conn.execute(
                """
                DELETE FROM scratchpad_scopes
                WHERE expires_at IS NOT NULL AND expires_at < ?
                  AND scope_id NOT IN (SELECT DISTINCT scope_id FROM scratchpad_entries)
                """,
                (cutoff,),
            )
        removed_refs = 0
        for raw_ref in raw_refs:
            try:
                target = (self.project_root / raw_ref).resolve()
                if _is_relative_to(target, self.refs_root.resolve()) and target.exists():
                    target.unlink()
                    removed_refs += 1
            except Exception as exc:
                LOGGER.warning("work-session scratchpad raw-ref cleanup failed for %s: %s", raw_ref, exc)
                continue
        for child in list(self.refs_root.glob("*")) if self.refs_root.exists() else []:
            if child.is_dir():
                try:
                    if not any(child.iterdir()):
                        shutil.rmtree(child)
                except Exception as exc:
                    LOGGER.warning("work-session scratchpad ref directory cleanup failed for %s: %s", child, exc)
                    continue
        return {"entries": len(entry_ids), "scopes": len(scope_ids), "refs": removed_refs}

    def schema_columns(self, table: str) -> list[str]:
        if table not in self._SCHEMA_TABLES:
            raise ValueError(f"unknown scratchpad table: {table}")
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [str(row["name"]) for row in rows]
