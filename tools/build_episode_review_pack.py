#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected object json: {path}")
    return raw


def _normalize_status(value: str) -> str:
    normalized = str(value or "").strip().upper()
    aliases = {
        "ACCEPT": "APPROVE",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"APPROVE", "REJECT", "EDIT", "PENDING"}:
        raise ValueError(f"invalid review_status={value!r}; expected APPROVE/REJECT/EDIT/PENDING")
    return normalized


def _write_review_tsv(path: Path, cards: list[dict[str, Any]]) -> None:
    fieldnames = [
        "episode_id",
        "title",
        "summary",
        "timestamp_start",
        "timestamp_end",
        "actors",
        "topic_tags",
        "citations_count",
        "quality_flags",
        "source_id",
        "day_key",
        "domain",
        "promotion_status",
        "confidence",
        "evidence_strength",
        "retrieval_weight",
        "atom_count",
        "citation_count",
        "cue_terms",
        "question_seed",
        "review_status",
        "edited_title",
        "edited_summary",
        "edited_actors",
        "edited_topic_tags",
        "edited_domain",
        "edited_topics",
        "review_note",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for card in cards:
            writer.writerow(
                {
                    "episode_id": str(card.get("episode_id") or ""),
                    "title": str(card.get("title") or ""),
                    "summary": str(card.get("summary") or ""),
                    "timestamp_start": str(card.get("timestamp_start") or card.get("start_at") or ""),
                    "timestamp_end": str(card.get("timestamp_end") or card.get("end_at") or ""),
                    "actors": ", ".join(str(item).strip() for item in list(card.get("actors") or card.get("entities") or []) if str(item).strip()),
                    "topic_tags": ", ".join(str(item).strip() for item in list(card.get("topic_tags") or card.get("topics") or []) if str(item).strip()),
                    "citations_count": str(card.get("citations_count") or card.get("citation_count") or 0),
                    "quality_flags": ", ".join(str(item).strip() for item in list(card.get("quality_flags") or []) if str(item).strip()),
                    "source_id": str(card.get("source_id") or ""),
                    "day_key": str(card.get("day_key") or ""),
                    "domain": str(card.get("domain") or ""),
                    "promotion_status": str(card.get("promotion_status") or "promoted"),
                    "confidence": str(card.get("confidence") or ""),
                    "evidence_strength": str(card.get("evidence_strength") or ""),
                    "retrieval_weight": str(card.get("retrieval_weight") or ""),
                    "atom_count": str(card.get("atom_count") or ""),
                    "citation_count": str(card.get("citation_count") or card.get("citations_count") or 0),
                    "cue_terms": ", ".join(str(item).strip() for item in list(card.get("cue_terms") or []) if str(item).strip()),
                    "question_seed": str(card.get("question_seed") or ""),
                    "review_status": "PENDING",
                    "edited_title": "",
                    "edited_summary": "",
                    "edited_actors": "",
                    "edited_topic_tags": "",
                    "edited_domain": "",
                    "edited_topics": "",
                    "review_note": "",
                }
            )


def _write_review_guide(path: Path, *, source_cards: Path, review_tsv: Path, case_count: int) -> None:
    lines = [
        "# Episode Review Pack",
        "",
        "Use this sheet to approve/reject/edit event-style episode cards before runtime retrieval.",
        "",
        "## Files",
        f"- source_cards: `{source_cards}`",
        f"- review_sheet: `{review_tsv}`",
        "",
        "## Review Status",
        "- `APPROVE`: keep card as-is",
        "- `REJECT`: remove card from reviewed set",
        "- `EDIT`: keep card with edits from `edited_*` fields (`edited_title`, `edited_summary`, `edited_actors`, `edited_topic_tags`, etc.)",
        "- `PENDING`: unresolved row (ignored in compile)",
        "",
        "## Compile Reviewed Set",
        f"- `python3 tools/build_episode_review_pack.py --compile-reviewed {review_tsv} --source-cards {source_cards}`",
        "- Output: `episode_cards.reviewed.json`",
        "",
        f"Rows in review sheet: **{case_count}**",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_meta(path: Path, *, source_cards: Path) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cards": str(source_cards),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse_value_list(value: str, fallback: list[Any]) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return [str(item).strip() for item in list(fallback or []) if str(item).strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in text.split(","):
        clean = str(item).strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _parse_topics(value: str, fallback: list[Any]) -> list[str]:
    return _parse_value_list(value, fallback)


def _compile_reviewed(
    *,
    review_tsv: Path,
    source_cards: Path,
    out_path: Path,
) -> dict[str, Any]:
    source_payload = _load_json(source_cards)
    source_cards_list = list(source_payload.get("cards") or [])
    source_by_id = {
        str(card.get("episode_id") or ""): dict(card)
        for card in source_cards_list
        if str(card.get("episode_id") or "").strip()
    }
    if not source_by_id:
        raise ValueError("source cards payload has no cards")

    approved: list[dict[str, Any]] = []
    counts = {"APPROVE": 0, "REJECT": 0, "EDIT": 0, "PENDING": 0}
    with review_tsv.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp, delimiter="\t")
        for line_no, row in enumerate(reader, start=2):
            episode_id = str((row or {}).get("episode_id") or "").strip()
            if not episode_id:
                raise ValueError(f"review row {line_no}: missing episode_id")
            if episode_id not in source_by_id:
                raise ValueError(f"review row {line_no}: unknown episode_id={episode_id!r}")
            status = _normalize_status(str((row or {}).get("review_status") or ""))
            counts[status] += 1
            if status == "PENDING" or status == "REJECT":
                continue
            card = dict(source_by_id[episode_id])
            if status == "EDIT":
                edited_title = str((row or {}).get("edited_title") or "").strip()
                edited_summary = str((row or {}).get("edited_summary") or "").strip()
                edited_actors = str((row or {}).get("edited_actors") or "").strip()
                edited_topic_tags = str((row or {}).get("edited_topic_tags") or "").strip()
                edited_domain = str((row or {}).get("edited_domain") or "").strip()
                edited_topics = str((row or {}).get("edited_topics") or "").strip()
                if edited_title:
                    card["title"] = edited_title
                if edited_summary:
                    card["summary"] = edited_summary
                if edited_actors:
                    actors = _parse_value_list(edited_actors, list(card.get("actors") or card.get("entities") or []))
                    card["actors"] = actors
                    card["entities"] = list(actors)
                topics_value = edited_topic_tags or edited_topics
                if topics_value:
                    topic_tags = _parse_topics(topics_value, list(card.get("topic_tags") or card.get("topics") or []))
                    card["topic_tags"] = topic_tags
                    card["topics"] = list(topic_tags)
                if edited_domain:
                    card["domain"] = edited_domain
            actors = _parse_value_list("", list(card.get("actors") or card.get("entities") or []))
            topic_tags = _parse_topics("", list(card.get("topic_tags") or card.get("topics") or []))
            card["actors"] = actors
            card["entities"] = list(actors)
            card["topic_tags"] = topic_tags
            card["topics"] = list(topic_tags)
            card["timestamp_start"] = str(card.get("timestamp_start") or card.get("start_at") or "")
            card["start_at"] = str(card.get("timestamp_start") or card.get("start_at") or "")
            card["timestamp_end"] = str(card.get("timestamp_end") or card.get("end_at") or "")
            card["end_at"] = str(card.get("timestamp_end") or card.get("end_at") or "")
            approved.append(card)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    compiled_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cards": str(source_cards),
        "review_tsv": str(review_tsv),
        "episode_count": len(approved),
        "review_counts": counts,
        "cards": approved,
    }
    out_path.write_text(json.dumps(compiled_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return compiled_payload


def _resolve_latest_episode_cards() -> Path | None:
    episodes_dir = REPO_ROOT / "runtime" / "episodes"
    if not episodes_dir.exists():
        return None
    candidates = sorted(episodes_dir.glob("episode_cards_*.json"))
    return candidates[-1] if candidates else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/compile human review pack for episode cards.")
    parser.add_argument(
        "--episodes",
        default="",
        help="Path to episode cards json. Default: latest runtime/episodes/episode_cards_*.json",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Output directory for generated review pack.",
    )
    parser.add_argument(
        "--compile-reviewed",
        default="",
        help="Path to reviewed TSV for compile mode.",
    )
    parser.add_argument(
        "--source-cards",
        default="",
        help="Source episode cards json path required for compile mode.",
    )
    args = parser.parse_args(argv)

    compile_reviewed = str(args.compile_reviewed or "").strip()
    if compile_reviewed:
        review_tsv = Path(compile_reviewed).expanduser().resolve()
        if not review_tsv.exists():
            print(f"error=review tsv not found: {review_tsv}")
            return 2
        source_cards_arg = str(args.source_cards or "").strip()
        source_cards: Path
        if source_cards_arg:
            source_cards = Path(source_cards_arg).expanduser().resolve()
        else:
            meta_path = review_tsv.with_name("episode_cards.review_meta.json")
            if not meta_path.exists():
                print("error=compile mode needs --source-cards or colocated episode_cards.review_meta.json")
                return 2
            meta = _load_json(meta_path)
            source_cards = Path(str(meta.get("source_cards") or "")).expanduser().resolve()
        if not source_cards.exists():
            print(f"error=source cards not found: {source_cards}")
            return 2
        out_dir = (
            Path(args.out_dir).expanduser().resolve()
            if str(args.out_dir or "").strip()
            else review_tsv.parent
        )
        out_path = out_dir / "episode_cards.reviewed.json"
        try:
            payload = _compile_reviewed(review_tsv=review_tsv, source_cards=source_cards, out_path=out_path)
        except Exception as exc:
            print(f"error=failed to compile reviewed cards: {exc}")
            return 2
        print(f"reviewed_cards_json={out_path}")
        print(f"episode_count={int(payload.get('episode_count') or 0)}")
        return 0

    episodes_arg = str(args.episodes or "").strip()
    if episodes_arg:
        cards_path = Path(episodes_arg).expanduser().resolve()
    else:
        latest = _resolve_latest_episode_cards()
        if latest is None:
            print("error=no episode cards found; run tools/build_episode_cards.py first or pass --episodes")
            return 2
        cards_path = latest.resolve()
    if not cards_path.exists():
        print(f"error=episode cards not found: {cards_path}")
        return 2

    payload = _load_json(cards_path)
    cards = list(payload.get("cards") or [])
    if not cards:
        print(f"error=episode cards payload has no cards: {cards_path}")
        return 2

    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if str(args.out_dir or "").strip()
        else REPO_ROOT / "runtime" / "episodes" / f"review_pack_{_stamp()}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    review_tsv = out_dir / "episode_cards.review.tsv"
    guide_md = out_dir / "episode_cards.review.md"
    meta_json = out_dir / "episode_cards.review_meta.json"

    _write_review_tsv(review_tsv, cards)
    _write_review_guide(guide_md, source_cards=cards_path, review_tsv=review_tsv, case_count=len(cards))
    _write_meta(meta_json, source_cards=cards_path)

    print(f"review_tsv={review_tsv}")
    print(f"review_guide={guide_md}")
    print(f"review_meta={meta_json}")
    print(f"episode_count={len(cards)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
