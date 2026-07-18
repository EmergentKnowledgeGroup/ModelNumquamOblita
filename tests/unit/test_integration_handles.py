from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.memory import SqliteAtomStore
from engine.runtime.integration_handles import IntegrationHandleError, IntegrationHandleSigner


def test_handles_survive_restart_and_reject_tampering(tmp_path) -> None:
    db_path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(db_path)
    signer = IntegrationHandleSigner(store)
    issued = signer.issue("retrieval_receipt", {"retrieved_evidence_ids": ["a1"]}, ttl_seconds=600)
    identity = store.runtime_control_identity()
    store.close()

    reopened = SqliteAtomStore(db_path)
    restarted = IntegrationHandleSigner(reopened)
    assert restarted.store_uuid == identity["store_uuid"]
    assert restarted.verify(issued["handle"], expected_kind="retrieval_receipt")["retrieved_evidence_ids"] == ["a1"]
    with pytest.raises(IntegrationHandleError, match="HANDLE_INVALID"):
        restarted.verify(issued["handle"] + "x", expected_kind="retrieval_receipt")
    reopened.close()


def test_expired_and_cross_store_handles_fail(tmp_path) -> None:
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    first = SqliteAtomStore(tmp_path / "first.sqlite3")
    signer = IntegrationHandleSigner(first, clock=lambda: now)
    issued = signer.issue("source_registration", {"source_id": "s1"}, ttl_seconds=60)

    expired = IntegrationHandleSigner(first, clock=lambda: now + timedelta(seconds=61))
    with pytest.raises(IntegrationHandleError, match="HANDLE_EXPIRED"):
        expired.verify(issued["handle"], expected_kind="source_registration")

    second = SqliteAtomStore(tmp_path / "second.sqlite3")
    with pytest.raises(IntegrationHandleError, match="HANDLE_INVALID"):
        IntegrationHandleSigner(second).verify(issued["handle"], expected_kind="source_registration")
    first.close()
    second.close()


def test_missing_control_key_fails_closed(tmp_path) -> None:
    db_path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(db_path)
    with store._conn:
        store._conn.execute("DELETE FROM runtime_control WHERE control_key='signing_key_hex'")
    store.close()

    with pytest.raises(RuntimeError, match="CONTROL_KEY_UNAVAILABLE"):
        SqliteAtomStore(db_path)


def test_offline_rotation_invalidates_old_handles_without_changing_store_identity(tmp_path) -> None:
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    signer = IntegrationHandleSigner(store)
    before = store.runtime_control_identity()
    issued = signer.issue("retrieval_receipt", {"retrieved_evidence_ids": []}, ttl_seconds=600)
    after = store.rotate_runtime_signing_key()
    assert after["store_uuid"] == before["store_uuid"]
    assert after["signing_key_id"] != before["signing_key_id"]
    with pytest.raises(IntegrationHandleError, match="HANDLE_INVALID"):
        IntegrationHandleSigner(store).verify(issued["handle"], expected_kind="retrieval_receipt")
    store.close()
