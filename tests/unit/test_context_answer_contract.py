import json

import pytest

from engine.continuity import ContinuityStore
from engine.contracts import AtomType, CandidateAtom, MemoryPack, MemoryPackItem, SourceRef
from engine.memory import AtomStore
from engine.responder import build_responder_messages, enforce_reply_contract, verify_reply_against_package
from engine.retrieval import ClaimVerifier, MemoryRetriever, VerificationDecision, VerificationResult
from engine.runtime import RuntimeSession
from engine.runtime.server import _integration_context_diet_v2


def _runtime(text="We are not launching on Friday."):
    store = AtomStore()
    store.add_candidate(CandidateAtom(candidate_id="launch", atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[SourceRef(source_id="launch_source", message_id="m1")],
        confidence=0.9, salience=0.9))
    return RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=ContinuityStore())


def test_packet_checks_requested_claim_and_preserves_related_memory():
    runtime = _runtime()
    try:
        package = runtime.build_context_package("Recall launching on Friday.", package_version="v2",
            memory_preference="memory_assist", answer_claims=["We are launching on Friday."])
        verdict = package["service_verdict"]
        assert verdict["decision"] == "ABSTAIN"
        assert verdict["scope"] == "answer_claims"
        assert verdict["answer_status"] == "UNVERIFIED"
        assert package["ltm_evidence"]
        assert package["ltm_evidence"][0]["related_text"]["text"] == "We are not launching on Friday."
        assert package["ltm_evidence"][0]["related_text"]["kind"] == "canonical_memory"
        reply = enforce_reply_contract(package, "Yes, Friday!")
        assert "not have enough" in reply
        assert "?" in reply
        assert "Yes, Friday" not in reply
        assert verify_reply_against_package(package, reply).ok
        messages = build_responder_messages(package)
        assert "We are not launching on Friday." in str(messages)
        assert "answer_claims" in str(messages)
    finally:
        runtime.close()


def test_no_claim_request_keeps_recall_but_labels_the_verdict_scope():
    runtime = _runtime()
    try:
        package = runtime.build_context_package("Recall launching on Friday.", package_version="v2", memory_preference="memory_assist")
        assert package["service_verdict"]["decision"] == "PASS"
        assert package["service_verdict"]["scope"] == "retrieved_evidence"
        assert package["service_verdict"]["answer_status"] == "NOT_CHECKED"
    finally:
        runtime.close()


def test_exact_claim_pass_keeps_the_claims_own_citation():
    runtime = _runtime()
    try:
        package = runtime.build_context_package("Recall launching on Friday.", package_version="v2",
            memory_preference="memory_assist", answer_claims=["We are not launching on Friday."])
        assert package["service_verdict"]["decision"] == "PASS"
        assert package["service_verdict"]["answer_status"] == "SUPPORTED"
        assert package["service_verdict"]["citations"] == ["launch_source#m1"]
    finally:
        runtime.close()


def test_related_excerpt_is_bounded_and_labels_omitted_context():
    source = "We are not launching on Friday. " + "More source context. " * 320
    runtime = _runtime(source)
    try:
        package = runtime.build_context_package("Recall launching on Friday.", package_version="v2",
            memory_preference="memory_assist", answer_claims=["We are launching on Friday."])
        related = package["ltm_evidence"][0]["related_text"]
        assert len(related["text"]) <= 320  # Existing v2 evidence excerpt budget.
        assert related["text"].startswith("We are not launching on Friday.")
        assert related["truncated"] is True
        assert runtime.retriever.store.list_atoms()[0].canonical_text == source.strip()
    finally:
        runtime.close()


def test_existing_abstention_keeps_related_text_and_clarification():
    runtime = _runtime()
    try:
        package = runtime.build_context_package("Recall launching on Monday.", package_version="v2", memory_preference="memory_assist")
        assert package["service_verdict"]["decision"] == "ABSTAIN"
        assert package["service_verdict"]["answer_status"] == "UNVERIFIED"
        assert package["ltm_evidence"][0]["related_text"]["kind"] == "canonical_memory"
        assert "?" in enforce_reply_contract(package, "Monday.")
    finally:
        runtime.close()


def test_unverified_packet_cannot_accept_a_generated_assertion_with_an_abstention_marker():
    package = {"service_verdict": {"decision": "ABSTAIN", "scope": "answer_claims", "answer_status": "UNVERIFIED"}}
    reply = "I do not have enough supported information, but we are launching on Friday."
    assert not verify_reply_against_package(package, reply).ok


@pytest.mark.parametrize("decision", [VerificationDecision.ABSTAIN, VerificationDecision.CLARIFY, VerificationDecision.NO_MEMORY])
def test_exact_text_cannot_override_an_existing_gate(decision, monkeypatch):
    runtime = _runtime()
    monkeypatch.setattr(runtime.verifier, "verify", lambda *args, **kwargs: VerificationResult(
        decision=decision, checks=[], unsupported_claims=[], needs_uncertainty=decision is VerificationDecision.CLARIFY))
    try:
        package = runtime.build_context_package("Recall launching on Friday.", package_version="v2",
            memory_preference="memory_assist", answer_claims=["We are not launching on Friday."])
        assert package["service_verdict"]["decision"] == decision.value
        assert package["service_verdict"]["answer_status"] == "UNVERIFIED"
        assert package["service_verdict"]["citations"] == []
    finally:
        runtime.close()


@pytest.mark.parametrize("claims", ["Friday", [False], [""], []])
def test_malformed_claim_request_is_rejected(claims):
    runtime = _runtime()
    try:
        with pytest.raises(ValueError, match="answer_claims"):
            runtime.build_context_package("Recall launching on Friday.", package_version="v2", answer_claims=claims)
    finally:
        runtime.close()


def test_context_diet_carries_verdict_even_when_all_evidence_is_dropped():
    verdict = {"decision": "ABSTAIN", "scope": "answer_claims", "answer_status": "UNVERIFIED"}
    result = _integration_context_diet_v2(context_sections=[], evidence_rows=[{
        "evidence_id": "too_big", "summary": "long text " * 5000}], route="ltm_light", confidence=0.8,
        temporal_context=None, total_token_budget=200, temporal_token_budget=192, temporal_due_text_budget_bytes=160,
        service_verdict=verdict)
    assert json.loads(result["agent_context"])["verification"] == verdict
    assert result["truncation"]["dropped_evidence_items"] == 1
    assert result["estimated_tokens"] <= result["token_budget"]


def test_local_alternative_does_not_reverse_the_source():
    runtime = object.__new__(RuntimeSession)
    item = MemoryPackItem(atom_id="launch", canonical_text="We are not launching on Friday.", confidence=0.9,
                          source_refs=[SourceRef(source_id="launch_source", message_id="m1")])
    pack = MemoryPack(core=[item])
    verdict = VerificationResult(decision=VerificationDecision.PASS, checks=[], unsupported_claims=[], needs_uncertainty=False)
    reply, _ = runtime._compose_response('Was it "We are launching on Friday." or "We are launching on Monday."?',
                                        verdict, pack, memory_cards=[], memory_route="ltm_light")
    assert 'I can support "We are launching on Friday."' not in reply
    assert "We are not launching on Friday." in reply
