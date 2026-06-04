#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.ingest import run_sqlite_import_job, write_import_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Import memories from JSON, JSONL, transcript text, or mixed source folders into sqlite store.")
    parser.add_argument("--input", required=True, help="Path to source file or folder")
    parser.add_argument(
        "--store",
        default=str(REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3"),
        help="Path to sqlite memory store",
    )
    parser.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / ".runtime" / "imports"),
        help="Directory for import reports",
    )
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    report_json = out_dir / f"import_{ts}.json"
    report_md = out_dir / f"import_{ts}.md"

    report = run_sqlite_import_job(input_path=args.input, sqlite_path=args.store)
    write_import_report(report, json_path=report_json, md_path=report_md)

    print(f"report_json={report_json}")
    print(f"report_md={report_md}")
    if report.store_path:
        print(f"store_path={report.store_path}")
    if not report.ok:
        print(f"error_code={report.error_code}")
        print(f"error_message={report.error_message}")
        return 2

    print(f"persisted_add_or_update={report.counters.persisted_add_or_update}")
    print(f"proposals_created={report.counters.proposals_created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
