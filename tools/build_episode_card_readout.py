#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(text: str, limit: int = 240) -> str:
    value = " ".join(str(text or "").split()).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _read_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("episode cards json must be an object")
    return payload


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _render_card(index: int, card: dict[str, Any]) -> list[str]:
    title = str(card.get("title") or "").strip() or str(card.get("summary") or "").strip() or f"Episode {index}"
    status = str(card.get("promotion_status") or "unknown").strip().lower() or "unknown"
    source_id = str(card.get("source_id") or "").strip()
    day_key = str(card.get("day_key") or "").strip()
    domain = str(card.get("domain") or "").strip()
    evidence = _as_float(card.get("evidence_strength"), 0.0)
    retrieval = _as_float(card.get("retrieval_weight"), 0.0)
    confidence = _as_float(card.get("confidence"), 0.0)
    atom_count = _as_int(card.get("atom_count"), 0)
    citation_count = _as_int(card.get("citation_count"), 0)
    citations = [str(item).strip() for item in list(card.get("citations") or []) if str(item).strip()]
    message_ids = [str(item).strip() for item in list(card.get("message_ids") or []) if str(item).strip()]
    cue_terms = [str(item).strip() for item in list(card.get("cue_terms") or []) if str(item).strip()]
    actors = [str(item).strip() for item in list(card.get("actors") or card.get("entities") or []) if str(item).strip()]
    topic_tags = [str(item).strip() for item in list(card.get("topic_tags") or card.get("topics") or []) if str(item).strip()]
    quality_flags = [str(item).strip() for item in list(card.get("quality_flags") or []) if str(item).strip()]
    question_seed = str(card.get("question_seed") or "").strip()
    timestamp_start = str(card.get("timestamp_start") or card.get("start_at") or "").strip()
    timestamp_end = str(card.get("timestamp_end") or card.get("end_at") or "").strip()
    quality_status = "questionable" if quality_flags else "clean"

    lines = [
        f"## {index}. {title}",
        "",
        f"- status: `{status}`",
        f"- quality_status: `{quality_status}`",
        f"- source: `{source_id}`",
        f"- day: `{day_key}`",
        f"- domain: `{domain}`",
        f"- atom_count: `{atom_count}`",
        f"- citation_count: `{citation_count}`",
        f"- confidence: `{confidence:.4f}`",
        f"- evidence_strength: `{evidence:.4f}`",
        f"- retrieval_weight: `{retrieval:.4f}`",
    ]
    if timestamp_start or timestamp_end:
        lines.append(f"- time_window: `{timestamp_start or '-'} -> {timestamp_end or '-'}`")
    if actors:
        lines.append(f"- actors: `{', '.join(actors[:10])}`")
    if topic_tags:
        lines.append(f"- topic_tags: `{', '.join(topic_tags[:10])}`")
    if quality_flags:
        lines.append(f"- quality_flags: `{', '.join(quality_flags[:8])}`")
    if cue_terms:
        lines.append(f"- cue_terms: `{', '.join(cue_terms[:10])}`")
    if question_seed:
        lines.append(f"- question_seed: `{question_seed}`")
    if citations:
        lines.append(f"- citations: `{', '.join(citations[:10])}`")
    if message_ids:
        lines.append(f"- message_ids: `{', '.join(message_ids[:12])}`")
    summary = _compact(str(card.get("summary") or ""), limit=320)
    if summary:
        lines.extend(["", "### Summary", "", "```text", summary, "```"])
    lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Render human-readable markdown from episode card JSON.")
    parser.add_argument("--episodes", required=True, help="Path to episode_cards json")
    parser.add_argument("--out", default="", help="Output markdown path (default: sibling episode_cards.readout.md)")
    parser.add_argument("--max-cards", type=int, default=200, help="Max cards to render")
    args = parser.parse_args()

    episodes_path = Path(args.episodes).expanduser().resolve()
    if not episodes_path.exists():
        print(f"error=episodes path not found: {episodes_path}")
        return 2

    try:
        payload = _read_payload(episodes_path)
    except Exception as exc:
        print(f"error=failed to parse episode cards: {exc}")
        return 2

    cards = [dict(item) for item in list(payload.get("cards") or []) if isinstance(item, dict)]
    if not cards:
        print(f"error=no cards in payload: {episodes_path}")
        return 2

    out_path = (
        Path(args.out).expanduser().resolve()
        if str(args.out).strip()
        else episodes_path.with_name("episode_cards.readout.md")
    )
    max_cards = max(1, _as_int(args.max_cards, 200))
    cards = cards[:max_cards]

    promoted_count = sum(1 for card in cards if str(card.get("promotion_status") or "").strip().lower() == "promoted")
    candidate_count = max(0, len(cards) - promoted_count)

    lines: list[str] = [
        "# Episode Card Readout",
        "",
        f"- generated_at: `{_iso_now()}`",
        f"- source_file: `{episodes_path}`",
        f"- rendered_cards: `{len(cards)}`",
        f"- promoted_cards: `{promoted_count}`",
        f"- candidate_cards: `{candidate_count}`",
        "",
        "This file is for human review. `promoted` cards are used first for retrieval; `candidate` cards stay available for review and optional promotion.",
        "",
    ]

    for index, card in enumerate(cards, start=1):
        lines.extend(_render_card(index, card))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    print(f"episode_readout_md={out_path}")
    print(f"rendered_cards={len(cards)}")
    print(f"promoted_cards={promoted_count}")
    print(f"candidate_cards={candidate_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
