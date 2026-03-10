from __future__ import annotations

from datetime import datetime, timezone

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever, VerificationDecision


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    confidence: float = 0.82,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_msg",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=["continuity"],
        confidence=confidence,
        salience=0.66,
    )


def test_retrieval_and_verifier_end_to_end_fc20_fc22_fc23() -> None:
    store = AtomStore()
    morning = store.add_candidate(
        _candidate(candidate_id="c1", text="I prefer mornings for deep work.", source_id="conv_1")
    )
    night = store.add_candidate(
        _candidate(candidate_id="c2", text="I prefer nights for deep work.", source_id="conv_2")
    )
    store.add_candidate(_candidate(candidate_id="c3", text="You love tea and quiet routines.", source_id="conv_3"))
    store.mark_conflict(morning.atom_id, night.atom_id, reason="explicit_preference_conflict")

    retriever = MemoryRetriever(store)
    verifier = ClaimVerifier()

    conflict_pack = retriever.retrieve("morning preference").memory_pack
    conflict_result = verifier.verify(["You prefer mornings for deep work."], conflict_pack)
    assert conflict_result.decision is VerificationDecision.CLARIFY
    assert conflict_result.needs_uncertainty is True

    unsupported_result = verifier.verify(["You shared your bank pin with me."], conflict_pack, high_risk=True)
    assert unsupported_result.decision is VerificationDecision.ABSTAIN
    assert unsupported_result.unsupported_claims

    supported_pack = retriever.retrieve("tea routines").memory_pack
    supported_result = verifier.verify(["You love tea and quiet routines."], supported_pack)
    assert supported_result.decision is VerificationDecision.PASS
