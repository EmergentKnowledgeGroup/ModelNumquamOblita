#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.ingest.streaming_json import iter_json_array_objects


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a small fixture from a large conversations export.")
    parser.add_argument("--input", required=True, help="Path to conversations JSON export")
    parser.add_argument("--output", required=True, help="Path to fixture output JSON")
    parser.add_argument("--limit", type=int, default=5, help="Max conversations to include")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    limit = max(1, args.limit)
    rows = []
    for index, convo in enumerate(iter_json_array_objects(args.input), start=1):
        rows.append(convo)
        if index >= limit:
            break
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} conversations to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
