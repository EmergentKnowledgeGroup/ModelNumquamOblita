from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.contracts import (
    AtomType,
    CandidateAtom,
    EfficiencyMetricsContract,
    MemoryPackItem,
    NormalizedTurn,
    SourceRef,
    WriteAction,
    WriteDecision,
    candidate_atom_from_dict,
    contract_to_dict,
    efficiency_metrics_from_dict,
    memory_pack_from_items,
)


def test_normalized_turn_validates_role_and_text() -> None:
    """NormalizedTurn should enforce allowed roles and non-empty text."""

    turn = NormalizedTurn(source_id="src", role="Assistant", text="hello")
    assert turn.role == "assistant"
    with pytest.raises(ValueError):
        NormalizedTurn(source_id="src", role="unknown", text="x")
    with pytest.raises(ValueError):
        NormalizedTurn(source_id="src", role="assistant", text="   ")


def test_candidate_atom_roundtrip_from_dict() -> None:
    """CandidateAtom dictionary conversion should preserve canonical fields."""

    payload = {
        "candidate_id": "cand-1",
        "atom_type": "episode",
        "canonical_text": "We discussed memory safety.",
        "source_refs": [
            {
                "source_id": "convo-1",
                "message_id": "m-1",
                "timestamp": "2026-02-08T10:11:12+00:00",
                "span_start": 2,
                "span_end": 8,
            }
        ],
        "entities": ["user"],
        "topics": ["memory"],
        "confidence": 0.9,
        "salience": 0.7,
    }
    atom = candidate_atom_from_dict(payload)
    assert atom.atom_type is AtomType.EPISODE
    encoded = contract_to_dict(atom)
    assert encoded["atom_type"] == "episode"
    assert encoded["source_refs"][0]["timestamp"].startswith("2026-02-08T10:11:12")


def test_write_decision_validation() -> None:
    """WriteDecision should normalize stage and reject unsupported stage values."""

    decision = WriteDecision(
        candidate_id="cand-1",
        action=WriteAction.PROPOSE_DELETE,
        confidence=0.88,
        reason_code="conflict_high",
        gate_stage="b",
    )
    assert decision.gate_stage == "B"
    with pytest.raises(ValueError):
        WriteDecision(
            candidate_id="cand-2",
            action=WriteAction.ADD,
            confidence=0.2,
            reason_code="ok",
            gate_stage="C",
        )


def test_memory_pack_factory() -> None:
    """MemoryPack factory should create a pack with provided confidence."""

    ref = SourceRef(source_id="s1", timestamp=datetime.now(tz=timezone.utc))
    core = MemoryPackItem(atom_id="a1", canonical_text="fact", confidence=0.8, source_refs=[ref])
    pack = memory_pack_from_items([core], pack_confidence=0.8)
    assert len(pack.core) == 1
    assert pack.pack_confidence == pytest.approx(0.8)


def test_memory_pack_factory_accepts_additive_efficiency_contract() -> None:
    """MemoryPack should carry optional additive efficiency metrics without breaking callers."""

    ref = SourceRef(source_id="s1", timestamp=datetime.now(tz=timezone.utc))
    core = MemoryPackItem(atom_id="a1", canonical_text="fact", confidence=0.8, source_refs=[ref])
    efficiency = efficiency_metrics_from_dict(
        {
            "latency_p50_ms": 120.0,
            "latency_p95_ms": 240.0,
            "tokens_prompt_avg": 42.0,
            "tokens_completion_avg": 18.0,
            "tokens_total_avg": 60.0,
            "retrieval_fanout_avg": 6.0,
            "retrieval_fanout_p95": 11.0,
        }
    )
    pack = memory_pack_from_items([core], efficiency=efficiency, pack_confidence=0.8)
    encoded = contract_to_dict(pack)
    assert isinstance(pack.efficiency.tokens_total_avg if pack.efficiency is not None else 0.0, float)
    assert encoded["efficiency"]["latency_p50_ms"] == pytest.approx(120.0)
    assert encoded["efficiency"]["tokens_total_avg"] == pytest.approx(60.0)


def test_efficiency_contract_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="tokens_total_avg must be >= 0"):
        EfficiencyMetricsContract(tokens_total_avg=-1.0)
