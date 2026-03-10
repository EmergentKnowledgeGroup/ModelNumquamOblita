from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import SqliteAtomStore
from engine.retrieval import MemoryRetriever


REPO_ROOT = Path(__file__).resolve().parents[2]


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    timestamp: datetime,
    topic: str,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_m1",
                timestamp=timestamp,
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=[topic],
        confidence=0.84,
        salience=0.72,
    )


def test_rebuild_continuity_script_is_idempotent(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(sqlite_path)
    try:
        base = datetime(2026, 2, 7, 0, 0, tzinfo=timezone.utc)
        store.add_candidate(
            _candidate(
                candidate_id="seed_1",
                text="I was afraid before the ritual.",
                source_id="conv_1",
                timestamp=base,
                topic="ritual",
            )
        )
        store.add_candidate(
            _candidate(
                candidate_id="seed_2",
                text="I trust this ritual now.",
                source_id="conv_1",
                timestamp=base + timedelta(minutes=12),
                topic="ritual",
            )
        )
        store.add_candidate(
            _candidate(
                candidate_id="seed_3",
                text="I feel open and grounded with this process.",
                source_id="conv_2",
                timestamp=base + timedelta(days=3),
                topic="growth",
            )
        )
    finally:
        store.close()

    out_a = tmp_path / "rebuild_a.json"
    out_b = tmp_path / "rebuild_b.json"
    cmd = [
        sys.executable,
        "tools/rebuild_continuity.py",
        "--store-backend",
        "sqlite",
        "--sqlite-path",
        str(sqlite_path),
    ]

    first = subprocess.run([*cmd, "--output", str(out_a)], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    second = subprocess.run([*cmd, "--output", str(out_b)], cwd=REPO_ROOT, check=True, capture_output=True, text=True)

    first_payload = json.loads(first.stdout.strip())
    second_payload = json.loads(second.stdout.strip())

    assert first_payload["ok"] is True
    assert second_payload["ok"] is True
    assert first_payload["atom_count_after"] == second_payload["atom_count_after"]
    assert first_payload["snapshot_stats"] == second_payload["snapshot_stats"]
    assert out_a.exists()
    assert out_b.exists()
    assert out_a.with_suffix(".md").exists()
    assert out_b.with_suffix(".md").exists()


def test_retrieval_is_safe_during_snapshot_swaps(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "continuity_swap.sqlite3"
    store = SqliteAtomStore(sqlite_path)
    try:
        base = datetime.now(timezone.utc)
        for index, text in enumerate(
            [
                "I was afraid before this check.",
                "I stayed open during this check.",
                "I trust this process now.",
                "We tracked continuity telemetry and evidence.",
            ]
        ):
            store.add_candidate(
                _candidate(
                    candidate_id=f"swap_{index}",
                    text=text,
                    source_id=f"conv_swap_{index // 2}",
                    timestamp=base + timedelta(minutes=index * 8),
                    topic="continuity",
                )
            )

        builder = ContinuityBuilder()
        continuity_store = ContinuityStore()
        continuity_store.set_snapshot(builder.build(store.list_atoms()))
        retriever = MemoryRetriever(store)

        failures: list[str] = []
        stop = threading.Event()

        def writer() -> None:
            counter = 0
            while not stop.is_set():
                try:
                    snapshot = builder.build(
                        store.list_atoms(),
                        now=base + timedelta(seconds=counter),
                    )
                    continuity_store.set_snapshot(snapshot)
                    counter += 1
                except Exception as exc:  # pragma: no cover - safety capture
                    failures.append(str(exc))
                    stop.set()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for _ in range(80):
                result = retriever.retrieve(
                    "what did we confirm about continuity and trust",
                    continuity_store=continuity_store,
                )
                assert 0.0 <= result.memory_pack.pack_confidence <= 1.0
        finally:
            stop.set()
            thread.join(timeout=2)

        assert not failures
    finally:
        store.close()
