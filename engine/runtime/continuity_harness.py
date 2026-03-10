from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from ..contracts import RetrievalOverrideRequestContract
from ..memory import AtomStatus, AtomStore, MemoryAtom
from .session import RuntimeSession


@dataclass(slots=True)
class ContinuityCheck:
    turn_index: int
    fixture_family: str
    anchor_atom_id: str
    decision: str
    citation_hit: bool
    retrieval_hit: bool
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContinuitySummary:
    generated_at: str
    atoms: int
    turns: int
    checks: int
    pass_decision_checks: int
    citation_hit_checks: int
    retrieval_hit_checks: int
    recall_rate: float
    citation_rate: float
    retrieval_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    fixture_case_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FILLER_PROMPTS = (
    "Keep this thread moving with normal chat.",
    "Let us continue casually for one turn.",
    "A quick check-in before we continue.",
    "Stay in the current thread and keep context steady.",
)

_FILLER_PROMPTS_V3 = (
    "Let us keep this conversational for one turn.",
    "Quick topic shift before we continue.",
    "No recall needed yet, just continue naturally.",
    "Small check-in, then we can return to details.",
    "Keep this turn light and steady.",
)


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


def _active_atoms(store: AtomStore) -> list[MemoryAtom]:
    return [atom for atom in store.list_atoms() if atom.status is not AtomStatus.TOMBSTONED]


def _snippet(text: str, *, max_words: int = 12) -> str:
    words = [word for word in str(text or "").split() if word]
    if not words:
        return "memory"
    return " ".join(words[:max_words])


def _citation_ids(atom: MemoryAtom) -> set[str]:
    return {
        str(ref.source_id).strip()
        for ref in list(atom.source_refs or [])
        if str(getattr(ref, "source_id", "")).strip()
    }


def run_continuity_harness(
    runtime: RuntimeSession,
    store: AtomStore,
    *,
    turns: int = 12,
    recall_interval: int = 4,
    fixture_mode: str = "basic",
) -> tuple[ContinuitySummary, list[ContinuityCheck]]:
    all_atoms = _active_atoms(store)
    atoms = all_atoms[: min(len(all_atoms), 10)]
    total_turns = max(0, int(turns))
    interval = max(1, int(recall_interval))
    mode = str(fixture_mode or "basic").strip().lower().replace("_", "-")
    if mode not in {"basic", "trust-v2", "trust-v3"}:
        raise ValueError(f"unsupported fixture_mode: {fixture_mode}")

    checks: list[ContinuityCheck] = []
    fixture_case_counts: dict[str, int] = {}
    if total_turns <= 0 or not atoms:
        summary = ContinuitySummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            atoms=len(all_atoms),
            turns=0,
            checks=0,
            pass_decision_checks=0,
            citation_hit_checks=0,
            retrieval_hit_checks=0,
            recall_rate=0.0,
            citation_rate=0.0,
            retrieval_rate=0.0,
            avg_latency_ms=0.0,
            p95_latency_ms=0.0,
            fixture_case_counts={},
        )
        return summary, checks

    filler_prompts = _FILLER_PROMPTS_V3 if mode == "trust-v3" else _FILLER_PROMPTS
    probe_families = ("direct_recall", "crosscheck_recall", "delayed_recall")
    for turn_index in range(total_turns):
        should_probe = ((turn_index + 1) % interval) == 0
        if not should_probe:
            prompt = filler_prompts[turn_index % len(filler_prompts)]
            runtime.handle_turn(prompt)
            continue

        anchor = atoms[(turn_index // interval) % len(atoms)]
        anchor_snippet = _snippet(anchor.canonical_text)
        probe_family = "direct_recall"
        if mode == "trust-v3":
            probe_family = probe_families[(turn_index // interval) % len(probe_families)]
            if probe_family == "crosscheck_recall":
                query = f"I might be mixing this up. What can you confirm from this thread: {anchor_snippet}?"
            elif probe_family == "delayed_recall":
                query = f"After all this context, what detail still holds: {anchor_snippet}?"
            else:
                query = f"What do you remember about this thread detail: {anchor_snippet}?"
        else:
            query = f"What do you remember about this thread detail: {anchor_snippet}?"
        trace = runtime.handle_turn(
            query,
            retrieval_query=anchor_snippet,
            retrieval_override=RetrievalOverrideRequestContract(
                query=anchor_snippet,
                invoker="engine.runtime.continuity_harness",
                reason=f"continuity_probe_turn:{turn_index + 1}",
                scope="continuity_harness",
                auth_context="continuity_harness",
            ),
        )
        citations = {
            str(item).strip().split("#", 1)[0]
            for item in list(trace.citations or [])
            if str(item).strip()
        }
        expected_citations = _citation_ids(anchor)
        citation_hit = bool(citations.intersection(expected_citations)) if expected_citations else bool(citations)
        retrieval_hit = str(anchor.atom_id) in {str(item) for item in list(trace.retrieved_atom_ids or [])}
        checks.append(
            ContinuityCheck(
                turn_index=turn_index + 1,
                fixture_family=probe_family,
                anchor_atom_id=str(anchor.atom_id),
                decision=str(trace.decision),
                citation_hit=bool(citation_hit),
                retrieval_hit=bool(retrieval_hit),
                latency_ms=float(trace.telemetry.total_ms),
            )
        )
        fixture_case_counts[probe_family] = fixture_case_counts.get(probe_family, 0) + 1

    check_count = len(checks)
    pass_decisions = sum(1 for row in checks if row.decision in {"PASS", "CLARIFY"})
    citation_hits = sum(1 for row in checks if row.citation_hit)
    retrieval_hits = sum(1 for row in checks if row.retrieval_hit)
    latencies = [row.latency_ms for row in checks]
    summary = ContinuitySummary(
        generated_at=datetime.now(timezone.utc).isoformat(),
        atoms=len(all_atoms),
        turns=total_turns,
        checks=check_count,
        pass_decision_checks=pass_decisions,
        citation_hit_checks=citation_hits,
        retrieval_hit_checks=retrieval_hits,
        recall_rate=_ratio(pass_decisions, check_count),
        citation_rate=_ratio(citation_hits, check_count),
        retrieval_rate=_ratio(retrieval_hits, check_count),
        avg_latency_ms=float(mean(latencies)) if latencies else 0.0,
        p95_latency_ms=_p95(latencies),
        fixture_case_counts=fixture_case_counts,
    )
    return summary, checks


def write_continuity_artifacts(
    *,
    out_dir: str | Path,
    summary: ContinuitySummary,
    checks: list[ContinuityCheck],
) -> tuple[Path, Path, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    summary_json = directory / "continuity_summary.json"
    summary_md = directory / "continuity_summary.md"
    checks_json = directory / "continuity_checks.json"

    summary_json.write_text(json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8")
    checks_json.write_text(json.dumps([item.to_dict() for item in checks], indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Continuity Harness Summary",
        "",
        f"- generated_at: `{summary.generated_at}`",
        f"- atoms: `{summary.atoms}`",
        f"- turns: `{summary.turns}`",
        f"- checks: `{summary.checks}`",
        f"- recall_rate: `{summary.recall_rate:.4f}`",
        f"- citation_rate: `{summary.citation_rate:.4f}`",
        f"- retrieval_rate: `{summary.retrieval_rate:.4f}`",
        f"- avg_latency_ms: `{summary.avg_latency_ms:.2f}`",
        f"- p95_latency_ms: `{summary.p95_latency_ms:.2f}`",
        "",
        "## Fixture case counts",
    ]
    for key in sorted(summary.fixture_case_counts.keys()):
        lines.append(f"- {key}: `{int(summary.fixture_case_counts.get(key) or 0)}`")
    summary_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary_json, summary_md, checks_json
