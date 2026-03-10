#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.memory import SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import (
    RuntimeSession,
    evaluate_truthset,
    generate_truthset,
    load_inmemory_store_from_json,
    load_truthset_jsonl,
    plan_live_eval_workload,
    summarize_live_eval_records,
    write_live_eval_artifacts,
    write_truthset_jsonl,
)

_AUTO_CHUNK_ATOM_THRESHOLD = max(1, int(os.getenv("NO_AUTO_CHUNK_ATOM_THRESHOLD", "25000")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Logger:
    def __init__(self, log_file: Path | None) -> None:
        self._fp: TextIO | None = None
        self._path = log_file
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


def _default_episode_cards_path() -> Path | None:
    episodes_dir = REPO_ROOT / "runtime" / "episodes"
    if not episodes_dir.exists():
        return None
    candidates = sorted(episodes_dir.glob("episode_cards_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    fallback = episodes_dir / "episode_cards.json"
    if fallback.exists():
        return fallback
    return None


def _normalize_compare_path(value: str | Path) -> str:
    try:
        resolved = Path(str(value)).expanduser().resolve()
    except Exception:
        resolved = Path(str(value))
    return str(resolved).replace("\\", "/").rstrip("/").lower()


def _episode_cards_match_store(cards_path: Path, memories_path: Path) -> bool:
    try:
        payload = json.loads(cards_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    target = _normalize_compare_path(memories_path)
    for key in ("source_store", "memories_path"):
        raw = str(payload.get(key) or "").strip()
        if raw and _normalize_compare_path(raw) == target:
            return True
    return False


def _open_store(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), False
    raise ValueError(f"unsupported memories path: {path}")


def _case_type_counts(cases: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in list(cases or []):
        key = str(getattr(case, "fixture_family", "") or getattr(case, "case_type", "") or "unknown").strip() or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live truthset eval against local memory store.")
    parser.add_argument(
        "--memories",
        default=str(_default_memory_path()),
        help="Path to sqlite store (.sqlite3/.db) or memory json file.",
    )
    parser.add_argument("--truthset", default="", help="Optional truthset.jsonl path.")
    parser.add_argument("--out-dir", default="", help="Output directory for eval artifacts.")
    parser.add_argument("--requested-cases", type=int, default=120, help="Requested number of eval cases.")
    parser.add_argument("--scan-budget", type=int, default=600000, help="Workload scan budget in scan-ops.")
    parser.add_argument("--supported-ratio", type=float, default=0.67, help="Supported case ratio when auto-generating truthset.")
    parser.add_argument(
        "--fixture-mode",
        choices=["basic", "trust-v2", "trust-v3"],
        default="trust-v3",
        help="Fixture family generation mode when auto-generating truthset.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Optional eval batch size. 0 disables chunking.",
    )
    parser.add_argument(
        "--batch-pause-ms",
        type=int,
        default=0,
        help="Optional pause between eval batches in milliseconds.",
    )
    parser.add_argument(
        "--episode-cards",
        default="",
        help="Optional path to episode_cards json (default: latest runtime/episodes/episode_cards_*.json).",
    )
    parser.add_argument("--disable-episodes", action="store_true", help="Disable episode-card retrieval path for this eval.")
    parser.add_argument("--episode-top-k", type=int, default=2, help="Episode candidate count before score threshold.")
    parser.add_argument("--episode-min-score", type=float, default=0.56, help="Episode score threshold [0..1].")
    parser.add_argument(
        "--write-partial-artifacts",
        action="store_true",
        help="Write partial progress artifacts after each batch.",
    )
    parser.add_argument("--plan-only", action="store_true", help="Only print effective workload plan.")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow zero-case execution to exit successfully (default fails closed).",
    )
    parser.add_argument("--log-file", default="", help="Optional log file path.")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    log_path = Path(args.log_file).expanduser().resolve() if args.log_file else None
    logger = Logger(log_path)

    try:
        if not memories_path.exists():
            logger.emit(f"error=memories path not found: {memories_path}")
            return 2

        logger.emit(f"Starting live eval CLI for memories={memories_path}")
        store, close_store = _open_store(memories_path)
        try:
            atoms = len(store.list_atoms())
            logger.emit(f"Detected atom_count={atoms}")
            logger.emit(f"fixture_mode={args.fixture_mode}")
            plan = plan_live_eval_workload(
                atom_count=atoms,
                requested_cases=int(args.requested_cases),
                scan_budget=int(args.scan_budget),
            )

            if args.plan_only:
                logger.emit("Plan-only mode; skipping runtime construction and eval execution.")
                if plan.warning:
                    logger.emit(f"warning={plan.warning}")
                logger.emit(f"atoms={plan.atoms}")
                logger.emit(f"requested_cases={plan.requested_cases}")
                logger.emit(f"effective_cases={plan.effective_cases}")
                logger.emit(f"scan_budget={plan.scan_budget}")
                logger.emit(f"estimated_scans={plan.estimated_scans}")
                return 0

            if args.truthset:
                truthset_path = Path(args.truthset).expanduser().resolve()
                cases = load_truthset_jsonl(truthset_path)
            else:
                cases = generate_truthset(
                    store,
                    total_cases=plan.effective_cases,
                    supported_ratio=float(args.supported_ratio),
                    fixture_mode=str(args.fixture_mode),
                )

            if not cases:
                message = "no eval cases generated or loaded"
                if args.allow_empty:
                    logger.emit(f"warning={message}")
                    return 0
                logger.emit(f"error={message}")
                return 2

            cases = cases[: plan.effective_cases]

            if args.out_dir:
                out_dir = Path(args.out_dir).expanduser().resolve()
            else:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                out_dir = REPO_ROOT / "runtime" / "evals" / f"safe_{stamp}"
            out_dir.mkdir(parents=True, exist_ok=True)

            generated_truthset_path = out_dir / "truthset.generated.jsonl"
            write_truthset_jsonl(cases, generated_truthset_path)
            case_counts_path = out_dir / "truthset.case_counts.json"
            case_counts = _case_type_counts(cases)
            case_counts_path.write_text(json.dumps(case_counts, indent=2) + "\n", encoding="utf-8")

            continuity = ContinuityStore()
            shared_language_keys = store.list_shared_language_keys() if hasattr(store, "list_shared_language_keys") else []
            continuity.set_snapshot(
                ContinuityBuilder().build(store.list_atoms(), shared_language_keys=shared_language_keys)
            )
            episode_cards_path: Path | None = None
            if not bool(args.disable_episodes):
                if str(args.episode_cards).strip():
                    episode_cards_path = Path(str(args.episode_cards)).expanduser().resolve()
                else:
                    default_cards = _default_episode_cards_path()
                    if default_cards is not None:
                        if _episode_cards_match_store(default_cards, memories_path):
                            episode_cards_path = default_cards
                        else:
                            logger.emit(
                                f"warning=episode_cards store mismatch, disabling episodes: {default_cards}"
                            )
                if episode_cards_path is not None and not episode_cards_path.exists():
                    logger.emit(f"warning=episode_cards path not found, disabling episodes: {episode_cards_path}")
                    episode_cards_path = None
            runtime = RuntimeSession(
                retriever=MemoryRetriever(store),
                verifier=ClaimVerifier(),
                continuity_store=continuity,
                enable_writeback=False,
                short_term_enabled=False,
                episode_cards_path=str(episode_cards_path) if episode_cards_path is not None else None,
                episode_top_k=max(1, int(args.episode_top_k)),
                episode_min_score=float(args.episode_min_score),
            )
            logger.emit(f"Runtime initialized with effective_cases={len(cases)}")
            logger.emit(f"episode_cards_enabled={bool(episode_cards_path)}")
            logger.emit(f"episode_cards_path={str(episode_cards_path) if episode_cards_path is not None else ''}")
            logger.emit("Generating truthset.")
            logger.emit(f"Running eval for {len(cases)} cases.")

            total_cases = len(cases)
            batch_size = max(0, int(args.batch_size))
            batch_size = min(batch_size, total_cases) if batch_size > 0 else 0
            batch_pause_ms = max(0, int(args.batch_pause_ms))
            if batch_size <= 0 and total_cases > 1 and plan.atoms >= _AUTO_CHUNK_ATOM_THRESHOLD:
                batch_size = min(4, total_cases)
                if batch_pause_ms <= 0:
                    batch_pause_ms = 100
                logger.emit(
                    f"auto_chunking enabled batch_size={batch_size} pause_ms={batch_pause_ms} "
                    f"(atoms={plan.atoms}, threshold={_AUTO_CHUNK_ATOM_THRESHOLD})"
                )

            records = []
            if batch_size > 0 and total_cases > batch_size:
                total_batches = (total_cases + batch_size - 1) // batch_size
                logger.emit(
                    f"chunking enabled batch_size={batch_size} batches={total_batches} pause_ms={batch_pause_ms}"
                )
                for batch_idx in range(total_batches):
                    start = batch_idx * batch_size
                    end = min(total_cases, start + batch_size)
                    batch_cases = cases[start:end]
                    logger.emit(
                        f"batch_start index={batch_idx + 1}/{total_batches} "
                        f"cases={len(batch_cases)} span={start + 1}-{end}"
                    )

                    def _progress(index: int, _total: int, record) -> None:
                        global_index = start + index
                        logger.emit(
                            "progress "
                            f"{global_index}/{total_cases} "
                            f"case={record.case_id} "
                            f"type={record.case_type} "
                            f"decision={record.actual_decision} "
                            f"latency_ms={record.latency_ms:.2f}"
                        )

                    _, batch_records = evaluate_truthset(
                        runtime,
                        batch_cases,
                        atoms=plan.atoms,
                        requested_cases=plan.requested_cases,
                        scan_budget=plan.scan_budget,
                        progress_cb=_progress,
                    )
                    records.extend(batch_records)

                    if args.write_partial_artifacts:
                        partial_records = out_dir / "records.partial.json"
                        partial_progress = out_dir / "progress.partial.json"
                        partial_records.write_text(
                            json.dumps([row.to_dict() for row in records], indent=2) + "\n",
                            encoding="utf-8",
                        )
                        partial_progress.write_text(
                            json.dumps(
                                {
                                    "generated_at": _now_iso(),
                                    "completed_cases": len(records),
                                    "total_cases": total_cases,
                                    "batch_index": batch_idx + 1,
                                    "batch_count": total_batches,
                                },
                                indent=2,
                            )
                            + "\n",
                            encoding="utf-8",
                        )

                    logger.emit(
                        f"batch_done index={batch_idx + 1}/{total_batches} completed_cases={len(records)}"
                    )
                    if batch_pause_ms > 0 and batch_idx + 1 < total_batches:
                        time.sleep(batch_pause_ms / 1000.0)
            else:
                if batch_size > 0:
                    logger.emit("chunking requested but not needed; running single batch.")

                def _progress(index: int, total: int, record) -> None:
                    logger.emit(
                        "progress "
                        f"{index}/{total} "
                        f"case={record.case_id} "
                        f"type={record.case_type} "
                        f"decision={record.actual_decision} "
                        f"latency_ms={record.latency_ms:.2f}"
                    )

                _, records = evaluate_truthset(
                    runtime,
                    cases,
                    atoms=plan.atoms,
                    requested_cases=plan.requested_cases,
                    scan_budget=plan.scan_budget,
                    progress_cb=_progress,
                )

            summary = summarize_live_eval_records(
                records=records,
                runtime=runtime,
                atoms=plan.atoms,
                requested_cases=plan.requested_cases,
                scan_budget=plan.scan_budget,
            )
            summary_json, summary_md, records_json = write_live_eval_artifacts(
                out_dir=out_dir,
                summary=summary,
                records=records,
            )
            logger.emit("Artifacts written successfully.")
            logger.emit(f"atoms={summary.atoms}")
            logger.emit(f"requested_cases={summary.requested_cases}")
            logger.emit(f"cases={summary.cases}")
            logger.emit(f"scan_budget={summary.scan_budget}")
            logger.emit(f"estimated_scans={summary.estimated_scans}")
            logger.emit(f"decision_accuracy={summary.decision_accuracy:.4f}")
            logger.emit(f"citation_hit_rate={summary.citation_hit_rate:.4f}")
            logger.emit(f"retrieval_hit_rate={summary.retrieval_hit_rate:.4f}")
            logger.emit(f"abstain_precision={summary.abstain_precision:.4f}")
            logger.emit(f"false_memory_rate={summary.false_memory_rate:.4f}")
            logger.emit(f"routine_over_recall_rate={summary.routine_over_recall_rate:.4f}")
            logger.emit(f"episode_hit_rate={summary.episode_hit_rate:.4f}")
            logger.emit(f"episode_false_recall_rate={summary.episode_false_recall_rate:.4f}")
            logger.emit(f"summary_json={summary_json}")
            logger.emit(f"summary_md={summary_md}")
            logger.emit(f"records_json={records_json}")
            logger.emit(f"truthset_generated_jsonl={generated_truthset_path}")
            logger.emit(f"truthset_case_counts_json={case_counts_path}")
            return 0
        finally:
            closer = getattr(store, "close", None)
            if callable(closer) and close_store:
                closer()
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
