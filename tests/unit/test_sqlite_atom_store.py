from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStatus, AtomStore, SqliteAtomStore


def _candidate(
    *,
    text: str,
    source: str,
    atom_type: AtomType = AtomType.ATOMIC_FACT,
    entities: list[str] | None = None,
    topics: list[str] | None = None,
    confidence: float = 0.8,
    salience: float = 0.7,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=f"cand_{source}",
        atom_type=atom_type,
        canonical_text=text,
        source_refs=[SourceRef(source_id=source, timestamp=datetime.now(timezone.utc))],
        entities=entities or [],
        topics=topics or [],
        confidence=confidence,
        salience=salience,
    )


def _exercise_store(store: AtomStore | SqliteAtomStore) -> dict[str, object]:
    first = store.add_candidate(_candidate(text="I trust continuity", source="c1", entities=["user"]))
    reinforced = store.add_candidate(_candidate(text="I trust continuity", source="c2", entities=["user"]))
    alternate = store.add_candidate(_candidate(text="I distrust continuity", source="c3", entities=["user"]))

    store.mark_conflict(first.atom_id, alternate.atom_id, reason="explicit_conflict")
    replacement = store.supersede_atom(
        first.atom_id,
        _candidate(text="I trust continuity deeply", source="c4", entities=["user"]),
        reason="manual_update",
    )

    tombstoned = store.tombstone_atom(alternate.atom_id, reason="cleanup", retention_days=0)
    purge_cutoff = tombstoned.purge_after or datetime.now(timezone.utc)
    purged_ids = store.purge_due_atoms(now=purge_cutoff + timedelta(seconds=1))

    first_after = store.get_atom(first.atom_id)
    replacement_after = store.get_atom(replacement.atom_id)
    events = [event.event_type.value for event in store.ledger.all_events()]

    return {
        "support_count": reinforced.support_count,
        "first_status": first_after.status.value,
        "replacement_links_old": replacement_after.version_of == first.atom_id,
        "conflict_neighbors_first": sorted(store.conflict_neighbors(first.atom_id)),
        "purged_count": len(purged_ids),
        "alternate_purged": alternate.atom_id in purged_ids,
        "atom_count": len(store.list_atoms()),
        "event_types": events,
    }


def _close_if_supported(store: AtomStore | SqliteAtomStore) -> None:
    closer = getattr(store, "close", None)
    if callable(closer):
        closer()


def test_sqlite_and_inmemory_backends_have_parity(tmp_path: Path) -> None:
    mem_store = AtomStore(salience_half_life_days=180)
    sqlite_store = SqliteAtomStore(tmp_path / "atoms.sqlite3", salience_half_life_days=180)
    try:
        mem_summary = _exercise_store(mem_store)
        sqlite_summary = _exercise_store(sqlite_store)
    finally:
        _close_if_supported(mem_store)
        _close_if_supported(sqlite_store)

    assert mem_summary == sqlite_summary


def test_sqlite_add_candidate_uses_type_specific_decay_defaults(tmp_path: Path) -> None:
    store = SqliteAtomStore(tmp_path / "decay.sqlite3", salience_half_life_days=180)
    try:
        episode = store.add_candidate(
            _candidate(
                text="We discussed yesterday's incident.",
                source="d1",
                atom_type=AtomType.EPISODE,
            )
        )
        fact = store.add_candidate(
            _candidate(
                text="The deployment region is us-central.",
                source="d2",
                atom_type=AtomType.ATOMIC_FACT,
            )
        )
        procedural = store.add_candidate(
            _candidate(
                text="Run checklist A then checklist B.",
                source="d3",
                atom_type=AtomType.PROCEDURAL_STYLE,
            )
        )
    finally:
        store.close()

    assert episode.salience_half_life_days == 120
    assert fact.salience_half_life_days == 270
    assert procedural.salience_half_life_days == 225


def test_sqlite_cache_token_changes_on_reinforce_without_count_delta(tmp_path: Path) -> None:
    store = SqliteAtomStore(tmp_path / "cache_token.sqlite3")
    try:
        fixed_now = datetime(2026, 3, 4, 23, 38, 40, 470921, timezone.utc)
        store._now = lambda: fixed_now  # type: ignore[assignment]
        store.add_candidate(_candidate(text="Cache token probe text", source="r1", entities=["user"]))
        token_before = store.cache_token()
        store.add_candidate(_candidate(text="Cache token probe text", source="r2", entities=["user"]))
        token_after = store.cache_token()
    finally:
        store.close()

    assert token_after != token_before


def test_sqlite_cache_scope_is_path_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "scope.sqlite3"
    store = SqliteAtomStore(db_path)
    try:
        scope = store.cache_scope()
    finally:
        store.close()

    assert scope == f"sqlite-atom-store:{db_path.resolve()}"


def test_sqlite_persists_atoms_and_conflicts_across_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "persist.sqlite3"
    store = SqliteAtomStore(db_path)
    try:
        left = store.add_candidate(_candidate(text="We confirmed this memory", source="c10", entities=["user"]))
        right = store.add_candidate(_candidate(text="We denied this memory", source="c11", entities=["user"]))
        store.mark_conflict(left.atom_id, right.atom_id, reason="explicit_conflict")
        store.tombstone_atom(right.atom_id, reason="pending_review", retention_days=30)
        event_count = len(store.ledger.all_events())
    finally:
        store.close()

    reopened = SqliteAtomStore(db_path)
    try:
        assert len(reopened.list_atoms()) == 2
        assert reopened.conflict_neighbors(left.atom_id) == {right.atom_id}
        assert reopened.get_atom(right.atom_id).status == AtomStatus.TOMBSTONED
        assert len(reopened.ledger.all_events()) == event_count
    finally:
        reopened.close()


def _create_v1_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE atoms (
                atom_id TEXT PRIMARY KEY,
                atom_type TEXT NOT NULL,
                canonical_text TEXT NOT NULL,
                source_refs_json TEXT NOT NULL,
                entities_json TEXT NOT NULL,
                topics_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                salience REAL NOT NULL,
                salience_half_life_days INTEGER NOT NULL,
                last_reinforced_at TEXT,
                support_count INTEGER NOT NULL,
                contradiction_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                version_of TEXT,
                tombstoned_at TEXT,
                purge_after TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE
            );

            CREATE TABLE provenance_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                atom_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source_refs_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );

            CREATE TABLE conflicts (
                left_atom_id TEXT NOT NULL,
                right_atom_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY (left_atom_id, right_atom_id)
            );

            CREATE INDEX idx_atoms_status ON atoms(status);
            CREATE INDEX idx_atoms_updated_at ON atoms(updated_at);
            CREATE INDEX idx_events_atom ON provenance_events(atom_id);
            CREATE INDEX idx_conflicts_left ON conflicts(left_atom_id);

            PRAGMA user_version=1;
            """
        )

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO atoms (
                atom_id, atom_type, canonical_text, source_refs_json, entities_json, topics_json,
                confidence, salience, salience_half_life_days, last_reinforced_at, support_count,
                contradiction_count, status, version_of, tombstoned_at, purge_after, created_at, updated_at, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "mem_seed",
                AtomType.ATOMIC_FACT.value,
                "Seed memory",
                "[{\"source_id\":\"seed\"}]",
                "[\"user\"]",
                "[\"seed\"]",
                0.7,
                0.6,
                180,
                now,
                1,
                0,
                AtomStatus.ACTIVE.value,
                None,
                None,
                None,
                now,
                now,
                "dedupe_seed",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_sqlite_migrates_schema_v1_to_v3(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.sqlite3"
    _create_v1_database(db_path)

    store = SqliteAtomStore(db_path)
    try:
        assert store.schema_version() == 3
        migrated = store.get_atom("mem_seed")
        assert migrated.canonical_text == "Seed memory"
    finally:
        store.close()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recognition_events'").fetchall()
    finally:
        conn.close()
    assert rows and rows[0][0] == "recognition_events"
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shared_language_keys'").fetchall()
    finally:
        conn.close()
    assert rows and rows[0][0] == "shared_language_keys"


def test_sqlite_shared_language_key_round_trip(tmp_path: Path) -> None:
    store = SqliteAtomStore(tmp_path / "slk.sqlite3")
    try:
        atom = store.add_candidate(_candidate(text="We coined a ritual phrase.", source="c40", entities=["user"]))
        row = store.upsert_shared_language_key(
            phrase="always together we find a way",
            atom_ids=[atom.atom_id],
            aliases=["atwfw"],
            domains=["ritual"],
            support_count=3,
            weight=0.91,
            confidence=0.86,
            curated=True,
        )
        keys = store.list_shared_language_keys()
    finally:
        store.close()

    assert row["phrase"] == "always together we find a way"
    assert keys and keys[0]["phrase"] == "always together we find a way"
    assert keys[0]["atom_ids"] == [atom.atom_id]


def test_sqlite_read_write_concurrency_does_not_corrupt(tmp_path: Path) -> None:
    store = SqliteAtomStore(tmp_path / "concurrency.sqlite3")
    errors: list[Exception] = []

    def writer() -> None:
        for idx in range(160):
            try:
                store.add_candidate(
                    _candidate(
                        text=f"Concurrent memory {idx % 13}",
                        source=f"source_{idx}",
                        entities=["user"],
                        topics=["concurrency"],
                    )
                )
            except Exception as exc:  # pragma: no cover - failure path assertion below
                errors.append(exc)
                return

    def reader() -> None:
        for _ in range(220):
            try:
                atoms = store.list_atoms()
                if atoms:
                    store.get_atom(atoms[0].atom_id)
            except Exception as exc:  # pragma: no cover - failure path assertion below
                errors.append(exc)
                return

    write_thread = threading.Thread(target=writer)
    read_thread = threading.Thread(target=reader)
    write_thread.start()
    read_thread.start()
    write_thread.join(timeout=10)
    read_thread.join(timeout=10)

    try:
        assert not errors
        assert len(store.list_atoms()) > 0
    finally:
        store.close()
