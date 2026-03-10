from __future__ import annotations

import inspect
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from ..contracts import RetrievalOverrideRequestContract, SourceRef
from ..memory import AtomStore, AtomStatus, MemoryAtom
from .session import RuntimeSession


@dataclass(slots=True)
class LoadSample:
    turn_id: str
    latency_ms: float
    decision: str
    memory_mode: str
    short_term_hits: int
    turn_cost_usd: float
    input_tokens: int
    output_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LoadSummary:
    generated_at: str
    atoms: int
    requested_turns: int
    turns: int
    failed_turns: int
    scan_budget: int
    estimated_scans: int
    throughput_qps: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    avg_latency_ms: float
    abstain_rate: float
    total_tokens: int
    total_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LoadPlan:
    atoms: int
    requested_turns: int
    effective_turns: int
    scan_budget: int
    estimated_scans: int
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * quantile))
    index = max(0, min(index, len(ordered) - 1))
    return float(ordered[index])


def _snippet(text: str, *, max_words: int = 12) -> str:
    words = [w for w in str(text or "").strip().split() if w]
    if not words:
        return "memory"
    return " ".join(words[:max_words])


def _active_atoms(store: AtomStore) -> list[MemoryAtom]:
    return [atom for atom in store.list_atoms() if atom.status is not AtomStatus.TOMBSTONED]


def plan_load_workload(*, atom_count: int, requested_turns: int, scan_budget: int) -> LoadPlan:
    atoms = max(0, int(atom_count))
    requested = max(1, int(requested_turns))
    budget = max(1, int(scan_budget))
    if atoms == 0:
        return LoadPlan(
            atoms=atoms,
            requested_turns=requested,
            effective_turns=0,
            scan_budget=budget,
            estimated_scans=0,
            warning="No active atoms available; load workload downshifted to 0 turns.",
        )
    safe_turns = max(1, budget // max(atoms, 1))
    effective = min(requested, safe_turns)
    warning = None
    if effective < requested:
        warning = (
            f"Workload downshifted from {requested} to {effective} turns "
            f"(atoms={atoms}, budget={budget} scan-ops)."
        )
    return LoadPlan(
        atoms=atoms,
        requested_turns=requested,
        effective_turns=effective,
        scan_budget=budget,
        estimated_scans=atoms * effective,
        warning=warning,
    )


def _query_bank(store: AtomStore, total: int) -> list[tuple[str, str]]:
    atoms = _active_atoms(store)
    if not atoms:
        return []
    queries: list[tuple[str, str]] = []
    for idx in range(total):
        atom = atoms[idx % len(atoms)]
        snippet = _snippet(atom.canonical_text)
        queries.append((f"Please recall this memory: {snippet}", snippet))
    return queries


def _runtime_supports_retrieval_override(runtime: Any) -> bool:
    handle_turn = getattr(runtime, "handle_turn", None)
    if not callable(handle_turn):
        return False
    try:
        return "retrieval_override" in inspect.signature(handle_turn).parameters
    except (TypeError, ValueError):
        return False


def run_load_harness(
    runtime: RuntimeSession,
    store: AtomStore,
    *,
    requested_turns: int,
    scan_budget: int,
) -> tuple[LoadSummary, list[LoadSample]]:
    atoms = len(_active_atoms(store))
    plan = plan_load_workload(atom_count=atoms, requested_turns=requested_turns, scan_budget=scan_budget)
    queries = _query_bank(store, plan.effective_turns)

    started = time.perf_counter()
    samples: list[LoadSample] = []
    failed_turns = 0
    supports_override = _runtime_supports_retrieval_override(runtime)
    for query, retrieval_query in queries:
        try:
            kwargs: dict[str, Any] = {"retrieval_query": retrieval_query}
            if supports_override:
                kwargs["retrieval_override"] = RetrievalOverrideRequestContract(
                    query=retrieval_query,
                    invoker="engine.runtime.load_harness",
                    reason="load_harness_anchor_query",
                    scope="load_harness",
                    auth_context="load_harness",
                )
            trace = runtime.handle_turn(query, **kwargs)
        except Exception:
            failed_turns += 1
            continue
        samples.append(
            LoadSample(
                turn_id=trace.turn_id,
                latency_ms=float(trace.telemetry.total_ms),
                decision=str(trace.decision),
                memory_mode=str(trace.memory_mode),
                short_term_hits=trace.short_term_hits,
                turn_cost_usd=float(trace.telemetry.turn_cost_usd),
                input_tokens=trace.telemetry.input_tokens,
                output_tokens=trace.telemetry.output_tokens,
            )
        )

    elapsed = max(time.perf_counter() - started, 1e-9)
    latencies = [sample.latency_ms for sample in samples]
    abstains = sum(1 for sample in samples if sample.decision == "ABSTAIN")
    total_tokens = sum(sample.input_tokens + sample.output_tokens for sample in samples)
    total_cost = sum(sample.turn_cost_usd for sample in samples)

    summary = LoadSummary(
        generated_at=datetime.now(timezone.utc).isoformat(),
        atoms=plan.atoms,
        requested_turns=plan.requested_turns,
        turns=len(samples),
        failed_turns=failed_turns,
        scan_budget=plan.scan_budget,
        estimated_scans=plan.estimated_scans,
        throughput_qps=_ratio(len(samples), elapsed),
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_p99_ms=_percentile(latencies, 0.99),
        avg_latency_ms=float(mean(latencies)) if latencies else 0.0,
        abstain_rate=_ratio(abstains, len(samples)),
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
    )
    return summary, samples


def write_load_artifacts(
    *,
    out_dir: str | Path,
    summary: LoadSummary,
    samples: list[LoadSample],
) -> tuple[Path, Path, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    summary_json = directory / "load_summary.json"
    summary_md = directory / "load_summary.md"
    samples_json = directory / "load_samples.json"

    summary_json.write_text(json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8")
    samples_json.write_text(json.dumps([item.to_dict() for item in samples], indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Runtime Load Summary",
        "",
        f"- generated_at: `{summary.generated_at}`",
        f"- atoms: `{summary.atoms}`",
        f"- requested_turns: `{summary.requested_turns}`",
        f"- turns: `{summary.turns}`",
        f"- failed_turns: `{summary.failed_turns}`",
        f"- scan_budget: `{summary.scan_budget}`",
        f"- estimated_scans: `{summary.estimated_scans}`",
        "",
        "## Metrics",
        f"- throughput_qps: `{summary.throughput_qps:.4f}`",
        f"- latency_p50_ms: `{summary.latency_p50_ms:.2f}`",
        f"- latency_p95_ms: `{summary.latency_p95_ms:.2f}`",
        f"- latency_p99_ms: `{summary.latency_p99_ms:.2f}`",
        f"- avg_latency_ms: `{summary.avg_latency_ms:.2f}`",
        f"- abstain_rate: `{summary.abstain_rate:.4f}`",
        f"- total_tokens: `{summary.total_tokens}`",
        f"- total_cost_usd: `{summary.total_cost_usd:.6f}`",
    ]
    summary_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary_json, summary_md, samples_json


def load_inmemory_store_from_json(path: str | Path) -> AtomStore:
    """Back-compat shim for scripts that only import load_harness symbols."""

    from .live_eval import load_inmemory_store_from_json as _from_live_eval

    return _from_live_eval(path)


def source_refs_for_atom(atom: MemoryAtom) -> list[SourceRef]:
    return list(atom.source_refs)
