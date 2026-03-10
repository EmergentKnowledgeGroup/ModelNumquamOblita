from __future__ import annotations

from engine.responder import build_responder_messages


def test_build_responder_messages_includes_evidence_and_sources() -> None:
    citation = "67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
    package = {
        "message": "What do you remember about tea?",
        "service_verdict": {"decision": "PASS"},
        "responder_guidance": {"render_citations": True},
        "ltm_evidence": [
            {
                "summary": "User: Tea helps focus during late sessions.",
                "citations": [citation],
            }
        ],
    }
    messages = build_responder_messages(package)
    assert len(messages) >= 2
    assert messages[0]["role"] == "system"
    assert citation in messages[1]["content"]


def test_build_responder_messages_includes_canonical_abstain_rule() -> None:
    package = {
        "message": "What do you remember about that?",
        "service_verdict": {"decision": "ABSTAIN"},
        "responder_guidance": {"render_citations": True},
        "ltm_evidence": [],
    }
    messages = build_responder_messages(package)
    assert len(messages) >= 2
    assert messages[0]["role"] == "system"
    assert "If service verdict is ABSTAIN, reply exactly: I don't have that memory." in messages[0]["content"]


def test_build_responder_messages_hides_citation_tokens_when_render_disabled() -> None:
    package = {
        "message": "What do you remember about tea?",
        "service_verdict": {"decision": "PASS"},
        "responder_guidance": {"render_citations": False},
        "ltm_evidence": [],
    }
    messages = build_responder_messages(package)
    rules = messages[0]["content"]
    assert "do not output citation tokens" in rules
    assert "include at least one citation token exactly as provided" not in rules
