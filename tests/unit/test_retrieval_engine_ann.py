from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engine.config import default_config
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import MemoryRetriever
from engine.retrieval.ann_sidecar import AnnQueryResult


def _candidate(*, candidate_id: str, text: str, source_id: str) -> CandidateAtom:
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
        entities=["user"],
        topics=["benchmark"],
        confidence=0.84,
        salience=0.72,
    )


def test_retriever_ann_candidates_are_additive_only_and_bounded(tmp_path: Path) -> None:
    store = AtomStore()
    baseline = store.add_candidate(
        _candidate(candidate_id="baseline", text="Project planner timeline and milestones.", source_id="conv_base")
    )
    ann_target = store.add_candidate(
        _candidate(candidate_id="ann_target", text="Phase cadence release ordering and roadmap sequencing.", source_id="conv_target")
    )
    distractor = store.add_candidate(
        _candidate(candidate_id="distractor", text="Fresh basil and mint can brighten a summer cocktail.", source_id="conv_noise")
    )

    cfg = default_config()
    cfg.retrieval.ann_sidecar.enabled = True
    cfg.retrieval.ann_sidecar.embedding_store_path = str(tmp_path / "retrieval.ann.sqlite3")
    cfg.retrieval.ann_sidecar.top_k_ann = 1
    cfg.retrieval.ann_sidecar.candidate_cap_ratio = 1.0
    cfg.retrieval.ann_sidecar.candidate_cap_floor = 1
    retriever = MemoryRetriever(store, config=cfg)
    retriever._candidate_pool_floor = lambda _profile: 1  # type: ignore[method-assign]

    def _fake_ann(*_args, **_kwargs) -> AnnQueryResult:
        return AnnQueryResult(
            candidate_ids=[ann_target.atom_id, ann_target.atom_id, "missing_atom", distractor.atom_id],
            latency_ms=1.0,
            used=True,
            fallback_reason="",
            store_fingerprint="fp_live",
            backend_version="test-backend",
        )

    retriever._query_ann_candidates = _fake_ann  # type: ignore[attr-defined]

    result = retriever.retrieve("project planner milestone timeline")

    assert baseline.atom_id in result.ranked_atom_ids
    assert ann_target.atom_id in result.ranked_atom_ids
    assert result.ann.used is True
    assert result.ann.candidate_count == 1
    assert result.ann.backend_version == "test-backend"
    assert result.ann.fallback_reason == ""


def test_retriever_ann_disable_is_a_true_kill_switch(tmp_path: Path) -> None:
    store = AtomStore()
    target = store.add_candidate(
        _candidate(candidate_id="target", text="Roadmap sequencing for milestone planning.", source_id="conv_target")
    )
    store.add_candidate(
        _candidate(candidate_id="noise", text="Project planner timeline and milestones.", source_id="conv_noise")
    )

    cfg = default_config()
    cfg.retrieval.ann_sidecar.enabled = False
    cfg.retrieval.ann_sidecar.embedding_store_path = str(tmp_path / "retrieval.ann.sqlite3")
    retriever = MemoryRetriever(store, config=cfg)

    called = {"count": 0}

    def _fake_ann(*_args, **_kwargs) -> AnnQueryResult:
        called["count"] += 1
        return AnnQueryResult(candidate_ids=[target.atom_id], used=True)

    retriever._query_ann_candidates = _fake_ann  # type: ignore[attr-defined]
    result = retriever.retrieve("project planner milestone timeline")

    assert called["count"] == 0
    assert result.ann.enabled is False
    assert result.ann.used is False
    assert result.ann.candidate_count == 0


def test_retriever_ann_fallback_does_not_change_baseline_ranked_ids(tmp_path: Path) -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(candidate_id="base_1", text="Project planner timeline and milestones.", source_id="conv_1")
    )
    store.add_candidate(
        _candidate(candidate_id="base_2", text="Project rollout checklist and planning blockers.", source_id="conv_2")
    )
    query = "project planner milestone timeline"

    baseline_cfg = default_config()
    baseline_cfg.retrieval.ann_sidecar.enabled = False
    baseline = MemoryRetriever(store, config=baseline_cfg).retrieve(query)

    cfg = default_config()
    cfg.retrieval.ann_sidecar.enabled = True
    cfg.retrieval.ann_sidecar.embedding_store_path = str(tmp_path / "retrieval.ann.sqlite3")
    retriever = MemoryRetriever(store, config=cfg)

    def _fake_ann(*_args, **_kwargs) -> AnnQueryResult:
        return AnnQueryResult(candidate_ids=[], latency_ms=51.0, used=False, fallback_reason="timeout")

    retriever._query_ann_candidates = _fake_ann  # type: ignore[attr-defined]
    result = retriever.retrieve(query)

    assert result.ranked_atom_ids == baseline.ranked_atom_ids
    assert result.ann.enabled is True
    assert result.ann.used is False
    assert result.ann.fallback_reason == "timeout"
