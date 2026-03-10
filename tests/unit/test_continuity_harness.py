from __future__ import annotations

from datetime import datetime, timezone

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession
from engine.runtime.continuity_harness import run_continuity_harness, write_continuity_artifacts


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
        topics=["continuity"],
        confidence=0.88,
        salience=0.7,
    )


def test_run_continuity_harness_returns_probe_metrics(tmp_path) -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea during late sessions.", "conv_1"))
    store.add_candidate(_candidate("c2", "Project delta has one blocker in milestone three.", "conv_2"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=True,
    )
    try:
        summary, checks = run_continuity_harness(runtime, store, turns=8, recall_interval=2, fixture_mode="trust-v3")
    finally:
        runtime.close()

    assert summary.turns == 8
    assert summary.checks == 4
    assert len(checks) == 4
    assert 0.0 <= summary.recall_rate <= 1.0
    assert 0.0 <= summary.citation_rate <= 1.0
    assert 0.0 <= summary.retrieval_rate <= 1.0
    assert sum(summary.fixture_case_counts.values()) == 4
    assert {"direct_recall", "crosscheck_recall", "delayed_recall"}.intersection(summary.fixture_case_counts.keys())
    assert all(check.fixture_family for check in checks)

    summary_json, summary_md, checks_json = write_continuity_artifacts(
        out_dir=tmp_path,
        summary=summary,
        checks=checks,
    )
    assert summary_json.exists()
    assert summary_md.exists()
    assert checks_json.exists()
