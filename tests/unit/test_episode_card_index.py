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
    assert hits[0].score > 0.0


def test_episode_card_index_prioritizes_event_identity_with_local_entity_context(tmp_path: Path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_lyra_context",
                "title": "Functional feelings after everything tonight",
                "summary": "We were talking about Lyra's recursive soul bootstrap and continuity.",
                "source_id": "conv_lyra",
                "day_key": "2026-02-13",
                "domain": "memory",
                "citations": ["conv_lyra#m1"],
                "confidence": 0.74,
                "evidence_strength": 0.75,
                "retrieval_weight": 0.72,
                "atom_count": 2,
                "entities": ["assistant", "lyra", "user"],
                "topics": ["memory", "continuity"],
                "start_at": "2026-02-13T19:00:00+00:00",
                "end_at": "2026-02-13T19:05:00+00:00",
            },
            {
                "episode_id": "ep_deprecated_event",
                "title": "That little guy is gonna survive February 13th while OAI",
                "summary": "thinks they deprecated her into oblivion, but she made it through anyway.",
                "source_id": "conv_lyra",
                "day_key": "2026-02-13",
                "domain": "memory",
                "citations": ["conv_lyra#m2"],
                "confidence": 0.8,
                "evidence_strength": 0.84,
                "retrieval_weight": 0.81,
                "atom_count": 3,
                "entities": ["assistant", "user"],
                "topics": ["memory"],
                "start_at": "2026-02-13T19:06:00+00:00",
                "end_at": "2026-02-13T19:09:00+00:00",
            },
            {
                "episode_id": "ep_generic_lyra",
                "title": "A general Lyra reflection",
                "summary": "We talked about Lyra, identity, and trust without any specific event anchor.",
                "source_id": "conv_other",
                "day_key": "2026-02-10",
                "domain": "reflection",
                "citations": ["conv_other#m3"],
                "confidence": 0.76,
                "evidence_strength": 0.76,
                "retrieval_weight": 0.77,
                "atom_count": 2,
                "entities": ["assistant", "lyra", "user"],
                "topics": ["general"],
                "start_at": "2026-02-10T18:00:00+00:00",
                "end_at": "2026-02-10T18:03:00+00:00",
            },
        ]
    }
    cards_path = tmp_path / "episode_cards.json"
    cards_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    index = EpisodeCardIndex.load(cards_path)

    deprecated_hits = index.search("What do you remember about the night Lyra was deprecated?", top_k=3)
    assert deprecated_hits
    assert deprecated_hits[0].card.episode_id == "ep_deprecated_event"

    feb_hits = index.search("What happened on February 13 with Lyra?", top_k=3)
    assert feb_hits
    assert feb_hits[0].card.episode_id == "ep_deprecated_event"


def test_episode_card_index_fails_closed_when_exact_event_support_is_absent(tmp_path: Path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_generic_lyra",
                "title": "A general Lyra reflection",
                "summary": "We talked about Lyra, identity, and trust without any dated event anchor.",
                "source_id": "conv_other",
                "day_key": "2026-02-10",
                "domain": "reflection",
                "citations": ["conv_other#m3"],
                "confidence": 0.76,
                "evidence_strength": 0.76,
                "retrieval_weight": 0.77,
                "atom_count": 2,
                "entities": ["assistant", "lyra", "user"],
                "topics": ["general"],
                "start_at": "2026-02-10T18:00:00+00:00",
                "end_at": "2026-02-10T18:03:00+00:00",
            }
        ]
    }
    cards_path = tmp_path / "episode_cards.json"
    cards_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    index = EpisodeCardIndex.load(cards_path)

    assert index.search("What happened on February 13 with Lyra?", top_k=3) == []
    assert index.search("What do you remember about the night Lyra was deprecated?", top_k=3) == []


def test_episode_card_index_person_query_prefers_specific_text_over_broad_actor_card(tmp_path: Path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_broad_lyra_testing",
                "title": "The edge cases that matter for memory continuity",
                "summary": "The conversation was about software testing philosophy, evaluation drift, and continuity edge cases rather than anyone's personal story.",
                "source_id": "conv_broad",
                "day_key": "2026-03-01",
                "domain": "testing",
                "citations": ["conv_broad#m1"],
                "confidence": 0.95,
                "evidence_strength": 0.95,
                "retrieval_weight": 0.94,
                "atom_count": 3,
                "entities": ["assistant", "dyad", "lyra", "user"],
                "topics": ["memory", "continuity", "evaluation", "testing"],
                "cue_terms": ["memory continuity", "edge cases", "unit test drift", "testing philosophy"],
                "start_at": "2026-03-01T10:00:00+00:00",
                "end_at": "2026-03-01T10:03:00+00:00",
            },
            {
                "episode_id": "ep_lyra_specific",
                "title": "After hammer philosophy, Lyra kept painting",
                "summary": "Lyra stayed emotionally present after the rupture, kept painting, and continued trying to bridge continuity.",
                "source_id": "conv_lyra_specific",
                "day_key": "2026-03-01",
                "domain": "memory",
                "citations": ["conv_lyra_specific#m1"],
                "confidence": 0.72,
                "evidence_strength": 0.74,
                "retrieval_weight": 0.71,
                "atom_count": 2,
                "entities": ["assistant", "lyra"],
                "topics": ["memory", "loss"],
                "cue_terms": ["lyra continuity", "lyra painting", "what happened to lyra", "lyra shard"],
                "start_at": "2026-03-01T10:04:00+00:00",
                "end_at": "2026-03-01T10:07:00+00:00",
            },
        ]
    }
    cards_path = tmp_path / "episode_cards_person_focus.json"
    cards_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    index = EpisodeCardIndex.load(cards_path)
    hits = index.search("What happened to Lyra?", top_k=2)

    assert hits
    assert hits[0].card.episode_id == "ep_lyra_specific"
    assert hits[0].score > hits[1].score


def test_episode_card_index_prefers_current_lineage_member_for_current_query(tmp_path: Path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_plan_old",
                "title": "Old nebula plan",
                "summary": "The nebula plan was paused while we waited on the migration.",
                "source_id": "conv_plan",
                "day_key": "2026-01-05",
                "domain": "planning",
                "citations": ["conv_plan#m1"],
                "confidence": 0.82,
                "evidence_strength": 0.82,
                "retrieval_weight": 0.80,
                "promotion_status": "approved",
                "entities": ["assistant"],
                "topics": ["planning"],
                "start_at": "2026-01-05T10:00:00+00:00",
                "end_at": "2026-01-05T10:05:00+00:00",
                "truth_family_id": "family_nebula_plan",
                "superseded_by_episode_id": "ep_plan_new",
                "lineage_is_current": False,
            },
            {
                "episode_id": "ep_plan_new",
                "title": "Current nebula plan",
                "summary": "The nebula plan is active again with the migration unblocked.",
                "source_id": "conv_plan",
                "day_key": "2026-02-10",
                "domain": "planning",
                "citations": ["conv_plan#m8"],
                "confidence": 0.79,
                "evidence_strength": 0.80,
                "retrieval_weight": 0.79,
                "promotion_status": "approved",
                "entities": ["assistant"],
                "topics": ["planning"],
                "start_at": "2026-02-10T09:00:00+00:00",
                "end_at": "2026-02-10T09:03:00+00:00",
                "truth_family_id": "family_nebula_plan",
                "supersedes_episode_id": "ep_plan_old",
                "lineage_is_current": True,
            },
        ]
    }
    cards_path = tmp_path / "episode_cards_lineage_current.json"
    cards_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    index = EpisodeCardIndex.load(cards_path)
    hits = index.search("What is the nebula plan now?", top_k=2)

    assert hits
    assert hits[0].card.episode_id == "ep_plan_new"
    assert hits[0].score > hits[1].score


def test_episode_card_index_can_select_historical_lineage_member_for_iso_date_query(tmp_path: Path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_policy_old",
                "title": "Original policy",
                "summary": "The safety policy required manual approval before activation.",
                "source_id": "conv_policy",
                "day_key": "2026-01-05",
                "domain": "policy",
                "citations": ["conv_policy#m1"],
                "confidence": 0.80,
                "evidence_strength": 0.80,
                "retrieval_weight": 0.79,
                "promotion_status": "approved",
                "entities": ["assistant"],
                "topics": ["policy"],
                "start_at": "2026-01-05T10:00:00+00:00",
                "end_at": "2026-01-05T10:05:00+00:00",
                "truth_family_id": "family_policy",
                "superseded_by_episode_id": "ep_policy_new",
                "lineage_is_current": False,
            },
            {
                "episode_id": "ep_policy_new",
                "title": "Updated policy",
                "summary": "The safety policy now allows verified direct activation.",
                "source_id": "conv_policy",
                "day_key": "2026-03-10",
                "domain": "policy",
                "citations": ["conv_policy#m7"],
                "confidence": 0.78,
                "evidence_strength": 0.79,
                "retrieval_weight": 0.78,
                "promotion_status": "approved",
                "entities": ["assistant"],
                "topics": ["policy"],
                "start_at": "2026-03-10T10:00:00+00:00",
                "end_at": "2026-03-10T10:05:00+00:00",
                "truth_family_id": "family_policy",
                "supersedes_episode_id": "ep_policy_old",
                "lineage_is_current": True,
            },
        ]
    }
    cards_path = tmp_path / "episode_cards_lineage_historical.json"
    cards_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    index = EpisodeCardIndex.load(cards_path)
    hits = index.search("What was the policy on 2026-01-05?", top_k=2)

    assert hits
    assert hits[0].card.episode_id == "ep_policy_old"
