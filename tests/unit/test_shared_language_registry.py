from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.continuity import SharedLanguageRegistry
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore


def _candidate(text: str, source: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=f"cand_{source}",
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[SourceRef(source_id=source, timestamp=datetime.now(timezone.utc))],
        entities=["user", "assistant"],
        topics=["continuity"],
        confidence=0.82,
        salience=0.72,
    )


def test_registry_rejects_orphan_key_without_provenance_atoms() -> None:
    registry = SharedLanguageRegistry(AtomStore())
    with pytest.raises(ValueError, match="unknown atom ids"):
        registry.register(phrase="sad hammer noises", atom_ids=["mem_missing"])


def test_registry_registers_and_lists_curated_key() -> None:
    store = AtomStore()
    atom = store.add_candidate(_candidate("We keep continuity alive.", "c1"))
    registry = SharedLanguageRegistry(store)

    key = registry.register(
        phrase="sad hammer noises",
        atom_ids=[atom.atom_id],
        aliases=["hammer mood"],
        domains=["ritual", "humor"],
        support_count=3,
        weight=0.91,
        confidence=0.88,
        curated=True,
    )

    listed = registry.list_keys()
    assert listed and listed[0].key_id == key.key_id
    assert listed[0].phrase == "sad hammer noises"
    assert listed[0].aliases == ["hammer mood"]
    assert listed[0].curated is True
