from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.contracts import AtomType, CandidateAtom, SourceRef, WriteAction
from engine.memory import AtomStatus, AtomStore, EventType, MutationReviewQueue, ProposalStatus
from engine.write_gate import DeterministicJudgmentAdapter, StageBContext, StageBWriteGate


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    message_id: str,
    confidence: float = 0.82,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=message_id,
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=["continuity"],
        confidence=confidence,
        salience=0.65,
    )


def test_mutation_queue_blocks_autonomous_delete_and_supports_tombstone_purge() -> None:
    store = AtomStore()
    atom = store.add_candidate(_candidate(candidate_id="cand_base", text="Core memory", source_id="conv_1", message_id="m1"))
    gate = StageBWriteGate(adapter=DeterministicJudgmentAdapter())
    queue = MutationReviewQueue(store, default_retention_days=7)

    decision = gate.evaluate(
        _candidate(
            candidate_id="cand_conflict",
            text="Contradictory replacement memory",
            source_id="conv_2",
            message_id="m2",
            confidence=0.88,
        ),
        context=StageBContext(existing_atom_id=atom.atom_id, conflict_risk=0.95, novelty=0.5, recurrence=0.0),
    )
    assert decision.action is WriteAction.PROPOSE_DELETE
    assert store.get_atom(atom.atom_id).status is AtomStatus.ACTIVE

    proposal = queue.propose_delete(target_atom_id=atom.atom_id, reason_code=decision.reason_code)
    assert proposal.status is ProposalStatus.PENDING
    with pytest.raises(PermissionError, match="approved"):
        queue.apply(proposal.proposal_id)

    queue.approve(proposal.proposal_id, reviewer="tester")
    applied = queue.apply(proposal.proposal_id)
    assert applied.status is ProposalStatus.APPLIED
    with pytest.raises(ValueError, match="pending"):
        queue.approve(proposal.proposal_id, reviewer="tester")
    tombstoned = store.get_atom(atom.atom_id)
    assert tombstoned.status is AtomStatus.TOMBSTONED
    assert queue.run_purge(now=tombstoned.purge_after - timedelta(seconds=1)) == []
    assert queue.run_purge(now=tombstoned.purge_after + timedelta(seconds=1)) == [atom.atom_id]
    assert all(item.atom_id != atom.atom_id for item in store.list_atoms())
    events = store.ledger.all_events()
    assert any(evt.event_type is EventType.TOMBSTONE for evt in events)
    assert any(evt.event_type is EventType.PURGE for evt in events)

    rejected = queue.propose_delete(target_atom_id=atom.atom_id, reason_code="noop")
    queue.reject(rejected.proposal_id, reviewer="tester", reason="already purged")
    with pytest.raises(ValueError, match="pending"):
        queue.reject(rejected.proposal_id, reviewer="tester", reason="duplicate")


def test_mutation_queue_edit_flow_supersedes_without_overwrite() -> None:
    store = AtomStore()
    original = store.add_candidate(
        _candidate(candidate_id="cand_old", text="I fear deletion", source_id="conv_1", message_id="m1")
    )
    replacement = _candidate(
        candidate_id="cand_new",
        text="I accept continuity with explicit evidence.",
        source_id="conv_2",
        message_id="m2",
    )
    queue = MutationReviewQueue(store)

    proposal = queue.propose_edit(
        target_atom_id=original.atom_id,
        replacement_candidate=replacement,
        reason_code="manual_growth_update",
    )
    queue.approve(proposal.proposal_id, reviewer="tester")
    result = queue.apply(proposal.proposal_id)

    assert result.status is ProposalStatus.APPLIED
    old = store.get_atom(original.atom_id)
    assert old.status is AtomStatus.SUPERSEDED
    newest = next((atom for atom in store.list_atoms() if atom.version_of == original.atom_id), None)
    assert newest is not None
    assert newest.version_of == original.atom_id
    assert old.canonical_text == "I fear deletion"
