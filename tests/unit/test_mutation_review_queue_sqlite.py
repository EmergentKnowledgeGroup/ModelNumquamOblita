from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from engine.contracts import AtomType, CandidateAtom, SourceRef, WriteAction
from engine.memory import AtomStatus, MutationReviewQueue, ProposalStatus, SqliteAtomStore
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


def test_sqlite_review_queue_idempotency_survives_restart_and_rejects_payload_conflicts(tmp_path) -> None:
    path = tmp_path / "atoms.sqlite3"
    first_store = SqliteAtomStore(path)
    first_queue = MutationReviewQueue(first_store)
    response = {"proposal_id": "", "status": "pending_review", "audit_ref": "audit_persisted"}
    first, state, receipt = first_queue.propose_idempotent(
        action=WriteAction.PROPOSE_CREATE,
        target_atom_id="",
        replacement_candidate=_candidate("Idempotent durable proposal"),
        reason_code="integration_create",
        metadata={"run_id": "run_1"},
        actor="operator-1",
        idempotency_key="idem_restart_1",
        payload_fingerprint="payload_a",
        response=response,
    )
    assert state == "created"
    assert first is not None
    assert receipt["proposal_id"] == first.proposal_id
    first_store.close()

    reopened = SqliteAtomStore(path)
    resumed = MutationReviewQueue(reopened)
    replay, replay_state, replay_receipt = resumed.propose_idempotent(
        action=WriteAction.PROPOSE_CREATE,
        target_atom_id="",
        replacement_candidate=_candidate("Idempotent durable proposal"),
        reason_code="integration_create",
        metadata={"run_id": "run_1"},
        actor="operator-1",
        idempotency_key="idem_restart_1",
        payload_fingerprint="payload_a",
        response=response,
    )
    assert replay_state == "replay"
    assert replay is not None and replay.proposal_id == first.proposal_id
    assert replay_receipt == receipt
    conflict, conflict_state, _ = resumed.propose_idempotent(
        action=WriteAction.PROPOSE_CREATE,
        target_atom_id="",
        replacement_candidate=_candidate("Conflicting durable proposal"),
        reason_code="integration_create",
        metadata={"run_id": "run_1"},
        actor="operator-1",
        idempotency_key="idem_restart_1",
        payload_fingerprint="payload_b",
        response=response,
    )
    assert conflict is None
    assert conflict_state == "conflict"
    assert len(resumed.list_all()) == 1
    reopened.close()


def test_sqlite_review_queue_idempotency_serializes_concurrent_store_connections(tmp_path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    first_store = SqliteAtomStore(path)
    second_store = SqliteAtomStore(path)
    first_queue = MutationReviewQueue(first_store)
    second_queue = MutationReviewQueue(second_store)
    barrier = threading.Barrier(2)

    def submit(queue: MutationReviewQueue):
        barrier.wait(timeout=5)
        return queue.propose_idempotent(
            action=WriteAction.PROPOSE_CREATE,
            target_atom_id="",
            replacement_candidate=_candidate("Concurrent durable proposal"),
            reason_code="integration_create",
            metadata={"run_id": "run_concurrent"},
            actor="operator-1",
            idempotency_key="idem_concurrent_1",
            payload_fingerprint="payload_concurrent",
            response={"proposal_id": "", "status": "pending_review", "audit_ref": "audit_concurrent"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, (first_queue, second_queue)))
    proposal_ids = {result[0].proposal_id for result in results if result[0] is not None}
    assert {result[1] for result in results} == {"created", "replay"}
    assert len(proposal_ids) == 1
    assert len(first_queue.list_all()) == 1
    first_store.close()
    second_store.close()


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


def test_sqlite_review_queue_rejects_edit_that_dedupes_to_its_target(tmp_path) -> None:
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    original = store.add_candidate(_candidate("Unchanged atom"))
    queue = MutationReviewQueue(store)
    proposal = queue.propose_edit(
        target_atom_id=original.atom_id,
        replacement_candidate=_candidate("Unchanged atom"),
        reason_code="manual_edit",
    )
    queue.approve(proposal.proposal_id, actor="reviewer-1")

    with pytest.raises(ValueError, match="replacement must differ from target"):
        queue.apply(proposal.proposal_id, actor="reviewer-1")

    assert queue.get(proposal.proposal_id).status is ProposalStatus.APPROVED
    assert store.get_atom(original.atom_id).status is AtomStatus.ACTIVE
    assert len(store.list_atoms()) == 1
    store.close()
