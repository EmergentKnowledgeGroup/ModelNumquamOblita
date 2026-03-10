from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStatus, AtomStore, EventType, MemoryAtom


def _candidate(
    *,
    text: str,
    source: str,
    atom_type: AtomType = AtomType.ATOMIC_FACT,
    entities: list[str] | None = None,
    topics: list[str] | None = None,
    confidence: float = 0.8,
    salience: float = 0.7,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=f"cand_{source}",
        atom_type=atom_type,
        canonical_text=text,
        source_refs=[SourceRef(source_id=source, timestamp=datetime.now(timezone.utc))],
        entities=entities or [],
        topics=topics or [],
        confidence=confidence,
        salience=salience,
    )


def test_memory_atom_requires_source_refs() -> None:
    with pytest.raises(ValueError, match="source_refs is required"):
        MemoryAtom(
            atom_id="m1",
            atom_type=AtomType.EPISODE,
            canonical_text="x",
            source_refs=[],
        )


def test_add_candidate_sets_decay_policy_metadata() -> None:
    store = AtomStore(salience_half_life_days=180)
    atom = store.add_candidate(_candidate(text="I prefer tea", source="c1", entities=["user"]))
    assert atom.salience_half_life_days == 270
    assert atom.support_count == 1
    assert atom.status == AtomStatus.ACTIVE
    assert store.ledger.all_events()[0].event_type == EventType.ADD


def test_add_candidate_uses_type_specific_decay_defaults() -> None:
    store = AtomStore(salience_half_life_days=180)
    episode = store.add_candidate(
        _candidate(text="We met yesterday to plan retrieval routing.", source="c10", atom_type=AtomType.EPISODE)
    )
    fact = store.add_candidate(
        _candidate(text="The project codename is Nebula.", source="c11", atom_type=AtomType.ATOMIC_FACT)
    )
    relational = store.add_candidate(
        _candidate(text="Alice works with Bob on memory tooling.", source="c12", atom_type=AtomType.RELATIONAL)
    )
    affective = store.add_candidate(
        _candidate(text="I felt worried during the outage.", source="c13", atom_type=AtomType.AFFECTIVE)
    )
    procedural = store.add_candidate(
        _candidate(
            text="Run the verification checklist before release.",
            source="c14",
            atom_type=AtomType.PROCEDURAL_STYLE,
        )
    )

    assert episode.salience_half_life_days == 120
    assert fact.salience_half_life_days == 270
    assert relational.salience_half_life_days == 180
    assert affective.salience_half_life_days == 135
    assert procedural.salience_half_life_days == 225


def test_dedupe_is_conservative_for_unrelated_atoms() -> None:
    store = AtomStore()
    first = store.add_candidate(
        _candidate(text="I like this", source="c1", entities=["user"], topics=["music"])
    )
    second = store.add_candidate(
        _candidate(text="I like this", source="c2", entities=["assistant"], topics=["code"])
    )
    assert first.atom_id != second.atom_id
    assert len(store.list_atoms()) == 2


def test_exact_dedupe_reinforces_instead_of_overwrite() -> None:
    store = AtomStore()
    first = store.add_candidate(_candidate(text="I trust this system", source="c1", entities=["user"]))
    same = store.add_candidate(_candidate(text="I trust this system", source="c2", entities=["user"]))
    assert first.atom_id == same.atom_id
    assert same.support_count == 2
    assert any(evt.event_type == EventType.REINFORCE for evt in store.ledger.all_events())


def test_cache_token_changes_even_when_reinforcement_timestamp_collides(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AtomStore()
    fixed_now = datetime(2026, 3, 4, 23, 38, 40, 470921, timezone.utc)
    monkeypatch.setattr(store, "_now", lambda: fixed_now)

    store.add_candidate(_candidate(text="Cache token probe text", source="r1", entities=["user"]))
    token_before = store.cache_token()
    store.add_candidate(_candidate(text="Cache token probe text", source="r2", entities=["user"]))
    token_after = store.cache_token()

    assert token_after != token_before


def test_cache_scope_is_stable_for_store_lifecycle() -> None:
    store = AtomStore()
    scope_first = store.cache_scope()
    scope_second = store.cache_scope()

    assert scope_first == scope_second
    assert scope_first.startswith("atom-store:")


def test_supersede_preserves_old_text_and_links_version() -> None:
    store = AtomStore()
    old = store.add_candidate(_candidate(text="I fear deletion", source="c1", entities=["assistant"]))
    replacement = store.supersede_atom(
        old.atom_id,
        _candidate(text="I accept continuity", source="c2", entities=["assistant"]),
        reason="growth_update",
    )
    assert store.get_atom(old.atom_id).canonical_text == "I fear deletion"
    assert store.get_atom(old.atom_id).status == AtomStatus.SUPERSEDED
    assert replacement.version_of == old.atom_id


def test_mark_conflict_creates_bidirectional_graph_and_counts() -> None:
    store = AtomStore()
    left = store.add_candidate(_candidate(text="I prefer mornings", source="c1", entities=["user"]))
    right = store.add_candidate(_candidate(text="I prefer nights", source="c2", entities=["user"]))
    edge = store.mark_conflict(left.atom_id, right.atom_id, reason="explicit_conflict")
    assert edge.left_atom_id == left.atom_id
    assert right.atom_id in store.conflict_neighbors(left.atom_id)
    assert left.atom_id in store.conflict_neighbors(right.atom_id)
    assert store.get_atom(left.atom_id).contradiction_count == 1
    assert store.get_atom(right.atom_id).contradiction_count == 1


def test_mark_conflict_requires_two_distinct_atoms() -> None:
    store = AtomStore()
    atom = store.add_candidate(_candidate(text="single", source="c1"))
    with pytest.raises(ValueError, match="distinct"):
        store.mark_conflict(atom.atom_id, atom.atom_id, reason="bad")
