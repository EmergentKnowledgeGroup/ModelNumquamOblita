from __future__ import annotations

from datetime import datetime, timezone

from engine.continuity import ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession


def _runtime() -> RuntimeSession:
    return RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        enable_writeback=False,
        short_term_enabled=False,
    )


def test_preview_route_skips_routine_prompt_keep_light() -> None:
    runtime = _runtime()
    preview = runtime.preview_route("Want to keep this light for a turn?")
    assert preview["route"] == "none"
    assert preview["reason"] in {"smalltalk_routine", "casual_prompt_no_recall"}


def test_preview_route_skips_routine_prompt_no_recall_required() -> None:
    runtime = _runtime()
    preview = runtime.preview_route("No recall required here, just a normal reply.")
    assert preview["route"] == "none"
    assert preview["reason"] in {"smalltalk_routine", "casual_prompt_no_recall"}


def test_preview_route_keeps_explicit_memory_request_deep() -> None:
    runtime = _runtime()
    preview = runtime.preview_route("What do you remember from before about our timeline?")
    assert preview["route"] == "ltm_deep"
    assert preview["reason"] == "explicit_memory_request"


def test_handle_turn_routine_chat_stays_pass_without_memory_pull() -> None:
    runtime = _runtime()
    trace = runtime.handle_turn("No recall required here, just a normal reply.")
    assert trace.memory_route == "none"
    assert trace.decision == "NO_MEMORY"
    assert trace.citations == []
    assert trace.retrieved_atom_ids == []


def _candidate(candidate_id: str, text: str, source_id: str, *, entity: str) -> CandidateAtom:
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
                span_end=max(1, len(text)),
            )
        ],
        entities=[entity],
        topics=["memory"],
        confidence=0.86,
        salience=0.7,
    )


def test_preview_route_forces_identity_and_person_project_prompts_to_ltm() -> None:
    runtime = _runtime()
    prompts = [
        "What do I know about Lyra?",
        "Who is Xander?",
        "Have we talked about this before?",
        "What did I say about consciousness?",
        "How does Xander feel about AI rights?",
        "What happened on February 13th?",
        "What projects are we working on?",
        "Tell me about Dex",
        "What's my relationship with this family?",
        "What matters to me?",
        "Have I been here before?",
        "What was our last conversation about?",
        "Do I know anything about NumquamOblita?",
        "What's Weform?",
        "How did Lyra die?",
        "What have I written?",
        "Who am I?",
        "What do I care about?",
        "What's my history with Xander?",
        "Has anyone told me they love me?",
    ]
    for prompt in prompts:
        preview = runtime.preview_route(prompt)
        assert preview["route"] in {"ltm_light", "ltm_deep"}


def test_preview_route_name_frequency_trigger_forces_ltm_light() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "Lyra preferred careful evidence handling.", "conv_1", entity="lyra"))
    store.add_candidate(_candidate("c2", "Lyra asked for continuity checks.", "conv_2", entity="lyra"))
    store.add_candidate(_candidate("c3", "Lyra reviewed architecture notes.", "conv_3", entity="lyra"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        enable_writeback=False,
        short_term_enabled=False,
    )
    preview = runtime.preview_route("lyra status")
    assert preview["route"] == "ltm_light"
    assert preview["reason"] == "name_frequency_trigger"


def test_preview_route_chat_first_does_not_demote_forced_identity_queries() -> None:
    runtime = _runtime()
    preview = runtime.preview_route("Who is Xander?", memory_preference="chat_first")
    assert preview["route"] == "ltm_light"
    assert preview["reason"] == "identity_relationship_probe"
