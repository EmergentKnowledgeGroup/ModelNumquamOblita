#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.runtime.drift import compare_eval_summaries, load_summary, write_drift_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two eval summaries and emit drift report.")
    parser.add_argument("--baseline", required=True, help="Path to baseline summary.json")
    parser.add_argument("--candidate", required=True, help="Path to candidate summary.json")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "runtime" / "evals" / "drift"), help="Output directory")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero if regressions are detected")
    args = parser.parse_args()

    baseline_path = Path(args.baseline).expanduser().resolve()
    candidate_path = Path(args.candidate).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    baseline = load_summary(baseline_path)
    candidate = load_summary(candidate_path)
    report = compare_eval_summaries(baseline=baseline, candidate=candidate)
    json_path, md_path = write_drift_report(
        out_dir=out_dir,
        report=report,
        baseline_path=baseline_path,
        candidate_path=candidate_path,
    )

    print(f"decision={report.decision}")
    print(f"regressions={','.join(report.regressions) if report.regressions else 'none'}")
    print(f"report_json={json_path}")
    print(f"report_md={md_path}")

    if args.fail_on_regression and report.decision != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
