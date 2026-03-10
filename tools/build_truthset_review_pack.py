#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.memory import SqliteAtomStore
from engine.runtime import TruthsetCase, generate_truthset, load_inmemory_store_from_json, write_truthset_jsonl


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


def _write_review_tsv(path: Path, cases: list[TruthsetCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp, delimiter="\t")
        writer.writerow(
            [
                "case_id",
                "status",
                "case_type",
                "fixture_family",
                "query",
                "retrieval_query",
                "expected_decision",
                "expected_citations_csv",
                "expected_atom_ids_csv",
                "high_risk",
                "review_note",
            ]
        )
        for case in cases:
            writer.writerow(
                [
                    case.case_id,
                    "PENDING",
                    case.case_type,
                    case.fixture_family,
                    case.query,
                    case.retrieval_query or "",
                    case.expected_decision,
                    ",".join(case.expected_citations),
                    ",".join(case.expected_atom_ids),
                    "true" if case.high_risk else "false",
                    "",
                ]
            )


def _write_review_guide(path: Path, *, case_count: int, source_path: Path, truthset_path: Path, review_tsv_path: Path) -> None:
    lines = [
        "# Truthset Review Pack",
        "",
        f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`",
        f"- source_memories: `{source_path}`",
        f"- candidate_cases: `{case_count}`",
        f"- candidate_truthset: `{truthset_path}`",
        f"- review_sheet: `{review_tsv_path}`",
        "",
        "## Review instructions",
        "1. Open the TSV in spreadsheet software.",
        "2. For each row, set `status` to `ACCEPT` or `REJECT`.",
        "3. Correct `expected_decision`/citations/atom ids where needed.",
        "4. Save as tab-separated UTF-8 TSV.",
        "",
        "## Compile reviewed truthset",
        "- `python3 tools/build_truthset_review_pack.py --compile-reviewed <review.tsv> --out-dir <dir>`",
        "- output: `truthset.reviewed.jsonl` (accepted rows only)",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _parse_csv_list(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _compile_reviewed_tsv(review_tsv: Path) -> list[TruthsetCase]:
    rows: list[TruthsetCase] = []
    with review_tsv.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp, delimiter="\t")
        for line_no, row in enumerate(reader, start=2):
            status = str(row.get("status") or "").strip().upper()
            if status not in {"ACCEPT", "REJECT"}:
                raise ValueError(f"review row {line_no}: invalid status={status!r}; expected ACCEPT or REJECT")
            if status != "ACCEPT":
                continue
            case_id = str(row.get("case_id") or "").strip()
            if not case_id:
                raise ValueError(f"review row {line_no}: missing case_id")
            case_type = str(row.get("case_type") or "supported_recall").strip()
            fixture_family = str(row.get("fixture_family") or case_type or "supported_recall").strip() or "supported_recall"
            query = str(row.get("query") or "").strip()
            if not query:
                raise ValueError(f"review row {line_no}: missing query")
            expected_decision = str(row.get("expected_decision") or "").strip().upper()
            if expected_decision not in {"PASS", "CLARIFY", "ABSTAIN"}:
                raise ValueError(f"review row {line_no}: invalid expected_decision={expected_decision!r}")
            retrieval_query = str(row.get("retrieval_query") or "").strip() or None
            citations = _parse_csv_list(str(row.get("expected_citations_csv") or ""))
            atom_ids = _parse_csv_list(str(row.get("expected_atom_ids_csv") or ""))
            high_risk = str(row.get("high_risk") or "").strip().lower() in {"1", "true", "yes", "y"}
            rows.append(
                TruthsetCase(
                    case_id=case_id,
                    case_type=case_type,
                    fixture_family=fixture_family,
                    query=query,
                    expected_decision=expected_decision,
                    expected_citations=citations,
                    expected_atom_ids=atom_ids,
                    retrieval_query=retrieval_query,
                    high_risk=high_risk,
                )
            )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and compile human-review truthset packs.")
    parser.add_argument("--memories", default=str(_default_memory_path()), help="Path to sqlite store or memories.json")
    parser.add_argument("--out-dir", default="", help="Output directory")
    parser.add_argument("--total-cases", type=int, default=120, help="Total candidate cases to generate")
    parser.add_argument("--supported-ratio", type=float, default=0.67, help="Supported case ratio")
    parser.add_argument(
        "--compile-reviewed",
        default="",
        help="Compile accepted rows from a reviewed TSV instead of generating a new pack",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.out_dir:
        out_dir = Path(args.out_dir).expanduser().resolve()
    else:
        out_dir = REPO_ROOT / "runtime" / "truthset" / f"review_pack_{_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.compile_reviewed:
        review_tsv = Path(args.compile_reviewed).expanduser().resolve()
        if not review_tsv.exists():
            print(f"error=review tsv not found: {review_tsv}")
            return 2
        cases = _compile_reviewed_tsv(review_tsv)
        if not cases:
            print("error=no accepted rows found in reviewed TSV")
            return 2
        output_path = out_dir / "truthset.reviewed.jsonl"
        write_truthset_jsonl(cases, output_path)
        print(f"reviewed_cases={len(cases)}")
        print(f"truthset_jsonl={output_path}")
        return 0

    memories_path = Path(args.memories).expanduser().resolve()
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2

    store, close_store = _open_store(memories_path)
    try:
        cases = generate_truthset(
            store,
            total_cases=max(1, int(args.total_cases)),
            supported_ratio=float(args.supported_ratio),
        )
    finally:
        closer = getattr(store, "close", None)
        if callable(closer) and close_store:
            closer()

    if not cases:
        print("error=no candidate truthset cases generated")
        return 2

    truthset_path = out_dir / "truthset.candidates.jsonl"
    review_tsv_path = out_dir / "truthset.review.tsv"
    guide_path = out_dir / "truthset.review.md"
    write_truthset_jsonl(cases, truthset_path)
    _write_review_tsv(review_tsv_path, cases)
    _write_review_guide(
        guide_path,
        case_count=len(cases),
        source_path=memories_path,
        truthset_path=truthset_path,
        review_tsv_path=review_tsv_path,
    )
    print(f"candidate_cases={len(cases)}")
    print(f"truthset_jsonl={truthset_path}")
    print(f"review_tsv={review_tsv_path}")
    print(f"review_guide={guide_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
