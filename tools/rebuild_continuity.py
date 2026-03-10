#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.config import default_config
from engine.continuity import ContinuityBuilder, ContinuityStore, Consolidator, SharedLanguageRegistry
from engine.memory import AtomStore, SqliteAtomStore


def _build_store(backend: str, sqlite_path: Path) -> AtomStore | SqliteAtomStore:
    kind = backend.strip().lower()
    if kind == "sqlite":
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return SqliteAtomStore(sqlite_path)
    if kind == "inmemory":
        return AtomStore()
    raise ValueError(f"unsupported backend: {backend}")


def _render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Continuity Rebuild Report",
        "",
        f"- Timestamp: `{payload['timestamp']}`",
        f"- Store backend: `{payload['store_backend']}`",
        f"- Atoms before: `{payload['atom_count_before']}`",
        f"- Atoms after: `{payload['atom_count_after']}`",
        f"- Shared-language keys: `{payload['shared_language_keys']}`",
        f"- Decayed atoms: `{payload['decayed_atoms']}`",
        f"- Archived atoms: `{payload['archived_atoms']}`",
        f"- Promoted candidates: `{payload['promoted_candidates']}`",
        f"- Applied promotions: `{payload['applied_promotions']}`",
        f"- Snapshot revision: `{payload['snapshot_revision']}`",
        "",
        "## Snapshot Stats",
        "",
    ]
    stats = payload.get("snapshot_stats")
    if isinstance(stats, dict) and stats:
        for key in sorted(stats):
            lines.append(f"- `{key}`: `{stats[key]}`")
    else:
        lines.append("- `(none)`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild continuity snapshot and optional promotions from current atoms.")
    parser.add_argument("--store-backend", choices=["sqlite", "inmemory"], default="sqlite")
    parser.add_argument(
        "--sqlite-path",
        default=str(REPO_ROOT / ".runtime" / "demo" / "atoms.sqlite3"),
        help="Path used when --store-backend=sqlite.",
    )
    parser.add_argument("--apply-promotions", action="store_true", help="Persist promoted semantic candidates.")
    parser.add_argument("--output", default="", help="Output JSON path. Defaults to runtime/continuity/rebuild_<timestamp>.json")
    args = parser.parse_args()

    as_of = datetime.now(timezone.utc)
    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    store = _build_store(args.store_backend, sqlite_path)
    try:
        atom_count_before = len(store.list_atoms())
        registry = SharedLanguageRegistry(store)
        shared_keys = registry.list_keys()

        continuity_store = ContinuityStore()
        consolidator = Consolidator(store, policy=default_config().decay)
        summary = consolidator.run_with_snapshot(
            continuity_store,
            builder=ContinuityBuilder(),
            now=as_of,
            shared_language_keys=shared_keys,
            apply_promotions=args.apply_promotions,
        )

        atom_count_after = len(store.list_atoms())
        stamp = as_of.strftime("%Y%m%d_%H%M%S")
        out_json = Path(args.output).expanduser().resolve() if args.output else REPO_ROOT / "runtime" / "continuity" / f"rebuild_{stamp}.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md = out_json.with_suffix(".md")

        payload: dict[str, object] = {
            "timestamp": as_of.isoformat(),
            "store_backend": args.store_backend,
            "sqlite_path": str(sqlite_path) if args.store_backend == "sqlite" else None,
            "atom_count_before": atom_count_before,
            "atom_count_after": atom_count_after,
            "shared_language_keys": len(shared_keys),
            "decayed_atoms": summary.decayed_atoms,
            "archived_atoms": summary.archived_atoms,
            "promoted_candidates": len(summary.promoted_candidates),
            "applied_promotions": summary.applied_promotions,
            "snapshot_revision": summary.snapshot_revision,
            "snapshot_stats": summary.snapshot_stats,
        }
        out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        out_md.write_text(_render_markdown(payload), encoding="utf-8", newline="\n")
        print(json.dumps({"ok": True, "report_json": str(out_json), "report_md": str(out_md), **payload}, ensure_ascii=False))
        return 0
    finally:
        closer = getattr(store, "close", None)
        if callable(closer):
            closer()


if __name__ == "__main__":
    raise SystemExit(main())
