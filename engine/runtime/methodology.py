from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

if TYPE_CHECKING:
    from .session import RuntimeSession


METHODOLOGY_STATE_SCHEMA = "numquamoblita.runtime.methodology_state.v1"
METHODOLOGY_ALLOWED_STATUSES = {"draft", "canary", "active", "retired"}
METHODOLOGY_ALLOWED_APPROVAL = {"pending", "approved", "rejected"}

DEFAULT_TRIGGER_CONFIG: dict[str, Any] = {
    "correction_threshold": 3,
    "clarify_rate_threshold": 0.35,
    "clarify_rate_delta": 0.12,
    "contradiction_growth_delta": 4,
    "warn_turn_rate_threshold": 0.45,
    "retrieval_passes_threshold": 2.75,
    "latency_multiplier_threshold": 1.35,
    "minimum_turns_for_canary_eval": 8,
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _compact_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 4:
        return text[:max_chars]
    return text[: max_chars - 1].rstrip() + "…"


def _normalize_free_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fingerprint_text(value: str) -> str:
    normalized = _normalize_free_text(value)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:24]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _append_event(state: dict[str, Any], *, event_type: str, actor: str, detail: Mapping[str, Any]) -> dict[str, Any]:
    row = {
        "event_id": _new_id("m_evt"),
        "event_type": str(event_type or "").strip() or "unknown",
        "actor": str(actor or "").strip() or "system",
        "created_at": _utc_iso(),
        "detail": dict(detail or {}),
    }
    history = [item for item in list(state.get("timeline") or []) if isinstance(item, Mapping)]
    history.append(row)
    state["timeline"] = history[-200:]
    state["updated_at"] = _utc_iso()
    return row


def default_methodology_state() -> dict[str, Any]:
    return {
        "schema": METHODOLOGY_STATE_SCHEMA,
        "updated_at": _utc_iso(),
        "active_methodology_id": "",
        "records": [],
        "timeline": [],
        "corrections": [],
        "correction_clusters": {},
        "maintenance_history": [],
        "last_quality_snapshot": {},
        "trigger_config": dict(DEFAULT_TRIGGER_CONFIG),
    }


def load_methodology_state(
    path: Path,
    *,
    max_records: int = 4000,
    max_corrections: int = 20000,
    max_history: int = 4000,
) -> dict[str, Any]:
    if not path.exists():
        return default_methodology_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_methodology_state()
    if not isinstance(raw, Mapping):
        return default_methodology_state()
    state = default_methodology_state()
    state["schema"] = str(raw.get("schema") or METHODOLOGY_STATE_SCHEMA)
    state["updated_at"] = str(raw.get("updated_at") or _utc_iso())
    state["active_methodology_id"] = str(raw.get("active_methodology_id") or "")
    state["trigger_config"] = {
        **dict(DEFAULT_TRIGGER_CONFIG),
        **dict(raw.get("trigger_config") or {}),
    }
    records = [dict(item) for item in list(raw.get("records") or []) if isinstance(item, Mapping)]
    state["records"] = records[-max_records:]
    timeline = [dict(item) for item in list(raw.get("timeline") or []) if isinstance(item, Mapping)]
    state["timeline"] = timeline[-max_history:]
    corrections = [dict(item) for item in list(raw.get("corrections") or []) if isinstance(item, Mapping)]
    state["corrections"] = corrections[-max_corrections:]
    clusters_raw = raw.get("correction_clusters")
    if isinstance(clusters_raw, Mapping):
        state["correction_clusters"] = {
            str(key): dict(value)
            for key, value in clusters_raw.items()
            if isinstance(key, str) and isinstance(value, Mapping)
        }
    state["maintenance_history"] = [
        dict(item) for item in list(raw.get("maintenance_history") or []) if isinstance(item, Mapping)
    ][-max_history:]
    last_snapshot = raw.get("last_quality_snapshot")
    if isinstance(last_snapshot, Mapping):
        state["last_quality_snapshot"] = dict(last_snapshot)
    return state


def persist_methodology_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state or {})
    payload["schema"] = METHODOLOGY_STATE_SCHEMA
    payload["updated_at"] = _utc_iso()
    blob = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(blob + "\n", encoding="utf-8")
    tmp_path.replace(path)


def compute_quality_snapshot(runtime: RuntimeSession, *, limit: int = 200) -> dict[str, Any]:
    window = max(10, int(limit))
    summary = dict(runtime.get_runtime_telemetry_summary(limit=window) or {})
    turns = [dict(row) for row in list(runtime.get_runtime_telemetry_turns(limit=window) or []) if isinstance(row, Mapping)]
    turns_considered = int(summary.get("turns_considered") or len(turns))
    clarify_turns = sum(1 for row in turns if str(row.get("decision") or "").strip().upper() == "CLARIFY")
    pass_turns = sum(1 for row in turns if str(row.get("decision") or "").strip().upper() == "PASS")
    warn_turns = int(summary.get("warn_turns") or 0)

    contradicted_atoms = 0
    contradiction_events = 0
    try:
        for atom in list(runtime.retriever.store.list_atoms()):
            contradiction_count = int(getattr(atom, "contradiction_count", 0))
            status = str(getattr(atom, "status", "")).strip().lower()
            if contradiction_count > 0 or status == "conflicted":
                contradicted_atoms += 1
                contradiction_events += max(1, contradiction_count)
    except Exception:
        contradicted_atoms = 0
        contradiction_events = 0

    route_counts = dict(summary.get("route_counts") or {})
    ltm_light = int(route_counts.get("ltm_light") or 0)
    ltm_deep = int(route_counts.get("ltm_deep") or 0)
    ltm_route_rate = (ltm_light + ltm_deep) / float(max(1, turns_considered))

    return {
        "computed_at": _utc_iso(),
        "window": window,
        "turns_considered": turns_considered,
        "pass_turns": pass_turns,
        "clarify_turns": clarify_turns,
        "clarify_rate": round(clarify_turns / float(max(1, turns_considered)), 6),
        "warn_turns": warn_turns,
        "warn_turn_rate": round(warn_turns / float(max(1, turns_considered)), 6),
        "avg_total_ms": round(float(summary.get("avg_total_ms") or 0.0), 6),
        "avg_retrieval_passes": round(float(summary.get("avg_retrieval_passes") or 0.0), 6),
        "contradicted_atoms": int(contradicted_atoms),
        "contradiction_events": int(contradiction_events),
        "ltm_route_rate": round(ltm_route_rate, 6),
        "route_counts": route_counts,
        "stop_reason_counts": dict(summary.get("stop_reason_counts") or {}),
        "warning_code_counts": dict(summary.get("warning_code_counts") or {}),
    }


def compare_quality_snapshots(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = {**dict(DEFAULT_TRIGGER_CONFIG), **dict(config or {})}
    baseline_turns = int(baseline.get("turns_considered") or 0)
    current_turns = int(current.get("turns_considered") or 0)
    min_turns = max(1, int(cfg.get("minimum_turns_for_canary_eval") or 8))

    clarify_delta = float(current.get("clarify_rate") or 0.0) - float(baseline.get("clarify_rate") or 0.0)
    warn_delta = float(current.get("warn_turn_rate") or 0.0) - float(baseline.get("warn_turn_rate") or 0.0)
    contradiction_delta = int(current.get("contradiction_events") or 0) - int(baseline.get("contradiction_events") or 0)
    baseline_latency = float(baseline.get("avg_total_ms") or 0.0)
    current_latency = float(current.get("avg_total_ms") or 0.0)
    latency_ratio = (current_latency / baseline_latency) if baseline_latency > 0.0 else 1.0

    reasons: list[str] = []
    warnings: list[str] = []

    enough_data = baseline_turns >= min_turns and current_turns >= min_turns
    if not enough_data:
        warnings.append("insufficient_turn_volume_for_strict_canary_decision")
    else:
        if clarify_delta >= float(cfg.get("clarify_rate_delta") or 0.12):
            reasons.append("clarify_rate_spike")
        if warn_delta >= float(cfg.get("clarify_rate_delta") or 0.12):
            reasons.append("warn_turn_rate_spike")
        if contradiction_delta >= int(cfg.get("contradiction_growth_delta") or 4):
            reasons.append("contradiction_growth")
        if latency_ratio >= float(cfg.get("latency_multiplier_threshold") or 1.35):
            reasons.append("latency_regression")

    should_rollback = bool(reasons)
    risk_label = "high" if should_rollback else ("medium" if warnings else "low")
    return {
        "should_rollback": should_rollback,
        "risk_label": risk_label,
        "reasons": reasons,
        "warnings": warnings,
        "delta": {
            "clarify_rate": round(clarify_delta, 6),
            "warn_turn_rate": round(warn_delta, 6),
            "contradiction_events": int(contradiction_delta),
            "latency_ratio": round(latency_ratio, 6),
        },
    }


def _record_by_id(state: Mapping[str, Any], methodology_id: str) -> dict[str, Any]:
    needle = str(methodology_id or "").strip()
    for row in list(state.get("records") or []):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("methodology_id") or "") == needle:
            return dict(row)
    raise KeyError(needle)


def list_methodology_records(
    state: Mapping[str, Any],
    *,
    status: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_status = str(status or "all").strip().lower() or "all"
    rows = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    if normalized_status != "all":
        rows = [row for row in rows if str(row.get("status") or "").strip().lower() == normalized_status]
    start = max(0, int(offset))
    window = max(1, int(limit))
    page = rows[start : start + window]
    return {
        "records": page,
        "offset": start,
        "limit": window,
        "total": len(rows),
        "has_more": start + len(page) < len(rows),
    }


def create_methodology_record(
    state: dict[str, Any],
    *,
    trigger_condition: str,
    action: str,
    rationale: str,
    actor: str,
    provenance_refs: list[str] | None = None,
    supersedes_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    trigger = _compact_text(trigger_condition, max_chars=800)
    action_text = _compact_text(action, max_chars=800)
    rationale_text = _compact_text(rationale, max_chars=800)
    if not trigger:
        raise ValueError("trigger_condition is required")
    if not action_text:
        raise ValueError("action is required")
    if not rationale_text:
        raise ValueError("rationale is required")
    supersedes = str(supersedes_id or "").strip()

    previous_versions = [
        dict(row)
        for row in list(state.get("records") or [])
        if isinstance(row, Mapping) and str(row.get("supersedes_id") or "") == supersedes and supersedes
    ]
    version = max([int(row.get("version") or 0) for row in previous_versions] + [0]) + 1

    refs = [str(item).strip() for item in list(provenance_refs or []) if str(item).strip()]
    row = {
        "methodology_id": _new_id("meth"),
        "trigger_condition": trigger,
        "action": action_text,
        "rationale": rationale_text,
        "version": version,
        "status": "draft",
        "approval_state": "pending",
        "created_at": _utc_iso(),
        "updated_at": _utc_iso(),
        "approved_at": "",
        "approved_by": "",
        "retired_at": "",
        "retired_reason": "",
        "risk_label": "review",
        "provenance_refs": refs[:16],
        "supersedes_id": supersedes,
        "metadata": dict(metadata or {}),
        "canary": {},
    }
    records = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    records.append(row)
    state["records"] = records[-4000:]
    _append_event(
        state,
        event_type="methodology_created",
        actor=actor,
        detail={
            "methodology_id": row["methodology_id"],
            "version": version,
            "supersedes_id": supersedes,
        },
    )
    return row


def review_methodology_record(
    state: dict[str, Any],
    *,
    methodology_id: str,
    decision: str,
    reviewer: str,
    note: str = "",
) -> dict[str, Any]:
    decision_norm = str(decision or "").strip().lower()
    if decision_norm not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    reviewer_text = str(reviewer or "").strip()
    if not reviewer_text:
        raise ValueError("reviewer is required")

    records = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    idx = next((i for i, row in enumerate(records) if str(row.get("methodology_id") or "") == methodology_id), -1)
    if idx < 0:
        raise KeyError(methodology_id)
    row = dict(records[idx])
    row["approval_state"] = "approved" if decision_norm == "approve" else "rejected"
    row["approved_at"] = _utc_iso()
    row["approved_by"] = reviewer_text
    row["updated_at"] = _utc_iso()
    if decision_norm == "reject":
        row["status"] = "retired"
        row["retired_at"] = _utc_iso()
        row["retired_reason"] = _compact_text(note or "review_rejected", max_chars=220)
        row["risk_label"] = "retired"
    records[idx] = row
    state["records"] = records
    _append_event(
        state,
        event_type="methodology_reviewed",
        actor=reviewer_text,
        detail={
            "methodology_id": methodology_id,
            "decision": decision_norm,
            "note": _compact_text(note, max_chars=300),
        },
    )
    return row


def promote_methodology_to_canary(
    state: dict[str, Any],
    *,
    methodology_id: str,
    runtime: RuntimeSession,
    actor: str,
    auto_rollback: bool = True,
) -> dict[str, Any]:
    records = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    idx = next((i for i, row in enumerate(records) if str(row.get("methodology_id") or "") == methodology_id), -1)
    if idx < 0:
        raise KeyError(methodology_id)
    row = dict(records[idx])
    if str(row.get("approval_state") or "").strip().lower() != "approved":
        raise ValueError("methodology must be approved before canary")
    previous_active = str(state.get("active_methodology_id") or "").strip()
    baseline = compute_quality_snapshot(runtime, limit=200)
    row["status"] = "canary"
    row["updated_at"] = _utc_iso()
    row["canary"] = {
        "started_at": _utc_iso(),
        "baseline_snapshot": baseline,
        "latest_snapshot": baseline,
        "latest_compare": {},
        "evaluation_count": 0,
        "rollback_triggered": False,
        "auto_rollback": bool(auto_rollback),
        "previous_active_id": previous_active,
    }
    records[idx] = row
    state["records"] = records
    _append_event(
        state,
        event_type="methodology_canary_started",
        actor=actor,
        detail={
            "methodology_id": methodology_id,
            "previous_active_id": previous_active,
            "auto_rollback": bool(auto_rollback),
        },
    )
    return row


def evaluate_methodology_canary(
    state: dict[str, Any],
    *,
    methodology_id: str,
    runtime: RuntimeSession,
    actor: str,
) -> dict[str, Any]:
    records = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    idx = next((i for i, row in enumerate(records) if str(row.get("methodology_id") or "") == methodology_id), -1)
    if idx < 0:
        raise KeyError(methodology_id)
    row = dict(records[idx])
    if str(row.get("status") or "").strip().lower() != "canary":
        raise ValueError("methodology is not in canary state")
    canary = dict(row.get("canary") or {})
    baseline = dict(canary.get("baseline_snapshot") or {})
    if not baseline:
        raise ValueError("missing canary baseline snapshot")
    current = compute_quality_snapshot(runtime, limit=200)
    compare = compare_quality_snapshots(
        baseline=baseline,
        current=current,
        config=dict(state.get("trigger_config") or {}),
    )
    evaluations = [dict(item) for item in list(canary.get("evaluations") or []) if isinstance(item, Mapping)]
    evaluations.append(
        {
            "evaluated_at": _utc_iso(),
            "snapshot": current,
            "comparison": compare,
        }
    )
    canary["evaluations"] = evaluations[-120:]
    canary["latest_snapshot"] = current
    canary["latest_compare"] = compare
    canary["evaluation_count"] = len(canary["evaluations"])

    rollback_triggered = bool(compare.get("should_rollback")) and bool(canary.get("auto_rollback"))
    if rollback_triggered:
        previous_active = str(canary.get("previous_active_id") or "").strip()
        row["status"] = "retired"
        row["retired_at"] = _utc_iso()
        row["retired_reason"] = "auto_rollback_canary_regression"
        row["risk_label"] = "high"
        canary["rollback_triggered"] = True
        restored = ""
        if previous_active:
            for inner_idx, inner_row in enumerate(records):
                if str(inner_row.get("methodology_id") or "") == previous_active:
                    restored_row = dict(inner_row)
                    restored_row["status"] = "active"
                    restored_row["updated_at"] = _utc_iso()
                    records[inner_idx] = restored_row
                    restored = previous_active
                    break
        state["active_methodology_id"] = restored
    row["canary"] = canary
    row["updated_at"] = _utc_iso()
    records[idx] = row
    state["records"] = records
    _append_event(
        state,
        event_type="methodology_canary_evaluated",
        actor=actor,
        detail={
            "methodology_id": methodology_id,
            "should_rollback": bool(compare.get("should_rollback")),
            "risk_label": str(compare.get("risk_label") or "low"),
            "reasons": list(compare.get("reasons") or []),
        },
    )
    return {
        "methodology_id": methodology_id,
        "status": str(row.get("status") or ""),
        "canary": canary,
        "comparison": compare,
        "active_methodology_id": str(state.get("active_methodology_id") or ""),
    }


def activate_methodology_record(state: dict[str, Any], *, methodology_id: str, actor: str) -> dict[str, Any]:
    records = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    idx = next((i for i, row in enumerate(records) if str(row.get("methodology_id") or "") == methodology_id), -1)
    if idx < 0:
        raise KeyError(methodology_id)
    row = dict(records[idx])
    if str(row.get("approval_state") or "").strip().lower() != "approved":
        raise ValueError("methodology must be approved before activation")
    status = str(row.get("status") or "").strip().lower()
    if status not in {"draft", "canary", "active"}:
        raise ValueError("methodology status must be draft/canary/active")

    previous_active = str(state.get("active_methodology_id") or "").strip()
    if previous_active and previous_active != methodology_id:
        for inner_idx, inner_row in enumerate(records):
            if str(inner_row.get("methodology_id") or "") == previous_active:
                retired = dict(inner_row)
                retired["status"] = "retired"
                retired["retired_at"] = _utc_iso()
                retired["retired_reason"] = f"superseded_by:{methodology_id}"
                retired["updated_at"] = _utc_iso()
                records[inner_idx] = retired
                break

    row["status"] = "active"
    row["updated_at"] = _utc_iso()
    row["risk_label"] = "low"
    records[idx] = row
    state["records"] = records
    state["active_methodology_id"] = methodology_id
    _append_event(
        state,
        event_type="methodology_activated",
        actor=actor,
        detail={
            "methodology_id": methodology_id,
            "previous_active_id": previous_active,
        },
    )
    return row


def rollback_methodology_record(
    state: dict[str, Any],
    *,
    methodology_id: str,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    records = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    idx = next((i for i, row in enumerate(records) if str(row.get("methodology_id") or "") == methodology_id), -1)
    if idx < 0:
        raise KeyError(methodology_id)
    row = dict(records[idx])
    canary = dict(row.get("canary") or {})
    fallback_id = str(canary.get("previous_active_id") or "").strip()
    if not fallback_id:
        for inner in records:
            inner_id = str(inner.get("methodology_id") or "")
            if inner_id and inner_id != methodology_id and str(inner.get("status") or "") == "active":
                fallback_id = inner_id
                break
    row["status"] = "retired"
    row["retired_at"] = _utc_iso()
    row["retired_reason"] = _compact_text(reason or "manual_rollback", max_chars=220)
    row["updated_at"] = _utc_iso()
    row["risk_label"] = "high"
    records[idx] = row

    restored = ""
    if fallback_id:
        for inner_idx, inner_row in enumerate(records):
            if str(inner_row.get("methodology_id") or "") == fallback_id:
                restored_row = dict(inner_row)
                restored_row["status"] = "active"
                restored_row["updated_at"] = _utc_iso()
                records[inner_idx] = restored_row
                restored = fallback_id
                break
    state["records"] = records
    state["active_methodology_id"] = restored
    _append_event(
        state,
        event_type="methodology_rollback",
        actor=actor,
        detail={
            "methodology_id": methodology_id,
            "restored_methodology_id": restored,
            "reason": _compact_text(reason, max_chars=240),
        },
    )
    return {
        "rolled_back_methodology_id": methodology_id,
        "restored_methodology_id": restored,
        "active_methodology_id": restored,
    }


def record_correction_event(
    state: dict[str, Any],
    *,
    text: str,
    assistant_id: str,
    session_id: str,
    actor: str,
) -> dict[str, Any]:
    raw_text = _compact_text(text, max_chars=1200)
    if not raw_text:
        raise ValueError("text is required")
    fingerprint = _fingerprint_text(raw_text)
    normalized = _normalize_free_text(raw_text)
    correction = {
        "correction_id": _new_id("corr"),
        "created_at": _utc_iso(),
        "assistant_id": str(assistant_id or "").strip() or "assistant_default",
        "session_id": str(session_id or "").strip() or "session_default",
        "fingerprint": fingerprint,
        "normalized_text": normalized,
        "raw_text": raw_text,
    }
    corrections = [dict(item) for item in list(state.get("corrections") or []) if isinstance(item, Mapping)]
    corrections.append(correction)
    state["corrections"] = corrections[-20000:]

    clusters = dict(state.get("correction_clusters") or {})
    cluster = dict(clusters.get(fingerprint) or {})
    cluster.setdefault("cluster_id", _new_id("corr_cluster"))
    cluster.setdefault("fingerprint", fingerprint)
    cluster.setdefault("first_seen_at", correction["created_at"])
    cluster["last_seen_at"] = correction["created_at"]
    cluster["count"] = int(cluster.get("count") or 0) + 1
    cluster["example_text"] = str(cluster.get("example_text") or raw_text)
    cluster["assistant_id"] = correction["assistant_id"]
    cluster["session_id"] = correction["session_id"]
    cluster.setdefault("generated_methodology_id", "")
    clusters[fingerprint] = cluster
    state["correction_clusters"] = clusters

    generated = {}
    threshold = max(2, int(dict(state.get("trigger_config") or {}).get("correction_threshold") or 3))
    if int(cluster.get("count") or 0) >= threshold and not str(cluster.get("generated_methodology_id") or "").strip():
        generated = create_methodology_record(
            state,
            trigger_condition=f"Repeated user correction pattern (fingerprint={fingerprint}).",
            action=f"Update methodology to avoid repeating correction: {_compact_text(raw_text, max_chars=180)}",
            rationale=f"Auto-generated from {int(cluster.get('count') or 0)} repeated corrections.",
            actor=actor,
            provenance_refs=[correction["correction_id"]],
            metadata={
                "source": "correction_cluster",
                "cluster_id": str(cluster.get("cluster_id") or ""),
                "threshold": threshold,
            },
        )
        cluster["generated_methodology_id"] = str(generated.get("methodology_id") or "")
        cluster["generated_at"] = _utc_iso()
        clusters[fingerprint] = cluster
        state["correction_clusters"] = clusters

    _append_event(
        state,
        event_type="correction_recorded",
        actor=actor,
        detail={
            "correction_id": correction["correction_id"],
            "fingerprint": fingerprint,
            "cluster_count": int(cluster.get("count") or 0),
            "generated_methodology_id": str(cluster.get("generated_methodology_id") or ""),
        },
    )
    return {
        "correction": correction,
        "cluster": cluster,
        "generated_methodology": generated,
    }


def list_correction_clusters(state: Mapping[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    clusters = [dict(value) for value in dict(state.get("correction_clusters") or {}).values() if isinstance(value, Mapping)]
    clusters.sort(
        key=lambda row: (
            int(row.get("count") or 0),
            str(row.get("last_seen_at") or ""),
        ),
        reverse=True,
    )
    return clusters[: max(1, int(limit))]


def evaluate_maintenance_triggers(
    state: dict[str, Any],
    *,
    runtime: RuntimeSession,
    actor: str,
    force: bool = False,
) -> dict[str, Any]:
    current = compute_quality_snapshot(runtime, limit=200)
    previous = dict(state.get("last_quality_snapshot") or {})
    cfg = {**dict(DEFAULT_TRIGGER_CONFIG), **dict(state.get("trigger_config") or {})}
    triggers: list[dict[str, Any]] = []

    if previous:
        clarify_delta = float(current.get("clarify_rate") or 0.0) - float(previous.get("clarify_rate") or 0.0)
        if float(current.get("clarify_rate") or 0.0) >= float(cfg.get("clarify_rate_threshold") or 0.35) and clarify_delta >= float(
            cfg.get("clarify_rate_delta") or 0.12
        ):
            triggers.append(
                {
                    "trigger": "clarify_rate_spike",
                    "severity": "high",
                    "current": float(current.get("clarify_rate") or 0.0),
                    "previous": float(previous.get("clarify_rate") or 0.0),
                    "delta": round(clarify_delta, 6),
                }
            )
        contradiction_delta = int(current.get("contradiction_events") or 0) - int(previous.get("contradiction_events") or 0)
        if contradiction_delta >= int(cfg.get("contradiction_growth_delta") or 4):
            triggers.append(
                {
                    "trigger": "contradiction_growth",
                    "severity": "high",
                    "current": int(current.get("contradiction_events") or 0),
                    "previous": int(previous.get("contradiction_events") or 0),
                    "delta": contradiction_delta,
                }
            )
    warn_rate = float(current.get("warn_turn_rate") or 0.0)
    avg_passes = float(current.get("avg_retrieval_passes") or 0.0)
    if warn_rate >= float(cfg.get("warn_turn_rate_threshold") or 0.45) or avg_passes >= float(cfg.get("retrieval_passes_threshold") or 2.75):
        triggers.append(
            {
                "trigger": "drift_threshold_breach",
                "severity": "medium",
                "warn_turn_rate": round(warn_rate, 6),
                "avg_retrieval_passes": round(avg_passes, 6),
            }
        )
    if force and not triggers:
        triggers.append(
            {
                "trigger": "manual_probe",
                "severity": "low",
                "reason": "forced_evaluation",
            }
        )

    risk_label = "high" if any(str(item.get("severity") or "") == "high" for item in triggers) else ("medium" if triggers else "low")
    evaluation = {
        "evaluation_id": _new_id("maint"),
        "created_at": _utc_iso(),
        "triggered": bool(triggers),
        "risk_label": risk_label,
        "triggers": triggers,
        "snapshot": current,
    }
    history = [dict(item) for item in list(state.get("maintenance_history") or []) if isinstance(item, Mapping)]
    history.append(evaluation)
    state["maintenance_history"] = history[-4000:]
    state["last_quality_snapshot"] = current
    _append_event(
        state,
        event_type="maintenance_evaluated",
        actor=actor,
        detail={
            "evaluation_id": evaluation["evaluation_id"],
            "triggered": bool(triggers),
            "risk_label": risk_label,
            "trigger_count": len(triggers),
        },
    )
    return evaluation


def build_operator_readout(state: Mapping[str, Any], *, runtime: RuntimeSession) -> dict[str, Any]:
    records = [dict(item) for item in list(state.get("records") or []) if isinstance(item, Mapping)]
    status_counts: dict[str, int] = {key: 0 for key in METHODOLOGY_ALLOWED_STATUSES}
    approval_counts: dict[str, int] = {key: 0 for key in METHODOLOGY_ALLOWED_APPROVAL}
    for row in records:
        status = str(row.get("status") or "").strip().lower()
        approval = str(row.get("approval_state") or "").strip().lower()
        if status in status_counts:
            status_counts[status] += 1
        if approval in approval_counts:
            approval_counts[approval] += 1
    active_id = str(state.get("active_methodology_id") or "")
    active = {}
    if active_id:
        try:
            active = _record_by_id(state, active_id)
        except KeyError:
            active = {}
    canary_rows = [row for row in records if str(row.get("status") or "") == "canary"]
    canary_rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    latest_canary = canary_rows[0] if canary_rows else {}
    maintenance_history = [dict(item) for item in list(state.get("maintenance_history") or []) if isinstance(item, Mapping)]
    maintenance_history.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    timeline = [dict(item) for item in list(state.get("timeline") or []) if isinstance(item, Mapping)]
    timeline.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    live_snapshot = compute_quality_snapshot(runtime, limit=120)
    return {
        "updated_at": str(state.get("updated_at") or _utc_iso()),
        "active_methodology_id": active_id,
        "active_methodology": active,
        "latest_canary": latest_canary,
        "counts": {
            "records_total": len(records),
            "status": status_counts,
            "approval": approval_counts,
            "pending_review": approval_counts.get("pending", 0),
        },
        "latest_maintenance": maintenance_history[:3],
        "recent_events": timeline[:12],
        "live_quality_snapshot": live_snapshot,
    }
