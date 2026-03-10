from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession
from engine.runtime.load_harness import plan_load_workload, run_load_harness


def _candidate(candidate_id: str, text: str, source_id: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_msg",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=["load"],
        confidence=0.88,
        salience=0.69,
    )


def test_plan_load_workload_downshifts() -> None:
    plan = plan_load_workload(atom_count=10000, requested_turns=200, scan_budget=600000)
    assert plan.effective_turns == 60
    assert plan.warning is not None


def test_plan_load_workload_zero_atoms() -> None:
    plan = plan_load_workload(atom_count=0, requested_turns=50, scan_budget=600000)
    assert plan.effective_turns == 0
    assert plan.estimated_scans == 0
    assert plan.warning is not None


def test_run_load_harness_outputs_metrics() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=False,
    )

    summary, samples = run_load_harness(
        runtime,
        store,
        requested_turns=5,
        scan_budget=20000,
    )

    assert len(samples) == 5
    assert summary.turns == 5
    assert summary.failed_turns == 0
    assert summary.total_tokens >= 1
    assert summary.latency_p95_ms >= 0.0
    assert summary.throughput_qps > 0.0


class _FlakyRuntime:
    def __init__(self) -> None:
        self._calls = 0

    def handle_turn(self, prompt: str, *, retrieval_query: str | None = None):  # type: ignore[no-untyped-def]
        self._calls += 1
        if self._calls == 2:
            raise RuntimeError("transient runtime failure")
        return SimpleNamespace(
            turn_id=f"turn_{self._calls}",
            telemetry=SimpleNamespace(
                total_ms=5.0,
                turn_cost_usd=0.0,
                input_tokens=12,
                output_tokens=8,
            ),
            decision="PASS",
            memory_mode="LTM",
            short_term_hits=0,
        )


def test_run_load_harness_tolerates_partial_failures() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    runtime = _FlakyRuntime()

    summary, samples = run_load_harness(
        runtime,  # type: ignore[arg-type]
        store,
        requested_turns=3,
        scan_budget=30000,
    )

    assert summary.turns == 2
    assert summary.failed_turns == 1
    assert len(samples) == 2
