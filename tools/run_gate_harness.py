#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.runtime import (
    EvalRecord,
    evaluate_gate,
    load_failure_cases,
    must_pass_case_ids,
    write_gate_report,
)


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NumquamOblita acceptance gate harness.")
    parser.add_argument("--records", required=True, help="Path to eval records JSON array.")
    parser.add_argument(
        "--failure-results",
        required=True,
        help="Path to JSON object of failure case results, e.g. {\"FC-04\": true}.",
    )
    parser.add_argument(
        "--dataset-counts",
        required=True,
        help="Path to JSON object with dataset counts: gold, contradiction, adversarial, drift, recognition.",
    )
    parser.add_argument(
        "--failure-library",
        default="V3_FAILURE_CASE_LIBRARY.md",
        help="Path to failure case markdown library.",
    )
    parser.add_argument("--out-dir", default="runtime/reports", help="Output directory for gate report files.")
    args = parser.parse_args()

    records_payload = _read_json(args.records)
    if not isinstance(records_payload, list):
        raise TypeError("--records must be a JSON array")
    records = [EvalRecord.from_dict(item) for item in records_payload]
    case_results = _read_json(args.failure_results)
    if not isinstance(case_results, dict):
        raise TypeError("--failure-results must be a JSON object")
    dataset_counts = _read_json(args.dataset_counts)
    if not isinstance(dataset_counts, dict):
        raise TypeError("--dataset-counts must be a JSON object")

    _ = load_failure_cases(args.failure_library)
    must_pass = must_pass_case_ids(args.failure_library)
    outcome = evaluate_gate(
        records,
        dataset_counts={str(key): int(value) for key, value in dataset_counts.items()},
        failure_case_results={str(key): bool(value) for key, value in case_results.items()},
        must_pass_case_ids=must_pass,
    )
    json_path, md_path = write_gate_report(outcome, out_dir=args.out_dir)
    print(f"gate_decision={outcome.decision}")
    print(f"gate_report_json={json_path}")
    print(f"gate_report_md={md_path}")
    if outcome.decision == "FAIL":
        return 2
    if outcome.decision == "CONDITIONAL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
