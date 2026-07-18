from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.contracts import SourceRef
from engine.memory.provisional_maintenance import MaintenancePolicy, run_maintenance
from engine.memory.provisional_store import (
    ProvisionalLifecycle,
    ProvisionalMemoryCandidate,
    ProvisionalMemoryEventType,
    ProvisionalMemoryKind,
    SqliteProvisionalMemoryStore,
)


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


def test_maintenance_cap_is_applied_after_terminal_records_are_filtered(tmp_path) -> None:
    clock = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
    store = SqliteProvisionalMemoryStore(tmp_path / "bounded.sqlite3", clock=lambda: clock[0])
    terminal = ProvisionalMemoryCandidate(
        kind=ProvisionalMemoryKind.FACT,
        canonical_text="an archived helper claim",
        source_refs=[SourceRef(source_id="terminal-src", message_id="terminal-msg")],
        source_role="user",
        session_id="terminal-session",
        source_id="terminal-src",
        message_id="terminal-msg",
        content="an archived helper claim",
    )
    terminal_registration = store.register_source(
        source_id=terminal.source_id,
        message_id=terminal.message_id,
        source_role=terminal.source_role,
        content=terminal.content,
        session_id=terminal.session_id,
    )
    terminal_id = store.observe_candidate(terminal, reason="turn", registration=terminal_registration).record_id
    store.set_lifecycle(terminal_id, ProvisionalLifecycle.ARCHIVED, reason="operator_archive")

    clock[0] += timedelta(seconds=1)
    for index, session in enumerate(("a", "b", "c")):
        candidate = _candidate(index, session=session)
        registration = store.register_source(
            source_id=candidate.source_id,
            message_id=candidate.message_id,
            source_role=candidate.source_role,
            content=candidate.content,
            session_id=session,
        )
        store.observe_candidate(candidate, reason="turn", registration=registration)

    transitions = run_maintenance(store, now=clock[0], policy=MaintenancePolicy(max_records=1))
    assert [transition.disposition for transition in transitions] == ["consolidated"]
    store.close()


def test_stale_supported_plan_is_durably_demoted_to_historical_recall(tmp_path) -> None:
    path = tmp_path / "historical-plan.sqlite3"
    observed_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    store = SqliteProvisionalMemoryStore(path, clock=lambda: observed_at)
    record_id = ""
    for index, session in enumerate(("a", "b", "c")):
        candidate = ProvisionalMemoryCandidate(
            kind=ProvisionalMemoryKind.PLAN,
            canonical_text="ship the release candidate",
            source_refs=[SourceRef(source_id=f"plan-src-{index}", message_id=f"plan-msg-{index}")],
            source_role="user",
            session_id=session,
            source_id=f"plan-src-{index}",
            message_id=f"plan-msg-{index}",
            content="ship the release candidate",
        )
        registration = store.register_source(
            source_id=candidate.source_id,
            message_id=candidate.message_id,
            source_role=candidate.source_role,
            content=candidate.content,
            session_id=session,
        )
        record_id = store.observe_candidate(candidate, reason="turn", registration=registration).record_id

    transitions = run_maintenance(
        store,
        now=observed_at + timedelta(days=31),
        policy=MaintenancePolicy(max_records=10),
    )
    assert [(item.record_id, item.disposition) for item in transitions] == [(record_id, "historical_plan")]
    assert store.get_record(record_id).lifecycle is ProvisionalLifecycle.DORMANT
    event = store.list_events(record_id=record_id)[-1]
    assert event.event_type is ProvisionalMemoryEventType.DORMANT
    assert event.reason == "plan_currentness_window"
    store.close()

    reopened = SqliteProvisionalMemoryStore(path)
    try:
        assert reopened.get_record(record_id).lifecycle is ProvisionalLifecycle.DORMANT
        assert reopened.list_events(record_id=record_id)[-1].reason == "plan_currentness_window"
    finally:
        reopened.close()


def test_maintenance_cursor_wraps_fairly_and_dry_run_does_not_mutate_state(tmp_path) -> None:
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    store = SqliteProvisionalMemoryStore(tmp_path / "fair.sqlite3", clock=lambda: now)
    record_ids = []
    for index in range(3):
        candidate = ProvisionalMemoryCandidate(
            kind=ProvisionalMemoryKind.FACT,
            canonical_text=f"fairness fact {index}",
            source_refs=[SourceRef(source_id=f"fair-{index}", message_id=f"message-{index}")],
            source_role="user", session_id=f"session-{index}", source_id=f"fair-{index}",
            message_id=f"message-{index}", content=f"fairness fact {index}",
        )
        registration = store.register_source(
            source_id=candidate.source_id, message_id=candidate.message_id, source_role="user",
            content=candidate.content, session_id=candidate.session_id,
        )
        record_ids.append(store.observe_candidate(candidate, reason="turn", registration=registration).record_id)

    first = run_maintenance(store, now=now, max_records=1, run_id="fair-1", return_result=True)
    second = run_maintenance(store, now=now, max_records=1, run_id="fair-2", return_result=True)
    third = run_maintenance(store, now=now, max_records=1, run_id="fair-3", return_result=True)
    assert [item["next_cursor"]["record_id"] for item in (first, second, third)] == record_ids
    replay = run_maintenance(store, now=now, max_records=1, run_id="fair-2", return_result=True)
    assert replay["state"] == "replay"

    cursor_before = store.maintenance_cursor()
    preview = run_maintenance(
        store, now=now + timedelta(days=91), max_records=1, dry_run=True, return_result=True
    )
    assert preview["state"] == "preview"
    assert preview["processed_count"] == 1
    assert preview["transitions"][0].disposition == "would_dormant"
    assert store.maintenance_cursor() == cursor_before
    assert all(store.get_record(record_id).lifecycle is ProvisionalLifecycle.ACTIVE for record_id in record_ids)
    assert store.maintenance_begin("active-run")["state"] == "acquired"
    assert store.maintenance_begin("active-run")["state"] == "join"
    assert store.maintenance_begin("other-run")["state"] == "conflict"
    store.close()
