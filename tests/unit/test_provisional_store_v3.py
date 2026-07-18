from __future__ import annotations

import sqlite3
from dataclasses import replace
from hashlib import sha256

import pytest

from engine.contracts import SourceRef
from engine.memory.provisional_store import (
    ProvisionalAuthorityTier,
    ProvisionalLifecycle,
    ProvisionalMemoryCandidate,
    ProvisionalMemoryEventType,
    ProvisionalMemoryKind,
    ProvisionalMemoryStatus,
    SqliteProvisionalMemoryStore,
)


def _candidate(*, source: str = "source-1", message: str = "message-1", session: str = "s-1", text: str = "user likes tea") -> ProvisionalMemoryCandidate:
    return ProvisionalMemoryCandidate(
        kind=ProvisionalMemoryKind.PREFERENCE,
        canonical_text=text,
        source_refs=[SourceRef(source_id=source, message_id=message)],
        source_role="user",
        session_id=session,
        source_id=source,
        message_id=message,
        content=text,
    )


def _create_v2_store(path, *, secret: bool = False) -> None:
    canonical_text = "API_KEY=sk-abcdefghijklmnopqrstuvwxyz" if secret else "legacy fact"
    event_reason = "password=legacy-secret-value" if secret else "legacy observation"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE provisional_records (
                record_id TEXT PRIMARY KEY, kind TEXT NOT NULL, canonical_text TEXT NOT NULL, source_refs_json TEXT NOT NULL,
                source_role TEXT NOT NULL, session_id TEXT NOT NULL, confidence REAL NOT NULL, salience REAL NOT NULL,
                stability REAL NOT NULL, reinforcement_count INTEGER NOT NULL, status TEXT NOT NULL,
                supersedes_record_id TEXT, superseded_by_record_id TEXT, conflict_with_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_reinforced_at TEXT, metadata_json TEXT NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE
            );
            CREATE TABLE provisional_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,
                record_id TEXT NOT NULL, timestamp TEXT NOT NULL, reason TEXT NOT NULL, source_refs_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            PRAGMA user_version=2;
        """)
        conn.execute("""INSERT INTO provisional_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            "legacy-1", "fact", canonical_text, '[{"source_id":"legacy-src","message_id":"legacy-msg","timestamp":null,"span_start":null,"span_end":null}]', "user", "s-1", 0.5, 0.5, 0.5, 8, "active", None, None,
            "[]", "2026-07-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00", None, "{}", "legacy-key",
        ))
        conn.execute(
            """INSERT INTO provisional_events(event_id,event_type,record_id,timestamp,reason,source_refs_json,metadata_json)
               VALUES (?,?,?,?,?,?,?)""",
            ("legacy-event-1", "observe", "legacy-1", "2026-07-01T00:00:00+00:00", event_reason, "[]", "{}"),
        )


def test_v2_to_current_migration_is_transactional_idempotent_and_has_stable_store_uuid(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    _create_v2_store(path)
    store = SqliteProvisionalMemoryStore(path)
    first_uuid = store.store_uuid
    assert store._schema_version() == 4
    assert store.get_record("legacy-1").independent_support_count == 0
    store.close()
    reopened = SqliteProvisionalMemoryStore(path)
    assert reopened.store_uuid == first_uuid
    reopened.close()


def test_v2_secret_preflight_aborts_before_sqlite_can_modify_original(tmp_path) -> None:
    path = tmp_path / "legacy-secret.sqlite3"
    _create_v2_store(path, secret=True)
    original_digest = sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="LEGACY_SECRET_DETECTED"):
        SqliteProvisionalMemoryStore(path)

    assert sha256(path.read_bytes()).hexdigest() == original_digest
    assert not path.with_name(f"{path.name}-wal").exists()
    assert not path.with_name(f"{path.name}-shm").exists()
    with sqlite3.connect(path) as unchanged:
        assert int(unchanged.execute("PRAGMA user_version").fetchone()[0]) == 2


def test_reviewer_authorized_v2_secret_scrub_requires_verified_backup_and_restores(tmp_path) -> None:
    path = tmp_path / "legacy-secret.sqlite3"
    backup_path = tmp_path / "backups" / "legacy-secret-v2.sqlite3"
    _create_v2_store(path, secret=True)
    original_digest = sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="SCRUB_REVIEW_AUTHORIZATION_REQUIRED"):
        SqliteProvisionalMemoryStore(path, scrub_legacy_secrets=True, legacy_backup_path=backup_path)
    assert sha256(path.read_bytes()).hexdigest() == original_digest
    with pytest.raises(ValueError, match="SCRUB_BACKUP_REQUIRED"):
        SqliteProvisionalMemoryStore(path, scrub_legacy_secrets=True, scrub_authorized_by="reviewer-1")
    assert sha256(path.read_bytes()).hexdigest() == original_digest

    store = SqliteProvisionalMemoryStore.migrate_legacy_store(
        path,
        scrub_legacy_secrets=True,
        scrub_authorized_by="reviewer-1",
        legacy_backup_path=backup_path,
    )
    try:
        assert store._schema_version() == 4
        assert store.get_record("legacy-1").canonical_text == "[REDACTED_LEGACY_SECRET]"
        control = dict(store._conn.execute("SELECT control_key, control_value FROM provisional_control").fetchall())
        assert control["legacy_scrub_authorized_by"] == "reviewer-1"
        assert control["legacy_scrub_backup"] == str(backup_path.resolve())
    finally:
        store.close()

    with sqlite3.connect(backup_path) as backup:
        assert int(backup.execute("PRAGMA user_version").fetchone()[0]) == 2
        assert str(backup.execute("PRAGMA integrity_check").fetchone()[0]).lower() == "ok"
        assert "sk-abcdefghijklmnopqrstuvwxyz" in str(
            backup.execute("SELECT canonical_text FROM provisional_records").fetchone()[0]
        )

    reopened = SqliteProvisionalMemoryStore(path)
    assert reopened._schema_version() == 4
    reopened.close()

    restored_path = tmp_path / "restored-v2.sqlite3"
    with sqlite3.connect(backup_path) as backup, sqlite3.connect(restored_path) as restored:
        backup.backup(restored)
    restored_digest = sha256(restored_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="LEGACY_SECRET_DETECTED"):
        SqliteProvisionalMemoryStore(restored_path)
    assert sha256(restored_path.read_bytes()).hexdigest() == restored_digest


def test_registered_evidence_is_exact_once_and_identity_conflicts_are_atomic(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "store.sqlite3")
    candidate = _candidate()
    reg = store.register_source(source_id="source-1", message_id="message-1", source_role="user", content=candidate.content, session_id="s-1")
    assert store.observe_candidate(candidate, reason="turn", registration=reg).support_delta == 1
    assert store.observe_candidate(candidate, reason="turn", registration=reg).support_delta == 0
    changed = _candidate(text="user likes coffee")
    changed_reg = store.register_source(source_id="source-1", message_id="message-1", source_role="user", content=changed.content, session_id="s-1")
    with pytest.raises(ValueError, match="EVIDENCE_IDENTITY_CONFLICT"):
        store.observe_candidate(changed, reason="turn", registration=changed_reg)
    assert len(store.list_records()) == 1  # identity conflict is atomic: no candidate row is added.


def test_store_bound_registration_handle_is_validated_before_support_is_counted(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "store.sqlite3")
    candidate = _candidate()
    registration = store.register_source(
        source_id=candidate.source_id,
        message_id=candidate.message_id,
        source_role=candidate.source_role,
        content=candidate.content,
        session_id=candidate.session_id,
    )

    disposition = store.observe_candidate(
        candidate,
        reason="turn",
        registration=replace(registration, handle="0" * 64),
    )

    assert disposition.support_delta == 0
    assert store.get_record(disposition.record_id).independent_support_count == 0
    store.close()


def test_registered_observation_rolls_back_candidate_and_event_when_evidence_insert_fails(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "atomic-observe.sqlite3")
    candidate = _candidate()
    registration = store.register_source(
        source_id=candidate.source_id,
        message_id=candidate.message_id,
        source_role=candidate.source_role,
        content=candidate.content,
        session_id=candidate.session_id,
    )
    with store._conn:
        store._conn.execute(
            """
            CREATE TRIGGER reject_evidence_insert
            BEFORE INSERT ON provisional_evidence_units
            BEGIN SELECT RAISE(ABORT, 'forced evidence failure'); END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced evidence failure"):
        store.observe_candidate(candidate, reason="turn", registration=registration)

    assert store.list_records() == []
    assert store.list_events() == []
    store.close()


@pytest.mark.parametrize("lifecycle", (ProvisionalLifecycle.DORMANT, ProvisionalLifecycle.ARCHIVED))
def test_new_independent_evidence_durably_reactivates_non_live_record(tmp_path, lifecycle) -> None:
    path = tmp_path / f"reactivate-{lifecycle.value}.sqlite3"
    store = SqliteProvisionalMemoryStore(path)
    original = _candidate()
    original_registration = store.register_source(
        source_id=original.source_id,
        message_id=original.message_id,
        source_role=original.source_role,
        content=original.content,
        session_id=original.session_id,
    )
    record_id = store.observe_candidate(original, reason="turn", registration=original_registration).record_id
    store.set_lifecycle(record_id, lifecycle, reason="maintenance")

    fresh = _candidate(source="source-2", message="message-2", session="s-2")
    fresh_registration = store.register_source(
        source_id=fresh.source_id,
        message_id=fresh.message_id,
        source_role=fresh.source_role,
        content=fresh.content,
        session_id=fresh.session_id,
    )
    disposition = store.observe_candidate(fresh, reason="new_independent_evidence", registration=fresh_registration)
    assert disposition.support_delta == 1
    reactivated = store.get_record(record_id)
    assert reactivated.lifecycle is ProvisionalLifecycle.ACTIVE
    assert reactivated.status is ProvisionalMemoryStatus.ACTIVE
    assert store.list_events(record_id=record_id)[-1].event_type is ProvisionalMemoryEventType.REACTIVATE
    store.close()

    reopened = SqliteProvisionalMemoryStore(path)
    try:
        assert reopened.get_record(record_id).lifecycle is ProvisionalLifecycle.ACTIVE
        assert reopened.list_events(record_id=record_id)[-1].event_type is ProvisionalMemoryEventType.REACTIVATE
    finally:
        reopened.close()


def test_unregistered_evidence_cannot_create_support_and_exact_claim_key_consolidates_immutably(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "store.sqlite3")
    first = _candidate()
    assert store.observe_candidate(first, reason="turn").support_delta == 0
    for idx in range(3):
        candidate = _candidate(source=f"source-{idx}", message=f"message-{idx}", session=f"s-{idx}")
        reg = store.register_source(source_id=candidate.source_id, message_id=candidate.message_id, source_role="user", content=candidate.content, session_id=candidate.session_id)
        store.observe_candidate(candidate, reason="turn", registration=reg)
    observed = max((r for r in store.list_records() if not r.derived), key=lambda r: r.independent_support_count)
    assert observed.independent_support_count == 3
    derived = store.create_consolidated_revision(record_ids=[observed.record_id])
    assert derived is not None and derived.authority_tier is ProvisionalAuthorityTier.CONSOLIDATED
    assert store.create_consolidated_revision(record_ids=[observed.record_id]).record_id == derived.record_id


def test_secret_like_content_is_rejected_before_record_or_digest_persistence(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "store.sqlite3")
    unsafe = _candidate(text="API_KEY=sk-abcdefghijklmnopqrstuvwxyz")
    unsafe.content = unsafe.canonical_text
    with pytest.raises(ValueError, match="LEGACY_SECRET_DETECTED"):
        store.observe_candidate(unsafe, reason="turn")
    assert store.list_records() == []


def test_live_provisional_backup_is_wal_consistent_and_reopenable(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "live.sqlite3")
    candidate = _candidate()
    registration = store.register_source(
        source_id=candidate.source_id,
        message_id=candidate.message_id,
        source_role="user",
        content=candidate.content,
        session_id=candidate.session_id,
    )
    store.observe_candidate(candidate, reason="turn", registration=registration)
    backup_path = store.backup_to(tmp_path / "backups" / "provisional.sqlite3")
    store.close()

    backup = SqliteProvisionalMemoryStore(backup_path)
    try:
        assert len(backup.list_records()) == 1
        assert backup.get_record(backup.list_records()[0].record_id).independent_support_count == 1
    finally:
        backup.close()


def test_ten_thousand_independent_supports_remain_provisional(tmp_path) -> None:
    store = SqliteProvisionalMemoryStore(tmp_path / "ten-thousand.sqlite3")
    digest = ""
    for index in range(3):
        candidate = _candidate(source=f"source-{index}", message=f"message-{index}", session=f"session-{index}")
        registration = store.register_source(
            source_id=candidate.source_id,
            message_id=candidate.message_id,
            source_role="user",
            content=candidate.content,
            session_id=candidate.session_id,
        )
        digest = registration.content_digest
        store.observe_candidate(candidate, reason="independent_support", registration=registration)
    observed = store.list_records()[0]
    # Bulk-load the remaining already-validated independent units so this truth-fence
    # test exercises the 10,000-support state without spending minutes re-testing
    # identity validation that has dedicated tests above.
    with store._lock, store._conn:
        store._conn.executemany(
            "INSERT INTO provisional_evidence_units VALUES (?, ?, ?, ?, 0, 0, 'user', ?, ?, 1, ?)",
            [
                (
                    f"bulk-fingerprint-{index}",
                    observed.record_id,
                    f"bulk-source-{index}",
                    f"bulk-message-{index}",
                    digest,
                    f"bulk-session-{index}",
                    "2026-07-17T00:00:00+00:00",
                )
                for index in range(3, 10_000)
            ],
        )
        store._conn.execute(
            "UPDATE provisional_records SET independent_support_count=10000, distinct_session_count=10000, maturity='reinforced' WHERE record_id=?",
            (observed.record_id,),
        )
    observed = store.get_record(observed.record_id)
    assert observed.independent_support_count == 10_000
    derived = store.create_consolidated_revision(record_ids=[observed.record_id])
    assert derived is not None
    assert {record.authority_tier for record in store.list_records()} <= {
        ProvisionalAuthorityTier.OBSERVED,
        ProvisionalAuthorityTier.CONSOLIDATED,
    }
    assert derived.authority_tier is ProvisionalAuthorityTier.CONSOLIDATED
    store.close()


def test_boundary_idempotency_survives_restart(tmp_path) -> None:
    path = tmp_path / "boundary.sqlite3"
    store = SqliteProvisionalMemoryStore(path)
    assert store.record_boundary(
        event_id="boundary-1",
        event_type="session_end",
        observed_at_utc="2026-07-17T20:00:00+00:00",
        metadata={"session_id": "session-1"},
    ) is True
    store.close()
    reopened = SqliteProvisionalMemoryStore(path)
    try:
        assert reopened.record_boundary(
            event_id="boundary-1",
            event_type="session_end",
            observed_at_utc="2099-01-01T00:00:00+00:00",
            metadata={"session_id": "session-1"},
        ) is False
    finally:
        reopened.close()
