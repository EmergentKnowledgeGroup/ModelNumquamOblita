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

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.memory import SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, TruthsetCase, load_inmemory_store_from_json, load_truthset_jsonl


def _open_store(path: Path) -> tuple[Any, bool]:
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), False
    raise ValueError(f"unsupported memories path: {path}")


def _load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("records.json must contain an array")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snippet(text: str, *, max_chars: int = 260) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def _atom_snapshot(store: Any, atom_id: str) -> dict[str, Any]:
    atom = store.get_atom(atom_id)
    if atom is None:
        return {"atom_id": atom_id, "missing": True}
    source_ids = sorted(
        {
            str(ref.source_id).strip()
            for ref in list(getattr(atom, "source_refs", []) or [])
            if str(getattr(ref, "source_id", "")).strip()
        }
    )
    return {
        "atom_id": str(atom.atom_id),
        "text": _snippet(str(atom.canonical_text)),
        "source_ids": source_ids,
    }


def _record_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in records:
        case_id = str(row.get("case_id") or "").strip()
        if case_id:
            mapped[case_id] = row
    return mapped


def _summary_metrics(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    keys = (
        "cases",
        "decision_accuracy",
        "citation_hit_rate",
        "retrieval_hit_rate",
        "false_memory_rate",
        "over_recall_rate",
        "avg_latency_ms",
        "p95_latency_ms",
        "total_cost_usd",
        "total_tokens",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _to_json_block(payload: Any) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"


def _estimate_context_tokens(trace_payload: dict[str, Any]) -> int:
    cards = list(trace_payload.get("memory_cards") or [])
    citations = list(trace_payload.get("citations") or [])
    card_text = " ".join(str(item.get("summary") or "") for item in cards if isinstance(item, dict))
    citation_text = " ".join(str(item or "") for item in citations)
    rough = card_text + " " + citation_text
    return max(0, len(str(rough).split()))


def _compact_cards(cards: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for card in cards[: max(1, int(limit))]:
        if not isinstance(card, dict):
            continue
        out.append(
            {
                "card_id": card.get("card_id"),
                "kind": card.get("kind"),
                "summary": _snippet(str(card.get("summary") or ""), max_chars=180),
                "confidence": card.get("confidence"),
                "citation_count": len(list(card.get("citations") or [])),
                "top_citation": (list(card.get("citations") or []) or [""])[0],
            }
        )
    return out


def _format_case_section(
    *,
    case: TruthsetCase,
    row: dict[str, Any] | None,
    trace_payload: dict[str, Any],
    expected_atoms: list[dict[str, Any]],
    retrieved_atoms: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    lines.append(f"## Case {case.case_id}")
    lines.append("")
    lines.append(f"- fixture: `{case.fixture_family}`")
    lines.append(f"- case_type: `{case.case_type}`")
    lines.append(f"- expected_decision: `{case.expected_decision}`")
    lines.append(f"- actual_decision: `{str(trace_payload.get('decision') or '').upper()}`")
    if row is not None:
        lines.append(f"- decision_correct (eval record): `{bool(row.get('decision_correct'))}`")
        lines.append(f"- latency_ms (eval record): `{float(row.get('latency_ms') or 0.0):.2f}`")
    lines.append("")
    lines.append("### Question")
    lines.append("")
    lines.append("```text")
    lines.append(str(case.query))
    lines.append("```")
    lines.append("")
    lines.append("### Memory Seed (Expected Atoms)")
    lines.append("")
    lines.append(_to_json_block(expected_atoms))
    lines.append("")
    lines.append("### Script Response")
    lines.append("")
    lines.append("```text")
    lines.append(str(trace_payload.get("response_text") or "").strip())
    lines.append("```")
    lines.append("")
    lines.append("### Recall Route (Script Judgment)")
    lines.append("")
    route_payload = {
        "memory_route": trace_payload.get("memory_route"),
        "memory_mode": trace_payload.get("memory_mode"),
        "route_reason": trace_payload.get("route_reason"),
        "route_reason_text": trace_payload.get("route_reason_text"),
        "retrieval_passes": trace_payload.get("retrieval_passes"),
        "retrieval_stop_reason": trace_payload.get("retrieval_stop_reason"),
        "retrieval_query_tokens": trace_payload.get("retrieval_query_tokens"),
    }
    lines.append(_to_json_block(route_payload))
    lines.append("")
    lines.append("### Speed + Cost")
    lines.append("")
    telemetry = trace_payload.get("telemetry") if isinstance(trace_payload.get("telemetry"), dict) else {}
    speed_payload = {
        "retrieval_ms": telemetry.get("retrieval_ms"),
        "verifier_ms": telemetry.get("verifier_ms"),
        "total_ms": telemetry.get("total_ms"),
        "input_tokens": telemetry.get("input_tokens"),
        "output_tokens": telemetry.get("output_tokens"),
        "turn_cost_usd": telemetry.get("turn_cost_usd"),
        "model_context_token_estimate": _estimate_context_tokens(trace_payload),
    }
    lines.append(_to_json_block(speed_payload))
    lines.append("")
    lines.append("### Context Sent To Model")
    lines.append("")
    cards_full = list(trace_payload.get("memory_cards") or [])
    citations_full = list(trace_payload.get("citations") or [])
    retrieved_full = list(trace_payload.get("retrieved_atom_ids") or [])
    context_payload = {
        "memory_route": trace_payload.get("memory_route"),
        "memory_mode": trace_payload.get("memory_mode"),
        "route_reason": trace_payload.get("route_reason"),
        "route_reason_text": trace_payload.get("route_reason_text"),
        "retrieval_passes": trace_payload.get("retrieval_passes"),
        "retrieval_stop_reason": trace_payload.get("retrieval_stop_reason"),
        "retrieval_query_tokens": trace_payload.get("retrieval_query_tokens"),
        "short_term_hits": trace_payload.get("short_term_hits"),
        "memory_cards_compact": _compact_cards(cards_full, limit=3),
        "citations_compact": citations_full[:8],
        "retrieved_atom_ids_compact": retrieved_full[:8],
        "counts": {
            "memory_cards": len(cards_full),
            "citations": len(citations_full),
            "retrieved_atom_ids": len(retrieved_full),
        },
    }
    lines.append(_to_json_block(context_payload))
    lines.append("")
    lines.append("### Memory Cards Chosen")
    lines.append("")
    lines.append(_to_json_block(trace_payload.get("memory_cards") or []))
    lines.append("")
    lines.append("### Retrieved Memory Atoms")
    lines.append("")
    lines.append(_to_json_block(retrieved_atoms))
    lines.append("")
    if row is not None:
        record_payload = {
            "expected_decision": row.get("expected_decision"),
            "actual_decision": row.get("actual_decision"),
            "decision_correct": row.get("decision_correct"),
            "citation_hit": row.get("citation_hit"),
            "retrieval_hit": row.get("retrieval_hit"),
            "false_memory": row.get("false_memory"),
            "over_recall": row.get("over_recall"),
            "latency_ms": row.get("latency_ms"),
            "memory_mode": row.get("memory_mode"),
            "expected_memory_mode": row.get("expected_memory_mode"),
            "memory_mode_match": row.get("memory_mode_match"),
            "citations": row.get("citations"),
            "retrieved_atom_ids": row.get("retrieved_atom_ids"),
        }
        lines.append("### Eval Record")
        lines.append("")
        lines.append(_to_json_block(record_payload))
        lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a human-readable eval readout (memory -> question -> response -> context)."
    )
    parser.add_argument("--memories", required=True, help="Path to memory store (.sqlite3/.db/.json).")
    parser.add_argument("--truthset", required=True, help="Path to truthset jsonl used for eval.")
    parser.add_argument("--records", required=True, help="Path to eval records.json.")
    parser.add_argument("--summary", default="", help="Optional path to eval summary.json.")
    parser.add_argument("--out", default="", help="Output markdown path. Default: <records_dir>/human_readout.md")
    parser.add_argument("--max-cases", type=int, default=12, help="Max cases to render (0 = all).")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    truthset_path = Path(args.truthset).expanduser().resolve()
    records_path = Path(args.records).expanduser().resolve()
    summary_path = Path(args.summary).expanduser().resolve() if args.summary else None
    out_path = (
        Path(args.out).expanduser().resolve()
        if args.out
        else records_path.parent / "human_readout.md"
    )
    max_cases = max(0, int(args.max_cases))

    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2
    if not truthset_path.exists():
        print(f"error=truthset path not found: {truthset_path}")
        return 2
    if not records_path.exists():
        print(f"error=records path not found: {records_path}")
        return 2

    cases = load_truthset_jsonl(truthset_path)
    if max_cases > 0:
        cases = cases[:max_cases]
    records = _load_records(records_path)
    records_by_case = _record_map(records)
    metrics = _summary_metrics(summary_path)

    store, close_store = _open_store(memories_path)
    try:
        continuity = ContinuityStore()
        shared_language_keys = (
            store.list_shared_language_keys() if hasattr(store, "list_shared_language_keys") else []
        )
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

        lines: list[str] = []
        lines.append("# Human Eval Readout")
        lines.append("")
        lines.append(f"- generated_at: `{_now_iso()}`")
        lines.append(f"- memories: `{memories_path}`")
        lines.append(f"- truthset: `{truthset_path}`")
        lines.append(f"- records: `{records_path}`")
        lines.append(f"- rendered_cases: `{len(cases)}`")
        if metrics:
            lines.append("")
            lines.append("## Eval Summary")
            lines.append("")
            for key in (
                "cases",
                "decision_accuracy",
                "citation_hit_rate",
                "retrieval_hit_rate",
                "false_memory_rate",
                "over_recall_rate",
                "avg_latency_ms",
                "p95_latency_ms",
                "total_cost_usd",
                "total_tokens",
            ):
                if key in metrics:
                    lines.append(f"- {key}: `{metrics[key]}`")

        for case in cases:
            row = records_by_case.get(case.case_id)
            trace = runtime.handle_turn(
                case.query,
                high_risk=case.high_risk,
                retrieval_query=case.retrieval_query,
                retrieval_override=case.build_retrieval_override(
                    invoker="tools.build_human_eval_readout",
                    scope="human_eval_readout",
                ),
            )
            trace_payload = runtime.trace_to_dict(trace)
            expected_atoms = [_atom_snapshot(store, atom_id) for atom_id in list(case.expected_atom_ids or [])[:5]]
            retrieved_atoms = [
                _atom_snapshot(store, atom_id) for atom_id in list(trace.retrieved_atom_ids or [])[:8]
            ]
            lines.extend(
                _format_case_section(
                    case=case,
                    row=row,
                    trace_payload=trace_payload,
                    expected_atoms=expected_atoms,
                    retrieved_atoms=retrieved_atoms,
                )
            )
    finally:
        closer = getattr(store, "close", None)
        if callable(closer) and close_store:
            closer()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"human_readout_md={out_path}")
    print(f"rendered_cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
