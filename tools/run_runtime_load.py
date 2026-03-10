#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.memory import SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession
from engine.runtime.load_harness import (
    load_inmemory_store_from_json,
    plan_load_workload,
    run_load_harness,
    write_load_artifacts,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Logger:
    def __init__(self, log_file: Path | None) -> None:
        self._fp: TextIO | None = None
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._fp = log_file.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def emit(self, message: str) -> None:
        line = f"[{_now_iso()}] {message}"
        print(line)
        if self._fp is not None:
            self._fp.write(line + "\n")
            self._fp.flush()


def _default_memory_path() -> Path:
    sqlite_default = REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3"
    if sqlite_default.exists():
        return sqlite_default
    imports_dir = REPO_ROOT / "runtime" / "imports"
    if imports_dir.exists():
        candidates = sorted(imports_dir.rglob("memories.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return sqlite_default


def _open_store(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), False
    raise ValueError(f"unsupported memories path: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run runtime load harness with CI-safe downshifts.")
    parser.add_argument("--memories", default=str(_default_memory_path()), help="Path to sqlite store or memories.json")
    parser.add_argument("--out-dir", default="", help="Output directory for load artifacts")
    parser.add_argument("--requested-turns", type=int, default=40, help="Requested number of harness turns")
    parser.add_argument("--scan-budget", type=int, default=600000, help="Max scan-ops budget")
    parser.add_argument("--ci-safe", action="store_true", help="Force a CI-safe max of 12 turns")
    parser.add_argument("--log-file", default="", help="Optional log file path")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    log_path = Path(args.log_file).expanduser().resolve() if args.log_file else None
    logger = Logger(log_path)

    try:
        if not memories_path.exists():
            logger.emit(f"error=memories path not found: {memories_path}")
            return 2

        requested_turns = int(args.requested_turns)
        if args.ci_safe:
            requested_turns = min(requested_turns, 12)

        logger.emit(f"Starting load harness for memories={memories_path}")
        store, close_store = _open_store(memories_path)
        try:
            atom_count = len(store.list_atoms())
            logger.emit(f"Detected atom_count={atom_count}")
            plan = plan_load_workload(
                atom_count=atom_count,
                requested_turns=requested_turns,
                scan_budget=int(args.scan_budget),
            )
            if plan.warning:
                logger.emit(f"warning={plan.warning}")

            continuity = ContinuityStore()
            shared_language_keys = store.list_shared_language_keys() if hasattr(store, "list_shared_language_keys") else []
            continuity.set_snapshot(
                ContinuityBuilder().build(store.list_atoms(), shared_language_keys=shared_language_keys)
            )
            runtime = RuntimeSession(
                retriever=MemoryRetriever(store),
                verifier=ClaimVerifier(),
                continuity_store=continuity,
                enable_writeback=False,
                short_term_enabled=False,
            )

            if args.out_dir:
                out_dir = Path(args.out_dir).expanduser().resolve()
            else:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                out_dir = REPO_ROOT / "runtime" / "evals" / f"load_{stamp}"
            out_dir.mkdir(parents=True, exist_ok=True)

            summary, samples = run_load_harness(
                runtime,
                store,
                requested_turns=plan.effective_turns,
                scan_budget=plan.scan_budget,
            )
            summary_json, summary_md, samples_json = write_load_artifacts(
                out_dir=out_dir,
                summary=summary,
                samples=samples,
            )

            logger.emit("Load artifacts written successfully.")
            logger.emit(f"atoms={summary.atoms}")
            logger.emit(f"requested_turns={summary.requested_turns}")
            logger.emit(f"turns={summary.turns}")
            logger.emit(f"scan_budget={summary.scan_budget}")
            logger.emit(f"estimated_scans={summary.estimated_scans}")
            logger.emit(f"throughput_qps={summary.throughput_qps:.4f}")
            logger.emit(f"latency_p95_ms={summary.latency_p95_ms:.2f}")
            logger.emit(f"latency_p99_ms={summary.latency_p99_ms:.2f}")
            logger.emit(f"abstain_rate={summary.abstain_rate:.4f}")
            logger.emit(f"summary_json={summary_json}")
            logger.emit(f"summary_md={summary_md}")
            logger.emit(f"samples_json={samples_json}")
            return 0
        finally:
            closer = getattr(store, "close", None)
            if callable(closer) and close_store:
                closer()
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
