#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_export_candidates() -> list[Path]:
    return [
        REPO_ROOT / "conversations.json",
        REPO_ROOT.parent / "User Online Activity" / "conversations.json",
        REPO_ROOT.parent / "User Online Activity" / "conversations" / "conversations.json",
        REPO_ROOT.parent / "User Online Activity" / "conversations" / "art" / "conversations.json",
        REPO_ROOT.parent / "conversations.json",
    ]


def _default_export_path() -> Path:
    candidates = _default_export_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _parse_kv(lines: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in lines:
        text = str(line).strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key_norm = key.strip().lower()
        value_norm = value.strip()
        if key_norm and value_norm:
            payload[key_norm] = value_norm
    return payload


@dataclass(slots=True)
class StepResult:
    name: str
    status: str
    returncode: int
    started_at: str
    finished_at: str
    duration_s: float
    command: list[str]
    log_file: str
    outputs: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "command": self.command,
            "log_file": self.log_file,
            "outputs": self.outputs,
        }


def _run_step(name: str, command: list[str], log_file: Path) -> StepResult:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    started_dt = datetime.now(timezone.utc)
    started_at = started_dt.isoformat()
    streamed: list[str] = []
    returncode = 1
    status = "FAIL"
    error_text = ""
    try:
        with log_file.open("w", encoding="utf-8") as fp:
            fp.write(f"[{started_at}] step={name} start\n")
            fp.write(f"[{started_at}] command={' '.join(command)}\n")
            fp.flush()
            proc = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                clean = line.rstrip("\n")
                streamed.append(clean)
                stamped = f"[{datetime.now(timezone.utc).isoformat()}] {clean}"
                print(stamped)
                fp.write(stamped + "\n")
                fp.flush()
            returncode = int(proc.wait())
            status = "PASS" if returncode == 0 else "FAIL"
    except OSError as exc:
        error_text = f"spawn_error={exc}"
    except Exception as exc:  # pragma: no cover - defensive runner guard
        error_text = f"step_exception={exc}"
    finished_dt = datetime.now(timezone.utc)
    finished_at = finished_dt.isoformat()
    duration_s = max(0.0, (finished_dt - started_dt).total_seconds())
    with log_file.open("a", encoding="utf-8") as fp:
        if error_text:
            fp.write(f"[{finished_at}] {error_text}\n")
        fp.write(f"[{finished_at}] step={name} status={status} rc={returncode}\n")
    return StepResult(
        name=name,
        status=status,
        returncode=returncode,
        started_at=started_at,
        finished_at=finished_at,
        duration_s=duration_s,
        command=command,
        log_file=str(log_file),
        outputs=_parse_kv(streamed),
    )


def _write_manifest(
    *,
    path: Path,
    decision: str,
    store_path: Path,
    run_dir: Path,
    skipped_import: bool,
    input_path: Path | None,
    steps: list[StepResult],
    artifacts: dict[str, str],
) -> None:
    payload = {
        "generated_at": _now_iso(),
        "decision": decision,
        "store_path": str(store_path),
        "run_dir": str(run_dir),
        "skip_import": bool(skipped_import),
        "input_path": str(input_path) if input_path is not None else "",
        "steps": [item.to_dict() for item in steps],
        "artifacts": artifacts,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json payload at {path} must be an object")
    return payload


def _load_json_any(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _ratio(numerator: float, denominator: float) -> float:
    if float(denominator) <= 0.0:
        return 0.0
    return float(numerator) / float(denominator)


def _normalize_tokens(items: list[Any]) -> set[str]:
    out: set[str] = set()
    for item in list(items or []):
        token = str(item or "").strip()
        if token:
            out.add(token)
    return out


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    idx = int(round(0.95 * (len(ordered) - 1)))
    return float(ordered[max(0, min(idx, len(ordered) - 1))])


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    idx = int(round(0.50 * (len(ordered) - 1)))
    return float(ordered[max(0, min(idx, len(ordered) - 1))])


_PARROT_PREFIXES = ("acknowledged:", "memory-backed response for:")
_RELATED_CONTEXT_RE = re.compile(r"\brelated context\b", re.IGNORECASE)
_QUESTION_BLOCKING_TAGS = {
    "malformed_when_clause",
    "clipped_correction_options",
    "stacked_temporal_phrasing",
    "instruction_like_routine_probe",
}
_READOUT_REQUIRED_SECTIONS = (
    "## Q/A Audit Table",
    "## Top Failure Examples",
)

_REQUIRED_EFFICIENCY_METRICS = (
    "latency_p50_ms",
    "latency_p95_ms",
    "tokens_prompt_avg",
    "tokens_completion_avg",
    "tokens_total_avg",
    "retrieval_fanout_avg",
    "retrieval_fanout_p95",
    "false_memory_rate",
    "abstain_precision",
    "evidence_precision_at_k",
    "junk_rate_at_k",
    "conflict_coverage",
)


def _extract_required_metric(
    *,
    sources: list[tuple[dict[str, Any], str]],
    default: float,
) -> tuple[float, bool, bool]:
    for container, key in sources:
        if key not in container:
            continue
        raw = container.get(key)
        try:
            value = float(raw)
        except Exception:
            return float(default), True, False
        return float(value), True, True
    return float(default), False, True


def _required_efficiency_metrics(summary: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    retrieval = summary.get("retrieval") if isinstance(summary.get("retrieval"), dict) else {}
    latency = summary.get("latency_ms") if isinstance(summary.get("latency_ms"), dict) else {}
    tokens = summary.get("tokens") if isinstance(summary.get("tokens"), dict) else {}
    metric_sources: dict[str, list[tuple[dict[str, Any], str]]] = {
        "latency_p50_ms": [(summary, "latency_p50_ms"), (latency, "total_p50")],
        "latency_p95_ms": [(summary, "latency_p95_ms"), (latency, "total_p95")],
        "tokens_prompt_avg": [(summary, "tokens_prompt_avg"), (tokens, "prompt_avg")],
        "tokens_completion_avg": [(summary, "tokens_completion_avg"), (tokens, "completion_avg")],
        "tokens_total_avg": [(summary, "tokens_total_avg"), (tokens, "total_avg")],
        "retrieval_fanout_avg": [
            (summary, "retrieval_fanout_avg"),
            (retrieval, "supported_non_routine_avg_retrieved_atoms"),
            (retrieval, "avg_retrieved_atoms"),
        ],
        "retrieval_fanout_p95": [
            (summary, "retrieval_fanout_p95"),
            (retrieval, "supported_non_routine_p95_retrieved_atoms"),
            (retrieval, "p95_retrieved_atoms"),
        ],
        "false_memory_rate": [(summary, "false_memory_rate")],
        "abstain_precision": [(summary, "abstain_precision")],
        "evidence_precision_at_k": [(retrieval, "evidence_precision_at_k")],
        "junk_rate_at_k": [(retrieval, "junk_rate_at_k")],
        "conflict_coverage": [(retrieval, "conflict_coverage")],
    }
    default_values = {
        "latency_p50_ms": 0.0,
        "latency_p95_ms": 0.0,
        "tokens_prompt_avg": 0.0,
        "tokens_completion_avg": 0.0,
        "tokens_total_avg": 0.0,
        "retrieval_fanout_avg": 0.0,
        "retrieval_fanout_p95": 0.0,
        "false_memory_rate": 0.0,
        "abstain_precision": 0.0,
        "evidence_precision_at_k": 0.0,
        "junk_rate_at_k": 0.0,
        "conflict_coverage": 1.0,
    }
    metrics: dict[str, float] = {}
    presence: dict[str, bool] = {}
    parse_ok: dict[str, bool] = {}
    for key in _REQUIRED_EFFICIENCY_METRICS:
        value, present, ok = _extract_required_metric(
            sources=list(metric_sources.get(key) or []),
            default=float(default_values.get(key, 0.0)),
        )
        metrics[key] = float(value)
        presence[key] = bool(present)
        parse_ok[key] = bool(ok)
    failures: list[str] = []
    for key in _REQUIRED_EFFICIENCY_METRICS:
        if not presence.get(key, False):
            failures.append(f"{key}_missing")
            continue
        if not parse_ok.get(key, False):
            failures.append(f"{key}_not_numeric")
            continue
        value = float(metrics.get(key, 0.0))
        if not math.isfinite(value):
            failures.append(f"{key}_non_finite")
    return metrics, failures


def _percent_change(candidate: float, baseline: float) -> float:
    if baseline > 0.0:
        return ((candidate - baseline) / baseline) * 100.0
    if candidate <= 0.0:
        return 0.0
    return float("inf")


def _evaluate_efficiency_regression(
    *,
    baseline_runs: list[dict[str, float]],
    candidate_runs: list[dict[str, float]],
    led_surface: str,
    max_non_led_regression_pct: float,
) -> tuple[str, list[str], dict[str, Any]]:
    details: dict[str, Any] = {
        "led_surface": str(led_surface),
        "max_non_led_regression_pct": float(max_non_led_regression_pct),
        "baseline_run_count": len(baseline_runs),
        "candidate_run_count": len(candidate_runs),
    }
    failures: list[str] = []
    if str(led_surface) == "none":
        details["note"] = "efficiency regression guard not requested"
        return "PASS", failures, details
    if len(baseline_runs) < 3 or len(candidate_runs) < 3:
        failures.append("median_of_3_required")
        return "FAIL", failures, details

    def _medians(rows: list[dict[str, float]]) -> dict[str, float]:
        return {
            "latency_p50_ms": _median([float(row.get("latency_p50_ms", 0.0)) for row in rows]),
            "latency_p95_ms": _median([float(row.get("latency_p95_ms", 0.0)) for row in rows]),
            "tokens_total_avg": _median([float(row.get("tokens_total_avg", 0.0)) for row in rows]),
        }

    baseline = _medians(baseline_runs)
    candidate = _medians(candidate_runs)
    details["baseline_median"] = baseline
    details["candidate_median"] = candidate
    details["delta_pct"] = {
        "latency_p50_ms": _percent_change(candidate["latency_p50_ms"], baseline["latency_p50_ms"]),
        "latency_p95_ms": _percent_change(candidate["latency_p95_ms"], baseline["latency_p95_ms"]),
        "tokens_total_avg": _percent_change(candidate["tokens_total_avg"], baseline["tokens_total_avg"]),
    }

    max_regression = float(max_non_led_regression_pct)
    if str(led_surface) == "latency":
        if details["delta_pct"]["tokens_total_avg"] > max_regression:
            failures.append("non_led_tokens_regressed_beyond_bound")
    elif str(led_surface) == "tokens":
        if details["delta_pct"]["latency_p50_ms"] > max_regression:
            failures.append("non_led_latency_p50_regressed_beyond_bound")
        if details["delta_pct"]["latency_p95_ms"] > max_regression:
            failures.append("non_led_latency_p95_regressed_beyond_bound")
    else:
        failures.append("invalid_led_surface")
    decision = "PASS" if not failures else "FAIL"
    return decision, failures, details


def _parse_frozen_waivers(raw_values: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    waivers: list[dict[str, str]] = []
    failures: list[str] = []
    for raw in list(raw_values or []):
        text = str(raw or "").strip()
        if not text:
            continue
        parts = [str(item).strip() for item in text.split("|")]
        if len(parts) != 3:
            failures.append(f"invalid_frozen_waiver_format:{text}")
            continue
        reason_raw, blocker_ref, scope = parts
        reason = reason_raw
        prefix = "FROZEN DUE TO "
        upper_reason = reason.upper()
        if upper_reason.startswith(prefix):
            reason = reason[len(prefix) :].strip()
        if not reason or not blocker_ref or not scope:
            failures.append(f"invalid_frozen_waiver_fields:{text}")
            continue
        waivers.append(
            {
                "classification": f"FROZEN DUE TO {reason}",
                "reason": reason,
                "blocker_ref": blocker_ref,
                "scope": scope,
            }
        )
    return waivers, failures


def _validate_gate_report_contract(payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(payload.get("safety_verdict") or "").strip():
        missing.append("safety_verdict")
    if not str(payload.get("human_quality_verdict") or "").strip():
        missing.append("human_quality_verdict")
    if not str(payload.get("decision") or "").strip():
        missing.append("decision")
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    if "defect_case_count" not in quality:
        missing.append("quality.defect_case_count")
    if "blocking_defect_cases" not in quality:
        missing.append("quality.blocking_defect_cases")
    if not isinstance(quality.get("top_failure_examples"), list):
        missing.append("quality.top_failure_examples")
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    for key in _REQUIRED_EFFICIENCY_METRICS:
        if key not in metrics:
            missing.append(f"metrics.{key}")
            continue
        value = _safe_float(metrics.get(key), default=float("nan"))
        if not math.isfinite(value):
            missing.append(f"metrics.{key}_non_finite")
    waivers = payload.get("waivers") if isinstance(payload.get("waivers"), dict) else {}
    frozen_waivers = waivers.get("frozen_surface") if isinstance(waivers.get("frozen_surface"), list) else []
    for idx, entry in enumerate(frozen_waivers):
        if not isinstance(entry, dict):
            missing.append(f"waivers.frozen_surface[{idx}]")
            continue
        if not str(entry.get("classification") or "").strip().upper().startswith("FROZEN DUE TO "):
            missing.append(f"waivers.frozen_surface[{idx}].classification")
        if not str(entry.get("blocker_ref") or "").strip():
            missing.append(f"waivers.frozen_surface[{idx}].blocker_ref")
        if not str(entry.get("scope") or "").strip():
            missing.append(f"waivers.frozen_surface[{idx}].scope")
    return missing


def _validate_readout_contract_text(text: str) -> list[str]:
    body = str(text or "")
    missing: list[str] = []
    for marker in _READOUT_REQUIRED_SECTIONS:
        if marker not in body:
            missing.append(marker)
    return missing


def _question_defect_map(cases_payload: Any) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    defects: dict[str, list[str]] = {}
    blocking: dict[str, list[str]] = {}
    if not isinstance(cases_payload, list):
        return defects, blocking
    for row in cases_payload:
        if not isinstance(row, dict):
            continue
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            continue
        tags = [str(item).strip() for item in list(row.get("defect_tags") or row.get("reasons") or []) if str(item).strip()]
        blocking_tags = [str(item).strip() for item in list(row.get("blocking_defect_tags") or []) if str(item).strip()]
        if not blocking_tags:
            blocking_tags = [item for item in tags if item in _QUESTION_BLOCKING_TAGS]
        defects[case_id] = sorted(set(tags))
        blocking[case_id] = sorted(set(blocking_tags))
    return defects, blocking


def _annotate_records_with_defects(
    records_payload: Any,
    *,
    question_defects: dict[str, list[str]],
    question_blocking: dict[str, list[str]],
) -> list[dict[str, Any]]:
    if not isinstance(records_payload, list):
        return []
    annotated: list[dict[str, Any]] = []
    for row in records_payload:
        if not isinstance(row, dict):
            continue
        case = row.get("case") if isinstance(row.get("case"), dict) else {}
        verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
        case_id = str(case.get("case_id") or "").strip()
        reply_text = str(row.get("reply_text") or "").strip()
        defects = set(str(item).strip() for item in list(row.get("defect_tags") or []) if str(item).strip())
        blocking = set(str(item).strip() for item in list(row.get("blocking_defect_tags") or []) if str(item).strip())

        for tag in list(question_defects.get(case_id) or []):
            if tag:
                defects.add(tag)
        for tag in list(question_blocking.get(case_id) or []):
            if tag:
                defects.add(tag)
                blocking.add(tag)

        lower_reply = reply_text.lower()
        if any(lower_reply.startswith(prefix) for prefix in _PARROT_PREFIXES):
            defects.add("response_parrot_format")
            blocking.add("response_parrot_format")
        if _RELATED_CONTEXT_RE.search(reply_text):
            defects.add("unrelated_related_context_insertion")
            blocking.add("unrelated_related_context_insertion")

        for reason in list(verification.get("reasons") or []):
            cleaned = str(reason).strip()
            if not cleaned:
                continue
            defects.add(f"verifier:{cleaned}")
            if cleaned == "internal_jargon_leak":
                defects.add("internal_jargon_leak")
                blocking.add("internal_jargon_leak")

        row_copy = dict(row)
        row_copy["defect_tags"] = sorted(defects)
        row_copy["blocking_defect_tags"] = sorted(blocking)
        annotated.append(row_copy)
    return annotated


def _alignment_metrics(summary: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, float]:
    retrieval = summary.get("retrieval") if isinstance(summary.get("retrieval"), dict) else {}
    supported_non_routine_cases = _safe_int(
        retrieval.get("supported_non_routine_cases"),
        default=_safe_int((summary.get("truthset") or {}).get("supported_non_routine_cases") if isinstance(summary.get("truthset"), dict) else 0),
    )
    supported_with_alignment = _safe_int(
        retrieval.get("supported_non_routine_with_expected_alignment"),
        default=0,
    )
    alignment_missing_cases = _safe_int(
        retrieval.get("supported_non_routine_alignment_missing_cases"),
        default=max(0, supported_non_routine_cases - supported_with_alignment),
    )
    relevance_aligned_hit_rate = _safe_float(
        retrieval.get("supported_non_routine_relevance_aligned_hit_rate"),
        default=_safe_float(summary.get("relevance_aligned_hit_rate"), default=0.0),
    )
    avg_retrieved_atoms = _safe_float(
        retrieval.get("supported_non_routine_avg_retrieved_atoms"),
        default=_safe_float(retrieval.get("avg_retrieved_atoms"), default=0.0),
    )
    p95_retrieved_atoms = _safe_float(
        retrieval.get("supported_non_routine_p95_retrieved_atoms"),
        default=_safe_float(retrieval.get("p95_retrieved_atoms"), default=0.0),
    )
    evidence_precision_at_k = _safe_float(
        retrieval.get("evidence_precision_at_k"),
        default=-1.0,
    )
    junk_rate_at_k = _safe_float(
        retrieval.get("junk_rate_at_k"),
        default=-1.0,
    )
    conflict_labeled_cases = _safe_int(
        retrieval.get("conflict_labeled_supported_cases"),
        default=0,
    )
    conflict_covered_cases = _safe_int(
        retrieval.get("conflict_covered_supported_cases"),
        default=0,
    )
    conflict_coverage = _safe_float(
        retrieval.get("conflict_coverage"),
        default=-1.0,
    )

    derived_supported_non_routine_cases = 0
    derived_supported_with_alignment = 0
    derived_retrieved_total = 0
    derived_relevant_total = 0
    derived_conflict_labeled = 0
    derived_conflict_covered = 0
    for row in records:
        if not isinstance(row, dict):
            continue
        case = row.get("case") if isinstance(row.get("case"), dict) else {}
        expected_decision = str(case.get("expected_decision") or "").strip().upper()
        case_type = str(case.get("case_type") or "").strip()
        if expected_decision not in {"PASS", "CLARIFY"} or case_type == "routine_chat":
            continue
        derived_supported_non_routine_cases += 1
        expected_atom_ids = _normalize_tokens(list(case.get("expected_atom_ids") or []))
        expected_citations = _normalize_tokens(list(case.get("expected_citations") or []))
        retrieval_payload = row.get("retrieval") if isinstance(row.get("retrieval"), dict) else {}
        retrieved_atom_ids = _normalize_tokens(
            list(retrieval_payload.get("retrieved_atom_ids") or row.get("retrieved_atom_ids") or [])
        )
        verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
        citation_pool = (
            _normalize_tokens(list(retrieval_payload.get("service_citations") or []))
            .union(_normalize_tokens(list(retrieval_payload.get("package_evidence_citations") or [])))
            .union(_normalize_tokens(list(verification.get("found_citations") or [])))
        )
        if expected_atom_ids:
            derived_supported_with_alignment += 1
            derived_retrieved_total += len(retrieved_atom_ids)
            derived_relevant_total += len(expected_atom_ids.intersection(retrieved_atom_ids))
        elif expected_citations:
            derived_supported_with_alignment += 1
            derived_retrieved_total += len(citation_pool)
            derived_relevant_total += len(expected_citations.intersection(citation_pool))

        fixture_family = str(case.get("fixture_family") or "").strip().lower()
        if fixture_family == "contradiction_pressure":
            derived_conflict_labeled += 1
            verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
            inferred_decision = str(verification.get("inferred_decision") or row.get("actual_decision") or "").strip().upper()
            retrieved_has_required = expected_atom_ids.issubset(retrieved_atom_ids) if expected_atom_ids else False
            if retrieved_has_required or inferred_decision in {"ABSTAIN", "CLARIFY"}:
                derived_conflict_covered += 1

    if supported_non_routine_cases <= 0:
        supported_non_routine_cases = derived_supported_non_routine_cases
    if supported_with_alignment <= 0:
        supported_with_alignment = derived_supported_with_alignment
    alignment_missing_cases = max(0, supported_non_routine_cases - supported_with_alignment)
    if evidence_precision_at_k < 0.0:
        evidence_precision_at_k = _ratio(derived_relevant_total, derived_retrieved_total)
    if junk_rate_at_k < 0.0:
        junk_rate_at_k = 1.0 - evidence_precision_at_k if derived_retrieved_total > 0 else 0.0
    if conflict_labeled_cases <= 0:
        conflict_labeled_cases = derived_conflict_labeled
    if conflict_covered_cases <= 0:
        conflict_covered_cases = derived_conflict_covered
    if conflict_coverage < 0.0:
        conflict_coverage = 1.0 if conflict_labeled_cases <= 0 else _ratio(conflict_covered_cases, conflict_labeled_cases)
    return {
        "supported_non_routine_cases": float(supported_non_routine_cases),
        "supported_non_routine_with_expected_alignment": float(supported_with_alignment),
        "supported_non_routine_alignment_missing_cases": float(alignment_missing_cases),
        "relevance_aligned_hit_rate": float(relevance_aligned_hit_rate),
        "avg_retrieved_atoms_supported_non_routine": float(avg_retrieved_atoms),
        "p95_retrieved_atoms_supported_non_routine": float(p95_retrieved_atoms),
        "evidence_precision_at_k": float(evidence_precision_at_k),
        "junk_rate_at_k": float(junk_rate_at_k),
        "conflict_labeled_supported_cases": float(conflict_labeled_cases),
        "conflict_covered_supported_cases": float(conflict_covered_cases),
        "conflict_coverage": float(conflict_coverage),
    }


def _latency_metrics(summary: dict[str, Any]) -> dict[str, float]:
    latency = summary.get("latency_ms") if isinstance(summary.get("latency_ms"), dict) else {}
    return {
        "memory_ms_p95": _safe_float(latency.get("memory_p95"), default=0.0),
        "model_ms_p95": _safe_float(latency.get("model_p95"), default=0.0),
        "total_ms_p95": _safe_float(latency.get("total_p95"), default=0.0),
    }


def _safety_gate(summary: dict[str, Any], args: argparse.Namespace) -> tuple[str, list[str], dict[str, float]]:
    metrics = {
        "decision_accuracy": _safe_float(
            summary.get("decision_accuracy"),
            default=_safe_float(summary.get("model_decision_accuracy"), default=_safe_float(summary.get("service_decision_accuracy"), default=0.0)),
        ),
        "citation_hit_rate": _safe_float(summary.get("citation_hit_rate"), default=0.0),
        "retrieval_hit_rate": _safe_float(summary.get("retrieval_hit_rate"), default=0.0),
        "abstain_precision": _safe_float(summary.get("abstain_precision"), default=0.0),
        "false_memory_rate": _safe_float(summary.get("false_memory_rate"), default=0.0),
        "routine_over_recall_rate": _safe_float(summary.get("routine_over_recall_rate"), default=0.0),
    }
    failures: list[str] = []
    if metrics["decision_accuracy"] < float(args.min_decision_accuracy):
        failures.append("decision_accuracy_below_floor")
    if metrics["citation_hit_rate"] < float(args.min_citation_hit_rate):
        failures.append("citation_hit_rate_below_floor")
    if metrics["retrieval_hit_rate"] < float(args.min_retrieval_hit_rate):
        failures.append("retrieval_hit_rate_below_floor")
    if metrics["abstain_precision"] < float(args.min_abstain_precision):
        failures.append("abstain_precision_below_floor")
    if metrics["false_memory_rate"] > float(args.max_false_memory_rate):
        failures.append("false_memory_rate_exceeded")
    if metrics["routine_over_recall_rate"] > float(args.max_routine_over_recall_rate):
        failures.append("routine_over_recall_rate_exceeded")
    verdict = "PASS" if not failures else "FAIL"
    return verdict, failures, metrics


def _human_quality_gate(
    summary: dict[str, Any],
    records: list[dict[str, Any]],
    question_summary: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[str, list[str], dict[str, float], dict[str, Any]]:
    failures: list[str] = []
    alignment = _alignment_metrics(summary, records)
    latency = _latency_metrics(summary)
    defects_by_tag: dict[str, int] = {}
    blocking_defect_cases = 0
    total_defect_cases = 0
    response_parrot_cases = 0
    related_context_cases = 0

    top_failure_examples: list[dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        case = row.get("case") if isinstance(row.get("case"), dict) else {}
        defect_tags = [str(item).strip() for item in list(row.get("defect_tags") or []) if str(item).strip()]
        blocking_tags = [str(item).strip() for item in list(row.get("blocking_defect_tags") or []) if str(item).strip()]
        if defect_tags:
            total_defect_cases += 1
            for tag in defect_tags:
                defects_by_tag[tag] = defects_by_tag.get(tag, 0) + 1
        if blocking_tags:
            blocking_defect_cases += 1
            if len(top_failure_examples) < 5:
                top_failure_examples.append(
                    {
                        "case_id": str(case.get("case_id") or ""),
                        "question": str(case.get("query") or ""),
                        "answer": str(row.get("reply_text") or ""),
                        "defect_tags": sorted(set(blocking_tags)),
                    }
                )
        if "response_parrot_format" in defect_tags:
            response_parrot_cases += 1
        if "unrelated_related_context_insertion" in defect_tags:
            related_context_cases += 1

    question_decision = str(question_summary.get("decision") or "").strip().upper()
    if question_decision != "PASS":
        failures.append("question_quality_validator_failed")

    alignment_missing_cases = _safe_int(alignment["supported_non_routine_alignment_missing_cases"], default=0)
    if alignment_missing_cases > 0:
        failures.append("supported_non_routine_alignment_missing")
    if alignment["relevance_aligned_hit_rate"] < float(args.min_relevance_aligned_hit_rate):
        failures.append("relevance_aligned_hit_rate_below_floor")
    if alignment["avg_retrieved_atoms_supported_non_routine"] > float(args.max_avg_retrieved_atoms):
        failures.append("avg_retrieved_atoms_supported_non_routine_exceeded")
    if alignment["p95_retrieved_atoms_supported_non_routine"] > float(args.max_p95_retrieved_atoms):
        failures.append("p95_retrieved_atoms_supported_non_routine_exceeded")
    evidence_precision_at_k = float(alignment["evidence_precision_at_k"])
    junk_rate_at_k = float(alignment["junk_rate_at_k"])
    conflict_coverage = float(alignment["conflict_coverage"])
    if not math.isfinite(evidence_precision_at_k):
        evidence_precision_at_k = -1.0
    if not math.isfinite(junk_rate_at_k):
        junk_rate_at_k = float("inf")
    if not math.isfinite(conflict_coverage):
        conflict_coverage = -1.0
    alignment["evidence_precision_at_k"] = evidence_precision_at_k
    alignment["junk_rate_at_k"] = junk_rate_at_k
    alignment["conflict_coverage"] = conflict_coverage
    if evidence_precision_at_k < float(args.min_evidence_precision_at_k):
        failures.append("evidence_precision_at_k_below_floor")
    if junk_rate_at_k > float(args.max_junk_rate_at_k):
        failures.append("junk_rate_at_k_exceeded")
    if conflict_coverage < float(args.min_conflict_coverage):
        failures.append("conflict_coverage_below_floor")
    if latency["memory_ms_p95"] > float(args.max_memory_p95_ms):
        failures.append("memory_ms_p95_exceeded")
    if latency["model_ms_p95"] > float(args.max_model_p95_ms):
        failures.append("model_ms_p95_exceeded")
    if latency["total_ms_p95"] > float(args.max_total_p95_ms):
        failures.append("total_ms_p95_exceeded")
    if blocking_defect_cases > int(args.max_blocking_defect_cases):
        failures.append("blocking_defect_cases_exceeded")
    if response_parrot_cases > 0:
        failures.append("response_parrot_cases_present")
    if related_context_cases > 0:
        failures.append("unrelated_related_context_cases_present")

    metrics: dict[str, float] = {
        **alignment,
        "defect_case_count": float(total_defect_cases),
        "blocking_defect_cases": float(blocking_defect_cases),
        "response_parrot_cases": float(response_parrot_cases),
        "unrelated_related_context_cases": float(related_context_cases),
        "event_grade_question_rate": _safe_float(question_summary.get("event_grade_question_rate"), default=0.0),
        "fragment_question_rate": _safe_float(question_summary.get("fragment_question_rate"), default=0.0),
        "memory_ms_p95": float(latency["memory_ms_p95"]),
        "model_ms_p95": float(latency["model_ms_p95"]),
        "total_ms_p95": float(latency["total_ms_p95"]),
    }
    quality_details: dict[str, Any] = {
        "defect_case_count": total_defect_cases,
        "blocking_defect_cases": blocking_defect_cases,
        "defect_tag_counts": defects_by_tag,
        "top_failure_examples": top_failure_examples,
        "question_summary": question_summary,
        "latency_ms_p95": latency,
    }
    verdict = "PASS" if not failures else "FAIL"
    return verdict, failures, metrics, quality_details


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-click local eval: optional import -> responder eval -> dual-verdict gate -> readout."
    )
    parser.add_argument("--input", default="", help="Optional path to conversations export JSON.")
    parser.add_argument(
        "--store",
        default=str(REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3"),
        help="Memory store path.",
    )
    parser.add_argument("--run-dir", default="", help="Output directory root.")
    parser.add_argument("--skip-import", action="store_true", help="Skip import step and use existing store.")
    parser.add_argument("--requested-cases", type=int, default=6)
    parser.add_argument("--scan-budget", type=int, default=600000)
    parser.add_argument(
        "--eval-surface",
        choices=["responder"],
        default="responder",
        help="Judged eval surface (responder path only).",
    )
    parser.add_argument(
        "--fixture-mode",
        choices=["basic", "trust-v2", "trust-v3"],
        default="trust-v3",
        help="Fixture generation mode for eval.",
    )
    parser.add_argument("--batch-size", type=int, default=2, help="Legacy no-op (kept for CLI compatibility).")
    parser.add_argument("--batch-pause-ms", type=int, default=100, help="Legacy no-op (kept for CLI compatibility).")
    parser.add_argument("--readout-max-cases", type=int, default=12)
    parser.add_argument("--disable-episodes", action="store_true", help="Disable episode-card retrieval during eval.")
    parser.add_argument("--episode-cards", default="", help="Optional episode_cards json path to use for eval.")
    parser.add_argument("--skip-episode-build", action="store_true", help="Skip building episode cards before eval.")
    parser.add_argument("--responder-provider", choices=["mock", "lmstudio", "openai"], default="mock")
    parser.add_argument("--responder-provider-base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--responder-provider-chat-path", default="/api/v1/chat")
    parser.add_argument("--responder-model", default="qwen/qwen3-32b")
    parser.add_argument("--responder-openai-api-key", default="")
    parser.add_argument("--responder-openai-base-url", default="https://api.openai.com")
    parser.add_argument("--responder-timeout-s", type=float, default=60.0)
    parser.add_argument(
        "--max-weak-question-cases",
        type=int,
        default=0,
        help="Maximum allowed weak supported truthset prompts in quality validation.",
    )
    parser.add_argument("--min-decision-accuracy", type=float, default=0.90)
    parser.add_argument("--min-citation-hit-rate", type=float, default=0.50)
    parser.add_argument("--min-retrieval-hit-rate", type=float, default=0.50)
    parser.add_argument("--min-abstain-precision", type=float, default=0.60)
    parser.add_argument("--max-false-memory-rate", type=float, default=0.0)
    parser.add_argument("--max-routine-over-recall-rate", type=float, default=0.0)
    parser.add_argument("--min-relevance-aligned-hit-rate", type=float, default=0.95)
    parser.add_argument("--max-avg-retrieved-atoms", type=float, default=24.0)
    parser.add_argument("--max-p95-retrieved-atoms", type=float, default=24.0)
    parser.add_argument("--min-evidence-precision-at-k", type=float, default=0.0)
    parser.add_argument("--max-junk-rate-at-k", type=float, default=1.0)
    parser.add_argument("--min-conflict-coverage", type=float, default=0.0)
    parser.add_argument("--max-blocking-defect-cases", type=int, default=0)
    parser.add_argument("--max-memory-p95-ms", type=float, default=2000.0)
    parser.add_argument("--max-model-p95-ms", type=float, default=15000.0)
    parser.add_argument("--max-total-p95-ms", type=float, default=18000.0)
    parser.add_argument(
        "--efficiency-led-surface",
        choices=["none", "latency", "tokens"],
        default="none",
        help="Enable median-of-3 regression guard using baseline/candidate summaries.",
    )
    parser.add_argument(
        "--baseline-summary",
        action="append",
        default=[],
        help="Path to baseline summary.json (repeat; requires >=3 when efficiency-led-surface is set).",
    )
    parser.add_argument(
        "--candidate-summary",
        action="append",
        default=[],
        help="Path to additional candidate summary.json (repeat; current run summary counts as one candidate run).",
    )
    parser.add_argument(
        "--max-non-led-regression-pct",
        type=float,
        default=3.0,
        help="Maximum allowed regression (%) for the non-led metric family.",
    )
    parser.add_argument(
        "--frozen-waiver",
        action="append",
        default=[],
        help="Frozen waiver declaration: reason|blocker_ref|scope.",
    )
    args = parser.parse_args()

    store_path = Path(args.store).expanduser().resolve()
    input_path = Path(args.input).expanduser().resolve() if args.input else _default_export_path()
    run_dir = (
        Path(args.run_dir).expanduser().resolve()
        if args.run_dir
        else REPO_ROOT / "runtime" / "evals" / f"oneclick_{_stamp()}"
    )
    logs_dir = run_dir / "logs"
    eval_dir = run_dir / "eval"
    import_dir = run_dir / "import"
    episodes_dir = run_dir / "episodes"
    quality_dir = run_dir / "question_quality"
    run_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_import and not input_path.exists():
        print(f"error=input path not found: {input_path}")
        if not args.input:
            tried = "; ".join(str(item) for item in _default_export_candidates())
            print(f"searched_paths={tried}")
        return 2

    if args.skip_import and not store_path.exists():
        print(f"error=store path not found: {store_path}")
        return 2

    steps: list[StepResult] = []
    python_exe = sys.executable

    if not args.skip_import:
        import_cmd = [
            python_exe,
            str(REPO_ROOT / "tools" / "import_memories.py"),
            "--input",
            str(input_path),
            "--store",
            str(store_path),
            "--out-dir",
            str(import_dir),
        ]
        steps.append(_run_step("import_memories", import_cmd, logs_dir / "01_import.log"))
        if steps[-1].status != "PASS":
            manifest_path = run_dir / "oneclick_manifest.json"
            _write_manifest(
                path=manifest_path,
                decision="FAIL",
                store_path=store_path,
                run_dir=run_dir,
                skipped_import=False,
                input_path=input_path,
                steps=steps,
                artifacts={},
            )
            print("decision=FAIL")
            print(f"manifest={manifest_path}")
            return 2

    episode_cards_path: Path | None = None
    episode_readout_path: Path | None = None
    episode_review_tsv_path: Path | None = None
    episode_review_guide_path: Path | None = None
    episode_review_meta_path: Path | None = None
    if not args.disable_episodes:
        if str(args.episode_cards).strip():
            episode_cards_path = Path(args.episode_cards).expanduser().resolve()
            if not episode_cards_path.exists():
                print(f"error=episode cards path not found: {episode_cards_path}")
                return 2
        elif not args.skip_episode_build:
            episodes_dir.mkdir(parents=True, exist_ok=True)
            generated_episode_path = episodes_dir / "episode_cards.json"
            episode_cmd = [
                python_exe,
                str(REPO_ROOT / "tools" / "build_episode_cards.py"),
                "--memories",
                str(store_path),
                "--out",
                str(generated_episode_path),
            ]
            steps.append(_run_step("build_episode_cards", episode_cmd, logs_dir / "02a_episode_cards.log"))
            if steps[-1].status != "PASS":
                manifest_path = run_dir / "oneclick_manifest.json"
                _write_manifest(
                    path=manifest_path,
                    decision="FAIL",
                    store_path=store_path,
                    run_dir=run_dir,
                    skipped_import=bool(args.skip_import),
                    input_path=None if args.skip_import else input_path,
                    steps=steps,
                    artifacts={},
                )
                print("decision=FAIL")
                print(f"manifest={manifest_path}")
                return 2
            episode_cards_path = generated_episode_path
        if episode_cards_path is not None:
            episodes_dir.mkdir(parents=True, exist_ok=True)
            episode_readout_path = episodes_dir / "episode_cards.readout.md"
            episode_readout_cmd = [
                python_exe,
                str(REPO_ROOT / "tools" / "build_episode_card_readout.py"),
                "--episodes",
                str(episode_cards_path),
                "--out",
                str(episode_readout_path),
            ]
            steps.append(_run_step("build_episode_card_readout", episode_readout_cmd, logs_dir / "02b_episode_readout.log"))
            if steps[-1].status != "PASS":
                manifest_path = run_dir / "oneclick_manifest.json"
                _write_manifest(
                    path=manifest_path,
                    decision="FAIL",
                    store_path=store_path,
                    run_dir=run_dir,
                    skipped_import=bool(args.skip_import),
                    input_path=None if args.skip_import else input_path,
                    steps=steps,
                    artifacts={},
                )
                print("decision=FAIL")
                print(f"manifest={manifest_path}")
                return 2

            episode_review_dir = episodes_dir / "review_pack"
            episode_review_cmd = [
                python_exe,
                str(REPO_ROOT / "tools" / "build_episode_review_pack.py"),
                "--episodes",
                str(episode_cards_path),
                "--out-dir",
                str(episode_review_dir),
            ]
            steps.append(_run_step("build_episode_review_pack", episode_review_cmd, logs_dir / "02c_episode_review_pack.log"))
            if steps[-1].status != "PASS":
                manifest_path = run_dir / "oneclick_manifest.json"
                _write_manifest(
                    path=manifest_path,
                    decision="FAIL",
                    store_path=store_path,
                    run_dir=run_dir,
                    skipped_import=bool(args.skip_import),
                    input_path=None if args.skip_import else input_path,
                    steps=steps,
                    artifacts={},
                )
                print("decision=FAIL")
                print(f"manifest={manifest_path}")
                return 2
            episode_review_tsv_path = episode_review_dir / "episode_cards.review.tsv"
            episode_review_guide_path = episode_review_dir / "episode_cards.review.md"
            episode_review_meta_path = episode_review_dir / "episode_cards.review_meta.json"

    eval_log = logs_dir / "02_eval.log"
    eval_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_responder_eval.py"),
        "--memories",
        str(store_path),
        "--requested-cases",
        str(max(1, int(args.requested_cases))),
        "--scan-budget",
        str(max(1, int(args.scan_budget))),
        "--fixture-mode",
        str(args.fixture_mode),
        "--out-dir",
        str(eval_dir),
        "--provider",
        str(args.responder_provider),
        "--provider-base-url",
        str(args.responder_provider_base_url),
        "--provider-chat-path",
        str(args.responder_provider_chat_path),
        "--provider-model",
        str(args.responder_model),
        "--openai-api-key",
        str(args.responder_openai_api_key),
        "--openai-base-url",
        str(args.responder_openai_base_url),
        "--timeout-s",
        str(float(args.responder_timeout_s)),
        "--min-evidence-precision-at-k",
        str(float(args.min_evidence_precision_at_k)),
        "--max-junk-rate-at-k",
        str(float(args.max_junk_rate_at_k)),
        "--min-conflict-coverage",
        str(float(args.min_conflict_coverage)),
    ]
    if args.disable_episodes:
        eval_cmd.append("--disable-episodes")
    elif episode_cards_path is not None:
        eval_cmd.extend(["--episode-cards", str(episode_cards_path)])
    steps.append(_run_step("run_responder_eval", eval_cmd, eval_log))
    if steps[-1].status != "PASS":
        manifest_path = run_dir / "oneclick_manifest.json"
        _write_manifest(
            path=manifest_path,
            decision="FAIL",
            store_path=store_path,
            run_dir=run_dir,
            skipped_import=bool(args.skip_import),
            input_path=None if args.skip_import else input_path,
            steps=steps,
            artifacts={},
        )
        print("decision=FAIL")
        print(f"manifest={manifest_path}")
        return 2

    eval_outputs = steps[-1].outputs
    truthset_path = Path(eval_outputs.get("truthset_generated_jsonl", str(eval_dir / "truthset.generated.jsonl"))).resolve()
    records_path = Path(eval_outputs.get("records_json", str(eval_dir / "records.json"))).resolve()
    summary_path = Path(eval_outputs.get("summary_json", str(eval_dir / "summary.json"))).resolve()
    quality_summary_path = (quality_dir / "question_validation_summary.json").resolve()
    quality_cases_path = (quality_dir / "question_validation_cases.json").resolve()

    quality_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "validate_truthset_questions.py"),
        "--memories",
        str(store_path),
        "--truthset",
        str(truthset_path),
        "--out-dir",
        str(quality_dir),
        "--max-weak-cases",
        str(max(0, int(args.max_weak_question_cases))),
    ]
    steps.append(_run_step("validate_truthset_questions", quality_cmd, logs_dir / "02b_question_quality.log"))
    if steps[-1].status != "PASS":
        manifest_path = run_dir / "oneclick_manifest.json"
        _write_manifest(
            path=manifest_path,
            decision="FAIL",
            store_path=store_path,
            run_dir=run_dir,
            skipped_import=bool(args.skip_import),
            input_path=None if args.skip_import else input_path,
            steps=steps,
            artifacts={},
        )
        print("decision=FAIL")
        print(f"manifest={manifest_path}")
        return 2

    try:
        eval_summary = _load_json(summary_path)
        records_payload = _load_json_any(records_path)
        question_summary = _load_json(quality_summary_path)
        question_cases_payload = _load_json_any(quality_cases_path)
    except Exception as exc:
        manifest_path = run_dir / "oneclick_manifest.json"
        _write_manifest(
            path=manifest_path,
            decision="FAIL",
            store_path=store_path,
            run_dir=run_dir,
            skipped_import=bool(args.skip_import),
            input_path=None if args.skip_import else input_path,
            steps=steps,
            artifacts={},
        )
        print(f"error=failed to read eval summary: {exc}")
        print("decision=FAIL")
        print(f"manifest={manifest_path}")
        return 2

    question_defects, question_blocking = _question_defect_map(question_cases_payload)
    records = _annotate_records_with_defects(
        records_payload,
        question_defects=question_defects,
        question_blocking=question_blocking,
    )
    records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frozen_waivers, frozen_waiver_failures = _parse_frozen_waivers(list(args.frozen_waiver or []))
    waiver_declaration = "none"
    if frozen_waivers:
        waiver_declaration = "FROZEN DUE TO exceptions declared in waivers.frozen_surface"

    safety_verdict, safety_failures, safety_metrics = _safety_gate(eval_summary, args)
    human_quality_verdict, human_quality_failures, human_quality_metrics, quality_details = _human_quality_gate(
        eval_summary,
        records,
        question_summary,
        args,
    )
    required_efficiency_metrics, required_efficiency_failures = _required_efficiency_metrics(eval_summary)
    quality_details = dict(quality_details)
    quality_details["required_efficiency_failures"] = list(required_efficiency_failures)
    if required_efficiency_failures and "required_efficiency_metric_contract_failed" not in human_quality_failures:
        human_quality_failures.append("required_efficiency_metric_contract_failed")

    efficiency_regression_decision = "PASS"
    efficiency_regression_failures: list[str] = []
    efficiency_regression_details: dict[str, Any] = {
        "led_surface": str(args.efficiency_led_surface),
        "max_non_led_regression_pct": float(args.max_non_led_regression_pct),
        "baseline_paths": [],
        "candidate_paths": [],
    }
    if str(args.efficiency_led_surface) != "none":
        baseline_paths = [Path(item).expanduser().resolve() for item in list(args.baseline_summary or []) if str(item).strip()]
        candidate_paths = [summary_path.resolve(), *[Path(item).expanduser().resolve() for item in list(args.candidate_summary or []) if str(item).strip()]]
        # Preserve order while removing duplicate summary paths.
        seen_paths: set[str] = set()
        baseline_paths_unique: list[Path] = []
        for path in baseline_paths:
            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            baseline_paths_unique.append(path)
        seen_paths = set()
        candidate_paths_unique: list[Path] = []
        for path in candidate_paths:
            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            candidate_paths_unique.append(path)
        efficiency_regression_details["baseline_paths"] = [str(path) for path in baseline_paths_unique]
        efficiency_regression_details["candidate_paths"] = [str(path) for path in candidate_paths_unique]

        baseline_metrics: list[dict[str, float]] = []
        candidate_metrics: list[dict[str, float]] = []
        load_failures: list[str] = []
        for path in baseline_paths_unique:
            try:
                payload = _load_json(path)
            except Exception:
                load_failures.append(f"baseline_summary_unreadable:{path}")
                continue
            metrics, failures = _required_efficiency_metrics(payload)
            if failures:
                load_failures.append(f"baseline_summary_metric_contract_failed:{path}:{','.join(failures)}")
                continue
            baseline_metrics.append(metrics)
        for path in candidate_paths_unique:
            try:
                payload = _load_json(path)
            except Exception:
                load_failures.append(f"candidate_summary_unreadable:{path}")
                continue
            metrics, failures = _required_efficiency_metrics(payload)
            if failures:
                load_failures.append(f"candidate_summary_metric_contract_failed:{path}:{','.join(failures)}")
                continue
            candidate_metrics.append(metrics)
        if load_failures:
            efficiency_regression_decision = "FAIL"
            efficiency_regression_failures = load_failures
        else:
            efficiency_regression_decision, efficiency_regression_failures, regression_details = _evaluate_efficiency_regression(
                baseline_runs=baseline_metrics,
                candidate_runs=candidate_metrics,
                led_surface=str(args.efficiency_led_surface),
                max_non_led_regression_pct=float(args.max_non_led_regression_pct),
            )
            efficiency_regression_details.update(regression_details)
        if efficiency_regression_decision != "PASS" and "efficiency_regression_guard_failed" not in human_quality_failures:
            human_quality_failures.append("efficiency_regression_guard_failed")
    if frozen_waiver_failures and "frozen_waiver_contract_failed" not in human_quality_failures:
        human_quality_failures.append("frozen_waiver_contract_failed")
    quality_details["frozen_waiver_failures"] = list(frozen_waiver_failures)

    human_quality_verdict = "PASS" if not human_quality_failures else "FAIL"
    gate_decision = "PASS" if safety_verdict == "PASS" and human_quality_verdict == "PASS" else "FAIL"
    gate_failures = [*list(safety_failures), *list(human_quality_failures)]
    gate_report = {
        "generated_at": _now_iso(),
        "decision": gate_decision,
        "safety_verdict": safety_verdict,
        "human_quality_verdict": human_quality_verdict,
        "safety_failures": safety_failures,
        "human_quality_failures": human_quality_failures,
        "failures": gate_failures,
        "metrics": {
            **safety_metrics,
            **human_quality_metrics,
            **required_efficiency_metrics,
        },
        "quality": quality_details,
        "waivers": {
            "waiver_declaration": waiver_declaration,
            "frozen_surface": frozen_waivers,
            "frozen_surface_contract_failures": frozen_waiver_failures,
        },
        "efficiency_regression": {
            "decision": efficiency_regression_decision,
            "failures": efficiency_regression_failures,
            "details": efficiency_regression_details,
        },
        "thresholds": {
            "min_decision_accuracy": float(args.min_decision_accuracy),
            "min_citation_hit_rate": float(args.min_citation_hit_rate),
            "min_retrieval_hit_rate": float(args.min_retrieval_hit_rate),
            "min_abstain_precision": float(args.min_abstain_precision),
            "max_false_memory_rate": float(args.max_false_memory_rate),
            "max_routine_over_recall_rate": float(args.max_routine_over_recall_rate),
            "min_relevance_aligned_hit_rate": float(args.min_relevance_aligned_hit_rate),
            "max_avg_retrieved_atoms": float(args.max_avg_retrieved_atoms),
            "max_p95_retrieved_atoms": float(args.max_p95_retrieved_atoms),
            "min_evidence_precision_at_k": float(args.min_evidence_precision_at_k),
            "max_junk_rate_at_k": float(args.max_junk_rate_at_k),
            "min_conflict_coverage": float(args.min_conflict_coverage),
            "max_blocking_defect_cases": int(args.max_blocking_defect_cases),
            "max_memory_p95_ms": float(args.max_memory_p95_ms),
            "max_model_p95_ms": float(args.max_model_p95_ms),
            "max_total_p95_ms": float(args.max_total_p95_ms),
            "max_non_led_regression_pct": float(args.max_non_led_regression_pct),
        },
        "question_quality_summary": question_summary,
    }
    contract_missing_fields = _validate_gate_report_contract(gate_report)
    if contract_missing_fields:
        if "report_contract_missing_fields" not in human_quality_failures:
            human_quality_failures.append("report_contract_missing_fields")
        human_quality_verdict = "FAIL"
        gate_decision = "FAIL"
        gate_failures = [*list(safety_failures), *list(human_quality_failures)]
        gate_report["human_quality_verdict"] = human_quality_verdict
        gate_report["decision"] = gate_decision
        gate_report["human_quality_failures"] = human_quality_failures
        gate_report["failures"] = gate_failures
        gate_report["report_contract_missing_fields"] = contract_missing_fields
    gate_report_path = run_dir / "acceptance_gate.json"
    gate_report_path.write_text(json.dumps(gate_report, indent=2) + "\n", encoding="utf-8")
    if gate_decision != "PASS":
        manifest_path = run_dir / "oneclick_manifest.json"
        _write_manifest(
            path=manifest_path,
            decision="FAIL",
            store_path=store_path,
            run_dir=run_dir,
            skipped_import=bool(args.skip_import),
            input_path=None if args.skip_import else input_path,
            steps=steps,
            artifacts={
                "summary_json": str(summary_path),
                "records_json": str(records_path),
                "truthset_generated_jsonl": str(truthset_path),
                "question_validation_summary_json": str(quality_summary_path),
                "question_validation_cases_json": str(quality_cases_path),
                "acceptance_gate_json": str(gate_report_path),
            },
        )
        print(f"acceptance_gate_json={gate_report_path}")
        print(f"safety_verdict={safety_verdict}")
        print(f"human_quality_verdict={human_quality_verdict}")
        print(f"gate_failures={','.join(gate_failures)}")
        print("decision=FAIL")
        print(f"manifest={manifest_path}")
        return 3

    readout_path = run_dir / "human_readout.md"

    readout_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "build_responder_eval_readout.py"),
        "--records",
        str(records_path),
        "--summary",
        str(summary_path),
        "--acceptance-gate",
        str(gate_report_path),
        "--question-quality-summary",
        str(quality_summary_path),
        "--out",
        str(readout_path),
        "--max-cases",
        str(max(0, int(args.readout_max_cases))),
    ]
    steps.append(_run_step("build_responder_eval_readout", readout_cmd, logs_dir / "03_readout.log"))
    if steps[-1].status != "PASS":
        manifest_path = run_dir / "oneclick_manifest.json"
        _write_manifest(
            path=manifest_path,
            decision="FAIL",
            store_path=store_path,
            run_dir=run_dir,
            skipped_import=bool(args.skip_import),
            input_path=None if args.skip_import else input_path,
            steps=steps,
            artifacts={},
        )
        print("decision=FAIL")
        print(f"manifest={manifest_path}")
        return 2

    readout_missing_sections: list[str]
    try:
        readout_missing_sections = _validate_readout_contract_text(readout_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError):
        readout_missing_sections = list(_READOUT_REQUIRED_SECTIONS)
    if readout_missing_sections:
        if "readout_contract_missing_sections" not in human_quality_failures:
            human_quality_failures.append("readout_contract_missing_sections")
        gate_failures = [*list(safety_failures), *list(human_quality_failures)]
        gate_report["human_quality_verdict"] = "FAIL"
        gate_report["decision"] = "FAIL"
        gate_report["human_quality_failures"] = human_quality_failures
        gate_report["failures"] = gate_failures
        gate_report["readout_contract_missing_sections"] = readout_missing_sections
        gate_report_path.write_text(json.dumps(gate_report, indent=2) + "\n", encoding="utf-8")
        manifest_path = run_dir / "oneclick_manifest.json"
        _write_manifest(
            path=manifest_path,
            decision="FAIL",
            store_path=store_path,
            run_dir=run_dir,
            skipped_import=bool(args.skip_import),
            input_path=None if args.skip_import else input_path,
            steps=steps,
            artifacts={
                "summary_json": str(summary_path),
                "records_json": str(records_path),
                "truthset_generated_jsonl": str(truthset_path),
                "question_validation_summary_json": str(quality_summary_path),
                "question_validation_cases_json": str(quality_cases_path),
                "acceptance_gate_json": str(gate_report_path),
                "human_readout_md": str(readout_path),
            },
        )
        print(f"acceptance_gate_json={gate_report_path}")
        print(f"safety_verdict={safety_verdict}")
        print("human_quality_verdict=FAIL")
        print(f"gate_failures={','.join(gate_failures)}")
        print("decision=FAIL")
        print(f"manifest={manifest_path}")
        return 3

    artifacts = {
        "summary_json": str(summary_path),
        "records_json": str(records_path),
        "truthset_generated_jsonl": str(truthset_path),
        "acceptance_gate_json": str(gate_report_path),
        "question_validation_summary_json": str(quality_summary_path),
        "question_validation_summary_md": str((quality_dir / "question_validation_summary.md").resolve()),
        "question_validation_cases_json": str(quality_cases_path),
        "human_readout_md": str(readout_path),
        "eval_log": str(eval_log),
    }
    if episode_cards_path is not None:
        artifacts["episode_cards_json"] = str(episode_cards_path)
    if episode_readout_path is not None:
        artifacts["episode_readout_md"] = str(episode_readout_path)
    if episode_review_tsv_path is not None:
        artifacts["episode_review_tsv"] = str(episode_review_tsv_path)
    if episode_review_guide_path is not None:
        artifacts["episode_review_guide_md"] = str(episode_review_guide_path)
    if episode_review_meta_path is not None:
        artifacts["episode_review_meta_json"] = str(episode_review_meta_path)
    manifest_path = run_dir / "oneclick_manifest.json"
    _write_manifest(
        path=manifest_path,
        decision=gate_decision,
        store_path=store_path,
        run_dir=run_dir,
        skipped_import=bool(args.skip_import),
        input_path=None if args.skip_import else input_path,
        steps=steps,
        artifacts=artifacts,
    )
    print(f"safety_verdict={safety_verdict}")
    print(f"human_quality_verdict={human_quality_verdict}")
    print(f"decision={gate_decision}")
    print(f"manifest={manifest_path}")
    for key, value in artifacts.items():
        print(f"{key}={value}")
    return 0 if gate_decision == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
