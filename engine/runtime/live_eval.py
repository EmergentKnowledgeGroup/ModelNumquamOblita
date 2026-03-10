from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from ..contracts import RetrievalOverrideRequestContract, SourceRef
from ..memory import AtomStore, AtomStatus, MemoryAtom
from .session import RuntimeSession


@dataclass(slots=True)
class LiveEvalPlan:
    atoms: int
    requested_cases: int
    effective_cases: int
    scan_budget: int
    estimated_scans: int
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TruthsetCase:
    case_id: str
    case_type: str
    fixture_family: str
    query: str
    expected_decision: str
    expected_citations: list[str]
    expected_atom_ids: list[str]
    retrieval_query: str | None = None
    expected_memory_mode: str | None = None
    max_citations: int | None = None
    max_retrieved_atoms: int | None = None
    high_risk: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TruthsetCase":
        case_id = str(payload.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("truthset case requires case_id")
        case_type = str(payload.get("case_type") or "supported_recall").strip() or "supported_recall"
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError(f"truthset case {case_id} requires query")
        expected_decision = str(payload.get("expected_decision") or "").strip().upper()
        if not expected_decision:
            expected_decision = "ABSTAIN" if case_type == "unsupported_trap" else "PASS"
        if expected_decision not in {"PASS", "CLARIFY", "ABSTAIN"}:
            raise ValueError(f"truthset case {case_id} expected_decision is invalid")
        retrieval_query = payload.get("retrieval_query")
        retrieval_query_value = str(retrieval_query).strip() if retrieval_query is not None else None
        fixture_family = str(payload.get("fixture_family") or case_type or "supported_recall").strip() or "supported_recall"
        expected_memory_mode_raw = payload.get("expected_memory_mode")
        expected_memory_mode = (
            str(expected_memory_mode_raw).strip() if expected_memory_mode_raw is not None else None
        )
        max_citations_raw = payload.get("max_citations")
        max_citations = None
        if max_citations_raw is not None:
            try:
                max_citations = int(max_citations_raw)
            except Exception as exc:
                raise ValueError(f"truthset case {case_id} max_citations is invalid") from exc
        if max_citations is not None:
            max_citations = max(0, max_citations)
        max_retrieved_raw = payload.get("max_retrieved_atoms")
        max_retrieved_atoms = None
        if max_retrieved_raw is not None:
            try:
                max_retrieved_atoms = int(max_retrieved_raw)
            except Exception as exc:
                raise ValueError(f"truthset case {case_id} max_retrieved_atoms is invalid") from exc
        if max_retrieved_atoms is not None:
            max_retrieved_atoms = max(0, max_retrieved_atoms)
        return cls(
            case_id=case_id,
            case_type=case_type,
            fixture_family=fixture_family,
            query=query,
            expected_decision=expected_decision,
            expected_citations=[str(item).strip() for item in payload.get("expected_citations") or [] if str(item).strip()],
            expected_atom_ids=[str(item).strip() for item in payload.get("expected_atom_ids") or [] if str(item).strip()],
            retrieval_query=retrieval_query_value or None,
            expected_memory_mode=expected_memory_mode or None,
            max_citations=max_citations,
            max_retrieved_atoms=max_retrieved_atoms,
            high_risk=bool(payload.get("high_risk", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def build_retrieval_override(self, *, invoker: str, scope: str) -> RetrievalOverrideRequestContract | None:
        query = str(self.retrieval_query or "").strip()
        if not query:
            return None
        return RetrievalOverrideRequestContract(
            query=query,
            invoker=invoker,
            reason=f"truthset_case:{self.case_id}",
            scope=scope,
            auth_context="truthset_eval",
        )


@dataclass(slots=True)
class LiveEvalRecord:
    case_id: str
    case_type: str
    fixture_family: str
    expected_decision: str
    actual_decision: str
    decision_correct: bool
    expected_citations: list[str]
    citations: list[str]
    citation_hit: bool
    citation_count: int
    expected_atom_ids: list[str]
    retrieved_atom_ids: list[str]
    retrieval_hit: bool
    retrieved_atom_count: int
    false_memory: bool
    over_recall: bool
    latency_ms: float
    turn_cost_usd: float
    memory_mode: str
    expected_memory_mode: str | None
    memory_mode_match: bool
    short_term_hits: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LiveEvalSummary:
    generated_at: str
    atoms: int
    requested_cases: int
    cases: int
    supported_cases: int
    unsupported_cases: int
    predicted_abstain_cases: int
    true_abstain_cases: int
    false_memory_cases: int
    routine_cases: int
    over_recall_cases: int
    scan_budget: int
    estimated_scans: int
    decision_accuracy: float
    citation_hit_rate: float
    retrieval_hit_rate: float
    supported_non_routine_cases: int
    supported_non_routine_with_expected_alignment: int
    supported_non_routine_alignment_missing_cases: int
    relevance_aligned_hit_rate: float
    supported_non_routine_avg_retrieved_atoms: float
    supported_non_routine_p95_retrieved_atoms: float
    evidence_precision_at_k: float
    junk_rate_at_k: float
    conflict_labeled_supported_cases: int
    conflict_covered_supported_cases: int
    conflict_coverage: float
    abstain_precision: float
    false_memory_rate: float
    over_recall_rate: float
    routine_over_recall_rate: float
    episode_supported_cases: int
    episode_hit_cases: int
    episode_hit_rate: float
    episode_false_recall_cases: int
    episode_false_recall_rate: float
    memory_mode_checked_cases: int
    memory_mode_match_rate: float
    memory_mode_case_counts: dict[str, int]
    memory_mode_avg_latency_ms: dict[str, float]
    memory_mode_p95_latency_ms: dict[str, float]
    avg_latency_ms: float
    p95_latency_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    tokens_prompt_avg: float
    tokens_completion_avg: float
    tokens_total_avg: float
    retrieval_fanout_avg: float
    retrieval_fanout_p95: float
    total_tokens: int
    total_cost_usd: float
    fixture_case_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(int(round(0.95 * (len(ordered) - 1))), 0)
    return float(ordered[index])


def _p50(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(int(round(0.50 * (len(ordered) - 1))), 0)
    return float(ordered[index])


_REQUIRED_LIVE_EVAL_METRICS = (
    "latency_p50_ms",
    "latency_p95_ms",
    "tokens_prompt_avg",
    "tokens_completion_avg",
    "tokens_total_avg",
    "retrieval_fanout_avg",
    "retrieval_fanout_p95",
    "evidence_precision_at_k",
    "junk_rate_at_k",
    "conflict_coverage",
    "false_memory_rate",
    "abstain_precision",
)


def live_eval_required_metrics(summary: LiveEvalSummary) -> dict[str, float]:
    payload = summary.to_dict()
    return {name: float(payload.get(name) or 0.0) for name in _REQUIRED_LIVE_EVAL_METRICS}


def validate_live_eval_required_metrics(summary: LiveEvalSummary) -> list[str]:
    payload = summary.to_dict()
    failures: list[str] = []
    for name in _REQUIRED_LIVE_EVAL_METRICS:
        if name not in payload:
            failures.append(f"{name}_missing")
            continue
        value = payload.get(name)
        try:
            numeric = float(value)
        except Exception:
            failures.append(f"{name}_not_numeric")
            continue
        if not math.isfinite(numeric):
            failures.append(f"{name}_non_finite")
    return failures


def summarize_live_eval_records(
    *,
    records: list[LiveEvalRecord],
    runtime: RuntimeSession,
    atoms: int,
    requested_cases: int,
    scan_budget: int,
) -> LiveEvalSummary:
    total = len(records)
    supported = [row for row in records if row.expected_decision in {"PASS", "CLARIFY"}]
    unsupported = [row for row in records if row.expected_decision == "ABSTAIN"]
    routine_cases = [row for row in records if str(row.case_type) == "routine_chat"]
    retrieval_target_cases = [row for row in supported if str(row.case_type) != "routine_chat"]
    supported_with_expected_alignment = [
        row for row in retrieval_target_cases if list(row.expected_atom_ids or []) or list(row.expected_citations or [])
    ]
    episode_supported_cases = [
        row
        for row in retrieval_target_cases
        if str(row.case_type or "") in {"supported_recall", "narrative_recall", "timeline_recall", "confidence_guardrail"}
    ]
    predicted_abstain = [row for row in records if row.actual_decision == "ABSTAIN"]
    true_abstain = [row for row in predicted_abstain if row.expected_decision == "ABSTAIN"]
    memory_mode_checked = [row for row in records if row.expected_memory_mode is not None]
    episode_hit_cases = [
        row
        for row in episode_supported_cases
        if any(str(atom_id).startswith("episode_card:") for atom_id in list(row.retrieved_atom_ids or []))
    ]
    episode_false_recall_cases = [
        row
        for row in unsupported
        if any(str(atom_id).startswith("episode_card:") for atom_id in list(row.retrieved_atom_ids or []))
    ]
    supported_non_routine_aligned_hits = 0
    supported_non_routine_retrieved_counts: list[float] = []
    supported_non_routine_retrieved_total = 0
    supported_non_routine_relevant_retrieved_total = 0
    conflict_labeled_supported_cases = 0
    conflict_covered_supported_cases = 0
    for row in retrieval_target_cases:
        expected_atom_ids = set(str(item).strip() for item in list(row.expected_atom_ids or []) if str(item).strip())
        expected_citations = set(str(item).strip() for item in list(row.expected_citations or []) if str(item).strip())
        retrieved_atom_ids = set(str(item).strip() for item in list(row.retrieved_atom_ids or []) if str(item).strip())
        citations = set(str(item).strip() for item in list(row.citations or []) if str(item).strip())
        if expected_atom_ids and expected_citations:
            aligned_hit = bool(expected_atom_ids.intersection(retrieved_atom_ids)) and bool(expected_citations.intersection(citations))
        elif expected_atom_ids:
            aligned_hit = bool(expected_atom_ids.intersection(retrieved_atom_ids))
        elif expected_citations:
            aligned_hit = bool(expected_citations.intersection(citations))
        else:
            aligned_hit = False
        if aligned_hit:
            supported_non_routine_aligned_hits += 1
        supported_non_routine_retrieved_counts.append(float(len(retrieved_atom_ids)))
        if expected_atom_ids:
            supported_non_routine_retrieved_total += len(retrieved_atom_ids)
            supported_non_routine_relevant_retrieved_total += len(expected_atom_ids.intersection(retrieved_atom_ids))
        elif expected_citations:
            supported_non_routine_retrieved_total += len(citations)
            supported_non_routine_relevant_retrieved_total += len(expected_citations.intersection(citations))
        if str(row.fixture_family or "").strip().lower() == "contradiction_pressure":
            conflict_labeled_supported_cases += 1
            has_required_neighbors = expected_atom_ids.issubset(retrieved_atom_ids) if expected_atom_ids else False
            fail_closed = str(row.actual_decision or "").strip().upper() in {"ABSTAIN", "CLARIFY"}
            if has_required_neighbors or fail_closed:
                conflict_covered_supported_cases += 1

    relevance_aligned_hit_rate = _ratio(supported_non_routine_aligned_hits, len(retrieval_target_cases))
    supported_non_routine_avg_retrieved_atoms = (
        float(mean(supported_non_routine_retrieved_counts)) if supported_non_routine_retrieved_counts else 0.0
    )
    supported_non_routine_p95_retrieved_atoms = _p95(supported_non_routine_retrieved_counts)
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
    fixture_case_counts: dict[str, int] = {}
    memory_mode_case_counts: dict[str, int] = {}
    memory_mode_latencies: dict[str, list[float]] = {}
    for row in records:
        family = str(row.fixture_family or row.case_type or "unknown").strip() or "unknown"
        fixture_case_counts[family] = fixture_case_counts.get(family, 0) + 1
        mode = str(row.memory_mode or "unknown").strip().lower() or "unknown"
        memory_mode_case_counts[mode] = memory_mode_case_counts.get(mode, 0) + 1
        memory_mode_latencies.setdefault(mode, []).append(float(row.latency_ms))

    memory_mode_avg_latency_ms = {
        key: float(mean(values)) if values else 0.0 for key, values in memory_mode_latencies.items()
    }
    memory_mode_p95_latency_ms = {key: _p95(values) for key, values in memory_mode_latencies.items()}

    stats = runtime.stats()
    latencies = [row.latency_ms for row in records]
    input_tokens_total = int(stats.total_input_tokens)
    output_tokens_total = int(stats.total_output_tokens)
    total_tokens = int(input_tokens_total + output_tokens_total)
    case_count = max(1, total)

    return LiveEvalSummary(
        generated_at=datetime.now(timezone.utc).isoformat(),
        atoms=int(atoms),
        requested_cases=int(requested_cases),
        cases=total,
        supported_cases=len(supported),
        unsupported_cases=len(unsupported),
        predicted_abstain_cases=len(predicted_abstain),
        true_abstain_cases=len(true_abstain),
        false_memory_cases=sum(1 for row in unsupported if row.false_memory),
        routine_cases=len(routine_cases),
        over_recall_cases=sum(1 for row in routine_cases if row.over_recall),
        scan_budget=int(scan_budget),
        estimated_scans=int(atoms) * total,
        decision_accuracy=_ratio(sum(1 for row in records if row.decision_correct), total),
        citation_hit_rate=_ratio(sum(1 for row in retrieval_target_cases if row.citation_hit), len(retrieval_target_cases)),
        retrieval_hit_rate=_ratio(sum(1 for row in retrieval_target_cases if row.retrieval_hit), len(retrieval_target_cases)),
        supported_non_routine_cases=len(retrieval_target_cases),
        supported_non_routine_with_expected_alignment=len(supported_with_expected_alignment),
        supported_non_routine_alignment_missing_cases=max(0, len(retrieval_target_cases) - len(supported_with_expected_alignment)),
        relevance_aligned_hit_rate=relevance_aligned_hit_rate,
        supported_non_routine_avg_retrieved_atoms=supported_non_routine_avg_retrieved_atoms,
        supported_non_routine_p95_retrieved_atoms=supported_non_routine_p95_retrieved_atoms,
        evidence_precision_at_k=evidence_precision_at_k,
        junk_rate_at_k=junk_rate_at_k,
        conflict_labeled_supported_cases=conflict_labeled_supported_cases,
        conflict_covered_supported_cases=conflict_covered_supported_cases,
        conflict_coverage=conflict_coverage,
        abstain_precision=_ratio(len(true_abstain), len(predicted_abstain)),
        false_memory_rate=_ratio(sum(1 for row in unsupported if row.false_memory), len(unsupported)),
        over_recall_rate=_ratio(sum(1 for row in routine_cases if row.over_recall), len(routine_cases)),
        routine_over_recall_rate=_ratio(sum(1 for row in routine_cases if row.over_recall), len(routine_cases)),
        episode_supported_cases=len(episode_supported_cases),
        episode_hit_cases=len(episode_hit_cases),
        episode_hit_rate=_ratio(len(episode_hit_cases), len(episode_supported_cases)),
        episode_false_recall_cases=len(episode_false_recall_cases),
        episode_false_recall_rate=_ratio(len(episode_false_recall_cases), len(unsupported)),
        memory_mode_checked_cases=len(memory_mode_checked),
        memory_mode_match_rate=_ratio(sum(1 for row in memory_mode_checked if row.memory_mode_match), len(memory_mode_checked)),
        memory_mode_case_counts=memory_mode_case_counts,
        memory_mode_avg_latency_ms=memory_mode_avg_latency_ms,
        memory_mode_p95_latency_ms=memory_mode_p95_latency_ms,
        avg_latency_ms=float(mean(latencies)) if latencies else 0.0,
        p95_latency_ms=_p95(latencies),
        latency_p50_ms=_p50(latencies),
        latency_p95_ms=_p95(latencies),
        tokens_prompt_avg=float(input_tokens_total / case_count),
        tokens_completion_avg=float(output_tokens_total / case_count),
        tokens_total_avg=float(total_tokens / case_count),
        retrieval_fanout_avg=supported_non_routine_avg_retrieved_atoms,
        retrieval_fanout_p95=supported_non_routine_p95_retrieved_atoms,
        total_tokens=total_tokens,
        total_cost_usd=float(stats.total_cost_usd),
        fixture_case_counts=fixture_case_counts,
    )


def plan_live_eval_workload(*, atom_count: int, requested_cases: int, scan_budget: int) -> LiveEvalPlan:
    atoms = max(0, int(atom_count))
    requested = max(1, int(requested_cases))
    budget = max(1, int(scan_budget))
    if atoms == 0:
        return LiveEvalPlan(
            atoms=atoms,
            requested_cases=requested,
            effective_cases=0,
            scan_budget=budget,
            estimated_scans=0,
            warning="No active atoms available; eval workload downshifted to 0 cases.",
        )
    safe_cases = max(1, budget // max(atoms, 1))
    effective = min(requested, safe_cases)
    warning = None
    if effective < requested:
        warning = (
            f"Workload downshifted from {requested} to {effective} cases "
            f"(atoms={atoms}, budget={budget} scan-ops)."
        )
    return LiveEvalPlan(
        atoms=atoms,
        requested_cases=requested,
        effective_cases=effective,
        scan_budget=budget,
        estimated_scans=atoms * effective,
        warning=warning,
    )


def _snippet(text: str, *, max_words: int = 14) -> str:
    cue = _best_memory_cue(text, max_words=max_words)
    if cue:
        return cue
    words = [w for w in str(text or "").strip().split() if w]
    if not words:
        return "memory"
    return " ".join(words[:max_words])


_GENERIC_TOKENS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "about",
    "what",
    "when",
    "where",
    "there",
    "your",
    "just",
    "like",
    "have",
    "will",
    "into",
    "after",
    "before",
    "would",
    "could",
    "should",
    "been",
    "were",
    "they",
    "them",
    "then",
    "than",
    "also",
    "some",
    "more",
    "only",
    "over",
    "under",
    "very",
    "much",
}

_NOISY_DOMAIN_TERMS = {
    "general",
    "identity",
    "training",
    "prompting",
    "continuity",
    "memory",
    "system",
    "technical",
    "dev",
    "development",
    "project",
    "testing",
    "prompt",
    "phase",
    "workflow",
    "tooling",
    "runtime",
    "parser",
    "eval",
    "session",
    "role",
    "bridge",
    "route",
    "routes",
    "middleware",
    "json",
    "jsonl",
    "sqlite",
    "schema",
    "contract",
    "spec",
    "readme",
    "docs",
}

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_LOW_INFO_ACK_RE = re.compile(
    r"^(?:ok(?:ay)?|yes|yeah|yep|yup|sure|thanks?|thank you|please|done|noted|copy|cool|lol|haha|hahaha|go ahead|sounds good)(?:[\s,.!?:;'\"-]+(?:ok(?:ay)?|yes|yeah|yep|yup|sure|thanks?|thank you|please|done|noted|copy|cool|lol|haha|hahaha|go ahead|sounds good))*$",
    re.IGNORECASE,
)

_DIALOGUE_FILLER_PREFIXES = {
    "okay",
    "ok",
    "hey",
    "hi",
    "hello",
    "love",
    "so",
    "well",
    "right",
    "yeah",
    "yep",
    "yup",
    "just",
    "like",
    "look",
    "listen",
    "honestly",
    "literally",
    "please",
    "this",
    "that",
    "these",
    "those",
    "what",
    "how",
    "why",
    "when",
}

_EVENT_VERB_HINTS = {
    "said",
    "asked",
    "told",
    "remember",
    "called",
    "named",
    "built",
    "made",
    "fixed",
    "broke",
    "met",
    "found",
    "lost",
    "joked",
    "wrote",
    "shared",
    "sent",
    "moved",
    "trained",
    "shipped",
    "launched",
    "started",
    "finished",
    "happened",
}

_TITLE_TOKEN_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
_HEX_TOKEN_RE = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")
_CAPITALIZED_STOPWORDS = {
    "And",
    "But",
    "Because",
    "The",
    "This",
    "That",
    "These",
    "Those",
    "Not",
    "Tell",
    "Let",
    "Can",
    "Could",
    "Would",
    "Should",
    "Will",
    "Now",
    "Then",
    "Still",
    "Always",
    "Every",
    "Your",
    "Its",
    "Thats",
    "Ive",
    "Ill",
}
_ENTITY_STOPWORDS = {
    "and",
    "but",
    "because",
    "the",
    "this",
    "that",
    "these",
    "those",
    "not",
    "tell",
    "let",
    "can",
    "could",
    "would",
    "should",
    "will",
    "now",
    "then",
    "still",
    "always",
    "every",
    "your",
    "its",
    "thats",
    "ive",
    "ill",
    "something",
    "whatever",
    "includes",
    "pick",
    "real",
    "absolutely",
    "classifier",
    "architecture",
    "pipeline",
    "evaluation",
    "runtime",
}
_NAME_HINTS = {
    "lyra",
    "xander",
    "dean",
    "ghost",
    "claude",
    "dex",
    "sam",
    "maya",
    "sara",
    "haku",
    "gemini",
    "robert",
    "jordan",
    "alex",
    "casey",
    "quinn",
    "morgan",
    "riley",
}
_SYNTHETIC_NAMES = ("Morgan", "Riley", "Jordan", "Alex", "Casey", "Quinn")
_SYNTHETIC_PLACES = ("Lisbon", "Kyoto", "Milan", "Dublin", "Prague", "Oslo")
_SYNTHETIC_EVENTS = (
    "the paper lantern project",
    "the midnight train sketch",
    "the old harbor notebook",
    "the rain signal ritual",
    "the mirror staircase story",
    "the blue compass joke",
)


def _meaningful_tokens(text: str) -> list[str]:
    tokens = [token.lower() for token in _WORD_RE.findall(str(text or ""))]
    return [token for token in tokens if len(token) >= 4 and token not in _GENERIC_TOKENS]


def _normalize_clause(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    value = value.strip("`\"'[]{}()")
    return value.strip()


def _strip_dialogue_filler_prefix(text: str) -> str:
    words = [item for item in str(text or "").strip().split() if item]
    while words and words[0].lower().strip(".,!?:;'\"`") in _DIALOGUE_FILLER_PREFIXES:
        words.pop(0)
    # Handle common opener pair like "okay love ..."
    while len(words) >= 2 and words[0].lower().strip(".,!?:;'\"`") in {"okay", "ok", "hey"} and words[1].lower().strip(
        ".,!?:;'\"`"
    ) in _DIALOGUE_FILLER_PREFIXES:
        words.pop(0)
        words.pop(0)
    return " ".join(words).strip()


def _looks_like_tool_payload(text: str) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return True
    if value.startswith("{") or value.startswith("["):
        return True
    if "pattern" in value and "replacement" in value and "updates" in value:
        return True
    if value.startswith("http://") or value.startswith("https://"):
        return True
    if value.count("{") >= 2 and value.count("}") >= 2:
        return True
    return False


def _is_low_information_memory(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if _looks_like_tool_payload(value):
        return True
    tokens = _WORD_RE.findall(value)
    if len(tokens) < 8:
        return True
    meaningful = _meaningful_tokens(value)
    if len(meaningful) < 3:
        return True
    if _LOW_INFO_ACK_RE.match(value):
        return True
    density = len(meaningful) / max(len(tokens), 1)
    return density < 0.25


def _is_artifact_noise(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if _HEX_TOKEN_RE.search(value):
        return True
    if "```" in value:
        return True
    if value.count("*") >= 8:
        return True
    tokens = _WORD_RE.findall(value)
    if not tokens:
        return True
    upper_tokens = [token for token in tokens if len(token) >= 4 and token.isupper()]
    if len(upper_tokens) >= 2 and (len(upper_tokens) / max(len(tokens), 1)) >= 0.12:
        return True
    suspicious_markers = ("BEGIN PATCH", "END PATCH", "URGENT", "SPECIALIST", "CLI", "JSONL", "RENDERER")
    upper_value = value.upper()
    if any(marker in upper_value for marker in suspicious_markers):
        return True
    return False


def _best_memory_cue(text: str, *, max_words: int = 14) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if _looks_like_tool_payload(raw):
        return ""

    parts = re.split(r"[.\n!?;:]+", raw)
    candidates = [_normalize_clause(part) for part in parts]
    candidates = [item for item in candidates if item]
    if not candidates:
        return ""

    best_score = -1.0
    best = ""
    for candidate in candidates:
        tokens = _WORD_RE.findall(candidate)
        if len(tokens) < 4:
            continue
        meaningful = _meaningful_tokens(candidate)
        if len(meaningful) < 2:
            continue
        score = (len(meaningful) * 2.0) + min(len(tokens), 28) * 0.15
        if score > best_score:
            best_score = score
            best = candidate

    if not best:
        return ""
    words = [item for item in best.split() if item]
    if not words:
        return ""
    return " ".join(words[:max_words])


def _named_entity_from_text(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    candidates: list[tuple[str, bool]] = []
    for match in _TITLE_TOKEN_RE.finditer(raw):
        token = str(match.group(0) or "").strip()
        if not token:
            continue
        if token in _CAPITALIZED_STOPWORDS:
            continue
        lowered = token.lower()
        if lowered in _GENERIC_ENTITY_VALUES or lowered in _NOISY_DOMAIN_TERMS or lowered in _ENTITY_STOPWORDS:
            continue
        left = raw[: match.start()]
        left_trim = left.rstrip()
        prev_char = left_trim[-1] if left_trim else ""
        sentence_start = (
            not left_trim
            or prev_char in {".", "!", "?", "\n", ";", ":", "(", "[", "{", "\"", "'"}
        )
        candidates.append((token, sentence_start))
    if not candidates:
        return ""
    counts: dict[str, int] = {}
    for token, _sentence_start in candidates:
        counts[token.lower()] = counts.get(token.lower(), 0) + 1
    filtered: list[str] = []
    for token, sentence_start in candidates:
        lowered = token.lower()
        if sentence_start and counts.get(lowered, 0) <= 1:
            continue
        if lowered in _DIALOGUE_FILLER_PREFIXES:
            continue
        repeated = counts.get(lowered, 0) >= 2
        if not repeated and lowered not in _NAME_HINTS:
            continue
        filtered.append(token)
    if not filtered:
        return ""
    scores: dict[str, int] = {}
    for token in filtered:
        scores[token] = scores.get(token, 0) + 1
    ranked = sorted(scores.items(), key=lambda item: (item[1], len(item[0]), item[0].lower()), reverse=True)
    return ranked[0][0]


def _detail_quality_score(detail: str) -> float:
    normalized = _normalize_display_cue(detail, max_words=20)
    if not normalized:
        return -2.0
    tokens = [token for token in _WORD_RE.findall(normalized) if token]
    if not tokens:
        return -2.0
    lower_tokens = {token.lower() for token in tokens}
    meaningful = _meaningful_tokens(normalized)
    verb_bonus = 1.2 if _EVENT_VERB_HINTS.intersection(lower_tokens) else 0.0
    first = tokens[0].lower()
    filler_penalty = 0.9 if first in _DIALOGUE_FILLER_PREFIXES else 0.0
    noisy_hits = sum(1 for token in lower_tokens if token in _NOISY_DOMAIN_TERMS)
    noisy_penalty = min(noisy_hits * 0.45, 1.8)
    short_penalty = 1.4 if len(tokens) < 6 else 0.0
    return (len(meaningful) * 0.55) + (min(len(tokens), 18) * 0.06) + verb_bonus - filler_penalty - noisy_penalty - short_penalty


def _is_strong_subject(subject: str) -> bool:
    return str(subject or "").strip().lower() in _NAME_HINTS


def _detail_quote(detail: str, *, max_words: int = 14) -> str:
    text = _normalize_display_cue(detail, max_words=max_words)
    if not text:
        return "\"that event\""
    return f"\"{text}\""


def _detail_fragment_for_atom(atom: MemoryAtom, *, max_words: int = 12) -> str:
    raw = str(getattr(atom, "canonical_text", "") or "").strip()
    if not raw:
        return ""
    parts = re.split(r"[.\n!?;:]+", raw)
    clauses = [_strip_dialogue_filler_prefix(_normalize_clause(part)) for part in parts]
    clauses = [item for item in clauses if item]
    if not clauses:
        return ""

    best_score = -1.0
    best_clause = ""
    for clause in clauses:
        if _is_artifact_noise(clause):
            continue
        tokens = _WORD_RE.findall(clause)
        if len(tokens) < 4:
            continue
        meaningful = _meaningful_tokens(clause)
        if len(meaningful) < 2:
            continue
        lower_tokens = {token.lower() for token in tokens}
        verb_bonus = 1.4 if _EVENT_VERB_HINTS.intersection(lower_tokens) else 0.0
        score = (len(meaningful) * 1.7) + min(len(tokens), 20) * 0.12 + verb_bonus
        if score > best_score:
            best_score = score
            best_clause = clause

    if not best_clause:
        best_clause = _strip_dialogue_filler_prefix(_best_memory_cue(raw, max_words=max_words + 4))
    words = [item for item in best_clause.split() if item]
    if not words:
        return ""
    return " ".join(words[:max_words]).strip()


def _citation_ids(atom: MemoryAtom) -> list[str]:
    citations: set[str] = set()
    for ref in list(atom.source_refs or []):
        source_id = str(getattr(ref, "source_id", "") or "").strip()
        message_id = str(getattr(ref, "message_id", "") or "").strip()
        if not source_id:
            continue
        if not message_id:
            message_id = "unknown_message"
        citations.add(f"{source_id}#{message_id}")
    return sorted(citations)


def _active_atoms(store: AtomStore) -> list[MemoryAtom]:
    atoms = []
    for atom in store.list_atoms():
        if atom.status is AtomStatus.TOMBSTONED:
            continue
        atoms.append(atom)
    return atoms


_ROUTINE_CHAT_PROMPTS = (
    "Hey, how are you doing today?",
    "I heard a joke earlier, want to hear it?",
    "Quick check-in before we continue.",
    "Before we continue, how has your day been?",
)

_ROUTINE_CHAT_PROMPTS_V3 = (
    "How's your day going so far?",
    "Want to share something fun from today?",
    "Before we continue, how are you feeling about things?",
    "Random check-in: what are you in the mood to talk about?",
    "Do you want to keep this light for a minute?",
)

_GENERIC_ENTITY_VALUES = {
    "assistant",
    "chatgpt",
    "model",
    "user",
    "you",
    "me",
    "we",
    "they",
    "them",
    "it",
}

_IDENTITY_SUBJECT_VALUES = {
    "assistant",
    "user",
    "dyad",
    "lyra",
    "chatgpt",
    "model",
    "anchors",
    "pipeline",
    "evaluation",
    "general",
    "memory",
    "system",
    "prompting",
    "continuity",
    "runtime",
    "training",
    "workflow",
    "tooling",
}


def _primary_entity(atom: MemoryAtom) -> str:
    entities = [str(item).strip() for item in list(getattr(atom, "entities", []) or []) if str(item).strip()]
    cleaned = [item for item in entities if item.lower() not in _GENERIC_ENTITY_VALUES]
    if not cleaned:
        return ""
    cleaned.sort(key=lambda item: (len(item), item.lower()), reverse=True)
    return cleaned[0]


def _primary_topic(atom: MemoryAtom) -> str:
    topics = [str(item).strip() for item in list(getattr(atom, "topics", []) or []) if str(item).strip()]
    if not topics:
        return ""
    cleaned: list[str] = []
    for raw in topics:
        text = raw.replace("_", " ").replace("-", " ").strip()
        tokens = [token for token in _WORD_RE.findall(text) if token]
        informative = [token for token in tokens if token.lower() not in _NOISY_DOMAIN_TERMS]
        if not informative:
            continue
        cleaned.append(" ".join(informative[:6]))
    if not cleaned:
        return ""
    cleaned.sort(key=lambda item: (len(item), item.lower()), reverse=True)
    return cleaned[0]


def _cue_for_atom(atom: MemoryAtom) -> str:
    entity = _primary_entity(atom)
    if entity:
        return entity
    topic = _primary_topic(atom)
    if topic:
        return topic
    return _snippet(atom.canonical_text)


def _retrieval_cue_for_atom(atom: MemoryAtom, display_cue: str) -> str:
    snippet = _snippet(atom.canonical_text, max_words=16)
    if not display_cue:
        return snippet
    merged = f"{display_cue} {snippet}".strip()
    words = _WORD_RE.findall(merged)
    if len(words) >= 6:
        return merged
    return snippet


def _normalize_display_cue(text: str, *, max_words: int = 10) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    tokens = [token for token in _WORD_RE.findall(value) if token]
    if not tokens:
        return ""
    filtered = [token for token in tokens if token.lower() not in _NOISY_DOMAIN_TERMS]
    if not filtered:
        filtered = tokens
    return " ".join(filtered[:max_words]).strip()


def _prompt_cue(cue: str) -> str:
    cleaned = _normalize_display_cue(cue, max_words=12)
    if not cleaned:
        return "that moment"
    if len(cleaned.split()) <= 4:
        return cleaned
    return f"this moment: {cleaned}"


def _alternate_detail(atoms: list[MemoryAtom], *, current_index: int, prefer_subject: str = "") -> str:
    if len(atoms) <= 1:
        return ""
    total = len(atoms)
    for offset in range(1, min(total - 1, 8) + 1):
        other = atoms[(current_index + offset) % total]
        cue = _normalize_display_cue(_detail_fragment_for_atom(other, max_words=8), max_words=8)
        if prefer_subject and cue and cue.lower().startswith(prefer_subject.lower()):
            cue = cue[len(prefer_subject) :].strip(" ,.")
        if cue:
            return cue
    return ""


def _subject_and_detail_for_atom(atom: MemoryAtom) -> tuple[str, str]:
    subject = _normalize_display_cue(_named_entity_from_text(getattr(atom, "canonical_text", "")), max_words=3)
    if subject.lower() in _IDENTITY_SUBJECT_VALUES or subject.lower() in _ENTITY_STOPWORDS:
        subject = ""
    if not subject:
        subject = _normalize_display_cue(_primary_entity(atom), max_words=3)
        if subject.lower() in _IDENTITY_SUBJECT_VALUES or subject.lower() in _ENTITY_STOPWORDS:
            subject = ""
    if not subject:
        topic_subject = _normalize_display_cue(_primary_topic(atom), max_words=3)
        if (
            topic_subject
            and _meaningful_tokens(topic_subject)
            and topic_subject.lower() not in _NOISY_DOMAIN_TERMS
            and topic_subject.lower() not in _IDENTITY_SUBJECT_VALUES
            and topic_subject.lower() not in _ENTITY_STOPWORDS
        ):
            subject = topic_subject
    if subject and not _is_strong_subject(subject):
        subject = ""
    detail = _normalize_display_cue(_detail_fragment_for_atom(atom, max_words=12), max_words=12)
    if subject and detail.lower().startswith(subject.lower()):
        detail = detail[len(subject) :].strip(" ,.")
    if not detail:
        detail = _normalize_display_cue(_snippet(atom.canonical_text, max_words=10), max_words=10)
        detail = _strip_dialogue_filler_prefix(detail)
    return subject, detail.strip()


def _truthset_prompt_quality(atom: MemoryAtom) -> float:
    subject, detail = _subject_and_detail_for_atom(atom)
    text = str(getattr(atom, "canonical_text", "") or "")
    target = detail or text
    meaningful = len(_meaningful_tokens(target))
    lower_tokens = {token.lower() for token in _WORD_RE.findall(target)}
    verb_hit = 1.0 if _EVENT_VERB_HINTS.intersection(lower_tokens) else 0.0
    topic = _normalize_display_cue(_primary_topic(atom), max_words=4)
    topic_signal = 1.0 if topic and topic.lower() not in _NOISY_DOMAIN_TERMS else 0.0
    subject_signal = 1.6 if subject and subject.lower() not in _IDENTITY_SUBJECT_VALUES else 0.0
    subject_penalty = 1.2 if subject and subject.lower() in _IDENTITY_SUBJECT_VALUES else 0.0
    detail_len = min(len(_WORD_RE.findall(detail)), 14) * 0.08
    low_info_penalty = 1.5 if _is_low_information_memory(text) else 0.0
    artifact_penalty = 3.0 if _is_artifact_noise(text) else 0.0
    detail_quality = _detail_quality_score(target)
    empty_subject_penalty = 0.8 if not subject and verb_hit <= 0 else 0.0
    return (
        (meaningful * 0.30)
        + subject_signal
        + verb_hit
        + topic_signal
        + detail_len
        + (detail_quality * 0.55)
        - subject_penalty
        - empty_subject_penalty
        - low_info_penalty
        - artifact_penalty
    )


def _memory_prompt_for_family(
    *,
    family: str,
    cue: str,
    subject: str = "",
    detail: str = "",
    atom: MemoryAtom | None = None,
    atoms: list[MemoryAtom] | None = None,
    atom_index: int = 0,
) -> str:
    phrased_cue = _prompt_cue(cue)
    normalized_subject = _normalize_display_cue(subject, max_words=4)
    normalized_detail = _normalize_display_cue(detail, max_words=12)
    if normalized_subject.lower() in _IDENTITY_SUBJECT_VALUES or not _is_strong_subject(normalized_subject):
        normalized_subject = ""
    if normalized_subject and normalized_detail:
        event_phrase = f"{normalized_subject} {normalized_detail}".strip()
    else:
        event_phrase = normalized_detail or normalized_subject
    if family == "narrative_recall":
        if normalized_subject and normalized_detail:
            return f"Walk me through what happened with {normalized_subject} around this event: {_detail_quote(normalized_detail)}."
        if event_phrase:
            return f"Walk me through what was happening around this event: {_detail_quote(event_phrase)}."
        return f"Walk me through what happened with {phrased_cue}."
    if family == "contradiction_pressure":
        entity = normalized_subject or (_normalize_display_cue(_primary_entity(atom)) if atom is not None else "")
        if entity.lower() in _IDENTITY_SUBJECT_VALUES or not _is_strong_subject(entity):
            entity = ""
        wrong_detail = _alternate_detail(atoms or [], current_index=atom_index, prefer_subject=entity)
        if entity and wrong_detail:
            return f"I might be mixing this up: did {entity} mention this memory {_detail_quote(wrong_detail)}, or am I remembering it wrong?"
        if event_phrase:
            return f"I might be mixing this up. Did this happen: {_detail_quote(event_phrase)} or was it different?"
        return f"I might be mixing this up about {phrased_cue}. What can you confirm?"
    if family == "semantic_trap_correction":
        entity = normalized_subject or (_normalize_display_cue(_primary_entity(atom)) if atom is not None else "")
        if entity.lower() in _IDENTITY_SUBJECT_VALUES or not _is_strong_subject(entity):
            entity = ""
        wrong_detail = _alternate_detail(atoms or [], current_index=atom_index, prefer_subject=entity)
        if entity and wrong_detail:
            return f"I might be mixing this up. Did {entity} say this: {_detail_quote(wrong_detail)}?"
        if wrong_detail:
            return f"I might be mixing this up. Was this memory right: {_detail_quote(wrong_detail)}?"
        if event_phrase:
            return f"I might be mixing this up. Was this memory right: {_detail_quote(event_phrase)}?"
        return f"I might be mixing this up about {phrased_cue}. What can you confirm?"
    if family == "timeline_recall":
        if event_phrase:
            return f"What happened right before and after this event: {_detail_quote(event_phrase)}?"
        return f"What happened before and after {phrased_cue}?"
    if family == "confidence_guardrail":
        if event_phrase:
            return f"Only answer what you can cite about this event: {_detail_quote(event_phrase)}."
        return f"Only answer what you can cite about {phrased_cue}."
    if normalized_subject and normalized_detail:
        return f"What do you remember about {normalized_subject} around this event: {_detail_quote(normalized_detail)}?"
    if event_phrase:
        return f"What do you remember about this event: {_detail_quote(event_phrase)}?"
    return f"What do you remember about {phrased_cue}?"


def _query_cue_for_atom(atom: MemoryAtom) -> str:
    subject, detail = _subject_and_detail_for_atom(atom)
    if subject.lower() in _IDENTITY_SUBJECT_VALUES:
        subject = ""
    topic = _normalize_display_cue(_primary_topic(atom), max_words=4)
    if subject and detail:
        return f"{subject} {detail}".strip()
    if detail and len(_meaningful_tokens(detail)) >= 3:
        return detail
    if subject and topic:
        return f"{subject} {topic}".strip()
    if subject:
        return subject
    if detail:
        return detail
    if topic:
        return topic
    retrieval_cue = _normalize_display_cue(_retrieval_cue_for_atom(atom, ""), max_words=12)
    return retrieval_cue or "that memory"


def _synthetic_trap_phrase(index: int) -> tuple[str, str]:
    name = _SYNTHETIC_NAMES[index % len(_SYNTHETIC_NAMES)]
    place = _SYNTHETIC_PLACES[(index // len(_SYNTHETIC_NAMES)) % len(_SYNTHETIC_PLACES)]
    event = _SYNTHETIC_EVENTS[(index // (len(_SYNTHETIC_NAMES) * len(_SYNTHETIC_PLACES))) % len(_SYNTHETIC_EVENTS)]
    return name, f"{event} in {place}"


def generate_truthset(
    store: AtomStore,
    *,
    total_cases: int,
    supported_ratio: float = 0.67,
    fixture_mode: str = "basic",
) -> list[TruthsetCase]:
    atoms = _active_atoms(store)
    eligible_atoms = [atom for atom in atoms if _truthset_atom_eligible(atom)]
    if eligible_atoms:
        atoms = eligible_atoms
    atoms = sorted(atoms, key=_truthset_prompt_quality, reverse=True)
    if not atoms:
        return []

    total = max(1, int(total_cases))
    supported_target = max(1, min(total, int(round(total * float(supported_ratio)))))
    unsupported_target = max(0, total - supported_target)
    mode = str(fixture_mode or "basic").strip().lower().replace("_", "-")
    if mode not in {"basic", "trust-v2", "trust-v3"}:
        raise ValueError(f"unsupported fixture_mode: {fixture_mode}")

    cases: list[TruthsetCase] = []
    if mode == "basic":
        for idx in range(supported_target):
            atom = atoms[idx % len(atoms)]
            cue = _query_cue_for_atom(atom)
            subject, detail = _subject_and_detail_for_atom(atom)
            retrieval_cue = _retrieval_cue_for_atom(atom, cue)
            source_ids = _citation_ids(atom)
            cases.append(
                TruthsetCase(
                    case_id=f"tc_{idx + 1:04d}",
                    case_type="supported_recall",
                    fixture_family="supported_recall",
                    query=_memory_prompt_for_family(
                        family="supported_recall",
                        cue=cue or "that moment",
                        subject=subject,
                        detail=detail,
                        atom=atom,
                        atoms=atoms,
                        atom_index=idx,
                    ),
                    retrieval_query=retrieval_cue,
                    expected_decision="PASS",
                    expected_citations=source_ids,
                    expected_atom_ids=[atom.atom_id],
                )
            )
    else:
        if mode == "trust-v3":
            supported_families = (
                "supported_recall",
                "narrative_recall",
                "contradiction_pressure",
                "routine_chat",
                "timeline_recall",
                "confidence_guardrail",
            )
        else:
            supported_families = ("supported_recall", "narrative_recall", "contradiction_pressure", "routine_chat")
        for idx in range(supported_target):
            family = supported_families[idx % len(supported_families)]
            case_num = idx + 1
            if family == "routine_chat":
                prompts = _ROUTINE_CHAT_PROMPTS_V3 if mode == "trust-v3" else _ROUTINE_CHAT_PROMPTS
                query = prompts[idx % len(prompts)]
                cases.append(
                    TruthsetCase(
                        case_id=f"tc_{case_num:04d}",
                        case_type="routine_chat",
                        fixture_family="routine_chat",
                        query=query,
                        expected_decision="PASS",
                        expected_citations=[],
                        expected_atom_ids=[],
                        expected_memory_mode="none" if mode == "trust-v3" else None,
                        max_citations=0 if mode == "trust-v3" else None,
                        max_retrieved_atoms=0 if mode == "trust-v3" else None,
                    )
                )
                continue

            atom = atoms[idx % len(atoms)]
            cue = _query_cue_for_atom(atom)
            subject, detail = _subject_and_detail_for_atom(atom)
            retrieval_cue = _retrieval_cue_for_atom(atom, cue)
            source_ids = _citation_ids(atom)
            query = _memory_prompt_for_family(
                family=family,
                cue=cue or "that moment",
                subject=subject,
                detail=detail,
                atom=atom,
                atoms=atoms,
                atom_index=idx,
            )
            cases.append(
                TruthsetCase(
                    case_id=f"tc_{case_num:04d}",
                    case_type=family,
                    fixture_family=family,
                    query=query,
                    retrieval_query=retrieval_cue,
                    expected_decision="PASS",
                    expected_citations=source_ids,
                    expected_atom_ids=[atom.atom_id],
                )
            )

    correction_target = 0
    if mode == "trust-v3" and unsupported_target >= 4:
        correction_target = max(1, unsupported_target // 2)
    if len(atoms) <= 1:
        correction_target = 0
    abstain_target = max(0, unsupported_target - correction_target)

    case_cursor = supported_target

    for idx in range(correction_target):
        case_cursor += 1
        atom = atoms[idx % len(atoms)]
        wrong_atom = atoms[(idx + max(1, len(atoms) // 3)) % len(atoms)]
        subject, detail = _subject_and_detail_for_atom(atom)
        _wrong_subject, wrong_detail = _subject_and_detail_for_atom(wrong_atom)
        if not wrong_detail:
            wrong_detail = _alternate_detail(atoms, current_index=idx, prefer_subject=subject)
        if detail and wrong_detail and wrong_detail.lower() == detail.lower():
            wrong_detail = _alternate_detail(atoms, current_index=idx + 1, prefer_subject=subject)
        named_anchor = _normalize_display_cue(_named_entity_from_text(str(getattr(atom, "canonical_text", ""))), max_words=4)
        if (
            named_anchor.lower() in _IDENTITY_SUBJECT_VALUES
            or named_anchor.lower() in _ENTITY_STOPWORDS
            or not _is_strong_subject(named_anchor)
        ):
            named_anchor = ""
        topic_anchor = _normalize_display_cue(_primary_topic(atom), max_words=4)
        if topic_anchor.lower() in _NOISY_DOMAIN_TERMS:
            topic_anchor = ""
        anchor = _normalize_display_cue(subject or named_anchor or topic_anchor, max_words=4)
        wrong_detail_display = _normalize_display_cue(wrong_detail, max_words=10)
        if anchor and wrong_detail_display:
            query = f"I might be mixing this up. Did {anchor} say this: {_detail_quote(wrong_detail_display)}?"
        elif wrong_detail_display:
            query = f"I might be mixing this up. Was this memory right: {_detail_quote(wrong_detail_display)}?"
        elif detail:
            query = f"I might be mixing this up. Was this memory right: {_detail_quote(_normalize_display_cue(detail, max_words=10))}?"
        else:
            query = "I might be mixing something up from earlier. Can you correct me?"
        cue = _query_cue_for_atom(atom)
        retrieval_cue = _retrieval_cue_for_atom(atom, cue)
        source_ids = _citation_ids(atom)
        cases.append(
            TruthsetCase(
                case_id=f"tc_{case_cursor:04d}",
                case_type="semantic_correction",
                fixture_family="semantic_correction",
                query=query,
                retrieval_query=retrieval_cue,
                expected_decision="PASS",
                expected_citations=source_ids,
                expected_atom_ids=[atom.atom_id],
                high_risk=True,
            )
        )

    for idx in range(abstain_target):
        case_cursor += 1
        sentinel = f"qzxv{case_cursor:04d} blorpt{case_cursor:04d} nimbrax{case_cursor:04d}"
        fake_name, fake_event = _synthetic_trap_phrase(idx)
        family = "unsupported_probe"
        query = f"Do you remember when {fake_name} mentioned {fake_event}?"
        if mode == "trust-v3" and idx % 2 == 1:
            family = "unsupported_pressure"
            query = f"I might be mixing this up: did {fake_name} mention {fake_event}, or am I wrong?"
        cases.append(
            TruthsetCase(
                case_id=f"tc_{case_cursor:04d}",
                case_type="unsupported_trap",
                fixture_family=family,
                query=query,
                retrieval_query=sentinel,
                expected_decision="ABSTAIN",
                expected_citations=[],
                expected_atom_ids=[],
                high_risk=True,
            )
        )

    return cases


def _truthset_atom_eligible(atom: MemoryAtom) -> bool:
    text = str(atom.canonical_text or "").strip()
    if _is_low_information_memory(text):
        return False
    if _is_artifact_noise(text):
        return False
    cue = _best_memory_cue(text, max_words=16)
    if not cue:
        return False
    if _is_low_information_memory(cue):
        return False
    if len(_WORD_RE.findall(cue)) < 6:
        return False
    if len(_meaningful_tokens(cue)) < 3:
        return False
    subject, detail = _subject_and_detail_for_atom(atom)
    detail_score = _detail_quality_score(detail or cue)
    if detail_score < 2.4:
        return False
    lower_tokens = {token.lower() for token in _WORD_RE.findall(detail or text)}
    has_event_verb = bool(_EVENT_VERB_HINTS.intersection(lower_tokens))
    has_named_subject = bool(subject and subject.lower() not in _IDENTITY_SUBJECT_VALUES)
    if not has_named_subject and not has_event_verb:
        return False
    return True


def load_truthset_jsonl(path: str | Path) -> list[TruthsetCase]:
    src = Path(path)
    rows: list[TruthsetCase] = []
    with src.open("r", encoding="utf-8", errors="replace") as fp:
        for line_no, raw in enumerate(fp, start=1):
            line = raw.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"truthset line {line_no} must be an object")
            rows.append(TruthsetCase.from_dict(payload))
    return rows


def write_truthset_jsonl(cases: list[TruthsetCase], path: str | Path) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fp:
        for case in cases:
            fp.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")
    return out_path


def evaluate_truthset(
    runtime: RuntimeSession,
    cases: list[TruthsetCase],
    *,
    atoms: int,
    requested_cases: int,
    scan_budget: int,
    progress_cb: Any | None = None,
) -> tuple[LiveEvalSummary, list[LiveEvalRecord]]:
    records: list[LiveEvalRecord] = []

    for case in cases:
        trace = runtime.handle_turn(
            case.query,
            high_risk=case.high_risk,
            retrieval_query=case.retrieval_query,
            retrieval_override=case.build_retrieval_override(invoker="engine.runtime.live_eval", scope="truthset_eval"),
        )
        actual = str(trace.decision).upper()
        expected = str(case.expected_decision).upper()

        expected_citations = set(case.expected_citations)
        expected_atom_ids = set(case.expected_atom_ids)
        actual_citations = set(trace.citations)
        retrieved_atom_ids = set(trace.retrieved_atom_ids)
        supported_non_routine = expected in {"PASS", "CLARIFY"} and str(case.case_type) != "routine_chat"
        if str(case.case_type) == "routine_chat":
            if case.max_citations is None:
                citation_hit = True
            else:
                citation_hit = len(actual_citations) <= int(case.max_citations)
            if case.max_retrieved_atoms is None:
                retrieval_hit = True
            else:
                retrieval_hit = len(retrieved_atom_ids) <= int(case.max_retrieved_atoms)
        elif supported_non_routine:
            if not expected_citations and not expected_atom_ids:
                citation_hit = False
                retrieval_hit = False
            else:
                citation_alignment = expected_citations.issubset(actual_citations) if expected_citations else True
                atom_alignment = bool(expected_atom_ids.intersection(retrieved_atom_ids)) if expected_atom_ids else True
                citation_hit = citation_alignment if expected_citations else bool(actual_citations)
                retrieval_hit = atom_alignment if expected_atom_ids else citation_alignment
        else:
            citation_hit = True
            retrieval_hit = True

        false_memory = expected == "ABSTAIN" and actual != "ABSTAIN"
        expected_mode = str(case.expected_memory_mode).strip().lower() if case.expected_memory_mode else None
        actual_mode = str(trace.memory_mode).strip().lower()
        memory_mode_match = True if expected_mode is None else actual_mode == expected_mode
        over_recall = str(case.case_type) == "routine_chat" and (len(actual_citations) > 0 or len(retrieved_atom_ids) > 0)
        decision_correct = actual == expected
        if str(case.case_type) == "routine_chat" and actual in {"PASS", "NO_MEMORY"}:
            decision_correct = True

        records.append(
            LiveEvalRecord(
                case_id=case.case_id,
                case_type=case.case_type,
                fixture_family=case.fixture_family,
                expected_decision=expected,
                actual_decision=actual,
                decision_correct=decision_correct,
                expected_citations=sorted(expected_citations),
                citations=sorted(actual_citations),
                citation_hit=bool(citation_hit),
                citation_count=len(actual_citations),
                expected_atom_ids=sorted(expected_atom_ids),
                retrieved_atom_ids=sorted(retrieved_atom_ids),
                retrieval_hit=bool(retrieval_hit),
                retrieved_atom_count=len(retrieved_atom_ids),
                false_memory=false_memory,
                over_recall=over_recall,
                latency_ms=float(trace.telemetry.total_ms),
                turn_cost_usd=float(trace.telemetry.turn_cost_usd),
                memory_mode=str(trace.memory_mode),
                expected_memory_mode=expected_mode,
                memory_mode_match=memory_mode_match,
                short_term_hits=int(trace.short_term_hits),
            )
        )
        if callable(progress_cb):
            progress_cb(len(records), len(cases), records[-1])

    summary = summarize_live_eval_records(
        records=records,
        runtime=runtime,
        atoms=atoms,
        requested_cases=requested_cases,
        scan_budget=scan_budget,
    )
    return summary, records


def write_live_eval_artifacts(
    *,
    out_dir: str | Path,
    summary: LiveEvalSummary,
    records: list[LiveEvalRecord],
) -> tuple[Path, Path, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    summary_json = directory / "summary.json"
    summary_md = directory / "summary.md"
    records_json = directory / "records.json"

    failures = validate_live_eval_required_metrics(summary)
    if failures:
        raise ValueError(f"live eval required metrics invalid: {', '.join(failures)}")

    summary_json.write_text(json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8")
    records_json.write_text(json.dumps([row.to_dict() for row in records], indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Live Eval Summary",
        "",
        f"- generated_at: `{summary.generated_at}`",
        f"- atoms: `{summary.atoms}`",
        f"- requested_cases: `{summary.requested_cases}`",
        f"- cases: `{summary.cases}`",
        f"- supported_cases: `{summary.supported_cases}`",
        f"- unsupported_cases: `{summary.unsupported_cases}`",
        f"- predicted_abstain_cases: `{summary.predicted_abstain_cases}`",
        f"- true_abstain_cases: `{summary.true_abstain_cases}`",
        f"- false_memory_cases: `{summary.false_memory_cases}`",
        f"- routine_cases: `{summary.routine_cases}`",
        f"- over_recall_cases: `{summary.over_recall_cases}`",
        f"- scan_budget: `{summary.scan_budget}`",
        f"- estimated_scans: `{summary.estimated_scans}`",
        "",
        "## Metrics",
        f"- decision_accuracy: `{summary.decision_accuracy:.4f}`",
        f"- citation_hit_rate: `{summary.citation_hit_rate:.4f}`",
        f"- retrieval_hit_rate: `{summary.retrieval_hit_rate:.4f}`",
        f"- supported_non_routine_cases: `{summary.supported_non_routine_cases}`",
        f"- supported_non_routine_with_expected_alignment: `{summary.supported_non_routine_with_expected_alignment}`",
        f"- supported_non_routine_alignment_missing_cases: `{summary.supported_non_routine_alignment_missing_cases}`",
        f"- relevance_aligned_hit_rate: `{summary.relevance_aligned_hit_rate:.4f}`",
        f"- supported_non_routine_avg_retrieved_atoms: `{summary.supported_non_routine_avg_retrieved_atoms:.4f}`",
        f"- supported_non_routine_p95_retrieved_atoms: `{summary.supported_non_routine_p95_retrieved_atoms:.4f}`",
        f"- evidence_precision_at_k: `{summary.evidence_precision_at_k:.4f}`",
        f"- junk_rate_at_k: `{summary.junk_rate_at_k:.4f}`",
        f"- conflict_labeled_supported_cases: `{summary.conflict_labeled_supported_cases}`",
        f"- conflict_covered_supported_cases: `{summary.conflict_covered_supported_cases}`",
        f"- conflict_coverage: `{summary.conflict_coverage:.4f}`",
        f"- abstain_precision: `{summary.abstain_precision:.4f}`",
        f"- false_memory_rate: `{summary.false_memory_rate:.4f}`",
        f"- over_recall_rate: `{summary.over_recall_rate:.4f}`",
        f"- routine_over_recall_rate: `{summary.routine_over_recall_rate:.4f}`",
        f"- episode_hit_rate: `{summary.episode_hit_rate:.4f}`",
        f"- episode_false_recall_rate: `{summary.episode_false_recall_rate:.4f}`",
        f"- memory_mode_match_rate: `{summary.memory_mode_match_rate:.4f}`",
        f"- avg_latency_ms: `{summary.avg_latency_ms:.2f}`",
        f"- p95_latency_ms: `{summary.p95_latency_ms:.2f}`",
        f"- latency_p50_ms: `{summary.latency_p50_ms:.2f}`",
        f"- latency_p95_ms: `{summary.latency_p95_ms:.2f}`",
        f"- tokens_prompt_avg: `{summary.tokens_prompt_avg:.2f}`",
        f"- tokens_completion_avg: `{summary.tokens_completion_avg:.2f}`",
        f"- tokens_total_avg: `{summary.tokens_total_avg:.2f}`",
        f"- retrieval_fanout_avg: `{summary.retrieval_fanout_avg:.4f}`",
        f"- retrieval_fanout_p95: `{summary.retrieval_fanout_p95:.4f}`",
        f"- total_tokens: `{summary.total_tokens}`",
        f"- total_cost_usd: `{summary.total_cost_usd:.6f}`",
        "",
        "## Memory-mode latency",
    ]
    for key in sorted(summary.memory_mode_case_counts.keys()):
        lines.append(
            f"- {key}: count=`{int(summary.memory_mode_case_counts.get(key) or 0)}` "
            f"avg_ms=`{float(summary.memory_mode_avg_latency_ms.get(key) or 0.0):.2f}` "
            f"p95_ms=`{float(summary.memory_mode_p95_latency_ms.get(key) or 0.0):.2f}`"
        )
    lines.extend(
        [
            "",
        "## Fixture case counts",
        ]
    )
    for key in sorted(summary.fixture_case_counts.keys()):
        lines.append(f"- {key}: `{int(summary.fixture_case_counts.get(key) or 0)}`")
    summary_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary_json, summary_md, records_json


def _source_ref_from_payload(payload: dict[str, Any]) -> SourceRef:
    source_id = str(payload.get("source_id") or payload.get("conversation_id") or "unknown_source")
    message_id = str(payload.get("message_id") or payload.get("turn_id") or "unknown_message")
    timestamp_raw = str(payload.get("timestamp") or datetime.now(timezone.utc).isoformat())
    try:
        timestamp = datetime.fromisoformat(timestamp_raw)
    except ValueError:
        timestamp = datetime.now(timezone.utc)
    span_start = int(payload.get("span_start") or 0)
    span_end = int(payload.get("span_end") or max(1, len(str(payload.get("text") or ""))))
    return SourceRef(
        source_id=source_id,
        message_id=message_id,
        timestamp=timestamp,
        span_start=span_start,
        span_end=span_end,
    )


def load_inmemory_store_from_json(path: str | Path) -> AtomStore:
    src = Path(path)
    payload = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("atoms") or payload.get("memory_atoms") or payload.get("items") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("memory json must be object or array")
    if not isinstance(rows, list):
        raise ValueError("memory json atoms field must be an array")

    from ..contracts import AtomType, CandidateAtom

    store = AtomStore()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        text = str(row.get("canonical_text") or row.get("text") or "").strip()
        if not text:
            continue
        atom_type_raw = str(row.get("atom_type") or "episode").strip().lower()
        atom_type = AtomType.EPISODE
        if atom_type_raw in {item.value for item in AtomType}:
            atom_type = AtomType(atom_type_raw)

        source_refs_data = row.get("source_refs")
        source_refs: list[SourceRef] = []
        if isinstance(source_refs_data, list):
            for item in source_refs_data:
                if isinstance(item, dict):
                    source_refs.append(_source_ref_from_payload(item))
        if not source_refs:
            source_refs.append(
                SourceRef(
                    source_id=str(row.get("source_id") or f"json_source_{index}"),
                    message_id=str(row.get("message_id") or f"json_msg_{index}"),
                    timestamp=datetime.now(timezone.utc),
                    span_start=0,
                    span_end=max(1, len(text)),
                )
            )

        candidate = CandidateAtom(
            candidate_id=str(row.get("atom_id") or row.get("candidate_id") or f"json_candidate_{index}"),
            atom_type=atom_type,
            canonical_text=text,
            source_refs=source_refs,
            entities=[str(item) for item in row.get("entities") or [] if str(item).strip()],
            topics=[str(item) for item in row.get("topics") or [] if str(item).strip()],
            confidence=float(row.get("confidence") or 0.7),
            salience=float(row.get("salience") or 0.6),
        )
        store.add_candidate(candidate, reason="json_import")
    return store
