from __future__ import annotations

from pathlib import Path

from engine.memory import SqliteAtomStore
from engine.runtime import generate_truthset, write_truthset_jsonl


def build_truthset(store_path: Path, truthset_path: Path, *, total_cases: int = 6) -> None:
    store = SqliteAtomStore(store_path)
    try:
        cases = generate_truthset(store, total_cases=total_cases, supported_ratio=0.5)
    finally:
        store.close()
    write_truthset_jsonl(cases, truthset_path)
