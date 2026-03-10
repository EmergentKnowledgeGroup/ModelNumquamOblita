#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.memory import SqliteAtomStore
from engine.runtime import (
    generate_truthset,
    load_inmemory_store_from_json,
    write_truthset_jsonl,
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def _family_counts(cases: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in list(cases or []):
        family = str(getattr(case, "fixture_family", "") or getattr(case, "case_type", "") or "unknown").strip() or "unknown"
        counts[family] = counts.get(family, 0) + 1
    return counts


def _decision_counts(cases: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in list(cases or []):
        decision = str(getattr(case, "expected_decision", "") or "UNKNOWN").strip().upper() or "UNKNOWN"
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def _render_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Known-Truth Eval Pack",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- memories_path: `{summary['memories_path']}`",
        f"- fixture_mode: `{summary['fixture_mode']}`",
        f"- total_cases: `{summary['total_cases']}`",
        f"- output_jsonl: `{summary['output_jsonl']}`",
        "",
        "## Expected decision counts",
    ]
    for key, value in sorted((summary.get("decision_counts") or {}).items()):
        lines.append(f"- {key}: `{int(value)}`")
    lines.extend(["", "## Fixture family counts"])
    for key, value in sorted((summary.get("fixture_family_counts") or {}).items()):
        lines.append(f"- {key}: `{int(value)}`")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build known-truth eval pack from local memories.")
    parser.add_argument("--memories", default=str(_default_memory_path()), help="Path to sqlite store (.sqlite3/.db) or memories.json.")
    parser.add_argument("--out-dir", default="", help="Output directory for known-truth pack.")
    parser.add_argument("--cases", type=int, default=120, help="Total cases to generate.")
    parser.add_argument("--supported-ratio", type=float, default=0.67, help="Supported-case ratio.")
    parser.add_argument("--fixture-mode", choices=["basic", "trust-v2", "trust-v3"], default="trust-v3")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2

    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else REPO_ROOT / "runtime" / "truthset" / f"known_truth_{_stamp()}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    store, close_store = _open_store(memories_path)
    try:
        cases = generate_truthset(
            store,
            total_cases=max(1, int(args.cases)),
            supported_ratio=float(args.supported_ratio),
            fixture_mode=str(args.fixture_mode),
        )
    finally:
        if close_store:
            closer = getattr(store, "close", None)
            if callable(closer):
                closer()

    if not cases:
        print("error=no cases generated from memory store")
        return 2

    jsonl_path = out_dir / "truthset.known_truth.jsonl"
    write_truthset_jsonl(cases, jsonl_path)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "memories_path": str(memories_path),
        "fixture_mode": str(args.fixture_mode),
        "total_cases": len(cases),
        "output_jsonl": str(jsonl_path),
        "decision_counts": _decision_counts(cases),
        "fixture_family_counts": _family_counts(cases),
    }
    summary_json = out_dir / "known_truth_summary.json"
    summary_md = out_dir / "known_truth_summary.md"
    summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary_md.write_text(_render_md(summary), encoding="utf-8")

    print(f"truthset_jsonl={jsonl_path}")
    print(f"summary_json={summary_json}")
    print(f"summary_md={summary_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
