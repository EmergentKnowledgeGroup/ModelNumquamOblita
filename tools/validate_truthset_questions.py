#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.memory import SqliteAtomStore
from engine.runtime.live_eval import TruthsetCase, load_inmemory_store_from_json, load_truthset_jsonl

_GENERIC = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "about",
    "what",
    "when",
    "where",
    "there",
    "your",
    "just",
    "like",
    "have",
    "will",
    "into",
    "after",
    "before",
    "would",
    "could",
    "should",
    "been",
    "were",
    "they",
    "them",
    "then",
    "than",
    "also",
    "some",
    "more",
    "only",
    "over",
    "under",
}
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_LOW_INFO_ACK_RE = re.compile(
    r"^(?:ok(?:ay)?|yes|yeah|yep|yup|sure|thanks?|thank you|please|done|noted|copy|cool|lol|haha|hahaha|go ahead|sounds good)(?:[\s,.!?:;'\"-]+(?:ok(?:ay)?|yes|yeah|yep|yup|sure|thanks?|thank you|please|done|noted|copy|cool|lol|haha|hahaha|go ahead|sounds good))*$",
    re.IGNORECASE,
)
_NOISY_DOMAIN_CUE_RE = re.compile(r"\b(?:general|identity|training|prompting|continuity|memory|system|technical)\b", re.IGNORECASE)
_AUXILIARY_TOKENS = {
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "can",
    "could",
    "should",
    "would",
    "will",
    "might",
    "may",
    "must",
}
_VERB_HINTS = {
    "said",
    "did",
    "happened",
    "started",
    "ended",
    "shared",
    "asked",
    "told",
    "confirmed",
    "reviewed",
    "planned",
    "changed",
    "moved",
    "fixed",
}
_ROUTINE_INSTRUCTION_RE = re.compile(
    r"\b(?:no\s+recall|required|memory\s+(?:lookup|pull)|keep\s+it\s+conversational|instruction|test[- ]?probe)\b",
    re.IGNORECASE,
)
_STACKED_TEMPORAL_RE = re.compile(
    r"(what happened next[^?]*(right before|right after|before and after))|((right before|right after)\s+(how|what|why|when|where|who)\b)",
    re.IGNORECASE,
)
_CORRECTION_OPTIONS_RE = re.compile(
    r"\b(?:was it|did (?:they|we|you|he|she) say)\s+(.+?)\s+or\s+(.+?)(?:\?|$)",
    re.IGNORECASE,
)

_BLOCKING_DEFECT_TAGS = {
    "malformed_when_clause",
    "clipped_correction_options",
    "stacked_temporal_phrasing",
    "instruction_like_routine_probe",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ratio(numerator: float, denominator: float) -> float:
    if float(denominator) <= 0.0:
        return 0.0
    return float(numerator) / float(denominator)


def _meaningful_tokens(text: str) -> list[str]:
    tokens = [token.lower() for token in _WORD_RE.findall(str(text or ""))]
    return [token for token in tokens if len(token) >= 4 and token not in _GENERIC]


def _looks_payload_like(text: str) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return True
    if value.startswith("{") or value.startswith("["):
        return True
    if "pattern" in value and "replacement" in value and "updates" in value:
        return True
    if value.startswith("http://") or value.startswith("https://"):
        return True
    return False


def _open_store(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), False
    raise ValueError(f"Unsupported memories path: {path}")


def _atom_text_map(store) -> dict[str, str]:
    return {str(atom.atom_id): str(atom.canonical_text or "") for atom in store.list_atoms()}


def _unquoted_when_tail(query_text: str) -> str:
    query = str(query_text or "")
    if not query:
        return ""
    lowered = query.lower()
    in_quote = False
    for idx, ch in enumerate(query):
        if ch in {'"', "“", "”"}:
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if lowered.startswith("when", idx):
            prev = lowered[idx - 1] if idx > 0 else " "
            nxt = lowered[idx + 4] if (idx + 4) < len(lowered) else " "
            if prev.isalnum() or nxt.isalnum():
                continue
            return str(query[idx + 4 :])
    return ""


def _contains_malformed_when_clause(query_text: str) -> bool:
    query = str(query_text or "").strip()
    if not query:
        return False
    tail = _unquoted_when_tail(query)
    if not tail:
        return False
    tail = str(tail or "").strip(" ?!.:,;")
    if not tail:
        return True
    tokens = [token.lower() for token in _WORD_RE.findall(tail)]
    if not tokens:
        return True
    verb_present = any(token in _AUXILIARY_TOKENS or token in _VERB_HINTS for token in tokens)
    if verb_present:
        return False
    return len(tokens) <= 6


def _contains_clipped_correction_options(query_text: str) -> bool:
    query = str(query_text or "").strip()
    if not query:
        return False
    match = _CORRECTION_OPTIONS_RE.search(query)
    if match is None:
        return False
    left = str(match.group(1) or "").strip(" \"'`.,;:!?")
    right = str(match.group(2) or "").strip(" \"'`.,;:!?")
    left_words = _WORD_RE.findall(left)
    right_words = _WORD_RE.findall(right)
    if not left_words or not right_words:
        return True
    return (len(left_words) <= 2 or len(right_words) <= 2)


def _contains_instruction_like_routine_probe(query_text: str) -> bool:
    return bool(_ROUTINE_INSTRUCTION_RE.search(str(query_text or "")))


def _evaluate_case(case: TruthsetCase, atom_map: dict[str, str]) -> dict[str, Any]:
    query_text = str(case.query or "").strip()
    retrieval_query = str(case.retrieval_query or "").strip()
    case_type = str(case.case_type or "").strip()
    defect_tags: list[str] = []
    words = _WORD_RE.findall(retrieval_query)
    meaningful = _meaningful_tokens(retrieval_query)

    if _contains_malformed_when_clause(query_text):
        defect_tags.append("malformed_when_clause")
    if _contains_clipped_correction_options(query_text):
        defect_tags.append("clipped_correction_options")
    if _STACKED_TEMPORAL_RE.search(query_text):
        defect_tags.append("stacked_temporal_phrasing")
    if case_type == "routine_chat" and _contains_instruction_like_routine_probe(query_text):
        defect_tags.append("instruction_like_routine_probe")

    if case_type != "routine_chat":
        if not retrieval_query:
            defect_tags.append("missing_retrieval_query")
        if len(words) < 6:
            defect_tags.append("too_short")
        if len(meaningful) < 3:
            defect_tags.append("low_signal_terms")
        if len(meaningful) / max(len(words), 1) < 0.25:
            defect_tags.append("low_signal_density")
        if _LOW_INFO_ACK_RE.match(retrieval_query):
            defect_tags.append("low_information_phrase")
        if _looks_payload_like(retrieval_query):
            defect_tags.append("payload_like")
    if _NOISY_DOMAIN_CUE_RE.search(query_text) and "what do you remember about" in query_text.lower():
        defect_tags.append("meta_jargon_replay")
    query_words = _WORD_RE.findall(query_text)
    if len(query_words) < 5:
        defect_tags.append("query_too_short")
    if len(query_words) > 28:
        defect_tags.append("query_too_long")

    expected_ids = [str(item).strip() for item in list(case.expected_atom_ids or []) if str(item).strip()]
    overlap = 0
    atom_word_count = 0
    if expected_ids and meaningful:
        best = 0
        for atom_id in expected_ids:
            atom_text = str(atom_map.get(atom_id) or "")
            atom_word_count = max(atom_word_count, len(_WORD_RE.findall(atom_text)))
            atom_tokens = set(_meaningful_tokens(atom_text))
            score = len(atom_tokens.intersection(set(meaningful)))
            if score > best:
                best = score
        overlap = best
        if overlap < 2:
            defect_tags.append("low_atom_overlap")
        if atom_word_count < 8:
            defect_tags.append("low_information_atom")

    compact_cue = (
        len(words) <= 4
        and len(meaningful) >= 1
        and overlap >= 1
        and atom_word_count >= 10
    )
    if compact_cue:
        defect_tags = [
            reason
            for reason in defect_tags
            if reason not in {"too_short", "low_signal_terms", "low_signal_density", "low_atom_overlap"}
        ]

    # Low density can still represent a valid memory cue when overlap and source length are strong.
    if "low_signal_density" in defect_tags and overlap >= 3 and atom_word_count >= 12:
        defect_tags = [reason for reason in defect_tags if reason != "low_signal_density"]

    deduped_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in defect_tags:
        cleaned = str(tag or "").strip()
        if not cleaned or cleaned in seen_tags:
            continue
        seen_tags.add(cleaned)
        deduped_tags.append(cleaned)
    blocking_tags = [tag for tag in deduped_tags if tag in _BLOCKING_DEFECT_TAGS]

    return {
        "case_id": case.case_id,
        "case_type": case.case_type,
        "fixture_family": case.fixture_family,
        "query": case.query,
        "retrieval_query": retrieval_query,
        "word_count": len(words),
        "meaningful_count": len(meaningful),
        "signal_density": round(len(meaningful) / max(len(words), 1), 4) if words else 0.0,
        "atom_word_count": atom_word_count,
        "atom_overlap": overlap,
        "defect_tags": deduped_tags,
        "blocking_defect_tags": blocking_tags,
        "reasons": deduped_tags,
        "weak": bool(deduped_tags),
    }


def _write_md(
    path: Path,
    *,
    decision: str,
    total: int,
    weak: int,
    weak_non_routine: int,
    weak_routine: int,
    blocking: int,
    rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# Truthset Question Validation",
        "",
        f"- generated_at: `{_now_iso()}`",
        f"- decision: `{decision}`",
        f"- total_supported_cases_checked: `{total}`",
        f"- weak_cases: `{weak}`",
        f"- weak_non_routine_cases: `{weak_non_routine}`",
        f"- weak_routine_cases: `{weak_routine}`",
        f"- blocking_defect_cases: `{blocking}`",
        "",
    ]
    if weak == 0 and blocking == 0:
        lines.append("All supported recall prompts passed quality checks.")
    else:
        lines.extend(["## Defect Cases", ""])
        for row in rows:
            if not row.get("weak"):
                continue
            lines.append(f"### {row.get('case_id')}")
            lines.append(f"- fixture: `{row.get('fixture_family')}`")
            lines.append(f"- defect_tags: `{', '.join(row.get('defect_tags') or [])}`")
            lines.append(f"- blocking_tags: `{', '.join(row.get('blocking_defect_tags') or [])}`")
            lines.append(f"- retrieval_query: `{row.get('retrieval_query')}`")
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated truthset questions for memory quality.")
    parser.add_argument("--memories", required=True, help="Path to sqlite store or memories.json")
    parser.add_argument("--truthset", required=True, help="Path to truthset jsonl")
    parser.add_argument("--out-dir", required=True, help="Output directory for validation artifacts")
    parser.add_argument("--max-weak-cases", type=int, default=0, help="Maximum allowed weak supported cases.")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    truthset_path = Path(args.truthset).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2
    if not truthset_path.exists():
        print(f"error=truthset path not found: {truthset_path}")
        return 2

    store, close_store = _open_store(memories_path)
    try:
        atom_map = _atom_text_map(store)
    finally:
        closer = getattr(store, "close", None)
        if close_store and callable(closer):
            closer()

    cases = load_truthset_jsonl(truthset_path)
    supported_non_routine = [
        case
        for case in cases
        if str(case.expected_decision).upper() in {"PASS", "CLARIFY"} and str(case.case_type) != "routine_chat"
    ]
    supported_routine = [
        case
        for case in cases
        if str(case.expected_decision).upper() in {"PASS", "CLARIFY"} and str(case.case_type) == "routine_chat"
    ]
    rows = [_evaluate_case(case, atom_map) for case in [*supported_non_routine, *supported_routine]]
    weak = [row for row in rows if bool(row.get("weak"))]
    weak_non_routine_cases = len(
        [row for row in weak if str(row.get("case_type") or "").strip() != "routine_chat"]
    )
    weak_routine_cases = len(weak) - weak_non_routine_cases
    blocking = [
        row
        for row in rows
        if bool(list(row.get("blocking_defect_tags") or []))
    ]
    defect_tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in list(row.get("defect_tags") or []):
            key = str(tag or "").strip()
            if not key:
                continue
            defect_tag_counts[key] = defect_tag_counts.get(key, 0) + 1
    decision = (
        "PASS"
        if weak_non_routine_cases <= max(0, int(args.max_weak_cases)) and len(blocking) == 0
        else "FAIL"
    )

    summary = {
        "generated_at": _now_iso(),
        "decision": decision,
        "memories_path": str(memories_path),
        "truthset_path": str(truthset_path),
        "total_supported_cases_checked": len(supported_non_routine),
        "routine_cases_checked": len(supported_routine),
        "weak_cases": len(weak),
        "weak_non_routine_cases": weak_non_routine_cases,
        "weak_routine_cases": weak_routine_cases,
        "blocking_defect_cases": len(blocking),
        "defect_tag_counts": defect_tag_counts,
        "event_grade_question_rate": round(
            _ratio(len(supported_non_routine) - weak_non_routine_cases, max(1, len(supported_non_routine))),
            4,
        ),
        "fragment_question_rate": round(
            _ratio(weak_non_routine_cases, max(1, len(supported_non_routine))),
            4,
        ),
        "max_weak_cases": max(0, int(args.max_weak_cases)),
    }
    summary_json = out_dir / "question_validation_summary.json"
    summary_md = out_dir / "question_validation_summary.md"
    details_json = out_dir / "question_validation_cases.json"
    summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    details_json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    _write_md(
        summary_md,
        decision=decision,
        total=len(supported_non_routine),
        weak=len(weak),
        weak_non_routine=weak_non_routine_cases,
        weak_routine=weak_routine_cases,
        blocking=len(blocking),
        rows=rows,
    )

    print(f"decision={decision}")
    print(f"total_supported_cases_checked={len(supported_non_routine)}")
    print(f"routine_cases_checked={len(supported_routine)}")
    print(f"weak_cases={len(weak)}")
    print(f"weak_non_routine_cases={weak_non_routine_cases}")
    print(f"weak_routine_cases={weak_routine_cases}")
    print(f"blocking_defect_cases={len(blocking)}")
    print(f"summary_json={summary_json}")
    print(f"summary_md={summary_md}")
    print(f"cases_json={details_json}")
    return 0 if decision == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
