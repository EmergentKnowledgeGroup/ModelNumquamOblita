from __future__ import annotations

import json
import time
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.config import default_config
from engine.contracts import (
    AtomType,
    CandidateAtom,
    MemoryPack,
    MemoryPackItem,
    RetrievalOverrideRequestContract,
    SourceRef,
    memory_pack_from_items,
)
from engine.memory import AtomStore
from engine.retrieval import ClaimCheck, ClaimVerifier, MemoryRetriever, VerificationDecision, VerificationResult
from engine.retrieval.engine import RetrievalResult, RetrievalScoredAtom
from engine.runtime import RuntimeSession, WritebackEvent


def _candidate(candidate_id: str, text: str, source_id: str) -> CandidateAtom:
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
        confidence=0.84,
        salience=0.7,
    )


def _write_episode_cards(path: Path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_plan",
                "summary": "We split the quarterly roadmap into milestones and risk tracks.",
                "source_id": "conv_plan",
                "day_key": "2026-01-05",
                "domain": "planning",
                "citations": ["conv_plan#m1", "conv_plan#m2"],
                "confidence": 0.9,
                "atom_count": 3,
                "entities": ["user", "assistant"],
                "topics": ["planning", "roadmap"],
                "start_at": "2026-01-05T10:00:00+00:00",
                "end_at": "2026-01-05T10:05:00+00:00",
            }
        ]
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_runtime_session_prewarm_passes_continuity_store_when_supported() -> None:
    continuity = ContinuityStore()

    class ContinuityAwarePrewarmRetriever:
        def __init__(self) -> None:
            self.prewarm_calls: list[object] = []
            self.store = AtomStore()

        def prewarm(self, *, continuity_store: ContinuityStore | None = None) -> None:
            self.prewarm_calls.append(continuity_store)

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = ContinuityAwarePrewarmRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=continuity,
    )
    try:
        assert len(retriever.prewarm_calls) == 1
        assert retriever.prewarm_calls[0] is continuity
    finally:
        runtime.close()


def test_runtime_session_prewarm_falls_back_for_legacy_signature() -> None:
    class LegacyPrewarmRetriever:
        def __init__(self) -> None:
            self.prewarm_calls = 0
            self.store = AtomStore()

        def prewarm(self) -> None:
            self.prewarm_calls += 1

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = LegacyPrewarmRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        assert retriever.prewarm_calls == 1
    finally:
        runtime.close()


def test_runtime_session_prewarm_does_not_fallback_on_internal_type_error() -> None:
    class ContinuityAwareButBrokenRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.prewarm_calls: list[object] = []

        def prewarm(self, *, continuity_store: ContinuityStore | None = None) -> None:
            self.prewarm_calls.append(continuity_store)
            raise TypeError("synthetic prewarm bug")

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = ContinuityAwareButBrokenRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        # Runtime prewarm logs failures, but should not retry via legacy fallback.
        assert len(retriever.prewarm_calls) == 1
    finally:
        runtime.close()


def test_runtime_session_uses_typed_runtime_retrieval_policy_from_config() -> None:
    cfg = default_config()
    cfg.runtime.retrieval.ltm_max_passes = 4
    cfg.runtime.retrieval.memory_signal_min_score = 0.52
    cfg.runtime.retrieval.prewarm_caches = False
    cfg.runtime.retrieval.routine_hard_cap_enabled = False
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
    )
    try:
        assert runtime.ltm_max_passes == 4
        assert runtime.memory_signal_min_score == pytest.approx(0.52)
        assert runtime.prewarm_caches is False
        assert runtime.routine_hard_cap_enabled is False
    finally:
        runtime.close()


def test_runtime_session_explicit_args_override_typed_runtime_retrieval_policy() -> None:
    cfg = default_config()
    cfg.runtime.retrieval.ltm_max_passes = 4
    cfg.runtime.retrieval.prewarm_caches = False
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        ltm_max_passes=1,
        prewarm_caches=True,
    )
    try:
        assert runtime.ltm_max_passes == 1
        assert runtime.prewarm_caches is True
    finally:
        runtime.close()


def test_runtime_session_raises_when_explicit_config_cannot_sync_to_retriever() -> None:
    cfg = default_config()

    class BrokenConfigRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self._config = default_config()

        @property
        def config(self):
            return self._config

        @config.setter
        def config(self, value) -> None:
            _ = value
            raise TypeError("cannot assign config")

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    with pytest.raises(RuntimeError, match="failed to apply explicit runtime config to retriever"):
        RuntimeSession(
            retriever=BrokenConfigRetriever(),  # type: ignore[arg-type]
            verifier=ClaimVerifier(),
            continuity_store=ContinuityStore(),
            config=cfg,
        )


def test_runtime_session_pipeline_and_telemetry() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in quiet sessions.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires evidence-backed recall.", "conv_2"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
    )
    try:
        trace = runtime.handle_turn("What did we confirm about continuity?")
        assert trace.turn_id
        assert trace.decision in {"PASS", "CLARIFY", "ABSTAIN"}
        assert trace.memory_mode in {"none", "stm_primary", "hybrid", "ltm_only"}
        assert trace.memory_route in {"none", "stm_only", "ltm_light", "ltm_deep"}
        assert isinstance(trace.route_reason, str) and trace.route_reason
        assert trace.short_term_hits >= 0
        assert trace.telemetry.total_ms >= trace.telemetry.retrieval_ms
        assert trace.telemetry.cumulative_tokens >= trace.telemetry.input_tokens
        assert runtime.stats().turns == 1
        payload = runtime.trace_to_dict(trace)
        assert isinstance(payload.get("route_reason_text"), str) and payload["route_reason_text"]
        assert payload.get("memory_preference") == "auto"
        assert isinstance(payload.get("retrieval_query_tokens"), int)
        override_payload = payload.get("retrieval_override")
        assert isinstance(override_payload, dict)
        assert override_payload.get("requested") is False
        assert override_payload.get("applied") is False
        assert payload.get("budget", {}).get("warning_state") in {"ok", "warn"}
        assert runtime.get_writeback(trace.writeback_event_id).status in {"queued", "running", "done"}
    finally:
        runtime.close()


def test_runtime_session_close_marks_pending_writebacks_failed_without_blocking() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    event_id = "wb_test_pending"
    with runtime._lock:
        runtime._writebacks[event_id] = WritebackEvent(  # type: ignore[attr-defined]
            event_id=event_id,
            turn_id="turn_test",
            status="queued",
            created_at=datetime.now(timezone.utc),
        )
        runtime._writeback_futures[event_id] = Future()  # type: ignore[attr-defined]

    start = time.perf_counter()
    runtime.close(wait_timeout_s=0.01)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    event = runtime.get_writeback(event_id)
    assert event is not None
    assert event.status == "failed"
    assert "runtime closed before writeback completed" in str(event.error or "")
    assert elapsed_ms < 300.0


def test_runtime_session_abstains_when_no_evidence_claims_exist() -> None:
    empty_store = AtomStore()
    runtime = RuntimeSession(
        retriever=MemoryRetriever(empty_store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("Do you remember anything about this?")
        assert trace.decision == "ABSTAIN"
        assert "cannot support a confident memory claim" in trace.response_text.lower()
    finally:
        runtime.close()


def test_runtime_session_abstains_when_query_match_is_weak() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in quiet sessions.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires evidence-backed recall.", "conv_2"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("Tell me about sentinel zxqv_no_match_memory detail")
        assert trace.decision == "ABSTAIN"
        assert any(
            item.get("reason")
            in {"QUERY_EVIDENCE_WEAK", "QUERY_SIGNAL_MISSING", "QUERY_INFORMATIVE_MISMATCH"}
            for item in trace.claim_checks
        )
    finally:
        runtime.close()


def test_runtime_session_abstains_when_signal_token_missing() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in quiet sessions.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires evidence-backed recall.", "conv_2"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("What do you remember about invoice_99x_ghostref?")
        assert trace.decision == "ABSTAIN"
        assert any(item.get("reason") == "QUERY_SIGNAL_MISSING" for item in trace.claim_checks)
    finally:
        runtime.close()


def test_runtime_session_enforces_direct_citation_gate() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in quiet sessions.", "conv_1"))

    class LooseVerifier:
        def verify(self, claims, memory_pack, *, high_risk=False):  # type: ignore[no-untyped-def]
            _ = claims
            _ = memory_pack
            _ = high_risk
            return VerificationResult(
                decision=VerificationDecision.PASS,
                checks=[ClaimCheck(claim="synthetic claim", supported=True, confidence=0.9, citations=[])],
                unsupported_claims=[],
                needs_uncertainty=False,
            )

    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=LooseVerifier(),  # type: ignore[arg-type]
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What do you remember about tea sessions?")
        assert trace.decision == "ABSTAIN"
        assert any(item.get("reason") == "DIRECT_CITATION_REQUIRED" for item in trace.claim_checks)
    finally:
        runtime.close()


def test_runtime_session_accepts_message_scoped_citations() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in quiet sessions.", "conv_tea"))

    class MessageScopedVerifier:
        def verify(self, claims, memory_pack, *, high_risk=False):  # type: ignore[no-untyped-def]
            _ = claims
            _ = memory_pack
            _ = high_risk
            return VerificationResult(
                decision=VerificationDecision.PASS,
                checks=[ClaimCheck(claim="supported by message citation", supported=True, confidence=0.9, citations=["conv_tea#msg_42"])],
                unsupported_claims=[],
                needs_uncertainty=False,
            )

    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=MessageScopedVerifier(),  # type: ignore[arg-type]
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What do you remember about tea sessions?")
        assert trace.decision == "PASS"
        assert trace.memory_route != "none"
    finally:
        runtime.close()


def test_runtime_session_direct_citation_gate_accepts_conflict_or_context_sources() -> None:
    class ConflictContextRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            context_item = MemoryPackItem(
                atom_id="ctx_1",
                canonical_text="We discussed tea preferences in a planning context.",
                confidence=0.81,
                source_refs=[
                    SourceRef(
                        source_id="conv_ctx",
                        message_id="ctx_msg_1",
                        timestamp=datetime.now(timezone.utc),
                        span_start=0,
                        span_end=64,
                    )
                ],
                conflict_state="active",
            )
            conflict_item = MemoryPackItem(
                atom_id="conf_1",
                canonical_text="Contradicted tea preference entry.",
                confidence=0.77,
                source_refs=[
                    SourceRef(
                        source_id="conv_conf",
                        message_id="conf_msg_1",
                        timestamp=datetime.now(timezone.utc),
                        span_start=0,
                        span_end=40,
                    )
                ],
                conflict_state="contradicted",
            )
            pack = memory_pack_from_items(
                [],
                context=[context_item],
                conflict=[conflict_item],
                pack_confidence=0.8,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["ctx_1", "conf_1"], scored_atoms=[])

    class ConflictCitationVerifier:
        def verify(self, claims, memory_pack, *, high_risk=False):  # type: ignore[no-untyped-def]
            _ = claims
            _ = memory_pack
            _ = high_risk
            return VerificationResult(
                decision=VerificationDecision.PASS,
                checks=[ClaimCheck(claim="supported by conflict citation", supported=True, confidence=0.8, citations=["conv_conf#msg_9"])],
                unsupported_claims=[],
                needs_uncertainty=False,
            )

    runtime = RuntimeSession(
        retriever=ConflictContextRetriever(),  # type: ignore[arg-type]
        verifier=ConflictCitationVerifier(),  # type: ignore[arg-type]
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What do you remember about tea preferences?")
        assert trace.decision == "PASS"
        assert trace.memory_route != "none"
    finally:
        runtime.close()


def test_runtime_session_front_desk_routes_none_for_smalltalk_without_retrieval() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("Hey Lyra, how are you doing?")
        assert trace.memory_route == "none"
        assert trace.route_reason == "smalltalk_routine"
        assert trace.memory_mode == "none"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_front_desk_routes_none_for_social_invite_prompt() -> None:
    """Social invite prompts should remain chat-only and skip memory retrieval."""
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("I heard a joke the other day, do you want to hear it?")
        assert trace.memory_route == "none"
        assert trace.route_reason in {"smalltalk_routine", "casual_prompt_no_recall"}
        assert trace.memory_mode == "none"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_front_desk_chat_first_pref_keeps_social_prompt_without_ltm() -> None:
    """`chat_first` should preserve no-recall routing for routine social prompts."""
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn(
            "Can I tell you a quick joke?",
            memory_preference="chat_first",
        )
        assert trace.memory_preference == "chat_first"
        assert trace.memory_route == "none"
        assert trace.route_reason in {"smalltalk_routine", "casual_prompt_no_recall"}
        assert trace.memory_mode == "none"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_front_desk_routes_stm_only_for_thread_reference() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.35,
    )
    try:
        runtime.handle_turn("Project delta has three milestones and one blocker.")
        before = len(retriever.queries)
        trace = runtime.handle_turn("Continue this thread with the same project context.")
        assert trace.memory_route == "stm_only"
        assert trace.route_reason == "thread_local_reference"
        assert len(retriever.queries) == before
    finally:
        runtime.close()


def test_runtime_session_front_desk_routes_ltm_deep_for_explicit_memory_prompt() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            source = SourceRef(
                source_id="conv_1",
                message_id="m_1",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=48,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_1",
                        canonical_text="invoice_99x was tied to the October review notes.",
                        confidence=0.92,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.92,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_1"], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What did we say last time about invoice_99x continuity?")
        assert trace.memory_route == "ltm_deep"
        assert trace.route_reason == "explicit_memory_request"
        assert retriever.queries
    finally:
        runtime.close()


def test_runtime_session_episode_retrieval_short_circuits_ltm(tmp_path: Path) -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    cards_path = tmp_path / "episode_cards.json"
    _write_episode_cards(cards_path)
    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        episode_cards_path=str(cards_path),
        episode_min_score=0.30,
        short_term_enabled=False,
    )
    try:
        trace = runtime.handle_turn("What do you remember about quarterly roadmap milestones?")
        assert trace.memory_route == "ltm_deep"
        assert trace.retrieval_stop_reason == "episode_primary_satisfied"
        assert retriever.queries == []
        assert trace.retrieved_atom_ids and trace.retrieved_atom_ids[0].startswith("episode_card:")
        assert trace.memory_cards and trace.memory_cards[0]["kind"] == "event_card"
        assert "roadmap" in str(trace.memory_cards[0].get("summary") or "").lower()
    finally:
        runtime.close()


def test_runtime_session_episode_retrieval_falls_back_to_atom_ltm(tmp_path: Path) -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            source = SourceRef(
                source_id="conv_atom",
                message_id="m_atom",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=30,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_ltm_1",
                        canonical_text="Atom-level fallback memory result.",
                        confidence=0.82,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.82,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_ltm_1"], scored_atoms=[])

    cards_path = tmp_path / "episode_cards.json"
    _write_episode_cards(cards_path)
    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        episode_cards_path=str(cards_path),
        episode_min_score=0.98,
        short_term_enabled=False,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What do you remember about invoice_99x continuity?")
        assert trace.memory_route == "ltm_deep"
        assert trace.retrieval_stop_reason != "episode_primary_satisfied"
        assert retriever.queries
        assert "atom_ltm_1" in trace.retrieved_atom_ids
    finally:
        runtime.close()


def test_runtime_session_high_risk_disables_episode_short_circuit(tmp_path: Path) -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            source = SourceRef(
                source_id="conv_safe",
                message_id="m_safe",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=32,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_safe_1",
                        canonical_text="Atom-level retrieval result under high-risk policy.",
                        confidence=0.80,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.80,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_safe_1"], scored_atoms=[])

    cards_path = tmp_path / "episode_cards.json"
    _write_episode_cards(cards_path)
    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        episode_cards_path=str(cards_path),
        episode_min_score=0.30,
        short_term_enabled=False,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn(
            "What do you remember about quarterly roadmap milestones?",
            high_risk=True,
        )
        assert trace.retrieval_stop_reason != "episode_primary_satisfied"
        assert retriever.queries
        assert "atom_safe_1" in trace.retrieved_atom_ids
    finally:
        runtime.close()


def test_runtime_session_front_desk_prioritizes_explicit_memory_over_greeting_prefix() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            source = SourceRef(
                source_id="conv_1",
                message_id="m_1",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=48,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_1",
                        canonical_text="invoice_99x was tied to the October review notes.",
                        confidence=0.92,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.92,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_1"], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("Hey, can you remember what we said about invoice_99x?")
        assert trace.memory_route == "ltm_deep"
        assert trace.route_reason == "explicit_memory_request"
        assert retriever.queries
    finally:
        runtime.close()


def test_runtime_session_front_desk_routes_none_for_casual_prompt_without_memory_signal() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("Can I ask you something quick?")
        assert trace.memory_route == "none"
        assert trace.route_reason == "casual_prompt_no_recall"
        assert trace.memory_mode == "none"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_front_desk_routes_none_for_low_signal_ambiguous_prompt() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("this topic feels odd and kind of vague today")
        assert trace.memory_route == "none"
        assert trace.route_reason == "ambiguous_low_signal_skip"
        assert trace.memory_mode == "none"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_front_desk_batch_guards_against_routine_over_trigger() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    prompts = [
        "Hey, how are you doing today?",
        "I heard a joke and wanted to share it with you.",
        "Can I ask you something quick before we continue?",
        "By the way, do you want to hear this funny thing from work?",
        "By the way, I read a long article about sleep and stress; do you want a quick summary?",
    ]

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        for prompt in prompts:
            trace = runtime.handle_turn(prompt)
            assert trace.memory_route == "none"
            assert trace.memory_mode == "none"
            assert trace.route_reason in {
                "smalltalk_routine",
                "casual_prompt_no_recall",
                "ambiguous_low_signal_skip",
            }
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_front_desk_hard_caps_routine_memory_signal_prompt() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("Can you give me a quick status of invoice_99x?")
        assert trace.memory_route == "none"
        assert trace.route_reason == "routine_hard_cap"
        assert trace.memory_mode == "none"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_chat_first_preference_reduces_memory_route() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn(
            "Can you give me a quick status of invoice_99x?",
            memory_preference="chat_first",
        )
        assert trace.memory_preference == "chat_first"
        assert trace.memory_route == "none"
        assert trace.route_reason == "memory_preference_chat_first"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_memory_assist_preference_still_respects_routine_hard_cap() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn(
            "Can I ask you something quick?",
            memory_preference="memory_assist",
        )
        assert trace.memory_preference == "memory_assist"
        assert trace.memory_route == "none"
        assert trace.route_reason == "routine_hard_cap"
        assert trace.memory_mode == "none"
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_routine_social_prompt_bank_stays_no_recall() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "routine_social_prompt_bank.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    prompts = [str(item).strip() for item in list(payload.get("prompts") or []) if str(item).strip()]
    assert prompts

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        for prompt in prompts:
            trace = runtime.handle_turn(prompt)
            assert trace.memory_route == "none"
            assert trace.memory_mode == "none"
            assert trace.route_reason in {
                "smalltalk_routine",
                "casual_prompt_no_recall",
                "ambiguous_low_signal_skip",
                "routine_hard_cap",
            }
        assert retriever.queries == []
    finally:
        runtime.close()


def test_runtime_session_preview_route_returns_reason_and_signal() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        preview = runtime.preview_route("Can I ask you something quick?")
        assert preview["route"] == "none"
        assert preview["reason"] == "casual_prompt_no_recall"
        assert preview["memory_preference"] == "auto"
        assert preview["memory_signal"] is False
        assert 0.0 <= float(preview["memory_signal_score"]) <= 1.0
        assert preview["predicted_memory_mode"] == "none"
        assert preview["will_query_ltm"] is False
        assert preview["arbitration_reason"] == "route_skip"
    finally:
        runtime.close()


def test_runtime_session_preview_route_respects_memory_preference() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        preview = runtime.preview_route(
            "Can you give me a quick status of invoice_99x?",
            memory_preference="chat_first",
        )
        assert preview["route"] == "none"
        assert preview["reason"] == "memory_preference_chat_first"
        assert preview["memory_preference"] == "chat_first"
        assert preview["memory_signal"] is True
        assert 0.0 <= float(preview["memory_signal_score"]) <= 1.0
    finally:
        runtime.close()


def test_runtime_session_preview_route_includes_session_stm_arbitration() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.35,
    )
    try:
        runtime.handle_turn("Project delta has three milestones and one blocker.", session_id="alpha")
        preview = runtime.preview_route(
            "Continue this thread about project delta blocker context.",
            session_id="alpha",
        )
        assert preview["session_id"] == "alpha"
        assert preview["route"] == "stm_only"
        assert preview["predicted_memory_mode"] == "stm_primary"
        assert preview["will_query_ltm"] is False
        assert preview["stm_hit_count"] > 0
        assert float(preview["stm_best_score"]) >= 0.0
        assert float(preview["stm_primary_threshold"]) >= 0.0
        assert preview["arbitration_reason"] == "stm_route_hit"
    finally:
        runtime.close()


def test_runtime_session_preview_route_raises_for_unknown_session() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        with pytest.raises(KeyError):
            runtime.preview_route("continue this thread", session_id="does-not-exist")
    finally:
        runtime.close()


def test_runtime_session_build_context_package_includes_stm_and_budget() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.35,
    )
    try:
        runtime.handle_turn("Project delta has three milestones and one blocker.", session_id="alpha")
        package = runtime.build_context_package(
            "Continue this thread about project delta blocker context.",
            session_id="alpha",
        )
        assert package["package_version"] == "v1"
        assert package["preview"]["route"] == "stm_only"
        assert package["working_set"]["session_id"] == "alpha"
        assert package["working_set"]["short_term_notes"] > 0
        assert package["working_set"]["short_term_hits"] > 0
        assert isinstance(package["working_set"]["top_notes"], list)
        assert package["ltm_query_plan"]["predicted_memory_mode"] == "stm_primary"
        assert package["ltm_query_plan"]["will_query_ltm"] is False
        assert package["ltm_query_plan"]["max_passes"] == runtime.ltm_max_passes
        assert package["responder_guidance"]["require_citations"] is True
    finally:
        runtime.close()


def test_runtime_session_build_context_package_raises_for_unknown_session() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        with pytest.raises(KeyError):
            runtime.build_context_package("continue this thread", session_id="does-not-exist")
    finally:
        runtime.close()


def test_runtime_session_uses_authorized_retrieval_query_override() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=False,
    )
    try:
        runtime.handle_turn(
            "short latest message",
            retrieval_query="thread context line 1\nthread context line 2\nshort latest message",
            retrieval_override=RetrievalOverrideRequestContract(
                query="thread context line 1\nthread context line 2\nshort latest message",
                invoker="tests.unit.test_runtime_session",
                reason="override_query_probe",
                scope="unit_test",
                auth_context="unit_test",
            ),
        )
        assert retriever.queries == ["thread context line 1\nthread context line 2\nshort latest message"]
    finally:
        runtime.close()


def test_runtime_session_authorized_override_forces_exact_single_pass() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=True,
        ltm_max_passes=3,
    )
    try:
        trace = runtime.handle_turn(
            "What do you remember about continuity planning?",
            retrieval_query="override continuity anchor",
            retrieval_override=RetrievalOverrideRequestContract(
                query="override continuity anchor",
                invoker="tests.unit.test_runtime_session",
                reason="override_single_pass_probe",
                scope="unit_test",
                auth_context="unit_test",
            ),
        )
        assert retriever.queries == ["override continuity anchor"]
        assert trace.retrieval_passes == 1
        assert trace.retrieval_stop_reason == "override_single_pass"
    finally:
        runtime.close()


def test_runtime_session_denies_legacy_raw_retrieval_query_without_override_context() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=False,
    )
    try:
        trace = runtime.handle_turn(
            "What do you remember about continuity planning?",
            retrieval_query="override continuity anchor",
        )
        assert retriever.queries == ["What do you remember about continuity planning?"]
        payload = runtime.trace_to_dict(trace)
        override_payload = dict(payload.get("retrieval_override") or {})
        assert override_payload.get("requested") is True
        assert override_payload.get("allowed") is False
        assert override_payload.get("applied") is False
        assert override_payload.get("denied_reason") == "missing_override_context"
    finally:
        runtime.close()


def test_runtime_session_override_cannot_bypass_routine_guard_without_explicit_memory_request() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=False,
    )
    try:
        trace = runtime.handle_turn(
            "No recall required here, just a normal reply.",
            retrieval_query="override continuity anchor",
            retrieval_override=RetrievalOverrideRequestContract(
                query="override continuity anchor",
                invoker="tests.unit.test_runtime_session",
                reason="routine_bypass_probe",
                scope="unit_test",
                auth_context="unit_test",
            ),
        )
        assert retriever.queries == []
        assert trace.memory_route == "none"
        payload = runtime.trace_to_dict(trace)
        override_payload = dict(payload.get("retrieval_override") or {})
        assert override_payload.get("requested") is True
        assert override_payload.get("allowed") is True
        assert override_payload.get("applied") is False
        assert override_payload.get("denied_reason") == "routine_guard_requires_explicit_memory_request"
    finally:
        runtime.close()


def test_retrieval_override_contract_requires_explicit_auth_context() -> None:
    with pytest.raises(ValueError, match="auth_context is required"):
        RetrievalOverrideRequestContract(
            query="override continuity anchor",
            invoker="tests.unit.test_runtime_session",
            reason="missing_auth_context_probe",
            scope="unit_test",
            auth_context="",
        )


def test_runtime_session_build_context_package_surfaces_retrieval_override_audit() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=False,
    )
    try:
        package = runtime.build_context_package(
            "What do you remember about continuity planning?",
            package_version="v2",
            retrieval_query="override continuity anchor",
            retrieval_override=RetrievalOverrideRequestContract(
                query="override continuity anchor",
                invoker="tests.unit.test_runtime_session",
                reason="package_override_probe",
                scope="unit_test",
                auth_context="unit_test",
            ),
        )
        assert retriever.queries == ["override continuity anchor"]
        override_payload = dict(package.get("retrieval_override") or {})
        assert override_payload.get("requested") is True
        assert override_payload.get("applied") is True
        stats_override = dict(dict(package.get("retrieval_stats") or {}).get("retrieval_override") or {})
        assert stats_override.get("invoker") == "tests.unit.test_runtime_session"
        assert stats_override.get("scope") == "unit_test"
    finally:
        runtime.close()


def test_runtime_session_surfaces_redacted_retrieval_diagnostics() -> None:
    store = AtomStore()
    selected_atom = store.add_candidate(
        _candidate("diag_selected", "We tracked the planning blocker in the delta thread.", "conv_diag_1")
    )
    dropped_atom = store.add_candidate(
        _candidate("diag_dropped", "An older tea preference note from a separate topic.", "conv_diag_2")
    )
    pack = memory_pack_from_items(
        [
            MemoryPackItem(
                atom_id=selected_atom.atom_id,
                canonical_text=selected_atom.canonical_text,
                confidence=0.91,
                source_refs=list(selected_atom.source_refs),
            )
        ],
        pack_confidence=0.91,
    )

    class DiagnosticRetriever:
        def __init__(self) -> None:
            self.store = store

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            return RetrievalResult(
                memory_pack=pack,
                ranked_atom_ids=[selected_atom.atom_id],
                scored_atoms=[
                    RetrievalScoredAtom(
                        atom=selected_atom,
                        score=0.91,
                        lexical=0.9,
                        semantic=0.9,
                        sequence=0.0,
                        temporal=0.0,
                        graph=0.0,
                        continuity=0.0,
                    ),
                    RetrievalScoredAtom(
                        atom=dropped_atom,
                        score=0.44,
                        lexical=0.4,
                        semantic=0.4,
                        sequence=0.0,
                        temporal=0.0,
                        graph=0.0,
                        continuity=0.0,
                    ),
                ],
                dropped_reasons={dropped_atom.atom_id: "BUDGET"},
            )

    runtime = RuntimeSession(
        retriever=DiagnosticRetriever(),  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=False,
    )
    try:
        package = runtime.build_context_package(
            "What do you remember about the planning blocker?",
            package_version="v2",
        )
        package_diagnostics = dict(package["retrieval_stats"]).get("retrieval_diagnostics")
        assert isinstance(package_diagnostics, dict)
        assert package_diagnostics["raw_text_included"] is False
        assert package_diagnostics["selected"][0]["atom_id"] == selected_atom.atom_id
        assert "canonical_text" not in package_diagnostics["selected"][0]
        assert package_diagnostics["dropped"][0]["atom_id"] == dropped_atom.atom_id
        assert package_diagnostics["dropped"][0]["reason_code"] == "BUDGET"
        assert "canonical_text" not in package_diagnostics["dropped"][0]
        assert package_diagnostics["dropped_reason_counts"] == {"BUDGET": 1}

        trace = runtime.handle_turn("What do you remember about the planning blocker?")
        payload = runtime.trace_to_dict(trace)
        diagnostics = payload.get("retrieval_diagnostics")
        assert isinstance(diagnostics, dict)
        assert diagnostics["raw_text_included"] is False
        assert diagnostics["selected_count"] == 1
        assert diagnostics["selected"][0]["atom_id"] == selected_atom.atom_id
        assert diagnostics["selected"][0]["section"] == "core"
        assert "canonical_text" not in diagnostics["selected"][0]
        assert diagnostics["dropped_count"] == 1
        assert diagnostics["dropped_reason_counts"] == {"BUDGET": 1}
        assert diagnostics["dropped"][0]["atom_id"] == dropped_atom.atom_id
        assert diagnostics["dropped"][0]["reason_code"] == "BUDGET"
        assert "canonical_text" not in diagnostics["dropped"][0]
    finally:
        runtime.close()


def test_runtime_session_multi_pass_retrieval_uses_compact_variant() -> None:
    class MultiPassRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            if len(self.queries) == 1:
                return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])
            source = SourceRef(
                source_id="conv_1",
                message_id="m_1",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=44,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_1",
                        canonical_text="invoice_99x ghostref was linked to the October continuity review.",
                        confidence=0.93,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.93,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_1"], scored_atoms=[])

    retriever = MultiPassRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=True,
        ltm_max_passes=2,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("Tell me about invoice_99x and ghostref continuity notes.")
        assert len(retriever.queries) == 2
        assert retriever.queries[0] == "Tell me about invoice_99x and ghostref continuity notes."
        assert "invoice_99x" in retriever.queries[1]
        assert "ghostref" in retriever.queries[1]
        assert trace.decision == "PASS"
    finally:
        runtime.close()


def test_runtime_session_routes_stm_primary_on_repeated_recent_prompt() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.45,
    )
    try:
        first = runtime.handle_turn("Remember this phrase: apricot tea protocol")
        assert first.memory_mode == "ltm_only"
        second = runtime.handle_turn("apricot tea protocol")
        assert second.memory_mode == "stm_primary"
        assert second.short_term_hits > 0
        assert any(atom_id.startswith("stm_") for atom_id in second.retrieved_atom_ids)
    finally:
        runtime.close()


def test_runtime_session_routes_hybrid_when_stm_hit_is_not_strong_enough() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "Apricot tea protocol requires evidence-backed checklists.", "conv_1"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.95,
    )
    try:
        runtime.handle_turn("apricot tea protocol kickoff")
        second = runtime.handle_turn("apricot protocol delta")
        assert second.memory_mode == "hybrid"
        assert second.short_term_hits > 0
        assert any(atom_id.startswith("stm_") for atom_id in second.retrieved_atom_ids)
        assert any(not atom_id.startswith("stm_") for atom_id in second.retrieved_atom_ids)
    finally:
        runtime.close()


def test_runtime_session_routes_ltm_only_when_no_stm_match_exists() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "Continuity requires evidence-backed recall.", "conv_1"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn("continuity evidence recall")
        assert trace.memory_mode == "ltm_only"
        assert trace.short_term_hits == 0
        assert all(not atom_id.startswith("stm_") for atom_id in trace.retrieved_atom_ids)
    finally:
        runtime.close()


def test_runtime_session_skips_writeback_for_synthetic_stm_ids() -> None:
    continuity = ContinuityStore()
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        short_term_primary_score=0.45,
    )
    try:
        runtime.handle_turn("Remember this phrase: lantern memory line")
        second = runtime.handle_turn("in this thread lantern memory line")
        assert second.memory_mode == "stm_primary"
        event = None
        for attempt in range(40):
            event = runtime.get_writeback(second.writeback_event_id)
            if event is not None and event.status in {"done", "failed"}:
                break
            time.sleep(0.01)
        assert event is not None and event.status in {"done", "failed"}, (
            "writeback did not complete before timeout in synthetic-stm writeback test"
        )
        assert all(not evt.atom_id.startswith("stm_") for evt in continuity.telemetry.events())
    finally:
        runtime.close()


def test_runtime_session_short_term_gate_score_uses_top_hit_not_average() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.45,
    )
    try:
        runtime.handle_turn("alpha beta gamma delta epsilon")
        runtime.handle_turn("alpha beta")
        pack, ranked_ids, hits, gate_score = runtime._retrieve_short_term("alpha beta gamma")
        assert hits >= 2
        assert ranked_ids
        top_confidence = max(item.confidence for item in pack.core)
        average_confidence = sum(item.confidence for item in pack.core) / len(pack.core)
        assert gate_score == top_confidence
        assert gate_score >= average_confidence
    finally:
        runtime.close()


def test_runtime_session_stm_uses_ngram_similarity_for_paraphrase() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.20,
        short_term_min_overlap=0.34,
        short_term_min_ngram=0.02,
        short_term_min_score=0.20,
    )
    try:
        first = runtime.handle_turn("functionltoolsartseres hammrmood memoryline")
        assert first.memory_mode == "ltm_only"
        second = runtime.handle_turn("functional tools art series hammer mood")
        assert second.memory_mode == "stm_primary"
        assert second.short_term_hits > 0
        assert any(atom_id.startswith("stm_") for atom_id in second.retrieved_atom_ids)
    finally:
        runtime.close()


def test_runtime_session_tracks_history_and_telemetry_per_session() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.35,
    )
    try:
        runtime.handle_turn("default channel warmup")
        session = runtime.start_session(label="alpha")
        session_id = str(session["session_id"])
        first = runtime.handle_turn("Project delta has three milestones and one blocker.", session_id=session_id)
        second = runtime.handle_turn("Continue this thread about project delta blocker context.", session_id=session_id)
        assert first.session_id == session_id
        assert second.session_id == session_id
        assert second.memory_route == "stm_only"
        assert second.short_term_hits > 0

        history = runtime.get_session_history(session_id)
        assert len(history) == 2
        assert [item.turn_id for item in history] == [first.turn_id, second.turn_id]

        telemetry = runtime.get_session_telemetry(session_id)
        assert telemetry["session_id"] == session_id
        assert telemetry["turn_count"] == 2
        assert sum(telemetry["route_counts"].values()) == 2
        assert telemetry["memory_preference_counts"]["auto"] == 2
        assert telemetry["memory_preference_counts"]["chat_first"] == 0
        assert telemetry["memory_preference_counts"]["memory_assist"] == 0

        default_history = runtime.get_session_history("default")
        assert len(default_history) == 1

        with pytest.raises(KeyError):
            runtime.get_session_history("missing-session")
        with pytest.raises(KeyError):
            runtime.get_session_telemetry("missing-session")
    finally:
        runtime.close()


def test_runtime_session_short_term_isolation_prevents_cross_session_leakage() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_primary_score=0.35,
    )
    try:
        left = str(runtime.start_session(label="left")["session_id"])
        right = str(runtime.start_session(label="right")["session_id"])
        runtime.handle_turn("Project delta has one blocker and two open tasks.", session_id=left)

        right_turn = runtime.handle_turn("Continue this thread about project delta blocker context.", session_id=right)
        assert right_turn.memory_route == "stm_only"
        assert right_turn.short_term_hits == 0

        left_turn = runtime.handle_turn("Continue this thread about project delta blocker context.", session_id=left)
        assert left_turn.memory_route == "stm_only"
        assert left_turn.short_term_hits > 0
    finally:
        runtime.close()


def test_runtime_session_auto_label_and_manual_rename_flow() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        created = runtime.start_session()
        session_id = str(created["session_id"])
        initial_label = str(created["label"])
        assert "·" in initial_label

        runtime.handle_turn("Atlas roadmap blockers need mitigation this week.", session_id=session_id)
        listed = [row for row in runtime.list_sessions() if str(row.get("session_id")) == session_id]
        assert listed
        auto_label = str(listed[0]["label"]).lower()
        assert "atlas" in auto_label or "blockers" in auto_label

        renamed = runtime.rename_session(session_id, label="critical-session")
        assert renamed["label"] == "critical-session"

        runtime.handle_turn("Second pass should keep manual label stable.", session_id=session_id)
        listed_after = [row for row in runtime.list_sessions() if str(row.get("session_id")) == session_id]
        assert listed_after
        assert str(listed_after[0]["label"]) == "critical-session"

        with pytest.raises(ValueError):
            runtime.rename_session(session_id, label="  ")
        with pytest.raises(KeyError):
            runtime.rename_session("missing-session", label="x")
    finally:
        runtime.close()


def test_runtime_session_rolls_evicted_notes_into_session_summary() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_capacity=4,
    )
    try:
        runtime.handle_turn("alpha marker one")
        runtime.handle_turn("beta marker two")
        runtime.handle_turn("gamma marker three")
        session = runtime._get_session("default")
        assert session is not None
        assert len(session.short_term) <= 4
        assert session.rolling_summary
        assert "alpha marker one" in session.rolling_summary
    finally:
        runtime.close()


def test_runtime_session_can_recall_from_stm_summary_after_eviction() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_capacity=2,
        short_term_primary_score=0.20,
        short_term_min_overlap=0.10,
        short_term_min_ngram=0.02,
        short_term_min_score=0.15,
        short_term_summary_match_floor=0.08,
    )
    try:
        runtime.handle_turn("crimson delta lantern protocol")
        runtime.handle_turn("filler one")
        runtime.handle_turn("filler two")
        runtime.handle_turn("filler three")
        trace = runtime.handle_turn("crimson lantern protocol check")
        assert trace.short_term_hits > 0
        assert any(atom_id.startswith("stm_summary_") for atom_id in trace.retrieved_atom_ids)
    finally:
        runtime.close()


def test_runtime_session_enforces_working_set_token_budget() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_capacity=32,
        short_term_working_set_token_limit=40,
        short_term_summary_max_chars=180,
    )
    try:
        for idx in range(8):
            runtime.handle_turn(
                f"token heavy continuity line {idx} with extra words for a working set budget pressure check"
            )
        session = runtime._get_session("default")
        assert session is not None
        assert runtime._session_working_set_tokens(session) <= runtime.short_term_working_set_token_limit
        assert session.rolling_summary
    finally:
        runtime.close()


def test_runtime_session_long_chat_keeps_stm_budget_and_recall_viable() -> None:
    """Long sessions should stay within STM caps and still support thread-local recall."""
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_capacity=12,
        short_term_working_set_token_limit=140,
        short_term_summary_max_chars=240,
        short_term_primary_score=0.20,
        short_term_min_overlap=0.10,
        short_term_min_ngram=0.02,
        short_term_min_score=0.15,
        short_term_summary_match_floor=0.08,
    )
    try:
        for idx in range(60):
            runtime.handle_turn(
                f"project timeline note {idx} keeps continuity detail and planning context active"
            )

        session = runtime._get_session("default")
        assert session is not None
        assert len(session.short_term) <= runtime.short_term_capacity
        assert runtime._session_working_set_tokens(session) <= runtime.short_term_working_set_token_limit
        assert session.rolling_summary
        assert len(session.rolling_summary) <= runtime.short_term_summary_max_chars

        trace = runtime.handle_turn("continue this thread from project timeline note 58")
        assert trace.memory_route == "stm_only"
        assert trace.short_term_hits > 0
    finally:
        runtime.close()


def test_runtime_session_ltm_card_assembly_returns_cited_cards() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c1",
            "During the October continuity review, invoice_99x was reconciled with ghostref notes and approved for archival.",
            "conv_1",
        )
    )
    store.add_candidate(
        _candidate(
            "c2",
            "You said continuity evidence should include source references in every memory-backed reply.",
            "conv_2",
        )
    )
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What do you remember about invoice_99x continuity evidence?")
        assert trace.memory_mode in {"ltm_only", "hybrid", "stm_primary"}
        assert trace.memory_cards
        assert all(card["citations"] for card in trace.memory_cards)
        assert all(str(card.get("summary_abstractive") or "").strip() for card in trace.memory_cards)
        assert all(card["kind"] in {"fact_card", "event_card", "relationship_card"} for card in trace.memory_cards)
    finally:
        runtime.close()


def test_runtime_session_ltm_cards_are_more_compact_than_raw_atom_payload() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c1",
            "In late September, continuity planning included a long-form sequence covering evidence policy, fallback handling, and a structured response rubric for memory-sensitive prompts.",
            "conv_1",
        )
    )
    store.add_candidate(
        _candidate(
            "c2",
            "The team agreed that every retained recollection should remain source-linked and reversible through explicit review controls.",
            "conv_2",
        )
    )
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("Tell me what we established about continuity planning and evidence policy.")
        assert trace.memory_cards
        atom_ids = [atom_id for atom_id in trace.retrieved_atom_ids if not atom_id.startswith("stm_")]
        raw_payload = []
        for atom_id in atom_ids:
            atom = store.get_atom(atom_id)
            raw_payload.append(
                {
                    "atom_id": atom.atom_id,
                    "atom_type": atom.atom_type.value,
                    "canonical_text": atom.canonical_text,
                    "source_refs": [
                        {
                            "source_id": ref.source_id,
                            "message_id": ref.message_id,
                            "timestamp": ref.timestamp.isoformat() if ref.timestamp else None,
                            "span_start": ref.span_start,
                            "span_end": ref.span_end,
                        }
                        for ref in atom.source_refs
                    ],
                    "entities": list(atom.entities),
                    "topics": list(atom.topics),
                    "confidence": atom.confidence,
                    "salience": atom.salience,
                    "support_count": atom.support_count,
                    "contradiction_count": atom.contradiction_count,
                    "status": atom.status.value,
                    "created_at": atom.created_at.isoformat(),
                    "updated_at": atom.updated_at.isoformat(),
                }
            )
        cards_size = len(json.dumps(trace.memory_cards, sort_keys=True))
        raw_size = len(json.dumps(raw_payload, sort_keys=True))
        assert cards_size < raw_size
    finally:
        runtime.close()


def test_runtime_session_ltm_cards_merge_related_atoms_by_source_and_kind() -> None:
    class MergeRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.a1 = self.store.add_candidate(_candidate("m1", "Invoice review kickoff covered continuity goals.", "conv_merge"))
            self.a2 = self.store.add_candidate(_candidate("m2", "Invoice review follow-up captured action owners.", "conv_merge"))
            self.a3 = self.store.add_candidate(_candidate("m3", "Invoice review closure recorded evidence links.", "conv_merge"))

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            items = [
                MemoryPackItem(
                    atom_id=self.a1.atom_id,
                    canonical_text=self.a1.canonical_text,
                    confidence=0.82,
                    source_refs=list(self.a1.source_refs),
                    conflict_state=self.a1.status.value,
                ),
                MemoryPackItem(
                    atom_id=self.a2.atom_id,
                    canonical_text=self.a2.canonical_text,
                    confidence=0.80,
                    source_refs=list(self.a2.source_refs),
                    conflict_state=self.a2.status.value,
                ),
                MemoryPackItem(
                    atom_id=self.a3.atom_id,
                    canonical_text=self.a3.canonical_text,
                    confidence=0.78,
                    source_refs=list(self.a3.source_refs),
                    conflict_state=self.a3.status.value,
                ),
            ]
            pack = memory_pack_from_items(items, pack_confidence=0.86)
            ranked_ids = [self.a1.atom_id, self.a2.atom_id, self.a3.atom_id]
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=ranked_ids, scored_atoms=[])

    retriever = MergeRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("what did we decide in the invoice review continuity thread?")
        assert trace.memory_cards
        assert len(trace.memory_cards) == 1
        card = trace.memory_cards[0]
        assert int(card["cluster_size"]) == 3
        assert len(card["atom_ids"]) == 3
        assert len(card["citations"]) == 3
    finally:
        runtime.close()


def test_runtime_session_ltm_cards_keep_conflicts_separate_from_active_cards() -> None:
    class ConflictRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.active = self.store.add_candidate(_candidate("a1", "Project arc remained active in continuity logs.", "conv_conflict"))
            self.conflict = self.store.add_candidate(_candidate("a2", "Project arc was marked outdated after contradiction review.", "conv_conflict"))

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            active_item = MemoryPackItem(
                atom_id=self.active.atom_id,
                canonical_text=self.active.canonical_text,
                confidence=0.83,
                source_refs=list(self.active.source_refs),
                conflict_state="active",
            )
            conflict_item = MemoryPackItem(
                atom_id=self.conflict.atom_id,
                canonical_text=self.conflict.canonical_text,
                confidence=0.81,
                source_refs=list(self.conflict.source_refs),
                conflict_state="contradicted",
            )
            pack = memory_pack_from_items(
                [active_item],
                conflict=[conflict_item],
                pack_confidence=0.84,
            )
            return RetrievalResult(
                memory_pack=pack,
                ranked_atom_ids=[self.active.atom_id, self.conflict.atom_id],
                scored_atoms=[],
            )

    retriever = ConflictRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("give me the latest project arc continuity status")
        assert trace.memory_cards
        contradiction_flags = {bool(item["contradiction"]) for item in trace.memory_cards}
        assert contradiction_flags == {False, True}
    finally:
        runtime.close()


def test_runtime_session_ltm_card_limit_keeps_contradictions_visible() -> None:
    class DenseRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.active_atoms = [
                self.store.add_candidate(_candidate(f"d{i}", f"Active memory line {i} for continuity coverage.", f"conv_dense_{i}"))
                for i in range(1, 8)
            ]
            self.conflict_atom = self.store.add_candidate(
                _candidate("dx", "Conflict memory line marked outdated.", "conv_dense_conflict")
            )

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            core = [
                MemoryPackItem(
                    atom_id=self.active_atoms[0].atom_id,
                    canonical_text=self.active_atoms[0].canonical_text,
                    confidence=0.82,
                    source_refs=list(self.active_atoms[0].source_refs),
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id=self.active_atoms[1].atom_id,
                    canonical_text=self.active_atoms[1].canonical_text,
                    confidence=0.81,
                    source_refs=list(self.active_atoms[1].source_refs),
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id=self.active_atoms[2].atom_id,
                    canonical_text=self.active_atoms[2].canonical_text,
                    confidence=0.80,
                    source_refs=list(self.active_atoms[2].source_refs),
                    conflict_state="active",
                ),
            ]
            context = [
                MemoryPackItem(
                    atom_id=self.active_atoms[3].atom_id,
                    canonical_text=self.active_atoms[3].canonical_text,
                    confidence=0.79,
                    source_refs=list(self.active_atoms[3].source_refs),
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id=self.active_atoms[4].atom_id,
                    canonical_text=self.active_atoms[4].canonical_text,
                    confidence=0.78,
                    source_refs=list(self.active_atoms[4].source_refs),
                    conflict_state="active",
                ),
            ]
            continuity = [
                MemoryPackItem(
                    atom_id=self.active_atoms[5].atom_id,
                    canonical_text=self.active_atoms[5].canonical_text,
                    confidence=0.77,
                    source_refs=list(self.active_atoms[5].source_refs),
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id=self.active_atoms[6].atom_id,
                    canonical_text=self.active_atoms[6].canonical_text,
                    confidence=0.76,
                    source_refs=list(self.active_atoms[6].source_refs),
                    conflict_state="active",
                ),
            ]
            conflict = [
                MemoryPackItem(
                    atom_id=self.conflict_atom.atom_id,
                    canonical_text=self.conflict_atom.canonical_text,
                    confidence=0.74,
                    source_refs=list(self.conflict_atom.source_refs),
                    conflict_state="contradicted",
                )
            ]
            pack = memory_pack_from_items(core, context=context, continuity=continuity, conflict=conflict, pack_confidence=0.83)
            ranked = [item.atom_id for item in core + context + continuity + conflict]
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=ranked, scored_atoms=[])

    retriever = DenseRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("show me dense continuity cards with contradiction context")
        assert trace.memory_cards
        assert len(trace.memory_cards) <= 6
        assert any(bool(card["contradiction"]) for card in trace.memory_cards)
    finally:
        runtime.close()


def test_runtime_session_followup_retrieval_runs_second_pass_on_weak_first_pass() -> None:
    class TwoPassRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.atom = self.store.add_candidate(
                _candidate("c1", "invoice_99x was tied to continuity evidence review notes.", "conv_1")
            )
            self.queries: list[str] = []

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            if len(self.queries) == 1:
                return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])
            scored = RetrievalScoredAtom(
                atom=self.atom,
                score=0.88,
                lexical=0.71,
                semantic=0.69,
                sequence=0.0,
                temporal=0.85,
                graph=0.40,
                continuity=0.50,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id=self.atom.atom_id,
                        canonical_text=self.atom.canonical_text,
                        confidence=0.88,
                        source_refs=list(self.atom.source_refs),
                        conflict_state=self.atom.status.value,
                    )
                ],
                pack_confidence=0.88,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=[self.atom.atom_id], scored_atoms=[scored])

    retriever = TwoPassRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=True,
        ltm_max_passes=2,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What did we say last time about invoice_99x continuity?")
        assert trace.retrieval_passes == 2
        assert trace.retrieval_stop_reason == "max_passes_reached"
        assert len(retriever.queries) == 2
    finally:
        runtime.close()


def test_runtime_session_followup_retrieval_stops_after_confident_first_pass() -> None:
    class StrongFirstPassRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.atom = self.store.add_candidate(
                _candidate("c1", "invoice_99x continuity recall remains evidence-backed.", "conv_1")
            )
            self.queries: list[str] = []

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            scored = RetrievalScoredAtom(
                atom=self.atom,
                score=0.92,
                lexical=0.84,
                semantic=0.82,
                sequence=0.0,
                temporal=0.88,
                graph=0.45,
                continuity=0.60,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id=self.atom.atom_id,
                        canonical_text=self.atom.canonical_text,
                        confidence=0.92,
                        source_refs=list(self.atom.source_refs),
                        conflict_state=self.atom.status.value,
                    )
                ],
                pack_confidence=0.92,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=[self.atom.atom_id], scored_atoms=[scored])

    retriever = StrongFirstPassRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=True,
        ltm_max_passes=2,
        ltm_followup_min_match_max=0.20,
        ltm_followup_min_pack_confidence=0.55,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What did we say last time about invoice_99x continuity and evidence?")
        assert trace.retrieval_passes == 1
        assert trace.retrieval_stop_reason in {"confidence_sufficient", "single_pass"}
        assert len(retriever.queries) == 1
    finally:
        runtime.close()


def test_runtime_session_followup_retrieval_honors_time_budget() -> None:
    class SlowRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.atom = self.store.add_candidate(
                _candidate("c1", "invoice_99x continuity review remained unresolved.", "conv_1")
            )
            self.queries: list[str] = []

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            time.sleep(0.03)
            scored = RetrievalScoredAtom(
                atom=self.atom,
                score=0.31,
                lexical=0.11,
                semantic=0.16,
                sequence=0.0,
                temporal=0.40,
                graph=0.05,
                continuity=0.20,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id=self.atom.atom_id,
                        canonical_text=self.atom.canonical_text,
                        confidence=0.31,
                        source_refs=list(self.atom.source_refs),
                        conflict_state=self.atom.status.value,
                    )
                ],
                pack_confidence=0.31,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=[self.atom.atom_id], scored_atoms=[scored])

    retriever = SlowRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=True,
        ltm_max_passes=2,
        ltm_followup_time_budget_ms=5.0,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What did we say last time about invoice_99x continuity?")
        assert trace.retrieval_passes == 1
        assert trace.retrieval_stop_reason == "time_budget_exceeded"
        assert len(retriever.queries) == 1
    finally:
        runtime.close()


def test_runtime_session_followup_retrieval_stops_on_repeated_query() -> None:
    class RepeatRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self.queries: list[str] = []

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    retriever = RepeatRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        ltm_multi_pass_enabled=True,
        ltm_max_passes=4,
        ltm_followup_time_budget_ms=2000.0,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("What do you remember about invoice_99x ghostref continuity status?")
        assert trace.retrieval_passes == 2
        assert trace.retrieval_stop_reason == "query_repeat"
        assert len(retriever.queries) == 2
        payload = runtime.trace_to_dict(trace)
        warnings = payload.get("budget", {}).get("warnings", [])
        codes = {str(item.get("code")) for item in warnings if isinstance(item, dict)}
        assert "RETRIEVAL_QUERY_REPEAT" in codes
    finally:
        runtime.close()


def test_runtime_session_budget_ledger_warns_on_threshold_overrun() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        turn_latency_warn_ms=0.1,
        turn_token_warn_limit=1,
        turn_cost_warn_limit_usd=0.0,
    )
    try:
        trace = runtime.handle_turn("A slightly longer prompt to trigger token and latency warnings.")
        payload = runtime.trace_to_dict(trace)
        budget = payload.get("budget", {})
        assert budget.get("warning_state") == "warn"
        warnings = budget.get("warnings", [])
        assert isinstance(warnings, list) and warnings
        codes = {str(item.get("code")) for item in warnings if isinstance(item, dict)}
        assert "TURN_TOKEN_HIGH" in codes
        assert "TURN_COST_HIGH" in codes
    finally:
        runtime.close()


def test_runtime_session_runtime_telemetry_summary_reports_routes_and_warnings() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("s1", "invoice_99x continuity reference exists in October notes.", "conv_1"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        turn_latency_warn_ms=0.1,
        turn_token_warn_limit=1,
        turn_cost_warn_limit_usd=0.0,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        runtime.handle_turn("Hey there.")
        runtime.handle_turn("What do you remember about invoice_99x continuity notes?")
        summary = runtime.get_runtime_telemetry_summary(limit=2)
        assert summary["turns_considered"] == 2
        assert summary["total_turns_seen"] >= 2
        assert sum(summary["route_counts"].values()) == 2
        assert summary["memory_preference_counts"]["auto"] == 2
        assert summary["memory_preference_counts"]["chat_first"] == 0
        assert summary["memory_preference_counts"]["memory_assist"] == 0
        assert isinstance(summary["warning_code_counts"], dict)
        assert summary["warn_turns"] >= 1
    finally:
        runtime.close()


def test_runtime_session_runtime_telemetry_turns_reports_latest_rows() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("s1", "invoice_99x continuity reference exists in October notes.", "conv_1"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        turn_latency_warn_ms=0.1,
        turn_token_warn_limit=1,
        turn_cost_warn_limit_usd=0.0,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        runtime.handle_turn("Hey there.")
        runtime.handle_turn("What do you remember about invoice_99x continuity notes?")
        rows = runtime.get_runtime_telemetry_turns(limit=2)
        assert len(rows) == 2
        first = rows[0]
        assert "turn_id" in first
        assert first["memory_route"] in {"none", "stm_only", "ltm_light", "ltm_deep"}
        assert isinstance(first["turn_tokens"], int)
        assert isinstance(first["turn_cost_usd"], float)
        assert first["warning_state"] in {"ok", "warn"}
        assert isinstance(first["warning_codes"], list)
    finally:
        runtime.close()
