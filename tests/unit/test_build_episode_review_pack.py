from __future__ import annotations

import csv
import json
from pathlib import Path

from tools import build_episode_review_pack


def _write_cards(path: Path) -> None:
    payload = {
        "generated_at": "2026-02-11T00:00:00+00:00",
        "episode_count": 2,
        "cards": [
            {
                "episode_id": "ep_001",
                "title": "Roadmap planning event",
                "summary": "Roadmap planning session with milestone tradeoffs.",
                "source_id": "conv_plan",
                "day_key": "2026-01-05",
                "domain": "planning",
                "atom_count": 3,
                "citation_count": 2,
                "topics": ["planning", "roadmap"],
                "confidence": 0.9,
                "promotion_status": "promoted",
                "evidence_strength": 0.82,
                "retrieval_weight": 0.85,
            },
            {
                "episode_id": "ep_002",
                "title": "Tone alignment event",
                "summary": "Tone alignment and escalation handling notes.",
                "source_id": "conv_style",
                "day_key": "2026-01-06",
                "domain": "style",
                "atom_count": 2,
                "citation_count": 1,
                "topics": ["tone"],
                "confidence": 0.8,
                "promotion_status": "candidate",
                "evidence_strength": 0.41,
                "retrieval_weight": 0.56,
            },
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_episode_review_pack_writes_tsv_and_guide(tmp_path: Path) -> None:
    cards_path = tmp_path / "episode_cards.json"
    out_dir = tmp_path / "review_pack"
    _write_cards(cards_path)

    code = build_episode_review_pack.main(
        [
            "--episodes",
            str(cards_path),
            "--out-dir",
            str(out_dir),
        ]
    )
    assert code == 0

    tsv_path = out_dir / "episode_cards.review.tsv"
    guide_path = out_dir / "episode_cards.review.md"
    meta_path = out_dir / "episode_cards.review_meta.json"
    assert tsv_path.exists()
    assert guide_path.exists()
    assert meta_path.exists()

    with tsv_path.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp, delimiter="\t"))
    assert len(rows) == 2
    assert rows[0]["review_status"] == "PENDING"
    assert rows[0]["title"] == "Roadmap planning event"
    assert rows[0]["edited_title"] == ""
    assert rows[0]["edited_summary"] == ""


def test_build_episode_review_pack_compile_applies_edits_and_rejects(tmp_path: Path) -> None:
    cards_path = tmp_path / "episode_cards.json"
    out_dir = tmp_path / "review_pack"
    _write_cards(cards_path)

    code = build_episode_review_pack.main(
        [
            "--episodes",
            str(cards_path),
            "--out-dir",
            str(out_dir),
        ]
    )
    assert code == 0

    tsv_path = out_dir / "episode_cards.review.tsv"
    with tsv_path.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp, delimiter="\t"))
    assert len(rows) == 2
    rows[0]["review_status"] = "EDIT"
    rows[0]["edited_title"] = "Edited planning title"
    rows[0]["edited_summary"] = "Edited planning summary."
    rows[0]["edited_domain"] = "program"
    rows[0]["edited_topics"] = "planning, cadence"
    rows[1]["review_status"] = "REJECT"
    with tsv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()), delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    code = build_episode_review_pack.main(
        [
            "--compile-reviewed",
            str(tsv_path),
        ]
    )
    assert code == 0

    reviewed_path = out_dir / "episode_cards.reviewed.json"
    assert reviewed_path.exists()
    reviewed_payload = json.loads(reviewed_path.read_text(encoding="utf-8"))
    cards = list(reviewed_payload.get("cards") or [])
    assert len(cards) == 1
    assert cards[0]["episode_id"] == "ep_001"
    assert cards[0]["title"] == "Edited planning title"
    assert cards[0]["summary"] == "Edited planning summary."
    assert cards[0]["domain"] == "program"
    assert cards[0]["topics"] == ["planning", "cadence"]
