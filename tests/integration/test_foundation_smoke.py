from __future__ import annotations

from datetime import datetime, timezone

from engine.config import default_config
from engine.contracts import AtomType, CandidateAtom, SourceRef


def test_foundation_smoke_contract_and_config() -> None:
    """Foundation smoke test should validate config defaults and contract wiring."""

    cfg = default_config()
    ref = SourceRef(source_id="seed", timestamp=datetime.now(timezone.utc))
    atom = CandidateAtom(
        candidate_id="seed-1",
        atom_type=AtomType.ATOMIC_FACT,
        canonical_text="The system requires evidence for claims.",
        source_refs=[ref],
        confidence=0.95,
        salience=0.65,
    )
    assert cfg.runtime.require_uncertainty_citations
    assert atom.source_refs[0].source_id == "seed"
