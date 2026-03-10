from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.config import DecayPolicy
from engine.continuity import ContinuityStore
from engine.continuity.consolidator import Consolidator
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession


def _candidate(*, candidate_id: str, text: str, timestamp: datetime) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=f"conv_{candidate_id}",
                message_id=f"m_{candidate_id}",
                timestamp=timestamp,
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user"],
        topics=["continuity"],
        confidence=0.82,
        salience=0.8,
    )


def _decayed_salience(*, recognized: bool | None) -> float:
    now = datetime.now(timezone.utc)
    store = AtomStore()
    atom = store.add_candidate(_candidate(candidate_id="base", text="I remember this continuity check.", timestamp=now))
    atom.last_reinforced_at = now - timedelta(days=180)
    atom.updated_at = now - timedelta(days=180)
    if recognized is not None:
        for _ in range(8):
            store.record_recognition_event(
                atom_id=atom.atom_id,
                recognized=recognized,
                score=1.0,
                query_text="continuity check",
                timestamp=now - timedelta(days=1),
            )
    consolidator = Consolidator(store, policy=DecayPolicy(half_life_days=180, minimum_salience=0.05))
    consolidator.run(now=now)
    return store.get_atom(atom.atom_id).salience


def test_recognition_uplift_slows_decay() -> None:
    baseline = _decayed_salience(recognized=None)
    uplifted = _decayed_salience(recognized=True)
    assert uplifted > baseline


def test_low_recognition_accelerates_decay() -> None:
    baseline = _decayed_salience(recognized=None)
    accelerated = _decayed_salience(recognized=False)
    assert accelerated < baseline


def test_recognition_events_persist_and_hydrate_runtime(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    sqlite_path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(sqlite_path)
    try:
        atom = store.add_candidate(_candidate(candidate_id="persist", text="I remember this for later.", timestamp=now))
        store.record_recognition_event(
            atom_id=atom.atom_id,
            recognized=True,
            score=0.9,
            query_text="later",
            timestamp=now,
        )
    finally:
        store.close()

    reopened = SqliteAtomStore(sqlite_path)
    try:
        events = reopened.list_recognition_events(atom_id=atom.atom_id)
        assert len(events) == 1
        assert events[0].recognized is True

        runtime = RuntimeSession(
            retriever=MemoryRetriever(reopened),
            verifier=ClaimVerifier(),
            continuity_store=ContinuityStore(),
            enable_writeback=False,
        )
        try:
            stats = runtime.stats()
            assert stats.recognition_events >= 1
            assert stats.recognition_rate > 0.0
        finally:
            runtime.close()
    finally:
        reopened.close()
