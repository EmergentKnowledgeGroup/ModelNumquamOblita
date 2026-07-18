from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.contracts import SourceRef
from engine.memory.provisional_maintenance import MaintenancePolicy, run_maintenance
from engine.memory.provisional_store import ProvisionalLifecycle, ProvisionalMemoryCandidate, ProvisionalMemoryKind, SqliteProvisionalMemoryStore


def _candidate(index: int, *, session: str) -> ProvisionalMemoryCandidate:
    return ProvisionalMemoryCandidate(
        kind=ProvisionalMemoryKind.FACT,
        canonical_text="the sky is blue",
        source_refs=[SourceRef(source_id=f"src-{index}", message_id=f"msg-{index}")],
        source_role="user", session_id=session, source_id=f"src-{index}", message_id=f"msg-{index}", content="the sky is blue",
    )


def test_bounded_maintenance_consolidates_and_decay_is_server_clock_controlled(tmp_path) -> None:
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    store = SqliteProvisionalMemoryStore(tmp_path / "store.sqlite3", clock=lambda: now)
    for index, session in enumerate(("a", "b", "c")):
        candidate = _candidate(index, session=session)
        registration = store.register_source(source_id=candidate.source_id, message_id=candidate.message_id, source_role="user", content=candidate.content, session_id=session)
        store.observe_candidate(candidate, reason="turn", registration=registration)
    transitions = run_maintenance(store, now=now, policy=MaintenancePolicy(max_records=10))
    assert [item.disposition for item in transitions] == ["consolidated"]
    source = next(record for record in store.list_records() if not record.derived)
    assert run_maintenance(store, now=now + timedelta(days=90), policy=MaintenancePolicy(max_records=10))[0].disposition == "dormant"
    assert store.get_record(source.record_id).lifecycle is ProvisionalLifecycle.DORMANT


def test_default_conflict_policy_blocks_consolidation(tmp_path) -> None:
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    store = SqliteProvisionalMemoryStore(tmp_path / "conflict.sqlite3", clock=lambda: now)
    record_ids: list[str] = []
    for claim_index, text in enumerate(("the launch is Friday", "the launch is Monday")):
        for support_index, session in enumerate(("a", "b", "c")):
            candidate = ProvisionalMemoryCandidate(
                kind=ProvisionalMemoryKind.FACT,
                canonical_text=text,
                source_refs=[SourceRef(source_id=f"src-{claim_index}-{support_index}", message_id=f"msg-{claim_index}-{support_index}")],
                source_role="user",
                session_id=f"{claim_index}-{session}",
                source_id=f"src-{claim_index}-{support_index}",
                message_id=f"msg-{claim_index}-{support_index}",
                content=text,
            )
            registration = store.register_source(
                source_id=candidate.source_id,
                message_id=candidate.message_id,
                source_role="user",
                content=candidate.content,
                session_id=candidate.session_id,
            )
            disposition = store.observe_candidate(candidate, reason="turn", registration=registration)
        record_ids.append(disposition.record_id)
    store.mark_conflict(record_ids[0], record_ids[1], reason="explicit_correction_conflict")
    assert run_maintenance(store, now=now, policy=MaintenancePolicy(max_records=10)) == []
    assert not any(record.derived for record in store.list_records())
    store.close()
