from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import MutationReviewQueue, ProposalStatus, SqliteAtomStore
from engine.memory.mutation_queue import DecisionConflictError


def _candidate(text: str = "Durable evidence atom") -> CandidateAtom:
    return CandidateAtom(
        candidate_id="candidate-durable",
        atom_type=AtomType.ATOMIC_FACT,
        canonical_text=text,
        source_refs=[SourceRef("source-1", "message-1", datetime.now(timezone.utc), 0, len(text))],
        confidence=0.8,
        salience=0.7,
    )


def test_sqlite_review_queue_persists_decisions_and_exact_once_apply(tmp_path) -> None:
    path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(path)
    queue = MutationReviewQueue(store)
    proposed = queue.propose_create(candidate=_candidate(), reason_code="explicit_remember", actor="operator-1")
    queue.approve(proposed.proposal_id, actor="reviewer-1")
    first = queue.apply(proposed.proposal_id, actor="reviewer-1")
    second = queue.apply(proposed.proposal_id, actor="reviewer-1")
    assert first.status is ProposalStatus.APPLIED
    assert first.applied_atom_id
    assert second.applied_atom_id == first.applied_atom_id
    assert len(store.list_atoms()) == 1
    store.close()

    reopened = SqliteAtomStore(path)
    resumed = MutationReviewQueue(reopened)
    persisted = resumed.get(proposed.proposal_id)
    assert persisted.status is ProposalStatus.APPLIED
    assert persisted.applied_atom_id == first.applied_atom_id
    assert resumed.apply(proposed.proposal_id, actor="reviewer-1").applied_atom_id == first.applied_atom_id
    assert len(reopened.list_atoms()) == 1


def test_sqlite_review_queue_pending_and_approved_survive_restart(tmp_path) -> None:
    path = tmp_path / "atoms.sqlite3"
    first_store = SqliteAtomStore(path)
    pending = MutationReviewQueue(first_store).propose_create(candidate=_candidate("Pending atom"), reason_code="explicit_remember")
    first_store.close()

    second_store = SqliteAtomStore(path)
    second_queue = MutationReviewQueue(second_store)
    assert second_queue.get(pending.proposal_id).status is ProposalStatus.PENDING
    second_queue.approve(pending.proposal_id, actor="reviewer-1")
    second_store.close()

    final_store = SqliteAtomStore(path)
    assert MutationReviewQueue(final_store).get(pending.proposal_id).status is ProposalStatus.APPROVED


def test_sqlite_review_queue_rejects_opposite_immutable_decision_after_restart(tmp_path) -> None:
    path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(path)
    queue = MutationReviewQueue(store)
    proposed = queue.propose_create(candidate=_candidate(), reason_code="explicit_remember")
    queue.reject(proposed.proposal_id, actor="reviewer-1", reason="not enough evidence")
    store.close()

    reopened = SqliteAtomStore(path)
    resumed = MutationReviewQueue(reopened)
    with pytest.raises(DecisionConflictError, match="DECISION_CONFLICT"):
        resumed.approve(proposed.proposal_id, actor="reviewer-2")
    assert resumed.get(proposed.proposal_id).status is ProposalStatus.REJECTED


def test_sqlite_review_queue_applies_prior_approval_and_persists_bridge_markers(tmp_path) -> None:
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    queue = MutationReviewQueue(store)
    proposed = queue.propose_create(
        candidate=_candidate(),
        reason_code="provisional_bridge_create",
        metadata={"provisional_record_id": "prov-123"},
    )
    queue.approve(proposed.proposal_id, actor="reviewer-1")
    applied = queue.apply(proposed.proposal_id, actor="reviewer-1", refresh_cache=lambda: (_ for _ in ()).throw(RuntimeError()))
    assert applied.status is ProposalStatus.APPLIED
    assert applied.applied_atom_id
    assert applied.refresh_pending is True
    bridge = store.mutation_bridge_state(proposed.proposal_id)
    assert bridge["provisional_record_id"] == "prov-123"
    assert bridge["applied_atom_id"] == applied.applied_atom_id
    assert bridge["bridge_sync_pending"] is True
    assert store.is_provisional_bridge_suppressed("prov-123") is True


def test_sqlite_review_queue_concurrent_apply_retries_create_one_atom(tmp_path) -> None:
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    queue = MutationReviewQueue(store)
    proposed = queue.propose_create(candidate=_candidate("Concurrent atom"), reason_code="explicit_remember")
    queue.approve(proposed.proposal_id, actor="reviewer-1")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: queue.apply(proposed.proposal_id, actor="reviewer-1"), range(2)))

    assert results[0].applied_atom_id == results[1].applied_atom_id
    assert len(store.list_atoms()) == 1
