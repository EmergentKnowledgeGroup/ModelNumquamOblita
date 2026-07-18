from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.ingest import run_sqlite_import_job
from engine.ingest.orchestrator import _backup_sqlite_store
from engine.memory import SqliteAtomStore


def _seed_candidate(candidate_id: str, text: str, source_id: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_message",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(1, len(text)),
            )
        ],
        confidence=0.9,
        salience=0.8,
    )


def _write_export(path: Path) -> None:
    export = [
        {
            "id": "conv-1",
            "mapping": {
                "1": {
                    "id": "1",
                    "message": {
                        "id": "m1",
                        "author": {"role": "user"},
                        "create_time": 1739000000,
                        "content": {"parts": ["I prefer tea during long debug sessions and I trust this system."]},
                    },
                },
                "2": {
                    "id": "2",
                    "message": {
                        "id": "m2",
                        "author": {"role": "assistant"},
                        "create_time": 1739000001,
                        "content": {"parts": ["We should keep continuity notes because memory matters."]},
                    },
                },
            },
        }
    ]
    path.write_text(json.dumps(export), encoding="utf-8")


def _write_wrapper_export(path: Path) -> None:
    payload = {
        "generated_at": "2026-02-12T00:00:00+00:00",
        "conversations": [
            {
                "id": "conv-wrap-1",
                "messages": [
                    {"id": "u1", "role": "user", "text": "Do not forget the lighthouse trip in June."},
                    {"id": "a1", "role": "assistant", "text": "The lighthouse trip matters and should remain retrievable."},
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_late_fact_export(path: Path) -> None:
    payload = {
        "generated_at": "2026-02-12T00:00:00+00:00",
        "conversations": [
            {
                "id": "conv-late-fact-1",
                "messages": [
                    {
                        "id": "u1",
                        "role": "user",
                        "text": (
                            "I was thinking of getting Emily to audition for a role, I'll definitely encourage her to give it a shot. "
                            "The play I attended was actually a production of The Glass Menagerie, have you heard of it?"
                        ),
                    },
                    {"id": "a1", "role": "assistant", "text": "The Glass Menagerie is a classic Tennessee Williams play."},
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_assistant_artifact_export(path: Path) -> None:
    filler = " ".join("This chapter explores wonder and adventure." for _ in range(80))
    payload = {
        "generated_at": "2026-02-12T00:00:00+00:00",
        "conversations": [
            {
                "id": "conv-assistant-artifact-1",
                "messages": [
                    {
                        "id": "u1",
                        "role": "user",
                        "text": "Write a children's book about dinosaurs and include an image description for the Plesiosaur.",
                    },
                    {
                        "id": "a1",
                        "role": "assistant",
                        "text": (
                            f"{filler} "
                            "::Plesiosaur Image:: == A Plesiosaur is shown swimming through the sea with a blue scaly body and long flippers."
                        ),
                    },
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_import_pipeline_is_idempotent_for_same_export(tmp_path: Path) -> None:
    input_path = tmp_path / "conversations.json"
    store_path = tmp_path / "atoms.sqlite3"
    _write_export(input_path)

    first = run_sqlite_import_job(input_path=input_path, sqlite_path=store_path)
    assert first.ok is True
    assert first.counters.persisted_add_or_update > 0

    store = SqliteAtomStore(store_path)
    try:
        first_count = len(store.list_atoms())
    finally:
        store.close()

    second = run_sqlite_import_job(input_path=input_path, sqlite_path=store_path)
    assert second.ok is True
    assert second.counters.persisted_add_or_update == 0

    store = SqliteAtomStore(store_path)
    try:
        second_count = len(store.list_atoms())
    finally:
        store.close()

    assert second_count == first_count


def test_import_pipeline_malformed_input_fails_without_partial_commit(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    broken = tmp_path / "broken.json"
    store_path = tmp_path / "atoms.sqlite3"
    _write_export(valid)
    broken.write_text("[{'bad':", encoding="utf-8")

    ok_report = run_sqlite_import_job(input_path=valid, sqlite_path=store_path)
    assert ok_report.ok is True

    store = SqliteAtomStore(store_path)
    try:
        before_count = len(store.list_atoms())
    finally:
        store.close()

    fail_report = run_sqlite_import_job(input_path=broken, sqlite_path=store_path)
    assert fail_report.ok is False
    assert fail_report.error_code == "INGEST_FAILURE"

    store = SqliteAtomStore(store_path)
    try:
        after_count = len(store.list_atoms())
    finally:
        store.close()

    assert after_count == before_count


def test_import_rejects_secrets_before_any_store_persistence(tmp_path: Path) -> None:
    input_path = tmp_path / "secret_export.json"
    store_path = tmp_path / "atoms.sqlite3"
    secret = "sk-MNO-CANARY-1234567890abcdef"  # noqa: S105
    input_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "secret-conversation",
                        "messages": [{"id": "u1", "role": "user", "text": f"api_key={secret}"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = run_sqlite_import_job(input_path=input_path, sqlite_path=store_path)

    assert report.ok is False
    assert report.error_code == "CONTENT_SAFETY_REJECTED"
    assert report.error_message == "LEGACY_SECRET_DETECTED"
    assert secret not in json.dumps(report.to_dict())
    assert not store_path.exists()
    assert not list(tmp_path.glob("atoms.sqlite3.tmp_*"))


def test_sqlite_import_snapshot_includes_committed_wal_state(tmp_path: Path) -> None:
    live_path = tmp_path / "live.sqlite3"
    snapshot_path = tmp_path / "snapshot.sqlite3"
    live_store = SqliteAtomStore(live_path)
    try:
        live_store._conn.execute("PRAGMA wal_autocheckpoint=0")  # noqa: SLF001 - hostile WAL fixture
        live_store.add_candidate(
            _seed_candidate("wal_candidate", "Committed memory waiting in WAL state.", "wal_source")
        )
        assert live_path.with_name(f"{live_path.name}-wal").exists()

        _backup_sqlite_store(live_path, snapshot_path)
        snapshot_store = SqliteAtomStore(snapshot_path)
        try:
            assert any(atom.canonical_text == "Committed memory waiting in WAL state." for atom in snapshot_store.list_atoms())
        finally:
            snapshot_store.close()
    finally:
        live_store.close()


def test_sqlite_import_snapshot_escapes_special_path_characters_for_uri_mode(tmp_path: Path) -> None:
    live_path = tmp_path / "live#snapshot.sqlite3"
    snapshot_path = tmp_path / "snapshot.sqlite3"
    live_store = SqliteAtomStore(live_path)
    try:
        live_store.add_candidate(_seed_candidate("uri_candidate", "URI-safe SQLite backup.", "uri_source"))
        _backup_sqlite_store(live_path, snapshot_path)
        snapshot_store = SqliteAtomStore(snapshot_path)
        try:
            assert any(atom.canonical_text == "URI-safe SQLite backup." for atom in snapshot_store.list_atoms())
        finally:
            snapshot_store.close()
    finally:
        live_store.close()


def test_import_report_counts_are_internally_consistent(tmp_path: Path) -> None:
    input_path = tmp_path / "conversations.json"
    store_path = tmp_path / "atoms.sqlite3"
    _write_export(input_path)

    report = run_sqlite_import_job(input_path=input_path, sqlite_path=store_path)
    assert report.ok is True

    outcomes = (
        report.counters.persisted_add_or_update
        + report.counters.proposals_created
        + sum(report.counters.rejected_reasons.values())
    )
    assert outcomes == report.counters.candidates_extracted


def test_import_pipeline_accepts_wrapper_object_root(tmp_path: Path) -> None:
    input_path = tmp_path / "db_wrapper.json"
    store_path = tmp_path / "atoms.sqlite3"
    _write_wrapper_export(input_path)

    report = run_sqlite_import_job(input_path=input_path, sqlite_path=store_path)
    assert report.ok is True
    assert report.counters.conversations_seen == 1
    assert report.counters.turns_emitted >= 2
    assert report.counters.messages_seen == 2
    assert Path(report.store_path or "").exists()


def test_import_pipeline_persists_bounded_raw_context_sidecar(tmp_path: Path) -> None:
    input_path = tmp_path / "quote_export.json"
    store_path = tmp_path / "atoms.sqlite3"
    payload = {
        "conversations": [
            {
                "id": "conv-quote-1",
                "messages": [
                    {"id": "u1", "role": "user", "text": "  Say this exactly.  "},
                    {"id": "a1", "role": "assistant", "text": "\r\nSure. I said it exactly.\r\n"},
                ],
            }
        ]
    }
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_sqlite_import_job(input_path=input_path, sqlite_path=store_path)
    assert report.ok is True

    store = SqliteAtomStore(store_path)
    try:
        rows = store.fetch_raw_context_slice("conv-quote-1", message_id="a1", before=1, after=0, max_turns=2, max_chars=200)
    finally:
        store.close()

    assert [row.message_id for row in rows] == ["u1", "a1"]
    assert rows[0].quote_text == "  Say this exactly.  "
    assert rows[1].quote_text == "\nSure. I said it exactly.\n"
