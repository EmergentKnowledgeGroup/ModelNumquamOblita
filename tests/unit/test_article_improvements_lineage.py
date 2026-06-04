from __future__ import annotations

from pathlib import Path

import pytest

from engine.runtime.server import _compile_reviewed_payload, _sanitize_review_decision_payload


def test_sanitize_review_decision_payload_preserves_explicit_lineage_fields() -> None:
    payload = _sanitize_review_decision_payload(
        {
            "decision": "edited",
            "truth_family_id": "family_nebula_plan",
            "supersedes_episode_id": "ep_plan_old",
            "ignored": "value",
        }
    )

    assert payload == {
        "decision": "edited",
        "truth_family_id": "family_nebula_plan",
        "supersedes_episode_id": "ep_plan_old",
    }


def test_compile_reviewed_payload_emits_lineage_and_inverse_links(tmp_path: Path) -> None:
    source_cards_path = tmp_path / "episode_cards.json"
    source_payload = {
        "cards": [
            {
                "episode_id": "ep_plan_old",
                "title": "Old nebula plan",
                "summary": "The nebula plan was paused.",
                "source_id": "conv_plan",
                "day_key": "2026-01-05",
                "domain": "planning",
                "citations": ["conv_plan#m1"],
            },
            {
                "episode_id": "ep_plan_new",
                "title": "Current nebula plan",
                "summary": "The nebula plan is active again.",
                "source_id": "conv_plan",
                "day_key": "2026-02-10",
                "domain": "planning",
                "citations": ["conv_plan#m8"],
            },
        ]
    }
    reviewed = _compile_reviewed_payload(
        source_payload=source_payload,
        review_decisions={
            "ep_plan_old": {"decision": "approved", "truth_family_id": "family_nebula_plan"},
            "ep_plan_new": {
                "decision": "edited",
                "truth_family_id": "family_nebula_plan",
                "supersedes_episode_id": "ep_plan_old",
            },
        },
        reviewer="tester",
        source_cards_path=source_cards_path,
        store_fingerprint="store-fp",
        schema_version=3,
        build_id="build-1",
    )

    cards = {str(card["episode_id"]): card for card in reviewed["cards"]}
    assert cards["ep_plan_old"]["truth_family_id"] == "family_nebula_plan"
    assert cards["ep_plan_old"]["superseded_by_episode_id"] == "ep_plan_new"
    assert cards["ep_plan_old"]["lineage_is_current"] is False
    assert cards["ep_plan_new"]["truth_family_id"] == "family_nebula_plan"
    assert cards["ep_plan_new"]["supersedes_episode_id"] == "ep_plan_old"
    assert cards["ep_plan_new"]["lineage_is_current"] is True


def test_compile_reviewed_payload_rejects_branching_supersession(tmp_path: Path) -> None:
    source_cards_path = tmp_path / "episode_cards.json"
    source_payload = {
        "cards": [
            {"episode_id": "ep_old", "summary": "Old truth", "source_id": "conv", "day_key": "2026-01-01", "domain": "memory", "citations": ["conv#m1"]},
            {"episode_id": "ep_new_a", "summary": "New truth A", "source_id": "conv", "day_key": "2026-01-02", "domain": "memory", "citations": ["conv#m2"]},
            {"episode_id": "ep_new_b", "summary": "New truth B", "source_id": "conv", "day_key": "2026-01-03", "domain": "memory", "citations": ["conv#m3"]},
        ]
    }

    with pytest.raises(ValueError, match="single-valued correction chain"):
        _compile_reviewed_payload(
            source_payload=source_payload,
            review_decisions={
                "ep_old": {"decision": "approved", "truth_family_id": "family_a"},
                "ep_new_a": {"decision": "edited", "truth_family_id": "family_a", "supersedes_episode_id": "ep_old"},
                "ep_new_b": {"decision": "edited", "truth_family_id": "family_a", "supersedes_episode_id": "ep_old"},
            },
            reviewer="tester",
            source_cards_path=source_cards_path,
            store_fingerprint="store-fp",
            schema_version=3,
            build_id="build-1",
        )
