from __future__ import annotations

import json
from pathlib import Path

from engine.retrieval import EpisodeCardIndex


def test_episode_card_index_load_and_search(tmp_path: Path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_plan",
                "summary": "We split the quarterly roadmap into milestones and risks.",
                "source_id": "conv_plan",
                "day_key": "2026-01-05",
                "domain": "planning",
                "citations": ["conv_plan#m1", "conv_plan#m2"],
                "confidence": 0.88,
                "atom_count": 3,
                "entities": ["user", "assistant"],
                "topics": ["planning", "roadmap"],
                "start_at": "2026-01-05T10:00:00+00:00",
                "end_at": "2026-01-05T10:05:00+00:00",
            },
            {
                "episode_id": "ep_style",
                "summary": "We adjusted tone and cadence for short-form replies.",
                "source_id": "conv_style",
                "day_key": "2026-01-06",
                "domain": "style",
                "citations": ["conv_style#m9"],
                "confidence": 0.77,
                "atom_count": 2,
                "entities": ["assistant"],
                "topics": ["style"],
                "start_at": "2026-01-06T14:10:00+00:00",
                "end_at": "2026-01-06T14:12:00+00:00",
            },
        ]
    }
    cards_path = tmp_path / "episode_cards.json"
    cards_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    index = EpisodeCardIndex.load(cards_path)
    hits = index.search("What did we decide for quarterly roadmap milestones?", top_k=2)

    assert hits
    assert hits[0].card.episode_id == "ep_plan"
    assert hits[0].score > hits[-1].score
