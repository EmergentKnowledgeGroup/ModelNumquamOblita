from __future__ import annotations

import json
from pathlib import Path

from engine.ingest import run_sqlite_import_job
from engine.memory import SqliteAtomStore


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
