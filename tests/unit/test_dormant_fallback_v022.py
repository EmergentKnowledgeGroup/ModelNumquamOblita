from __future__ import annotations

from engine.config import default_config
from engine.continuity import ContinuityStore
from engine.contracts import SourceRef
from engine.memory import SqliteAtomStore
from engine.memory.provisional_store import (
    ProvisionalLifecycle,
    ProvisionalMemoryCandidate,
    ProvisionalMemoryKind,
)
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession


def _candidate(text: str, suffix: str) -> ProvisionalMemoryCandidate:
    return ProvisionalMemoryCandidate(
        kind=ProvisionalMemoryKind.EVENT_NOTE,
        canonical_text=text,
        source_refs=[SourceRef(source_id=f"source-{suffix}", message_id=f"message-{suffix}")],
        source_role="user",
        session_id=f"session-{suffix}",
        confidence=0.8,
        salience=0.8,
        stability=0.7,
    )


def test_dormant_fallback_requires_strong_or_explicit_cue_and_stays_read_only(tmp_path) -> None:
    config = default_config()
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=config),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=config,
        enable_writeback=False,
    )
    try:
        store = runtime._provisional_store
        dormant_id = store.upsert_candidate(  # type: ignore[union-attr]
            _candidate("project aurora launches in november", "dormant"),
            reason="test",
        ).record_id
        store.set_lifecycle(dormant_id, ProvisionalLifecycle.DORMANT, reason="test")  # type: ignore[union-attr]
        archived_id = store.upsert_candidate(  # type: ignore[union-attr]
            _candidate("project atlas launches in december", "archived"),
            reason="test",
        ).record_id
        store.set_lifecycle(archived_id, ProvisionalLifecycle.ARCHIVED, reason="test")  # type: ignore[union-attr]

        before = store._conn.total_changes  # type: ignore[union-attr]
        weak_pack, weak_ids, weak_count, _ = runtime._retrieve_provisional_memory("aurora")
        assert weak_count == 0
        assert weak_ids == []
        assert not weak_pack.core

        strong_pack, strong_ids, strong_count, _ = runtime._retrieve_provisional_memory(
            "aurora launches november"
        )
        assert strong_count == 1
        assert strong_ids == [dormant_id]
        assert strong_pack.core[0].lifecycle == "dormant"

        explicit_pack, explicit_ids, _, _ = runtime._retrieve_provisional_memory(
            "what do you remember about aurora"
        )
        assert explicit_ids == [dormant_id]
        assert explicit_pack.core[0].authority_tier.startswith("provisional_")

        _, archived_ids, _, _ = runtime._retrieve_provisional_memory("atlas launches december")
        assert archived_id not in archived_ids
        assert store._conn.total_changes == before  # type: ignore[union-attr]
    finally:
        runtime.close()
        atom_store.close()


def test_active_results_prevent_dormant_displacement(tmp_path) -> None:
    config = default_config()
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store, config=config),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=config,
        enable_writeback=False,
    )
    try:
        store = runtime._provisional_store
        dormant_id = store.upsert_candidate(  # type: ignore[union-attr]
            _candidate("aurora launch november old plan", "old"),
            reason="test",
        ).record_id
        store.set_lifecycle(dormant_id, ProvisionalLifecycle.DORMANT, reason="test")  # type: ignore[union-attr]
        active_id = store.upsert_candidate(  # type: ignore[union-attr]
            _candidate("aurora launch november confirmed plan", "active"),
            reason="test",
        ).record_id

        pack, ids, _, _ = runtime._retrieve_provisional_memory("aurora launch november")
        assert active_id in ids
        assert dormant_id not in ids
        assert pack.core[0].lifecycle == "active"
    finally:
        runtime.close()
        atom_store.close()
