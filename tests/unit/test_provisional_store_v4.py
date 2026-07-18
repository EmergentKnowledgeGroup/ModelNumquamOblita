from __future__ import annotations

import sqlite3
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from engine.contracts import SourceRef
import engine.memory.provisional_store as provisional_store_module
from engine.memory.provisional_store import (
    ProvisionalMemoryCandidate,
    ProvisionalMemoryKind,
    SqliteProvisionalMemoryStore,
    TemporalDisposition,
)


NOW = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)


def _clock() -> datetime:
    return NOW


def _candidate() -> ProvisionalMemoryCandidate:
    return ProvisionalMemoryCandidate(
        kind=ProvisionalMemoryKind.EVENT_NOTE,
        canonical_text="renew licence",
        source_refs=[SourceRef(source_id="source", message_id="message")],
        source_role="user",
        session_id="session",
    )


def _record(store: SqliteProvisionalMemoryStore) -> str:
    return store.upsert_candidate(_candidate(), reason="test").record_id


def _truth_evidence_projection(store: SqliteProvisionalMemoryStore, record_id: str) -> tuple[object, ...]:
    """Snapshot every record/evidence field that temporal delivery must not reinforce."""

    record = store.get_record(record_id)
    events = tuple(
        tuple(row)
        for row in store._conn.execute(
            "SELECT * FROM provisional_events WHERE record_id=? ORDER BY event_id",
            (record_id,),
        ).fetchall()
    )
    evidence = tuple(
        tuple(row)
        for row in store._conn.execute(
            "SELECT * FROM provisional_evidence_units WHERE record_id=? ORDER BY evidence_fingerprint",
            (record_id,),
        ).fetchall()
    )
    return record, events, evidence


def test_v3_to_v4_upgrade_is_repeat_safe_and_adds_temporal_tables(tmp_path) -> None:
    path = tmp_path / "legacy-v3.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE provisional_records (record_id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT '');
            CREATE TABLE provisional_control (control_key TEXT PRIMARY KEY, control_value TEXT NOT NULL);
            INSERT INTO provisional_control VALUES ('store_uuid', 'legacy-store');
            PRAGMA user_version=3;
            """
        )
    first = SqliteProvisionalMemoryStore(path)
    assert first._schema_version() == 4
    assert first.store_uuid == "legacy-store"
    backup_path = path.with_name(f"{path.name}.pre-v4.sqlite3")
    assert backup_path.is_file()
    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 3
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert first._conn.execute(
        "SELECT control_value FROM provisional_control WHERE control_key='v4_pre_upgrade_backup'"
    ).fetchone()[0] == str(backup_path.resolve())
    assert {"temporal_disposition", "temporal_revision", "original_expression"} <= {
        row[1] for row in first._conn.execute("PRAGMA table_info(provisional_records)")
    }
    first.close()
    second = SqliteProvisionalMemoryStore(path)
    assert second._schema_version() == 4
    second.close()


def test_v3_to_v4_failure_rolls_back_and_moved_workspace_reopens(tmp_path, monkeypatch) -> None:
    path = tmp_path / "source" / "legacy-v3.sqlite3"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE provisional_records (record_id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT '');
            CREATE TABLE provisional_control (control_key TEXT PRIMARY KEY, control_value TEXT NOT NULL);
            INSERT INTO provisional_control VALUES ('store_uuid', 'stable-store');
            PRAGMA user_version=3;
            """
        )

    original = SqliteProvisionalMemoryStore._execute_schema_script

    def fail_schema(_self, _script: str) -> None:
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(SqliteProvisionalMemoryStore, "_execute_schema_script", fail_schema)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        SqliteProvisionalMemoryStore(path)
    with sqlite3.connect(path) as rolled_back:
        assert rolled_back.execute("PRAGMA user_version").fetchone()[0] == 3
        assert "store_uuid" not in {
            row[1] for row in rolled_back.execute("PRAGMA table_info(provisional_records)")
        }
        assert rolled_back.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    monkeypatch.setattr(SqliteProvisionalMemoryStore, "_execute_schema_script", original)
    migrated = SqliteProvisionalMemoryStore(path)
    assert migrated.store_uuid == "stable-store"
    migrated.close()

    moved = tmp_path / "moved-workspace" / "memory.sqlite3"
    moved.parent.mkdir(parents=True)
    shutil.copy2(path, moved)
    reopened = SqliteProvisionalMemoryStore(moved)
    assert reopened.store_uuid == "stable-store"
    assert reopened._schema_version() == 4
    reopened.close()


def test_schedule_list_and_resolve_are_scoped_half_open_and_replay_before_cas(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "temporal.sqlite3", clock=_clock)
    record_id = _record(store)
    kwargs = dict(
        temporal_kind="reminder",
        due_window_start_utc=NOW,
        due_window_end_utc=NOW + timedelta(hours=1),
        timezone_name="UTC",
        precision="exact",
        original_expression="at noon",
        idempotency_key="schedule-1",
        expected_revision=0,
    )
    scheduled = store.schedule_temporal(record_id, "principal", "runtime", **kwargs)
    assert scheduled["revision"] == 1
    # Exact same request returns before the now-stale expected revision is checked.
    assert store.schedule_temporal(record_id, "principal", "runtime", **kwargs) == scheduled
    with pytest.raises(ValueError, match="TEMPORAL_IDEMPOTENCY_CONFLICT"):
        store.schedule_temporal(record_id, "principal", "runtime", **(kwargs | {"original_expression": "different"}))

    due = store.list_temporal("principal", "runtime", due_only=True, now_utc=NOW)
    assert due[0]["eligibility"] == "due"
    assert store.list_temporal("principal", "runtime", due_only=True, now_utc=NOW + timedelta(hours=1))[0]["eligibility"] == "overdue"
    assert store.get_temporal(record_id, "principal", "runtime", now_utc=NOW + timedelta(hours=1))["eligibility"] == "overdue"
    with pytest.raises(KeyError):
        store.get_temporal(record_id, "other-principal", "runtime")

    resolved = store.resolve_temporal(record_id, "principal", "runtime", action="acknowledge", expected_revision=1, idempotency_key="ack-1")
    assert resolved["disposition"] == TemporalDisposition.ACKNOWLEDGED.value
    assert store.resolve_temporal(record_id, "principal", "runtime", action="acknowledge", expected_revision=1, idempotency_key="ack-1") == resolved
    store.close()


def test_turn_and_delivery_events_are_exact_once_and_delivery_does_not_mutate_record(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "events.sqlite3", clock=_clock)
    record_id = _record(store)
    store.schedule_temporal(
        record_id, "principal", "runtime", temporal_kind="future_event", due_window_start_utc=NOW,
        due_window_end_utc=NOW + timedelta(hours=1), timezone_name="UTC", precision="exact",
        original_expression="today", idempotency_key="schedule", expected_revision=0,
    )
    first_turn = store.record_turn_clock_event("principal", "runtime", event_id="turn-1", role="user", event_kind="server_receipt", idempotency_key="turn-idem")
    assert store.record_turn_clock_event("principal", "runtime", event_id="turn-1", role="user", event_kind="server_receipt", idempotency_key="turn-idem") == first_turn
    assert store.latest_turn_clock_events("principal", "runtime")["user"]["event_id"] == "turn-1"

    before = _truth_evidence_projection(store, record_id)
    payload_digest = sha256(b"receipt-payload").hexdigest()
    delivery = store.record_delivery_event(record_id, "principal", "runtime", delivery_id="delivery-1", receipt_identity="receipt-1", idempotency_key="delivery-idem", payload_digest=payload_digest)
    assert store.record_delivery_event(record_id, "principal", "runtime", delivery_id="delivery-1", receipt_identity="receipt-1", idempotency_key="delivery-idem", payload_digest=payload_digest) == delivery
    # Delivery telemetry is separate from truth/evidence: confidence, salience,
    # stability, support timestamps/counts, maturity, authority, lifecycle,
    # lineage/source refs, decay anchors, revision and updated_at all stay exact.
    assert _truth_evidence_projection(store, record_id) == before
    assert store.temporal_diagnostics("principal", "runtime")["delivery_count"] == 1
    store.close()


def test_snooze_preserves_original_window_duration_and_decay_grace(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "snooze.sqlite3", clock=_clock)
    record_id = _record(store)
    start = NOW
    end = NOW + timedelta(days=1)
    store.schedule_temporal(
        record_id,
        "principal",
        "runtime",
        temporal_kind="future_event",
        due_window_start_utc=start,
        due_window_end_utc=end,
        timezone_name="UTC",
        precision="date",
        original_expression="today",
        decay_not_before_utc=end + timedelta(days=7),
        idempotency_key="schedule-date",
        expected_revision=0,
    )
    snoozed = NOW + timedelta(days=10)
    store.resolve_temporal(
        record_id,
        "principal",
        "runtime",
        action="snooze",
        snoozed_until_utc=snoozed,
        expected_revision=1,
        idempotency_key="snooze-date",
    )

    projection = store.get_temporal(record_id, "principal", "runtime", now_utc=snoozed)
    record = projection["record"]
    assert projection["effective_window_end_utc"] - projection["effective_window_start_utc"] == timedelta(days=1)
    assert record.decay_not_before_utc == snoozed + timedelta(days=8)
    store.close()


def test_expiry_is_maintenance_only_after_grace_and_replays_before_cas(tmp_path) -> None:
    clock = [NOW]
    store = SqliteProvisionalMemoryStore(tmp_path / "expiry.sqlite3", clock=lambda: clock[0])
    record_id = _record(store)
    grace_end = NOW + timedelta(days=8)
    store.schedule_temporal(
        record_id,
        "principal",
        "runtime",
        temporal_kind="future_event",
        due_window_start_utc=NOW,
        due_window_end_utc=NOW + timedelta(days=1),
        timezone_name="UTC",
        precision="date",
        original_expression="today",
        decay_not_before_utc=grace_end,
        idempotency_key="schedule-expiry",
        expected_revision=0,
    )
    with pytest.raises(ValueError, match="TEMPORAL_EXPIRY_NOT_ELIGIBLE"):
        store.expire_temporal(
            record_id,
            "principal",
            "runtime",
            expected_revision=1,
            idempotency_key="expire-record",
            now_utc=grace_end - timedelta(seconds=1),
        )
    clock[0] = grace_end
    expired = store.expire_temporal(
        record_id,
        "principal",
        "runtime",
        expected_revision=1,
        idempotency_key="expire-record",
    )
    assert expired["disposition"] == TemporalDisposition.EXPIRED.value
    assert store.expire_temporal(
        record_id,
        "principal",
        "runtime",
        expected_revision=1,
        idempotency_key="expire-record",
    ) == expired
    store.close()


def test_concurrent_temporal_transition_allows_exactly_one_revision_winner(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "concurrent.sqlite3", clock=_clock)
    record_id = _record(store)
    store.schedule_temporal(
        record_id,
        "principal",
        "runtime",
        temporal_kind="reminder",
        due_window_start_utc=NOW,
        due_window_end_utc=NOW + timedelta(hours=1),
        timezone_name="UTC",
        precision="exact",
        original_expression="now",
        idempotency_key="schedule-concurrent",
        expected_revision=0,
    )

    def resolve(action: str) -> str:
        try:
            store.resolve_temporal(
                record_id,
                "principal",
                "runtime",
                action=action,
                expected_revision=1,
                idempotency_key=f"resolve-{action}",
            )
            return "won"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(resolve, ("acknowledge", "cancel")))
    assert outcomes == ["TEMPORAL_REVISION_CONFLICT", "won"]
    assert store.get_record(record_id).temporal_revision == 2
    store.close()


def test_temporal_retention_is_explicit_never_read_driven_and_preserves_records(tmp_path, monkeypatch) -> None:
    clock = [datetime(2010, 1, 1, tzinfo=timezone.utc)]
    store = SqliteProvisionalMemoryStore(tmp_path / "retention.sqlite3", clock=lambda: clock[0])
    record_id = _record(store)
    store.schedule_temporal(
        record_id, "principal", "runtime", temporal_kind="reminder", due_window_start_utc=clock[0],
        due_window_end_utc=clock[0] + timedelta(hours=1), timezone_name="UTC", precision="exact",
        original_expression="private temporal text", idempotency_key="schedule-retention", expected_revision=0,
    )
    store.record_turn_clock_event("principal", "runtime", event_id="old-turn", role="user", event_kind="server_receipt", idempotency_key="old-turn-idem")
    store.record_delivery_event(
        record_id, "principal", "runtime", delivery_id="old-delivery", receipt_identity="old-receipt",
        idempotency_key="old-delivery-idem", payload_digest=sha256(b"old-delivery").hexdigest(),
    )
    clock[0] = NOW
    store.record_turn_clock_event("principal", "runtime", event_id="new-turn", role="assistant", event_kind="server_completion_receipt", idempotency_key="new-turn-idem")
    store.record_delivery_event(
        record_id, "principal", "runtime", delivery_id="new-delivery", receipt_identity="new-receipt",
        idempotency_key="new-delivery-idem", payload_digest=sha256(b"new-delivery").hexdigest(),
    )
    assert store.latest_turn_clock_events("principal", "runtime")["assistant"]["event_id"] == "new-turn"
    assert store.latest_delivery_event(record_id, "principal", "runtime")["delivery_id"] == "new-delivery"
    assert store.temporal_diagnostics("principal", "runtime")["turn_clock_event_count"] == 2
    assert store.temporal_diagnostics("principal", "runtime")["delivery_count"] == 2
    result = store.maintain_temporal_retention(now=clock[0])
    assert result["turn_clock_events"] == 1
    assert result["delivery_events"] == 1
    assert store.temporal_diagnostics("principal", "runtime")["turn_clock_event_count"] == 1
    assert store.temporal_diagnostics("principal", "runtime")["delivery_count"] == 1
    assert store.get_record(record_id).original_expression == "private temporal text"
    store.close()


def test_temporal_retention_enforces_newest_bound_and_state_cap_fails_closed(tmp_path, monkeypatch) -> None:
    clock = [NOW]
    store = SqliteProvisionalMemoryStore(tmp_path / "caps.sqlite3", clock=lambda: clock[0])
    monkeypatch.setattr(provisional_store_module, "_TEMPORAL_RETAINED_EVENT_ROWS", 1)
    first = _record(store)
    store.schedule_temporal(
        first, "principal", "runtime", temporal_kind="reminder", due_window_start_utc=NOW,
        due_window_end_utc=NOW + timedelta(hours=1), timezone_name="UTC", precision="exact",
        original_expression="first", idempotency_key="schedule-first", expected_revision=0,
    )
    store.record_turn_clock_event("principal", "runtime", event_id="turn-a", role="user", event_kind="server_receipt", idempotency_key="turn-a")
    clock[0] = NOW + timedelta(seconds=1)
    store.record_turn_clock_event("principal", "runtime", event_id="turn-b", role="assistant", event_kind="server_completion_receipt", idempotency_key="turn-b")
    assert store.maintain_temporal_retention(now=clock[0])["turn_clock_events"] == 1
    assert store.latest_turn_clock_events("principal", "runtime")["assistant"]["event_id"] == "turn-b"

    monkeypatch.setattr(provisional_store_module, "_TEMPORAL_EVENT_HARD_CAP", 1)
    second = store.upsert_candidate(
        ProvisionalMemoryCandidate(
            kind=ProvisionalMemoryKind.EVENT_NOTE, canonical_text="second reminder",
            source_refs=[SourceRef(source_id="second", message_id="second")], source_role="user", session_id="second",
        ), reason="test",
    ).record_id
    with pytest.raises(ValueError, match="TEMPORAL_STATE_EVENT_CAP_REACHED"):
        store.schedule_temporal(
            second, "principal", "runtime", temporal_kind="reminder", due_window_start_utc=NOW,
            due_window_end_utc=NOW + timedelta(hours=1), timezone_name="UTC", precision="exact",
            original_expression="second", idempotency_key="schedule-second", expected_revision=0,
        )
    store.close()


def test_terminal_history_and_idempotency_expire_only_in_explicit_maintenance(tmp_path) -> None:
    clock = [datetime(2010, 1, 1, tzinfo=timezone.utc)]
    store = SqliteProvisionalMemoryStore(tmp_path / "terminal-retention.sqlite3", clock=lambda: clock[0])
    record_id = _record(store)
    store.schedule_temporal(
        record_id, "principal", "runtime", temporal_kind="future_event", due_window_start_utc=clock[0],
        due_window_end_utc=clock[0] + timedelta(hours=1), timezone_name="UTC", precision="exact",
        original_expression="old event", idempotency_key="old-schedule", expected_revision=0,
    )
    store.resolve_temporal(record_id, "principal", "runtime", action="acknowledge", expected_revision=1, idempotency_key="old-ack")
    clock[0] += timedelta(days=31)
    early_result = store.maintain_temporal_retention(now=clock[0])
    assert early_result["state_events"] == 0
    assert early_result["idempotency_rows"] == 2
    clock[0] = NOW
    assert store.temporal_diagnostics("principal", "runtime")["acknowledged_count"] == 1
    result = store.maintain_temporal_retention(now=clock[0])
    assert result["state_events"] == 2
    assert result["idempotency_rows"] == 0
    assert store.get_record(record_id).temporal_disposition is TemporalDisposition.ACKNOWLEDGED
    with store._lock:
        assert store._conn.execute("SELECT COUNT(*) FROM provisional_temporal_state_events").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM provisional_temporal_idempotency").fetchone()[0] == 0
    store.close()
