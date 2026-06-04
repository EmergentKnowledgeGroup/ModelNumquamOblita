from __future__ import annotations

from datetime import datetime, timezone

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.memory.store import AtomStatus
from tools import build_episode_cards


def _candidate(candidate_id: str, text: str, *, source_id: str, message_id: str, topic: str, ts: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=message_id,
                timestamp=datetime.fromisoformat(ts),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=[topic],
        confidence=0.85,
        salience=0.72,
    )


def test_build_cards_groups_same_source_day_and_topic() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c1",
            "We reviewed roadmap milestones for Q1.",
            source_id="conv_plan",
            message_id="m1",
            topic="planning",
            ts="2026-01-05T09:00:00+00:00",
        )
    )
    store.add_candidate(
        _candidate(
            "c2",
            "You asked for a risk table and mitigation options.",
            source_id="conv_plan",
            message_id="m2",
            topic="planning",
            ts="2026-01-05T09:02:00+00:00",
        )
    )
    store.add_candidate(
        _candidate(
            "c3",
            "Later we switched to tone calibration notes.",
            source_id="conv_plan",
            message_id="m3",
            topic="style",
            ts="2026-01-05T09:10:00+00:00",
        )
    )

    cards = build_episode_cards._build_cards(store.list_atoms())
    assert len(cards) == 2

    planning = [item for item in cards if str(item.get("domain")) == "planning"]
    assert planning
    planning_card = planning[0]
    assert int(planning_card.get("atom_count") or 0) == 2
    assert int(planning_card.get("citation_count") or 0) == 2
    assert str(planning_card.get("source_id")) == "conv_plan"
    assert str(planning_card.get("day_key")) == "2026-01-05"
    assert str(planning_card.get("promotion_status")) in {"promoted", "candidate"}
    assert list(planning_card.get("actors") or [])
    assert list(planning_card.get("topic_tags") or [])
    assert str(planning_card.get("timestamp_start") or "").strip()
    assert str(planning_card.get("timestamp_end") or "").strip()
    assert list(planning_card.get("cue_terms") or [])
    assert str(planning_card.get("question_seed") or "").strip()
    assert "title" in planning_card
    assert "event_window" in planning_card


def test_include_atom_excludes_tombstoned_and_archived_by_default() -> None:
    store = AtomStore()
    active = store.add_candidate(
        _candidate(
            "ca",
            "Active memory row.",
            source_id="conv_a",
            message_id="m1",
            topic="general",
            ts="2026-01-01T00:00:00+00:00",
        )
    )
    active.status = AtomStatus.ACTIVE
    tombstoned = store.add_candidate(
        _candidate(
            "ct",
            "Tombstoned memory row.",
            source_id="conv_a",
            message_id="m2",
            topic="general",
            ts="2026-01-01T00:01:00+00:00",
        )
    )
    tombstoned.status = AtomStatus.TOMBSTONED
    conflicted = store.add_candidate(
        _candidate(
            "cc",
            "Conflicted memory row.",
            source_id="conv_a",
            message_id="m3",
            topic="general",
            ts="2026-01-01T00:02:00+00:00",
        )
    )
    conflicted.status = AtomStatus.CONFLICTED

    assert build_episode_cards._include_atom(active, include_non_active=False) is True
    assert build_episode_cards._include_atom(tombstoned, include_non_active=False) is False
    assert build_episode_cards._include_atom(tombstoned, include_non_active=True) is False
    assert build_episode_cards._include_atom(conflicted, include_non_active=False) is False
    assert build_episode_cards._include_atom(conflicted, include_non_active=True) is True


def test_coerce_dt_normalizes_to_utc() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    aware = datetime.fromisoformat("2026-01-01T12:00:00+02:00")
    parsed_naive = build_episode_cards._coerce_dt("2026-01-01T12:00:00")

    normalized_naive = build_episode_cards._coerce_dt(naive)
    normalized_aware = build_episode_cards._coerce_dt(aware)

    assert normalized_naive is not None and normalized_naive.tzinfo == timezone.utc
    assert normalized_aware is not None and normalized_aware.tzinfo == timezone.utc
    assert parsed_naive is not None and parsed_naive.tzinfo == timezone.utc


def test_build_cards_demotes_low_event_shape_to_candidate() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c1",
            "Okay love, you absolutely killed it and I appreciate you so much for everything.",
            source_id="conv_affect",
            message_id="m1",
            topic="affect",
            ts="2026-01-07T08:00:00+00:00",
        )
    )
    store.add_candidate(
        _candidate(
            "c2",
            "You are amazing and this means so much to me, thank you forever.",
            source_id="conv_affect",
            message_id="m2",
            topic="affect",
            ts="2026-01-07T08:04:00+00:00",
        )
    )
    cards = build_episode_cards._build_cards(store.list_atoms(), min_atoms=2)
    assert cards
    card = cards[0]
    assert str(card.get("promotion_status")) == "candidate"
    flags = [str(item) for item in list(card.get("quality_flags") or [])]
    assert "weak_event_shape" in flags


def test_build_cards_falls_back_to_cluster_timestamps_when_refs_missing() -> None:
    store = AtomStore()
    atom_a = store.add_candidate(
        _candidate(
            "c1",
            "Dean shared launch checklist updates.",
            source_id="conv_ops",
            message_id="m1",
            topic="ops",
            ts="2026-01-08T10:00:00+00:00",
        )
    )
    atom_b = store.add_candidate(
        _candidate(
            "c2",
            "We confirmed deployment order and rollback notes.",
            source_id="conv_ops",
            message_id="m2",
            topic="ops",
            ts="2026-01-08T10:02:00+00:00",
        )
    )
    for atom in (atom_a, atom_b):
        for ref in atom.source_refs:
            ref.timestamp = None  # type: ignore[assignment]

    cards = build_episode_cards._build_cards(store.list_atoms())
    assert cards
    card = cards[0]
    assert str(card.get("start_at") or "").strip()
    assert str(card.get("end_at") or "").strip()
    assert str(card.get("timestamp_start") or "").strip()
    assert str(card.get("timestamp_end") or "").strip()


def test_build_cards_summary_does_not_repeat_title_prefix() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c1",
            "And what's the measured false-negative rate — how many queries that would have found a correct answer before?",
            source_id="conv_eval",
            message_id="m1",
            topic="testing",
            ts="2026-01-09T10:00:00+00:00",
        )
    )
    store.add_candidate(
        _candidate(
            "c2",
            "Before the fix, weak recall prompts would often miss a correct answer that earlier heuristics caught.",
            source_id="conv_eval",
            message_id="m2",
            topic="testing",
            ts="2026-01-09T10:03:00+00:00",
        )
    )

    cards = build_episode_cards._build_cards(store.list_atoms())
    assert cards
    card = cards[0]
    title = str(card.get("title") or "").strip()
    summary = str(card.get("summary") or "").strip()
    assert title
    assert summary
    assert not summary.lower().startswith(title.lower())


def test_build_cards_summary_keeps_meaningful_single_atom_fallback() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c1",
            "We reviewed the quarterly plan and split it into milestones.",
            source_id="conv_plan",
            message_id="m1",
            topic="planning",
            ts="2026-01-10T10:00:00+00:00",
        )
    )

    cards = build_episode_cards._build_cards(store.list_atoms())
    assert cards
    card = cards[0]
    assert "quarterly plan" in str(card.get("title") or "").lower()
    assert "quarterly plan" in str(card.get("summary") or "").lower()


def test_build_cards_refines_general_topic_when_card_text_has_clear_local_anchor() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c1",
            "We were reviewing the continuity constitution and what it means for persistent identity.",
            source_id="conv_identity",
            message_id="m1",
            topic="general",
            ts="2026-01-11T10:00:00+00:00",
        )
    )
    store.add_candidate(
        _candidate(
            "c2",
            "That conversation kept circling back to continuity safeguards and identity drift.",
            source_id="conv_identity",
            message_id="m2",
            topic="general",
            ts="2026-01-11T10:03:00+00:00",
        )
    )

    cards = build_episode_cards._build_cards(store.list_atoms())
    assert cards
    topics = [str(item).strip().lower() for item in list(cards[0].get("topic_tags") or []) if str(item).strip()]
    assert "general" not in topics
    assert any(topic in {"continuity", "identity"} for topic in topics)
