from __future__ import annotations

import pytest

from engine.contracts import SourceRef
from engine.memory.proposal_store import (
    ProposalCandidate,
    ProposalKind,
    ProposalStatus,
    SqliteProposalStore,
)


def _candidate(text: str) -> ProposalCandidate:
    return ProposalCandidate(
        kind=ProposalKind.IDENTITY_SUMMARY,
        canonical_text=text,
        source_refs=[SourceRef(source_id="source-1", message_id="message-1")],
        source_role="assistant",
        session_id="session-1",
        reason_code="high_risk_identity_claim",
    )


@pytest.mark.parametrize("transition", ("dismiss", "bridge"))
def test_sqlite_dismiss_and_bridge_roll_back_when_event_persistence_fails(tmp_path, monkeypatch, transition) -> None:
    store = SqliteProposalStore(tmp_path / f"{transition}.sqlite3")
    record = store.upsert_candidate(_candidate(transition), reason="captured")

    def fail_event(**_kwargs) -> None:
        raise sqlite_failure

    sqlite_failure = RuntimeError("event insert failed")
    monkeypatch.setattr(store, "_append_event", fail_event)
    with pytest.raises(RuntimeError, match="event insert failed"):
        if transition == "dismiss":
            store.dismiss(record.record_id, actor="reviewer-1", reason_code="not_supported")
        else:
            store.mark_bridged(record.record_id, proposal_id="proposal-1", actor="reviewer-1")

    persisted = store.get_record(record.record_id)
    assert persisted.status is ProposalStatus.PENDING
    assert "dismissed_by" not in persisted.metadata
    assert "bridge_proposal_id" not in persisted.metadata
    assert len(store.list_events()) == 1
    store.close()
