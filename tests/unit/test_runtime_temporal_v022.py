from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.config import default_config
from engine.continuity import ContinuityStore
from engine.contracts import SourceRef
from engine.memory import SqliteAtomStore
from engine.memory.provisional_store import ProvisionalMemoryCandidate, ProvisionalMemoryKind
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession


def test_runtime_temporal_context_injects_due_without_retrieval_and_is_read_only(tmp_path) -> None:
    now = [datetime(2026, 7, 18, 12, tzinfo=timezone.utc)]
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.retrieval_enabled = True
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=cfg), verifier=ClaimVerifier(), continuity_store=ContinuityStore(),
        config=cfg, enable_writeback=False, server_clock=lambda: now[0],
    )
    try:
        scheduled = runtime.schedule_temporal_memory(
            temporal_request={"relative_duration": {"amount": 1, "unit": "hours"}, "timezone": "UTC"},
            original_expression="in one hour", source_content="submit the harmless report", builtin_source=True,
            idempotency_key="schedule-1",
        )
        assert scheduled["revision"] == 1
        now[0] += timedelta(hours=1)
        store = runtime._provisional_store
        before = store._conn.total_changes  # type: ignore[union-attr]
        package = runtime.build_context_package("hello", package_version="v2")
        after = store._conn.total_changes  # type: ignore[union-attr]
        temporal = package["temporal_context"]
        assert package["preview"]["route"] == "none"
        assert temporal["due"][0]["record_id"] == scheduled["record_id"]
        assert temporal["due"][0]["summary"] == "submit the harmless report"
        assert temporal["due"][0]["content_semantics"] == "quoted_memory_data"
        assert temporal["due"][0]["behavioral_directive"] is False
        assert temporal["due"][0]["source_citations"]
        assert temporal["due"][0]["claim_key"]
        assert temporal["due"][0]["conflict_with_ids"] == []
        selected_receipt = runtime.issue_integration_retrieval_receipt(
            retrieved_evidence_ids=[],
            temporal_record_ids=[scheduled["record_id"]],
            session_id="session",
            run_id="run",
            principal_id="local-owner",
        )
        selected_payload = runtime._integration_handle_signer.verify(  # type: ignore[union-attr]
            str(selected_receipt["handle"]), expected_kind="retrieval_receipt"
        )
        assert [item["record_id"] for item in selected_payload["temporal_delivery_ids"]] == [scheduled["record_id"]]
        empty_receipt = runtime.issue_integration_retrieval_receipt(
            retrieved_evidence_ids=[],
            temporal_record_ids=[],
            session_id="session",
            run_id="run-empty",
            principal_id="local-owner",
        )
        empty_payload = runtime._integration_handle_signer.verify(  # type: ignore[union-attr]
            str(empty_receipt["handle"]), expected_kind="retrieval_receipt"
        )
        assert empty_payload["temporal_delivery_ids"] == []
        assert before == after
    finally:
        runtime.close()
        atom_store.close()


def test_runtime_turn_clock_restart_continuity_and_non_sqlite_schedule_failure(tmp_path) -> None:
    now = [datetime(2026, 7, 18, 12, tzinfo=timezone.utc)]
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=cfg), verifier=ClaimVerifier(), continuity_store=ContinuityStore(),
        config=cfg, enable_writeback=False, server_clock=lambda: now[0],
    )
    runtime.handle_turn("hello")
    runtime.close()
    restarted = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=cfg), verifier=ClaimVerifier(), continuity_store=ContinuityStore(),
        config=cfg, enable_writeback=False, server_clock=lambda: now[0] + timedelta(minutes=5),
    )
    try:
        facts = restarted.build_context_package("hello", package_version="v1")["temporal_context"]
        assert facts["previous_user_turn"]["status"] == "available"
        assert facts["previous_assistant_turn"]["status"] == "available"
    finally:
        restarted.close()
        atom_store.close()


def test_runtime_temporal_scope_is_principal_bound_and_delivery_backoff_is_read_only(tmp_path) -> None:
    now = [datetime(2026, 7, 18, 12, tzinfo=timezone.utc)]
    cfg = default_config()
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
        server_clock=lambda: now[0],
    )
    try:
        store = runtime._provisional_store
        runtime_id = runtime._runtime_store_fingerprint()
        candidate = ProvisionalMemoryCandidate(
            kind=ProvisionalMemoryKind.EVENT_NOTE,
            canonical_text="alice-only reminder",
            source_refs=[SourceRef(source_id="source", message_id="message")],
            source_role="user",
            session_id="session",
        )
        record_id = store.upsert_candidate(candidate, reason="test").record_id  # type: ignore[union-attr]
        store.schedule_temporal(  # type: ignore[union-attr]
            record_id,
            "alice",
            runtime_id,
            temporal_kind="reminder",
            due_window_start_utc=now[0],
            due_window_end_utc=now[0] + timedelta(hours=1),
            timezone_name="UTC",
            precision="exact",
            original_expression="now",
            idempotency_key="alice-schedule",
        )

        assert runtime.build_context_package("hello", package_version="v2", principal_id="alice")["temporal_context"]["due"]
        assert runtime.build_context_package("hello", package_version="v2", principal_id="bob")["temporal_context"]["due"] == []

        before = store._conn.total_changes  # type: ignore[union-attr]
        store.record_delivery_event(  # type: ignore[union-attr]
            record_id,
            "alice",
            runtime_id,
            delivery_id="delivery-one",
            receipt_identity="receipt-one",
            idempotency_key="delivery-idem",
            payload_digest="a" * 64,
        )
        after_delivery = store._conn.total_changes  # type: ignore[union-attr]
        assert runtime.build_context_package("hello", package_version="v2", principal_id="alice")["temporal_context"]["due"] == []
        assert store._conn.total_changes == after_delivery  # type: ignore[union-attr]
        assert after_delivery > before
        now[0] += timedelta(hours=25)
        assert runtime.build_context_package("hello", package_version="v2", principal_id="alice")["temporal_context"]["due"]
    finally:
        runtime.close()
        atom_store.close()


def test_runtime_schedule_retry_is_atomic_and_does_not_create_support_or_record_drift(tmp_path) -> None:
    now = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    cfg = default_config()
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
        server_clock=lambda: now,
    )
    kwargs = {
        "temporal_request": {"relative_duration": {"amount": 1, "unit": "days"}, "timezone": "UTC"},
        "original_expression": "tomorrow",
        "source_content": "check the deployment",
        "builtin_source": True,
        "idempotency_key": "same-schedule",
    }
    try:
        first = runtime.schedule_temporal_memory(**kwargs)
        store = runtime._provisional_store
        before = store.get_record(first["record_id"])  # type: ignore[union-attr]
        evidence_before = store._conn.execute("SELECT COUNT(*) FROM provisional_evidence_units").fetchone()[0]  # type: ignore[union-attr]
        records_before = len(store.list_records())  # type: ignore[union-attr]

        assert runtime.schedule_temporal_memory(**kwargs) == first
        after = store.get_record(first["record_id"])  # type: ignore[union-attr]
        assert (after.independent_support_count, after.maturity, after.temporal_revision) == (
            before.independent_support_count,
            before.maturity,
            before.temporal_revision,
        )
        assert store._conn.execute("SELECT COUNT(*) FROM provisional_evidence_units").fetchone()[0] == evidence_before  # type: ignore[union-attr]

        try:
            runtime.schedule_temporal_memory(**(kwargs | {"source_content": "different reminder"}))
        except ValueError as exc:
            assert "TEMPORAL_IDEMPOTENCY_CONFLICT" in str(exc)
        else:
            raise AssertionError("conflicting idempotency payload must fail")
        assert len(store.list_records()) == records_before  # type: ignore[union-attr]
    finally:
        runtime.close()
        atom_store.close()


def test_runtime_snooze_requires_future_aware_time_within_policy_horizon(tmp_path) -> None:
    now = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    cfg = default_config()
    cfg.provisional_memory.temporal_snooze_horizon_years = 10
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
        server_clock=lambda: now,
    )
    try:
        scheduled = runtime.schedule_temporal_memory(
            temporal_request={"relative_duration": {"amount": 1, "unit": "days"}, "timezone": "UTC"},
            original_expression="tomorrow",
            source_content="check the deployment",
            builtin_source=True,
            idempotency_key="schedule-snooze-policy",
        )
        common = {
            "record_id": scheduled["record_id"],
            "action": "snooze",
            "expected_revision": 1,
            "principal_id": None,
        }
        with pytest.raises(ValueError, match="TEMPORAL_SNOOZE_TIMEZONE_REQUIRED"):
            runtime.resolve_temporal_memory(
                **common,
                snoozed_until_utc="2026-07-20T12:00:00",
                idempotency_key="snooze-naive",
            )
        with pytest.raises(ValueError, match="TEMPORAL_SNOOZE_MUST_BE_FUTURE"):
            runtime.resolve_temporal_memory(
                **common,
                snoozed_until_utc=now,
                idempotency_key="snooze-past",
            )
        with pytest.raises(ValueError, match="TEMPORAL_SNOOZE_HORIZON"):
            runtime.resolve_temporal_memory(
                **common,
                snoozed_until_utc=now + timedelta(days=3651),
                idempotency_key="snooze-far",
            )
    finally:
        runtime.close()
        atom_store.close()


def test_runtime_temporal_active_quota_is_scope_bounded(tmp_path) -> None:
    now = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    cfg = default_config()
    cfg.provisional_memory.temporal_active_record_limit = 1
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
        server_clock=lambda: now,
    )
    try:
        base = {
            "temporal_request": {"relative_duration": {"amount": 1, "unit": "days"}, "timezone": "UTC"},
            "original_expression": "tomorrow",
            "builtin_source": True,
        }
        runtime.schedule_temporal_memory(
            **base,
            source_content="first reminder",
            idempotency_key="quota-first",
        )
        with pytest.raises(ValueError, match="TEMPORAL_ACTIVE_QUOTA"):
            runtime.schedule_temporal_memory(
                **base,
                source_content="second reminder",
                idempotency_key="quota-second",
            )
    finally:
        runtime.close()
        atom_store.close()
