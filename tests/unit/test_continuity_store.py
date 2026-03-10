from __future__ import annotations

from datetime import datetime, timezone

from engine.continuity import ContinuitySnapshot, ContinuityStore


def test_recognition_bonus_is_bounded() -> None:
    store = ContinuityStore(snapshot=ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    for _ in range(24):
        store.telemetry.record(atom_id="a1", recognized=True, score=1.0, query_text="x")
    bonus = store.telemetry.atom_bonus("a1")
    assert 0.0 <= bonus <= 0.06

    for _ in range(24):
        store.telemetry.record(atom_id="a2", recognized=False, score=1.0, query_text="x")
    negative_bonus = store.telemetry.atom_bonus("a2")
    assert -0.06 <= negative_bonus <= 0.0


def test_continuity_cache_token_changes_on_snapshot_revision() -> None:
    store = ContinuityStore(snapshot=ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    before = store.cache_token()
    store.set_snapshot(ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    after = store.cache_token()

    assert before != after
    assert store.cache_scope().startswith("continuity:")


def test_snapshot_view_returns_isolated_copy() -> None:
    store = ContinuityStore(snapshot=ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    original = store.snapshot_view()[1]
    assert original is not None

    _, first_view = store.snapshot_view()
    assert first_view is not None
    first_view.generated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)

    _, second_view = store.snapshot_view()
    assert second_view is not None
    assert second_view.generated_at == original.generated_at


def test_cache_token_changes_on_in_place_snapshot_mutation() -> None:
    store = ContinuityStore(snapshot=ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    before = store.cache_token()
    assert store.snapshot is not None

    store.snapshot.generated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    after = store.cache_token()

    assert before != after
