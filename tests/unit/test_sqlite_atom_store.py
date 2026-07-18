from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.contracts import AtomType, CandidateAtom, NormalizedTurn, SourceRef
from engine.memory import AtomStatus, AtomStore, SqliteAtomStore, backup_memory_family
from engine.memory.proposal_store import SqliteProposalStore
from engine.memory.provisional_store import SqliteProvisionalMemoryStore


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


def test_sqlite_write_batch_commits_multiple_candidate_writes_together(tmp_path: Path) -> None:
    store = SqliteAtomStore(tmp_path / "batch.sqlite3")
    try:
        with store.write_batch():
            first = store.add_candidate(_candidate(text="Batch memory one", source="b1", entities=["user"]))
            second = store.add_candidate(_candidate(text="Batch memory two", source="b2", entities=["user"]))
        assert store.get_atom(first.atom_id).canonical_text == "Batch memory one"
        assert store.get_atom(second.atom_id).canonical_text == "Batch memory two"
        assert len(store.ledger.all_events()) == 2
    finally:
        store.close()


def test_sqlite_write_batch_rolls_back_on_error(tmp_path: Path) -> None:
    store = SqliteAtomStore(tmp_path / "batch_rollback.sqlite3")
    try:
        try:
            with store.write_batch():
                store.add_candidate(_candidate(text="Should roll back", source="br1", entities=["user"]))
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        assert store.list_atoms() == []
        assert store.ledger.all_events() == []
    finally:
        store.close()


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


def test_sqlite_and_inmemory_raw_context_slice_have_parity(tmp_path: Path) -> None:
    def _exercise_raw(store: AtomStore | SqliteAtomStore) -> tuple[list[tuple[str, str]], tuple[object, ...]]:
        store.record_raw_turn(
            NormalizedTurn(
                source_id="conv_raw",
                conversation_id="conv_raw",
                message_id="m1",
                role="user",
                text="trimmed one",
                quote_text="  raw one  ",
                sequence_index=0,
            )
        )
        store.record_raw_turn(
            NormalizedTurn(
                source_id="conv_raw",
                conversation_id="conv_raw",
                message_id="m2",
                role="assistant",
                text="trimmed two",
                quote_text="raw two\nnext",
                sequence_index=1,
            )
        )
        rows = store.fetch_raw_context_slice("conv_raw", message_id="m2", before=1, after=0, max_turns=2, max_chars=200)
        payload = [(row.message_id or "", row.quote_text) for row in rows]
        return payload, store.cache_token()

    mem_store = AtomStore()
    sqlite_store = SqliteAtomStore(tmp_path / "raw.sqlite3")
    try:
        mem_payload, mem_token = _exercise_raw(mem_store)
        sqlite_payload, sqlite_token = _exercise_raw(sqlite_store)
    finally:
        _close_if_supported(mem_store)
        _close_if_supported(sqlite_store)

    assert mem_payload == [("m1", "  raw one  "), ("m2", "raw two\nnext")]
    assert sqlite_payload == mem_payload
    assert len(mem_token) >= 8
    assert len(sqlite_token) >= 8


def test_sqlite_atom_store_backup_captures_live_wal_state(tmp_path: Path) -> None:
    store = SqliteAtomStore(tmp_path / "live.sqlite3")
    atom = store.add_candidate(_candidate(text="Backup keeps this evidence.", source="backup_source"))
    source_identity = store.runtime_control_identity()
    backup_path = store.backup_to(tmp_path / "backups" / "atoms.sqlite3")
    store.close()

    backup = SqliteAtomStore(backup_path)
    try:
        assert backup.get_atom(atom.atom_id).canonical_text == "Backup keeps this evidence."
        identity = backup.runtime_control_identity()
        assert identity == source_identity
    finally:
        backup.close()
    reopened = SqliteAtomStore(backup_path)
    try:
        assert reopened.runtime_control_identity() == identity
    finally:
        reopened.close()


def test_sqlite_atom_store_restricts_live_and_backup_permissions(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        "engine.memory.sqlite_store.os.chmod",
        lambda path, mode: calls.append((Path(path).resolve(), mode)),
    )
    live_path = (tmp_path / "protected.sqlite3").resolve()
    backup_path = (tmp_path / "backups" / "protected.sqlite3").resolve()
    store = SqliteAtomStore(live_path)
    store.backup_to(backup_path)
    store.close()

    assert (live_path, 0o600) in calls
    assert (backup_path, 0o600) in calls

    calls.clear()
    reopened = SqliteAtomStore(live_path)
    reopened.close()
    assert calls == [(live_path, 0o600)]


def test_memory_family_backup_uses_sqlite_apis_and_records_only_topology_metadata(tmp_path: Path) -> None:
    atom_path = tmp_path / "atoms.sqlite3"
    atom_store = SqliteAtomStore(atom_path)
    atom_store.add_candidate(_candidate(text="Family backup atom", source="family"))
    provisional = SqliteProvisionalMemoryStore(atom_path.with_suffix(".provisional.sqlite3"))
    proposal = SqliteProposalStore(atom_path.with_suffix(".proposals.sqlite3"))
    provisional.close()
    proposal.close()
    manifest = backup_memory_family(atom_store, tmp_path / "backups")
    atom_store.close()

    assert manifest["schema"] == "mno.memory-family-backup.v1"
    assert manifest["artifacts"]["atom"]["present"] is True
    assert manifest["artifacts"]["provisional"]["present"] is True
    assert manifest["artifacts"]["proposal"]["present"] is True
    assert "Family backup atom" not in Path(manifest["manifest_path"]).read_text(encoding="utf-8")
    restored = SqliteAtomStore(tmp_path / "backups" / "atoms.sqlite3")
    try:
        assert len(restored.list_atoms()) == 1
    finally:
        restored.close()


def test_memory_family_backup_does_not_initialize_existing_sidecars(tmp_path: Path) -> None:
    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    provisional_path = tmp_path / "atoms.provisional.sqlite3"
    with sqlite3.connect(provisional_path) as provisional:
        provisional.execute("CREATE TABLE untouched_sidecar (value TEXT NOT NULL)")
        provisional.execute("INSERT INTO untouched_sidecar(value) VALUES ('preserve')")

    manifest = backup_memory_family(atom_store, tmp_path / "backups")
    atom_store.close()

    with sqlite3.connect(provisional_path) as provisional:
        tables = {str(row[0]) for row in provisional.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert tables == {"untouched_sidecar"}
    assert manifest["artifacts"]["provisional"]["present"] is True
