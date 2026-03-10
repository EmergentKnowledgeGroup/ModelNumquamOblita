#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _snippet(text: str, *, max_chars: int = 360) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _retrieval_diagnostics_summary(records: list[dict[str, Any]]) -> tuple[int, int, int, dict[str, int]]:
    cases_with_diagnostics = 0
    selected_total = 0
    dropped_total = 0
    reason_counts: dict[str, int] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        retrieval = row.get("retrieval") if isinstance(row.get("retrieval"), dict) else {}
        diagnostics = (
            retrieval.get("retrieval_diagnostics")
            if isinstance(retrieval.get("retrieval_diagnostics"), dict)
            else {}
        )
        selected_items = diagnostics.get("selected")
        dropped_items = diagnostics.get("dropped")
        reason_counts_payload = diagnostics.get("dropped_reason_counts")
        selected = [item for item in (selected_items if isinstance(selected_items, list) else []) if isinstance(item, dict)]
        dropped = [item for item in (dropped_items if isinstance(dropped_items, list) else []) if isinstance(item, dict)]
        if selected or dropped or isinstance(reason_counts_payload, dict):
            cases_with_diagnostics += 1
        selected_total += max(len(selected), _safe_int(diagnostics.get("selected_count"), default=len(selected)))
        dropped_total += max(len(dropped), _safe_int(diagnostics.get("dropped_count"), default=len(dropped)))
        for key, value in (reason_counts_payload.items() if isinstance(reason_counts_payload, dict) else []):
            reason = str(key or "").strip()
            if not reason:
                continue
            reason_counts[reason] = reason_counts.get(reason, 0) + max(0, _safe_int(value, default=0))
    return cases_with_diagnostics, selected_total, dropped_total, reason_counts


def _format_selected_audit(items: list[dict[str, Any]], *, max_items: int = 6) -> str:
    parts: list[str] = []
    for item in items[:max(1, int(max_items))]:
        atom_id = str(item.get("atom_id") or "").strip()
        section = str(item.get("section") or "").strip()
        if not atom_id or not section:
            continue
        score = _safe_float(item.get("score"), default=0.0)
        parts.append(f"{atom_id} [{section}, {score:.2f}]")
    return ", ".join(parts)


def _format_dropped_audit(items: list[dict[str, Any]], *, max_items: int = 6) -> str:
    parts: list[str] = []
    for item in items[:max(1, int(max_items))]:
        atom_id = str(item.get("atom_id") or "").strip()
        reason_code = str(item.get("reason_code") or "").strip()
        if not atom_id or not reason_code:
            continue
        if item.get("score") is None:
            parts.append(f"{atom_id} [{reason_code}]")
            continue
        score = _safe_float(item.get("score"), default=0.0)
        parts.append(f"{atom_id} [{reason_code}, {score:.2f}]")
    return ", ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a human_readout.md for responder eval records.")
    parser.add_argument("--records", required=True, help="Path to records.json emitted by run_responder_eval.py")
    parser.add_argument("--summary", required=True, help="Path to summary.json emitted by run_responder_eval.py")
    parser.add_argument("--acceptance-gate", default="", help="Optional path to acceptance_gate.json (dual verdict).")
    parser.add_argument("--question-quality-summary", default="", help="Optional path to question_validation_summary.json.")
    parser.add_argument("--out", default="", help="Output markdown path. Default: <records_dir>/human_readout.md")
    parser.add_argument("--max-cases", type=int, default=24)
    args = parser.parse_args()

    records_path = Path(args.records).expanduser().resolve()
    summary_path = Path(args.summary).expanduser().resolve()
    if not records_path.exists():
        print(f"error=records not found: {records_path}")
        return 2
    if not summary_path.exists():
        print(f"error=summary not found: {summary_path}")
        return 2

    out_path = Path(args.out).expanduser().resolve() if str(args.out).strip() else records_path.parent / "human_readout.md"

    records = _load_json(records_path)
    summary = _load_json(summary_path)
    if not isinstance(records, list):
        print("error=records must be an array")
        return 2
    if not isinstance(summary, dict):
        summary = {}

    defect_counts: dict[str, int] = {}
    blocking_defect_counts: dict[str, int] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        row_defects = [
            str(item).strip()
            for item in list(row.get("defect_tags") or [])
            if str(item).strip()
        ]
        if not row_defects:
            verification = row.get("verification")
            if isinstance(verification, dict):
                row_defects = [
                    f"verifier:{str(reason).strip()}"
                    for reason in list(verification.get("reasons") or [])
                    if str(reason).strip()
                ]
        for reason in row_defects:
            key = str(reason or "").strip() or "unknown"
            defect_counts[key] = defect_counts.get(key, 0) + 1
        for reason in list(row.get("blocking_defect_tags") or []):
            key = str(reason or "").strip() or "unknown"
            blocking_defect_counts[key] = blocking_defect_counts.get(key, 0) + 1

    lines: list[str] = []
    lines.append("# Responder Eval Readout")
    lines.append("")
    lines.append(f"- generated_at: `{_now_iso()}`")
    lines.append(f"- records: `{records_path}`")
    lines.append(f"- summary: `{summary_path}`")
    if str(args.acceptance_gate).strip():
        lines.append(f"- acceptance_gate: `{Path(args.acceptance_gate).expanduser().resolve()}`")
    if str(args.question_quality_summary).strip():
        lines.append(f"- question_quality_summary: `{Path(args.question_quality_summary).expanduser().resolve()}`")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    gate_payload: dict[str, Any] = {}
    if str(args.acceptance_gate).strip():
        try:
            gate_path = Path(args.acceptance_gate).expanduser().resolve()
            if gate_path.exists():
                gate_loaded = _load_json(gate_path)
                gate_payload = gate_loaded if isinstance(gate_loaded, dict) else {}
        except Exception:
            gate_payload = {}
    if gate_payload:
        lines.append(f"- safety_verdict: `{str(gate_payload.get('safety_verdict') or '').strip()}`")
        lines.append(f"- human_quality_verdict: `{str(gate_payload.get('human_quality_verdict') or '').strip()}`")
        lines.append(f"- decision: `{str(gate_payload.get('decision') or '').strip()}`")
        quality = gate_payload.get("quality") if isinstance(gate_payload.get("quality"), dict) else {}
        if quality:
            lines.append(f"- defect_case_count: `{int(quality.get('defect_case_count') or 0)}`")
            lines.append(f"- blocking_defect_cases: `{int(quality.get('blocking_defect_cases') or 0)}`")
    lines.append(f"- cases: `{int(summary.get('cases') or 0)}`")
    lines.append(f"- service_decision_accuracy: `{float(summary.get('service_decision_accuracy') or 0.0):.4f}`")
    lines.append(f"- model_verified_ok_rate: `{float(summary.get('model_verified_ok_rate') or 0.0):.4f}`")
    if "model_decision_accuracy" in summary:
        lines.append(f"- model_decision_accuracy: `{float(summary.get('model_decision_accuracy') or 0.0):.4f}`")
    latency = summary.get("latency_ms") if isinstance(summary.get("latency_ms"), dict) else {}
    lines.append(f"- memory_p95_ms: `{float(latency.get('memory_p95') or 0.0):.2f}`")
    lines.append(f"- model_p95_ms: `{float(latency.get('model_p95') or 0.0):.2f}`")
    lines.append(f"- total_p95_ms: `{float(latency.get('total_p95') or 0.0):.2f}`")
    lines.append("")

    if str(args.question_quality_summary).strip():
        try:
            qpath = Path(args.question_quality_summary).expanduser().resolve()
            if qpath.exists():
                qsum = _load_json(qpath)
                if isinstance(qsum, dict):
                    lines.append("## Question Quality")
                    lines.append("")
                    lines.append(f"- decision: `{str(qsum.get('decision') or '').strip()}`")
                    lines.append(f"- event_grade_question_rate: `{float(qsum.get('event_grade_question_rate') or 0.0):.4f}`")
                    lines.append(f"- fragment_question_rate: `{float(qsum.get('fragment_question_rate') or 0.0):.4f}`")
                    lines.append(f"- blocking_defect_cases: `{int(qsum.get('blocking_defect_cases') or 0)}`")
                    lines.append(f"- weak_cases: `{int(qsum.get('weak_cases') or 0)}`")
                    lines.append("")
        except Exception:
            pass

    lines.append("## Defects")
    lines.append("")
    if not defect_counts:
        lines.append("- none")
    else:
        for key in sorted(defect_counts, key=lambda k: defect_counts[k], reverse=True):
            lines.append(f"- `{key}`: `{defect_counts[key]}`")
    lines.append("")

    diag_cases, diag_selected_total, diag_dropped_total, diag_reason_counts = _retrieval_diagnostics_summary(records)
    lines.append("## Retrieval Diagnostics Summary")
    lines.append("")
    lines.append(f"- cases_with_diagnostics: `{diag_cases}`")
    lines.append(f"- selected_atoms_total: `{diag_selected_total}`")
    lines.append(f"- dropped_atoms_total: `{diag_dropped_total}`")
    if not diag_reason_counts:
        lines.append("- dropped_reason_counts: `none`")
    else:
        reason_summary = ", ".join(
            f"{key}={diag_reason_counts[key]}" for key in sorted(diag_reason_counts, key=diag_reason_counts.get, reverse=True)
        )
        lines.append(f"- dropped_reason_counts: `{reason_summary}`")
    lines.append("")

    lines.append("## Q/A Audit Table")
    lines.append("")
    lines.append("| Case | Type | Expected | Service | Verified | Defects |")
    lines.append("|---|---|---|---|---|---|")
    for row in records[: max(1, int(args.max_cases))]:
        if not isinstance(row, dict):
            continue
        case = row.get("case") if isinstance(row.get("case"), dict) else {}
        verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
        case_id = str(case.get("case_id") or "").strip() or "-"
        case_type = str(case.get("case_type") or "").strip() or "-"
        expected = str(case.get("expected_decision") or "").strip() or "-"
        service = str(row.get("service_decision") or "").strip() or "-"
        verified = "ok" if bool(verification.get("ok")) else "fail"
        defect_tags = [str(item).strip() for item in list(row.get("defect_tags") or []) if str(item).strip()]
        if not defect_tags:
            defect_tags = [str(item).strip() for item in list(verification.get("reasons") or []) if str(item).strip()]
        defects_text = ", ".join(defect_tags) if defect_tags else "none"
        lines.append(
            f"| `{case_id}` | `{case_type}` | `{expected}` | `{service}` | `{verified}` | `{_snippet(defects_text, max_chars=120)}` |"
        )
    lines.append("")

    if blocking_defect_counts:
        lines.append("## Blocking Defects")
        lines.append("")
        for key in sorted(blocking_defect_counts, key=lambda k: blocking_defect_counts[k], reverse=True):
            lines.append(f"- `{key}`: `{blocking_defect_counts[key]}`")
        lines.append("")

    top_examples: list[dict[str, Any]] = []
    if gate_payload:
        quality = gate_payload.get("quality") if isinstance(gate_payload.get("quality"), dict) else {}
        top_examples = [item for item in list(quality.get("top_failure_examples") or []) if isinstance(item, dict)]
    lines.append("## Top Failure Examples")
    lines.append("")
    if not top_examples:
        lines.append("- none")
    else:
        for item in top_examples[:5]:
            lines.append(f"- case_id: `{str(item.get('case_id') or '').strip()}`")
            lines.append(f"  - defects: `{', '.join(str(x) for x in list(item.get('defect_tags') or []) if str(x).strip())}`")
            lines.append(f"  - question: `{_snippet(str(item.get('question') or ''), max_chars=180)}`")
            lines.append(f"  - answer: `{_snippet(str(item.get('answer') or ''), max_chars=180)}`")
    lines.append("")

    lines.append("## Case Audit")
    lines.append("")
    shown = 0
    for row in records:
        if shown >= int(args.max_cases):
            break
        if not isinstance(row, dict):
            continue
        case = row.get("case") if isinstance(row.get("case"), dict) else {}
        verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
        lat = row.get("latency_ms") if isinstance(row.get("latency_ms"), dict) else {}
        evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        retrieval = row.get("retrieval") if isinstance(row.get("retrieval"), dict) else {}
        diagnostics = (
            retrieval.get("retrieval_diagnostics")
            if isinstance(retrieval.get("retrieval_diagnostics"), dict)
            else {}
        )
        selected_payload = diagnostics.get("selected")
        dropped_payload = diagnostics.get("dropped")
        selected_audit = [
            item
            for item in (selected_payload if isinstance(selected_payload, list) else [])
            if isinstance(item, dict)
        ]
        dropped_audit = [
            item
            for item in (dropped_payload if isinstance(dropped_payload, list) else [])
            if isinstance(item, dict)
        ]

        case_id = str(case.get("case_id") or "").strip() or f"case_{shown}"
        lines.append(f"### {case_id}")
        lines.append("")
        lines.append(f"- fixture: `{str(case.get('fixture_family') or '').strip()}`")
        lines.append(f"- case_type: `{str(case.get('case_type') or '').strip()}`")
        lines.append(f"- expected_decision: `{str(case.get('expected_decision') or '').strip()}`")
        lines.append(f"- service_decision: `{str(row.get('service_decision') or '').strip()}`")
        lines.append(f"- verified_ok: `{bool(verification.get('ok'))}`")
        lines.append(f"- memory_ms: `{float(lat.get('memory_ms') or 0.0):.2f}`")
        lines.append(f"- model_ms: `{float(lat.get('model_ms') or 0.0):.2f}`")
        lines.append(f"- total_ms: `{float(lat.get('total_ms') or 0.0):.2f}`")
        reasons = ", ".join(str(item) for item in list(verification.get("reasons") or []) if str(item).strip())
        if reasons:
            lines.append(f"- defects: `{reasons}`")
        defect_tags = ", ".join(str(item) for item in list(row.get("defect_tags") or []) if str(item).strip())
        if defect_tags:
            lines.append(f"- defect_tags: `{defect_tags}`")
        blocking_tags = ", ".join(str(item) for item in list(row.get("blocking_defect_tags") or []) if str(item).strip())
        if blocking_tags:
            lines.append(f"- blocking_defect_tags: `{blocking_tags}`")
        lines.append("")

        lines.append("Retrieval Audit:")
        lines.append("")
        if selected_audit:
            lines.append(f"- selected_evidence: `{_format_selected_audit(selected_audit)}`")
        else:
            lines.append("- selected_evidence: `(none)`")
        reason_counts_payload = diagnostics.get("dropped_reason_counts")
        reason_counts = reason_counts_payload if isinstance(reason_counts_payload, dict) else {}
        if reason_counts:
            sanitized_reason_counts = {
                str(key).strip(): max(0, _safe_int(value, default=0))
                for key, value in reason_counts.items()
                if str(key).strip()
            }
            reason_summary = ", ".join(
                f"{key}={sanitized_reason_counts[key]}"
                for key in sorted(sanitized_reason_counts, key=sanitized_reason_counts.get, reverse=True)
            )
            lines.append(f"- dropped_reason_counts: `{reason_summary}`")
        else:
            lines.append("- dropped_reason_counts: `none`")
        if dropped_audit:
            lines.append(f"- dropped_examples: `{_format_dropped_audit(dropped_audit)}`")
        else:
            lines.append("- dropped_examples: `(none)`")
        lines.append("")

        lines.append("Question:")
        lines.append("")
        lines.append("```text")
        lines.append(str(case.get("query") or "").strip())
        lines.append("```")
        lines.append("")

        lines.append("Top Evidence:")
        lines.append("")
        if not evidence:
            lines.append("- (none)")
        else:
            for item in evidence[:4]:
                if not isinstance(item, dict):
                    continue
                summary = _snippet(str(item.get("summary") or ""), max_chars=220)
                citations = ", ".join(str(c) for c in list(item.get("citations") or []) if str(c).strip())
                role_hint = str(item.get("role_hint") or "").strip()
                kind = str(item.get("kind") or "").strip()
                lines.append(f"- ({kind or 'evidence'} / {role_hint or 'unknown'}) {summary}")
                if citations:
                    lines.append(f"  sources: `{citations}`")
        lines.append("")

        lines.append("Model Reply:")
        lines.append("")
        lines.append("```text")
        lines.append(_snippet(str(row.get('reply_text') or ''), max_chars=900))
        lines.append("```")
        lines.append("")

        shown += 1

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"human_readout_md={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
