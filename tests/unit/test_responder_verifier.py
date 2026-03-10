from __future__ import annotations

from engine.responder import CANONICAL_ABSTAIN_PHRASE, enforce_reply_contract, verify_reply_against_package


def test_responder_verifier_pass_requires_known_citation() -> None:
    citation = "67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
    package = {
        "service_verdict": {"decision": "PASS"},
        "ltm_evidence": [{"citations": [citation]}],
    }
    ok = verify_reply_against_package(package, f"We discussed tea preferences. {citation}")
    assert ok.ok is True
    assert citation in ok.found_citations


def test_responder_verifier_fails_on_unknown_citation() -> None:
    citation = "67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
    unknown = "11111111-1111-1111-1111-111111111111#9"
    package = {
        "service_verdict": {"decision": "PASS"},
        "ltm_evidence": [{"citations": [citation]}],
    }
    out = verify_reply_against_package(package, f"Here is my answer. {unknown}")
    assert out.ok is False
    assert "unknown_citations_present" in out.reasons


def test_responder_verifier_abstain_requires_marker_and_no_citations() -> None:
    citation = "67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
    package = {
        "service_verdict": {"decision": "ABSTAIN"},
        "ltm_evidence": [{"citations": [citation]}],
    }
    out = verify_reply_against_package(package, "I don't have that memory yet. Can you share one more detail?")
    assert out.ok is True
    out2 = verify_reply_against_package(package, f"I don't have that memory. {citation}")
    assert out2.ok is False
    assert "citations_present_on_abstain" in out2.reasons


def test_responder_verifier_accepts_semantic_abstain_variant_with_unicode_apostrophe() -> None:
    package = {
        "service_verdict": {"decision": "ABSTAIN"},
        "ltm_evidence": [],
    }
    out = verify_reply_against_package(
        package,
        "I don’t have memory evidence about that event in my records.",
    )
    assert out.ok is True
    assert out.inferred_decision == "ABSTAIN"


def test_enforce_reply_contract_canonicalizes_abstain_output() -> None:
    package = {
        "service_verdict": {"decision": "ABSTAIN"},
        "ltm_evidence": [],
    }
    normalized = enforce_reply_contract(
        package,
        "I don’t have access to memories or details about that.",
    )
    assert normalized == CANONICAL_ABSTAIN_PHRASE


def test_responder_verifier_pass_allows_hidden_citations_when_internal_provenance_exists() -> None:
    citation = "67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
    package = {
        "service_verdict": {"decision": "PASS", "citations": [citation]},
        "responder_guidance": {"render_citations": False},
        "ltm_evidence": [{"citations": [citation]}],
    }
    out = verify_reply_against_package(package, "Yes, we discussed tea preferences during late sessions.")
    assert out.ok is True
    assert out.inferred_decision == "PASS"


def test_responder_verifier_pass_fails_when_hidden_mode_reply_abstains() -> None:
    citation = "67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
    package = {
        "service_verdict": {"decision": "PASS", "citations": [citation]},
        "responder_guidance": {"render_citations": False},
        "ltm_evidence": [{"citations": [citation]}],
    }
    out = verify_reply_against_package(package, "I don’t have a direct memory match for that.")
    assert out.ok is False
    assert "pass_response_abstained" in out.reasons
    assert out.inferred_decision == "ABSTAIN"


def test_responder_verifier_pass_hidden_mode_still_requires_internal_provenance() -> None:
    package = {
        "service_verdict": {"decision": "PASS", "citations": []},
        "responder_guidance": {"render_citations": False},
        "ltm_evidence": [],
    }
    out = verify_reply_against_package(package, "Yes, we discussed that before.")
    assert out.ok is False
    assert "missing_internal_citations_for_pass" in out.reasons


def test_enforce_reply_contract_strips_citation_artifacts_when_hidden() -> None:
    known = "67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
    unknown = "11111111-1111-1111-1111-111111111111#9"
    package = {
        "service_verdict": {"decision": "PASS", "citations": [known]},
        "responder_guidance": {"render_citations": False},
        "ltm_evidence": [{"citations": [known]}],
    }
    raw = (
        "Yes, that happened [1].\n\n"
        f"[1] Source: {unknown}\n"
        f"(source: {unknown})"
    )
    normalized = enforce_reply_contract(package, raw)
    assert unknown not in normalized
    assert "[1]" not in normalized
    out = verify_reply_against_package(package, normalized)
    assert out.ok is True
