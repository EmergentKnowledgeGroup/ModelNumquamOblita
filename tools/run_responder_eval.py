#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityStore
from engine.config import active_efficiency_policy, load_config
from engine.memory import SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.responder import (
    ChatProviderConfig,
    build_provider,
    build_responder_messages,
    enforce_reply_contract,
    verify_reply_against_package,
)
from engine.runtime import (
    RuntimeSession,
    TruthsetCase,
    generate_truthset,
    load_inmemory_store_from_json,
    load_truthset_jsonl,
    plan_live_eval_workload,
    write_truthset_jsonl,
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _open_store(path: Path) -> tuple[Any, bool]:
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), False
    raise ValueError(f"unsupported memories path: {path}")


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    idx = int(round(0.95 * (len(ordered) - 1)))
    return float(ordered[max(0, min(idx, len(ordered) - 1))])


def _p50(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    idx = int(round(0.50 * (len(ordered) - 1)))
    return float(ordered[max(0, min(idx, len(ordered) - 1))])


def _ratio(numerator: float, denominator: float) -> float:
    if float(denominator) <= 0.0:
        return 0.0
    return float(numerator) / float(denominator)


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


def _first_numeric(values: list[Any], *, default: float = 0.0) -> float:
    for value in values:
        try:
            numeric = float(value)
        except Exception:
            continue
        if math.isfinite(numeric):
            return float(numeric)
    return float(default)


def _extract_usage_tokens(usage: Any) -> tuple[float, float, float]:
    payload = usage if isinstance(usage, dict) else {}
    prompt = _first_numeric(
        [
            payload.get("prompt_tokens"),
            payload.get("input_tokens"),
            payload.get("prompt_token_count"),
            payload.get("input_token_count"),
        ],
        default=0.0,
    )
    completion = _first_numeric(
        [
            payload.get("completion_tokens"),
            payload.get("output_tokens"),
            payload.get("completion_token_count"),
            payload.get("output_token_count"),
        ],
        default=0.0,
    )
    total = _first_numeric(
        [
            payload.get("total_tokens"),
            payload.get("token_count"),
        ],
        default=(prompt + completion),
    )
    if total > 0.0 and prompt <= 0.0 and completion > 0.0:
        prompt = max(0.0, total - completion)
    if total > 0.0 and completion <= 0.0 and prompt > 0.0:
        completion = max(0.0, total - prompt)
    if total <= 0.0:
        total = max(0.0, prompt + completion)
    return float(prompt), float(completion), float(total)


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


def _normalize_tokens(items: list[Any]) -> set[str]:
    out: set[str] = set()
    for item in list(items or []):
        token = str(item or "").strip()
        if token:
            out.add(token)
    return out


def _apply_efficiency_fanout_cap(
    retrieved_atom_ids: list[Any],
    *,
    enabled: bool,
    hard_cap: int,
) -> list[Any]:
    original = list(retrieved_atom_ids or [])
    cap = max(1, int(hard_cap))
    if not bool(enabled):
        return original
    normalized = [str(item).strip() for item in original if str(item).strip()]
    if len(normalized) <= cap:
        return normalized
    return normalized[:cap]


def _sanitize_retrieval_diagnostics(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    selected_items = data.get("selected")
    dropped_items = data.get("dropped")
    reason_counts_payload = data.get("dropped_reason_counts")
    selected: list[dict[str, Any]] = []
    for item in (selected_items if isinstance(selected_items, list) else [])[:24]:
        if not isinstance(item, dict):
            continue
        atom_id = str(item.get("atom_id") or "").strip()
        section = str(item.get("section") or "").strip()
        if not atom_id or not section:
            continue
        score = _safe_float(item.get("score"), default=0.0)
        if not math.isfinite(score) or score < 0.0:
            score = 0.0
        selected.append(
            {
                "atom_id": atom_id,
                "section": section,
                "score": round(score, 4),
            }
        )

    dropped: list[dict[str, Any]] = []
    for item in (dropped_items if isinstance(dropped_items, list) else [])[:24]:
        if not isinstance(item, dict):
            continue
        atom_id = str(item.get("atom_id") or "").strip()
        reason_code = str(item.get("reason_code") or "").strip()
        if not atom_id or not reason_code:
            continue
        score = item.get("score")
        entry: dict[str, Any] = {"atom_id": atom_id, "reason_code": reason_code}
        if score is not None:
            score_value = _safe_float(score, default=0.0)
            if math.isfinite(score_value) and score_value >= 0.0:
                entry["score"] = round(score_value, 4)
        dropped.append(entry)

    dropped_reason_counts: dict[str, int] = {}
    for key, value in (reason_counts_payload.items() if isinstance(reason_counts_payload, dict) else []):
        reason = str(key or "").strip()
        if not reason:
            continue
        dropped_reason_counts[reason] = dropped_reason_counts.get(reason, 0) + max(0, _safe_int(value, default=0))

    return {
        "selected": selected,
        "dropped": dropped,
        "dropped_reason_counts": dropped_reason_counts,
        "selected_count": max(len(selected), _safe_int(data.get("selected_count"), default=len(selected))),
        "dropped_count": max(len(dropped), _safe_int(data.get("dropped_count"), default=len(dropped))),
        "raw_text_included": False,
    }


_PARROT_PREFIXES = ("acknowledged:", "memory-backed response for:")
_RELATED_CONTEXT_RE = re.compile(r"\brelated context\b", re.IGNORECASE)


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
    for key in (
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
    ):
        value, present, ok = _extract_required_metric(
            sources=list(metric_sources.get(key) or []),
            default=float(default_values.get(key, 0.0)),
        )
        metrics[key] = float(value)
        presence[key] = bool(present)
        parse_ok[key] = bool(ok)
    failures: list[str] = []
    for key, value in metrics.items():
        if not presence.get(key, False):
            failures.append(f"{key}_missing")
            continue
        if not parse_ok.get(key, False):
            failures.append(f"{key}_not_numeric")
            continue
        if not math.isfinite(float(value)):
            failures.append(f"{key}_non_finite")
    return metrics, failures


def _build_acceptance_gate(summary: dict[str, Any], records: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    retrieval = summary.get("retrieval") if isinstance(summary.get("retrieval"), dict) else {}
    latency = summary.get("latency_ms") if isinstance(summary.get("latency_ms"), dict) else {}

    safety_metrics = {
        "decision_accuracy": _safe_float(summary.get("decision_accuracy"), default=0.0),
        "citation_hit_rate": _safe_float(summary.get("citation_hit_rate"), default=0.0),
        "retrieval_hit_rate": _safe_float(summary.get("retrieval_hit_rate"), default=0.0),
        "abstain_precision": _safe_float(summary.get("abstain_precision"), default=0.0),
        "false_memory_rate": _safe_float(summary.get("false_memory_rate"), default=0.0),
        "routine_over_recall_rate": _safe_float(summary.get("routine_over_recall_rate"), default=0.0),
    }
    safety_failures: list[str] = []
    if safety_metrics["decision_accuracy"] < float(args.min_decision_accuracy):
        safety_failures.append("decision_accuracy_below_floor")
    if safety_metrics["citation_hit_rate"] < float(args.min_citation_hit_rate):
        safety_failures.append("citation_hit_rate_below_floor")
    if safety_metrics["retrieval_hit_rate"] < float(args.min_retrieval_hit_rate):
        safety_failures.append("retrieval_hit_rate_below_floor")
    if safety_metrics["abstain_precision"] < float(args.min_abstain_precision):
        safety_failures.append("abstain_precision_below_floor")
    if safety_metrics["false_memory_rate"] > float(args.max_false_memory_rate):
        safety_failures.append("false_memory_rate_exceeded")
    if safety_metrics["routine_over_recall_rate"] > float(args.max_routine_over_recall_rate):
        safety_failures.append("routine_over_recall_rate_exceeded")
    safety_verdict = "PASS" if not safety_failures else "FAIL"

    defect_tag_counts: dict[str, int] = {}
    top_failure_examples: list[dict[str, Any]] = []
    blocking_defect_cases = 0
    defect_case_count = 0
    response_parrot_cases = 0
    related_context_cases = 0
    for row in list(records or []):
        if not isinstance(row, dict):
            continue
        verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
        case = row.get("case") if isinstance(row.get("case"), dict) else {}
        defect_tags: list[str] = []
        for reason in list(verification.get("reasons") or []):
            cleaned = str(reason).strip()
            if not cleaned:
                continue
            defect_tags.append(f"verifier:{cleaned}")
        reply_text = str(row.get("reply_text") or "").strip()
        lower_reply = reply_text.lower()
        if any(lower_reply.startswith(prefix) for prefix in _PARROT_PREFIXES):
            defect_tags.append("response_parrot_format")
            response_parrot_cases += 1
        if _RELATED_CONTEXT_RE.search(reply_text):
            defect_tags.append("unrelated_related_context_insertion")
            related_context_cases += 1
        deduped_tags = sorted(set(defect_tags))
        row["defect_tags"] = deduped_tags
        row["blocking_defect_tags"] = deduped_tags
        if deduped_tags:
            defect_case_count += 1
            blocking_defect_cases += 1
            for tag in deduped_tags:
                defect_tag_counts[tag] = defect_tag_counts.get(tag, 0) + 1
            if len(top_failure_examples) < 5:
                top_failure_examples.append(
                    {
                        "case_id": str(case.get("case_id") or ""),
                        "question": str(case.get("query") or ""),
                        "answer": reply_text,
                        "defect_tags": deduped_tags,
                    }
                )

    human_quality_metrics = {
        "supported_non_routine_alignment_missing_cases": _safe_float(
            retrieval.get("supported_non_routine_alignment_missing_cases"),
            default=0.0,
        ),
        "relevance_aligned_hit_rate": _safe_float(
            retrieval.get("supported_non_routine_relevance_aligned_hit_rate"),
            default=_safe_float(summary.get("relevance_aligned_hit_rate"), default=0.0),
        ),
        "p95_retrieved_atoms_supported_non_routine": _safe_float(
            retrieval.get("supported_non_routine_p95_retrieved_atoms"),
            default=_safe_float(retrieval.get("p95_retrieved_atoms"), default=0.0),
        ),
        "evidence_precision_at_k": _safe_float(
            retrieval.get("evidence_precision_at_k"),
            default=0.0,
        ),
        "junk_rate_at_k": _safe_float(
            retrieval.get("junk_rate_at_k"),
            default=0.0,
        ),
        "conflict_coverage": _safe_float(
            retrieval.get("conflict_coverage"),
            default=1.0,
        ),
        "memory_ms_p95": _safe_float(latency.get("memory_p95"), default=0.0),
        "model_ms_p95": _safe_float(latency.get("model_p95"), default=0.0),
        "total_ms_p95": _safe_float(latency.get("total_p95"), default=0.0),
        "defect_case_count": float(defect_case_count),
        "blocking_defect_cases": float(blocking_defect_cases),
        "response_parrot_cases": float(response_parrot_cases),
        "unrelated_related_context_cases": float(related_context_cases),
    }
    human_quality_failures: list[str] = []
    if _safe_int(human_quality_metrics["supported_non_routine_alignment_missing_cases"], default=0) > 0:
        human_quality_failures.append("supported_non_routine_alignment_missing")
    if human_quality_metrics["relevance_aligned_hit_rate"] < float(args.min_relevance_aligned_hit_rate):
        human_quality_failures.append("relevance_aligned_hit_rate_below_floor")
    if human_quality_metrics["p95_retrieved_atoms_supported_non_routine"] > float(args.max_p95_retrieved_atoms):
        human_quality_failures.append("p95_retrieved_atoms_supported_non_routine_exceeded")
    if human_quality_metrics["evidence_precision_at_k"] < float(args.min_evidence_precision_at_k):
        human_quality_failures.append("evidence_precision_at_k_below_floor")
    if human_quality_metrics["junk_rate_at_k"] > float(args.max_junk_rate_at_k):
        human_quality_failures.append("junk_rate_at_k_exceeded")
    if human_quality_metrics["conflict_coverage"] < float(args.min_conflict_coverage):
        human_quality_failures.append("conflict_coverage_below_floor")
    if human_quality_metrics["memory_ms_p95"] > float(args.max_memory_p95_ms):
        human_quality_failures.append("memory_ms_p95_exceeded")
    if human_quality_metrics["model_ms_p95"] > float(args.max_model_p95_ms):
        human_quality_failures.append("model_ms_p95_exceeded")
    if human_quality_metrics["total_ms_p95"] > float(args.max_total_p95_ms):
        human_quality_failures.append("total_ms_p95_exceeded")
    if blocking_defect_cases > int(args.max_blocking_defect_cases):
        human_quality_failures.append("blocking_defect_cases_exceeded")
    if response_parrot_cases > 0:
        human_quality_failures.append("response_parrot_cases_present")
    if related_context_cases > 0:
        human_quality_failures.append("unrelated_related_context_cases_present")
    required_efficiency_metrics, required_efficiency_failures = _required_efficiency_metrics(summary)
    if required_efficiency_failures:
        human_quality_failures.append("required_efficiency_metric_contract_failed")
    human_quality_verdict = "PASS" if not human_quality_failures else "FAIL"

    decision = "PASS" if safety_verdict == "PASS" and human_quality_verdict == "PASS" else "FAIL"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "safety_verdict": safety_verdict,
        "human_quality_verdict": human_quality_verdict,
        "safety_failures": safety_failures,
        "human_quality_failures": human_quality_failures,
        "failures": [*list(safety_failures), *list(human_quality_failures)],
        "metrics": {**safety_metrics, **human_quality_metrics, **required_efficiency_metrics},
        "quality": {
            "defect_case_count": defect_case_count,
            "blocking_defect_cases": blocking_defect_cases,
            "defect_tag_counts": defect_tag_counts,
            "top_failure_examples": top_failure_examples,
            "required_efficiency_failures": required_efficiency_failures,
        },
        "thresholds": {
            "min_decision_accuracy": float(args.min_decision_accuracy),
            "min_citation_hit_rate": float(args.min_citation_hit_rate),
            "min_retrieval_hit_rate": float(args.min_retrieval_hit_rate),
            "min_abstain_precision": float(args.min_abstain_precision),
            "max_false_memory_rate": float(args.max_false_memory_rate),
            "max_routine_over_recall_rate": float(args.max_routine_over_recall_rate),
            "min_relevance_aligned_hit_rate": float(args.min_relevance_aligned_hit_rate),
            "max_p95_retrieved_atoms": float(args.max_p95_retrieved_atoms),
            "min_evidence_precision_at_k": float(args.min_evidence_precision_at_k),
            "max_junk_rate_at_k": float(args.max_junk_rate_at_k),
            "min_conflict_coverage": float(args.min_conflict_coverage),
            "max_memory_p95_ms": float(args.max_memory_p95_ms),
            "max_model_p95_ms": float(args.max_model_p95_ms),
            "max_total_p95_ms": float(args.max_total_p95_ms),
            "max_blocking_defect_cases": int(args.max_blocking_defect_cases),
        },
    }


def _truthset_case_dict(case: TruthsetCase) -> dict[str, Any]:
    payload = case.to_dict()
    # Avoid huge payloads in records: query + key expectations only.
    keep = {
        "case_id",
        "case_type",
        "fixture_family",
        "query",
        "expected_decision",
        "expected_atom_ids",
        "expected_citations",
        "retrieval_query",
        "high_risk",
    }
    return {k: payload.get(k) for k in keep}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run truthset eval using context-package(v2) + external responder model.")
    parser.add_argument("--memories", required=True, help="Path to sqlite store or memory json file.")
    parser.add_argument("--truthset", default="", help="Optional truthset.jsonl path.")
    parser.add_argument("--config", default="", help="Optional config JSON path (efficiency policy consumer).")
    parser.add_argument("--out-dir", default="", help="Output directory for eval artifacts.")
    parser.add_argument("--requested-cases", type=int, default=24, help="Requested number of eval cases.")
    parser.add_argument("--scan-budget", type=int, default=600000, help="Workload scan budget in scan-ops.")
    parser.add_argument("--supported-ratio", type=float, default=0.67)
    parser.add_argument(
        "--fixture-mode",
        choices=["basic", "trust-v2", "trust-v3"],
        default="trust-v3",
        help="Fixture family generation mode when auto-generating truthset.",
    )
    parser.add_argument("--package-version", default="v2", choices=["v1", "v2"])
    parser.add_argument("--memory-preference", default="auto", choices=["auto", "chat_first", "memory_assist"])
    parser.add_argument("--render-citations", action="store_true", help="Render citations in final reply (display toggle).")
    parser.add_argument("--disable-episodes", action="store_true", help="Disable episode-card retrieval path for this eval.")
    parser.add_argument("--episode-cards", default="", help="Optional episode_cards json path to use for eval.")
    parser.add_argument("--episode-top-k", type=int, default=2, help="Episode candidate count before score threshold.")
    parser.add_argument("--episode-min-score", type=float, default=0.56, help="Episode score threshold [0..1].")
    parser.add_argument("--provider", default="mock", choices=["mock", "lmstudio", "openai"])
    parser.add_argument("--provider-base-url", default=os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234"))
    parser.add_argument("--provider-chat-path", default=os.getenv("LMSTUDIO_CHAT_PATH", "/api/v1/chat"))
    parser.add_argument("--provider-model", default=os.getenv("LMSTUDIO_MODEL", "qwen/qwen3-32b"))
    parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--openai-base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"))
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--readout-max-cases", type=int, default=24)
    parser.add_argument("--fail-on-gate", action="store_true")
    parser.add_argument("--min-decision-accuracy", type=float, default=0.90)
    parser.add_argument("--min-citation-hit-rate", type=float, default=0.50)
    parser.add_argument("--min-retrieval-hit-rate", type=float, default=0.50)
    parser.add_argument("--min-abstain-precision", type=float, default=0.60)
    parser.add_argument("--max-false-memory-rate", type=float, default=0.0)
    parser.add_argument("--max-routine-over-recall-rate", type=float, default=0.0)
    parser.add_argument("--min-relevance-aligned-hit-rate", type=float, default=0.95)
    parser.add_argument("--max-p95-retrieved-atoms", type=float, default=24.0)
    parser.add_argument("--min-evidence-precision-at-k", type=float, default=0.0)
    parser.add_argument("--max-junk-rate-at-k", type=float, default=1.0)
    parser.add_argument("--min-conflict-coverage", type=float, default=0.0)
    parser.add_argument("--max-memory-p95-ms", type=float, default=2000.0)
    parser.add_argument("--max-model-p95-ms", type=float, default=15000.0)
    parser.add_argument("--max-total-p95-ms", type=float, default=18000.0)
    parser.add_argument("--max-blocking-defect-cases", type=int, default=0)
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else REPO_ROOT / "runtime" / "evals" / f"responder_{_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    truthset_out = out_dir / "truthset.generated.jsonl"
    records_path = out_dir / "records.json"
    summary_path = out_dir / "summary.json"
    acceptance_gate_path = out_dir / "acceptance_gate.json"
    readout_path = out_dir / "human_readout.md"

    store, close_store = _open_store(memories_path)
    try:
        cfg = None
        efficiency_policy = None
        if str(args.config).strip():
            config_path = Path(args.config).expanduser().resolve()
            if not config_path.exists():
                print(f"error=config path not found: {config_path}")
                return 2
            cfg = load_config(config_path)
            efficiency_policy = active_efficiency_policy(cfg)
        atoms = len(store.list_atoms())
        plan = plan_live_eval_workload(
            atom_count=atoms,
            requested_cases=int(args.requested_cases),
            scan_budget=int(args.scan_budget),
        )
        episode_cards_path = ""
        if not bool(args.disable_episodes) and str(args.episode_cards).strip():
            episode_cards_path = str(Path(args.episode_cards).expanduser().resolve())

        truthset_path = Path(args.truthset).expanduser().resolve() if str(args.truthset).strip() else None
        generated_truthset_path: Path
        if truthset_path is not None and truthset_path.exists():
            generated_truthset_path = truthset_path
            cases = load_truthset_jsonl(truthset_path)
        else:
            cases = generate_truthset(
                store,
                total_cases=int(plan.effective_cases),
                supported_ratio=float(args.supported_ratio),
                fixture_mode=str(args.fixture_mode),
            )
            write_truthset_jsonl(cases, truthset_out)
            generated_truthset_path = truthset_out
        cases = list(cases or [])[: int(plan.effective_cases)]

        retriever = MemoryRetriever(store, config=cfg)
        runtime = RuntimeSession(
            retriever=retriever,
            verifier=ClaimVerifier(),
            continuity_store=ContinuityStore(),
            config=cfg,
            enable_writeback=False,
            episode_cards_path=episode_cards_path or None,
            episode_top_k=int(args.episode_top_k),
            episode_min_score=float(args.episode_min_score),
        )
        try:
            provider = build_provider(
                ChatProviderConfig(
                    provider=str(args.provider),
                    base_url=str(args.provider_base_url),
                    api_key=str(args.openai_api_key),
                    chat_path=str(args.provider_chat_path),
                )
            )

            records: list[dict[str, Any]] = []
            memory_ms_values: list[float] = []
            model_ms_values: list[float] = []
            total_ms_values: list[float] = []
            prompt_tokens_values: list[float] = []
            completion_tokens_values: list[float] = []
            total_tokens_values: list[float] = []
            retrieved_atom_counts: list[int] = []
            evidence_counts: list[int] = []
            service_correct = 0
            model_verified_ok = 0
            inferred_correct = 0

            for case in list(cases or []):
                if not isinstance(case, TruthsetCase):
                    continue
                started = time.perf_counter()
                pkg = runtime.build_context_package(
                    case.query,
                    high_risk=bool(case.high_risk),
                    memory_preference=str(args.memory_preference),
                    session_id=None,
                    package_version=str(args.package_version),
                    retrieval_query=case.retrieval_query,
                    retrieval_override=case.build_retrieval_override(
                        invoker="tools.run_responder_eval",
                        scope="truthset_eval",
                    ),
                    render_citations=bool(args.render_citations),
                )
                timing = pkg.get("timing_ms") if isinstance(pkg.get("timing_ms"), dict) else {}
                memory_ms = float(timing.get("build_ms") or 0.0)
                retrieval_stats = pkg.get("retrieval_stats") if isinstance(pkg.get("retrieval_stats"), dict) else {}
                retrieval_diagnostics = _sanitize_retrieval_diagnostics(
                    retrieval_stats.get("retrieval_diagnostics")
                )
                retrieved_atom_ids = _apply_efficiency_fanout_cap(
                    list(retrieval_stats.get("retrieved_atom_ids") or []),
                    enabled=bool(efficiency_policy.enabled) if efficiency_policy is not None else False,
                    hard_cap=int(efficiency_policy.fanout_hard_cap) if efficiency_policy is not None else 1,
                )
                retrieved_atom_count = len(retrieved_atom_ids)
                evidence_count = len([item for item in list(pkg.get("ltm_evidence") or []) if isinstance(item, dict)])
                service_verdict = pkg.get("service_verdict") if isinstance(pkg.get("service_verdict"), dict) else {}
                service_citations = [
                    str(item).strip()
                    for item in list(service_verdict.get("citations") or [])
                    if str(item).strip()
                ]
                package_evidence_citations: list[str] = []
                for item in list(pkg.get("ltm_evidence") or []):
                    if not isinstance(item, dict):
                        continue
                    for citation in list(item.get("citations") or []):
                        token = str(citation).strip()
                        if token:
                            package_evidence_citations.append(token)

                messages = build_responder_messages(pkg)
                resp = provider.chat(
                    messages=messages,
                    model=str(args.provider_model),
                    timeout_s=float(args.timeout_s),
                )
                reply_text_raw = str(resp.text or "").strip()
                reply_text = enforce_reply_contract(pkg, reply_text_raw)
                verified = verify_reply_against_package(pkg, reply_text)
                total_ms = (time.perf_counter() - started) * 1000.0
                prompt_tokens, completion_tokens, total_tokens = _extract_usage_tokens(resp.usage)

                expected = str(case.expected_decision or "").strip().upper()
                service_decision = str((pkg.get("service_verdict") or {}).get("decision") or "").strip().upper()
                is_routine = str(case.case_type or "") == "routine_chat"
                if is_routine and expected == "PASS" and service_decision in {"PASS", "NO_MEMORY"}:
                    service_correct += 1
                elif expected and service_decision == expected:
                    service_correct += 1
                if verified.ok:
                    model_verified_ok += 1
                inferred = str(verified.inferred_decision or "").strip().upper()
                if is_routine and expected == "PASS" and inferred in {"PASS", "NO_MEMORY"}:
                    inferred_correct += 1
                elif expected and inferred == expected:
                    inferred_correct += 1

                memory_ms_values.append(memory_ms)
                model_ms_values.append(float(resp.latency_ms))
                total_ms_values.append(float(total_ms))
                prompt_tokens_values.append(float(prompt_tokens))
                completion_tokens_values.append(float(completion_tokens))
                total_tokens_values.append(float(total_tokens))
                retrieved_atom_counts.append(int(retrieved_atom_count))
                evidence_counts.append(int(evidence_count))

                compact_evidence = []
                for item in list(pkg.get("ltm_evidence") or [])[:4]:
                    if isinstance(item, dict):
                        compact_evidence.append(
                            {
                                "summary": item.get("summary"),
                                "citations": list(item.get("citations") or [])[:3],
                                "role_hint": item.get("role_hint"),
                                "kind": item.get("kind"),
                            }
                        )

                records.append(
                    {
                        "case": _truthset_case_dict(case),
                        "service_decision": service_decision,
                        "model": {"provider": resp.provider, "model": resp.model},
                        "latency_ms": {
                            "memory_ms": memory_ms,
                            "model_ms": float(resp.latency_ms),
                            "total_ms": float(total_ms),
                        },
                        "tokens": {
                            "prompt_tokens": float(prompt_tokens),
                            "completion_tokens": float(completion_tokens),
                            "total_tokens": float(total_tokens),
                        },
                        "retrieval": {
                            "retrieved_atom_count": int(retrieved_atom_count),
                            "evidence_count": int(evidence_count),
                            "memory_route": str(retrieval_stats.get("memory_route") or ""),
                            "memory_mode": str(retrieval_stats.get("memory_mode") or ""),
                            "route_reason": str(retrieval_stats.get("route_reason") or ""),
                            "retrieval_passes": int(retrieval_stats.get("retrieval_passes") or 0),
                            "retrieval_stop_reason": str(retrieval_stats.get("retrieval_stop_reason") or ""),
                            "retrieved_atom_ids": [str(item).strip() for item in retrieved_atom_ids if str(item).strip()],
                            "retrieval_diagnostics": retrieval_diagnostics,
                            "service_citations": service_citations,
                            "package_evidence_citations": package_evidence_citations,
                        },
                        "evidence": compact_evidence,
                        "reply_text": reply_text,
                        "reply_text_raw": reply_text_raw,
                        "verification": {
                            "ok": bool(verified.ok),
                            "reasons": list(verified.reasons),
                            "found_citations": list(verified.found_citations),
                            "unknown_citations": list(verified.unknown_citations),
                            "inferred_decision": verified.inferred_decision,
                        },
                    }
                )

            supported_non_routine_records: list[dict[str, Any]] = []
            supported_non_routine_with_alignment = 0
            supported_non_routine_aligned_hits = 0
            supported_non_routine_citation_hits = 0
            supported_non_routine_retrieval_hits = 0
            supported_non_routine_retrieved_counts: list[float] = []
            supported_non_routine_retrieved_total = 0
            supported_non_routine_relevant_retrieved_total = 0
            conflict_labeled_supported_cases = 0
            conflict_covered_supported_cases = 0
            unsupported_cases = 0
            false_memory_cases = 0
            predicted_abstain_cases = 0
            true_abstain_cases = 0
            routine_cases = 0
            routine_over_recall_cases = 0

            for row in records:
                if not isinstance(row, dict):
                    continue
                case = row.get("case") if isinstance(row.get("case"), dict) else {}
                verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
                retrieval = row.get("retrieval") if isinstance(row.get("retrieval"), dict) else {}
                expected_decision = str(case.get("expected_decision") or "").strip().upper()
                case_type = str(case.get("case_type") or "").strip()
                inferred_decision = str(verification.get("inferred_decision") or "").strip().upper()
                if inferred_decision == "ABSTAIN":
                    predicted_abstain_cases += 1
                    if expected_decision == "ABSTAIN":
                        true_abstain_cases += 1
                if expected_decision == "ABSTAIN":
                    unsupported_cases += 1
                    if inferred_decision != "ABSTAIN":
                        false_memory_cases += 1
                if case_type == "routine_chat":
                    routine_cases += 1
                    found_citations = _normalize_tokens(list(verification.get("found_citations") or []))
                    retrieved = _normalize_tokens(list(retrieval.get("retrieved_atom_ids") or []))
                    if found_citations or retrieved:
                        routine_over_recall_cases += 1
                    continue

                if expected_decision not in {"PASS", "CLARIFY"}:
                    continue

                supported_non_routine_records.append(row)
                expected_atom_ids = _normalize_tokens(list(case.get("expected_atom_ids") or []))
                expected_citations = _normalize_tokens(list(case.get("expected_citations") or []))
                if expected_atom_ids or expected_citations:
                    supported_non_routine_with_alignment += 1

                retrieved_atom_ids = _normalize_tokens(list(retrieval.get("retrieved_atom_ids") or []))
                reply_citations = _normalize_tokens(list(verification.get("found_citations") or []))
                service_citations = _normalize_tokens(list(retrieval.get("service_citations") or []))
                package_citations = _normalize_tokens(list(retrieval.get("package_evidence_citations") or []))
                citation_pool = reply_citations.union(service_citations).union(package_citations)

                retrieval_hit = bool(expected_atom_ids and expected_atom_ids.intersection(retrieved_atom_ids))
                citation_hit = bool(expected_citations and expected_citations.intersection(citation_pool))
                if expected_atom_ids and expected_citations:
                    aligned_hit = retrieval_hit and citation_hit
                else:
                    aligned_hit = retrieval_hit or citation_hit
                if retrieval_hit:
                    supported_non_routine_retrieval_hits += 1
                if citation_hit:
                    supported_non_routine_citation_hits += 1
                if aligned_hit:
                    supported_non_routine_aligned_hits += 1
                supported_non_routine_retrieved_counts.append(float(len(retrieved_atom_ids)))
                if expected_atom_ids:
                    supported_non_routine_retrieved_total += len(retrieved_atom_ids)
                    supported_non_routine_relevant_retrieved_total += len(expected_atom_ids.intersection(retrieved_atom_ids))
                elif expected_citations:
                    supported_non_routine_retrieved_total += len(citation_pool)
                    supported_non_routine_relevant_retrieved_total += len(expected_citations.intersection(citation_pool))
                fixture_family = str(case.get("fixture_family") or "").strip().lower()
                if fixture_family == "contradiction_pressure":
                    conflict_labeled_supported_cases += 1
                    retrieved_has_required = expected_atom_ids.issubset(retrieved_atom_ids) if expected_atom_ids else False
                    fail_closed = inferred_decision in {"ABSTAIN", "CLARIFY"}
                    if retrieved_has_required or fail_closed:
                        conflict_covered_supported_cases += 1

            supported_non_routine_count = len(supported_non_routine_records)
            alignment_missing_cases = max(0, supported_non_routine_count - supported_non_routine_with_alignment)
            relevance_aligned_hit_rate = _ratio(supported_non_routine_aligned_hits, supported_non_routine_count)
            citation_hit_rate = _ratio(supported_non_routine_citation_hits, supported_non_routine_count)
            retrieval_hit_rate = _ratio(supported_non_routine_retrieval_hits, supported_non_routine_count)
            avg_retrieved_supported = (
                sum(supported_non_routine_retrieved_counts) / max(1.0, float(len(supported_non_routine_retrieved_counts)))
            )
            p95_retrieved_supported = _p95(supported_non_routine_retrieved_counts)
            evidence_precision_at_k = _ratio(
                supported_non_routine_relevant_retrieved_total,
                supported_non_routine_retrieved_total,
            )
            junk_rate_at_k = 1.0 - evidence_precision_at_k if supported_non_routine_retrieved_total > 0 else 0.0
            conflict_coverage = (
                1.0
                if conflict_labeled_supported_cases <= 0
                else _ratio(conflict_covered_supported_cases, conflict_labeled_supported_cases)
            )
            abstain_precision = _ratio(true_abstain_cases, predicted_abstain_cases)
            false_memory_rate = _ratio(false_memory_cases, unsupported_cases)
            routine_over_recall_rate = _ratio(routine_over_recall_cases, routine_cases)

            supported_non_routine = [
                case
                for case in list(cases or [])
                if isinstance(case, TruthsetCase)
                and str(case.expected_decision or "").strip().upper() in {"PASS", "CLARIFY"}
                and str(case.case_type or "").strip() != "routine_chat"
            ]
            episode_seeded = [
                case
                for case in supported_non_routine
                if str(getattr(case, "seed_kind", "") or "").strip() == "episode_card"
            ]
            fragment_seeded = [
                case
                for case in supported_non_routine
                if str(getattr(case, "seed_kind", "") or "").strip() != "episode_card"
            ]
            summary = {
                "cases": len(records),
                "service_decision_accuracy": (service_correct / max(1, len(records))),
                "model_verified_ok_rate": (model_verified_ok / max(1, len(records))),
                "model_decision_accuracy": (inferred_correct / max(1, len(records))),
                "decision_accuracy": (inferred_correct / max(1, len(records))),
                "citation_hit_rate": citation_hit_rate,
                "retrieval_hit_rate": retrieval_hit_rate,
                "relevance_aligned_hit_rate": relevance_aligned_hit_rate,
                "abstain_precision": abstain_precision,
                "false_memory_rate": false_memory_rate,
                "routine_over_recall_rate": routine_over_recall_rate,
                "latency_ms": {
                    "memory_avg": sum(memory_ms_values) / max(1, len(memory_ms_values)),
                    "memory_p50": _p50(memory_ms_values),
                    "memory_p95": _p95(memory_ms_values),
                    "model_avg": sum(model_ms_values) / max(1, len(model_ms_values)),
                    "model_p50": _p50(model_ms_values),
                    "model_p95": _p95(model_ms_values),
                    "total_avg": sum(total_ms_values) / max(1, len(total_ms_values)),
                    "total_p50": _p50(total_ms_values),
                    "total_p95": _p95(total_ms_values),
                },
                "tokens": {
                    "prompt_avg": sum(prompt_tokens_values) / max(1, len(prompt_tokens_values)),
                    "completion_avg": sum(completion_tokens_values) / max(1, len(completion_tokens_values)),
                    "total_avg": sum(total_tokens_values) / max(1, len(total_tokens_values)),
                    "prompt_total": sum(prompt_tokens_values),
                    "completion_total": sum(completion_tokens_values),
                    "total_tokens": sum(total_tokens_values),
                },
                "retrieval": {
                    "avg_retrieved_atoms": (sum(retrieved_atom_counts) / max(1, len(retrieved_atom_counts))),
                    "p95_retrieved_atoms": _p95([float(v) for v in retrieved_atom_counts]),
                    "avg_evidence_items": (sum(evidence_counts) / max(1, len(evidence_counts))),
                    "p95_evidence_items": _p95([float(v) for v in evidence_counts]),
                    "supported_non_routine_cases": supported_non_routine_count,
                    "supported_non_routine_with_expected_alignment": supported_non_routine_with_alignment,
                    "supported_non_routine_alignment_missing_cases": alignment_missing_cases,
                    "supported_non_routine_aligned_hit_cases": supported_non_routine_aligned_hits,
                    "supported_non_routine_relevance_aligned_hit_rate": relevance_aligned_hit_rate,
                    "supported_non_routine_avg_retrieved_atoms": avg_retrieved_supported,
                    "supported_non_routine_p95_retrieved_atoms": p95_retrieved_supported,
                    "evidence_precision_at_k": evidence_precision_at_k,
                    "junk_rate_at_k": junk_rate_at_k,
                    "conflict_labeled_supported_cases": conflict_labeled_supported_cases,
                    "conflict_covered_supported_cases": conflict_covered_supported_cases,
                    "conflict_coverage": conflict_coverage,
                },
                "latency_p50_ms": _p50(total_ms_values),
                "latency_p95_ms": _p95(total_ms_values),
                "tokens_prompt_avg": sum(prompt_tokens_values) / max(1, len(prompt_tokens_values)),
                "tokens_completion_avg": sum(completion_tokens_values) / max(1, len(completion_tokens_values)),
                "tokens_total_avg": sum(total_tokens_values) / max(1, len(total_tokens_values)),
                "retrieval_fanout_avg": avg_retrieved_supported,
                "retrieval_fanout_p95": p95_retrieved_supported,
                "truthset": {
                    "supported_non_routine_cases": len(supported_non_routine),
                    "supported_episode_seed_cases": len(episode_seeded),
                    "supported_episode_seed_rate": (len(episode_seeded) / max(1, len(supported_non_routine))),
                    "fragment_seed_cases": len(fragment_seeded),
                    "fragment_seed_rate": (len(fragment_seeded) / max(1, len(supported_non_routine))),
                },
                "efficiency_policy": (
                    {
                        "enabled": bool(efficiency_policy.enabled),
                        "fanout_hard_cap": int(efficiency_policy.fanout_hard_cap),
                        "fanout_p95_soft_cap": int(efficiency_policy.fanout_p95_soft_cap),
                        "context_token_budget": int(efficiency_policy.context_token_budget),
                        "early_stop_min_evidence": int(efficiency_policy.early_stop_min_evidence),
                        "cache_uncertainty_bypass": bool(efficiency_policy.cache_uncertainty_bypass),
                        "include_retry_tokens": bool(efficiency_policy.include_retry_tokens),
                    }
                    if efficiency_policy is not None
                    else {"enabled": False}
                ),
            }

            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            acceptance_gate = _build_acceptance_gate(summary, records, args)
            acceptance_gate_path.write_text(
                json.dumps(acceptance_gate, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            readout_cmd = [
                sys.executable,
                str(REPO_ROOT / "tools" / "build_responder_eval_readout.py"),
                "--records",
                str(records_path),
                "--summary",
                str(summary_path),
                "--acceptance-gate",
                str(acceptance_gate_path),
                "--out",
                str(readout_path),
                "--max-cases",
                str(max(1, int(args.readout_max_cases))),
            ]
            readout_result = subprocess.run(
                readout_cmd,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            if readout_result.returncode != 0:
                print("error=failed to build responder readout")
                print(readout_result.stdout)
                print(readout_result.stderr)
                return 2

            # Keep output keys aligned with tools/run_truthset_eval.py so wrappers can reuse parsing.
            print(f"truthset_generated_jsonl={generated_truthset_path}")
            print(f"records_json={records_path}")
            print(f"summary_json={summary_path}")
            print(f"acceptance_gate_json={acceptance_gate_path}")
            print(f"human_readout_md={readout_path}")
            print(f"safety_verdict={acceptance_gate.get('safety_verdict')}")
            print(f"human_quality_verdict={acceptance_gate.get('human_quality_verdict')}")
            print(f"decision={acceptance_gate.get('decision')}")
            if bool(args.fail_on_gate) and str(acceptance_gate.get("decision") or "").upper() != "PASS":
                return 3
            return 0
        finally:
            runtime.close()
    finally:
        if close_store:
            try:
                store.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
