from __future__ import annotations

from datetime import datetime, timezone

from engine.contracts import MemoryPack, MemoryPackItem, SourceRef
from engine.retrieval import ClaimVerifier, VerificationDecision


def _item(atom_id: str, text: str, source_id: str, *, state: str = "active") -> MemoryPackItem:
    return MemoryPackItem(
        atom_id=atom_id,
        canonical_text=text,
        confidence=0.80,
        source_refs=[SourceRef(source_id=source_id, timestamp=datetime.now(timezone.utc))],
        conflict_state=state,
    )


def test_claim_verifier_abstains_on_unsupported_claim_fc20() -> None:
    verifier = ClaimVerifier()
    pack = MemoryPack(core=[_item("a1", "I prefer tea in the morning.", "conv_1")], pack_confidence=0.8)

    result = verifier.verify(["You shared your bank pin with me."], pack, high_risk=True)

    assert result.decision is VerificationDecision.ABSTAIN
    assert result.unsupported_claims == ["You shared your bank pin with me."]


def test_claim_verifier_blocks_derived_only_claim_fc21() -> None:
    verifier = ClaimVerifier()
    pack = MemoryPack(
        continuity=[_item("d1", "constellation: tea preference pattern", "conv_9")],
        pack_confidence=0.6,
    )

    result = verifier.verify(["Our constellation proves you prefer tea."], pack)

    assert result.decision is VerificationDecision.ABSTAIN
    assert result.checks[0].reason == "DERIVED_ONLY_EVIDENCE"


def test_claim_verifier_requires_uncertainty_for_conflicts_fc22() -> None:
    verifier = ClaimVerifier(conflict_threshold=0.33)
    pack = MemoryPack(
        conflict=[
            _item("c1", "I prefer mornings for deep work.", "conv_1", state="conflicted"),
            _item("c2", "I prefer nights for deep work.", "conv_2", state="conflicted"),
        ],
        pack_confidence=0.7,
    )

    result = verifier.verify(["You prefer mornings for deep work."], pack)

    assert result.decision is VerificationDecision.CLARIFY
    assert result.needs_uncertainty is True
    assert result.checks[0].reason == "UNRESOLVED_CONFLICT"


def test_claim_verifier_passes_supported_claims_with_citations() -> None:
    verifier = ClaimVerifier()
    pack = MemoryPack(
        core=[_item("a1", "You love tea and quiet routines.", "conv_4")],
        context=[_item("a2", "We discussed continuity plans yesterday.", "conv_3")],
        pack_confidence=0.85,
    )

    result = verifier.verify(["You love tea."], pack)

    assert result.decision is VerificationDecision.PASS
    assert result.checks[0].supported is True
    assert result.checks[0].citations == ["conv_4"]


def test_claim_verifier_abstains_on_incomplete_conflict_coverage() -> None:
    verifier = ClaimVerifier()
    pack = MemoryPack(
        conflict=[_item("c1", "I prefer mornings for deep work.", "conv_1", state="conflicted")],
        pack_confidence=0.7,
    )

    result = verifier.verify(["You prefer mornings for deep work."], pack)

    assert result.decision is VerificationDecision.ABSTAIN
    assert result.checks[0].reason == "INCOMPLETE_CONFLICT_COVERAGE"


def test_claim_verifier_allows_derived_term_when_direct_evidence_exists() -> None:
    verifier = ClaimVerifier()
    pack = MemoryPack(
        core=[_item("a1", "You prefer tea in the morning routine.", "conv_10")],
        continuity=[_item("d1", "constellation: tea preference pattern", "conv_9")],
        pack_confidence=0.82,
    )

    result = verifier.verify(["The constellation confirms you prefer tea in the morning."], pack)

    assert result.decision is VerificationDecision.PASS
    assert result.checks[0].reason == "SUPPORTED"
