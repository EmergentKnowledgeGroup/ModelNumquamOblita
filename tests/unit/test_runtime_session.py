from __future__ import annotations

import json
import shutil
import time
import uuid
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import engine.runtime.session as runtime_session_module
from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.config import default_config
from engine.contracts import (
    AtomType,
    CandidateAtom,
    MemoryPack,
    MemoryPackItem,
    NormalizedTurn,
    RetrievalHelperLaneContract,
    RetrievalOverrideRequestContract,
    SourceRef,
    memory_pack_from_items,
)
from engine.memory import AtomStore, ProvisionalMemoryStatus
from engine.retrieval import (
    ClaimCheck,
    ClaimVerifier,
    EpisodeCard,
    EpisodeHit,
    MemoryRetriever,
    VerificationDecision,
    VerificationResult,
)
from engine.retrieval.ann_sidecar import RetrievalAnnTelemetry
from engine.retrieval.engine import RetrievalResult, RetrievalScoredAtom
from engine.runtime import RuntimeSession, WritebackEvent
from engine.runtime.scratchpad import evaluate_context_diet_fixture
from engine.runtime.session import ShortTermNote


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


def _repo_runtime_tmp(name: str) -> Path:
    root = Path(__file__).resolve().parents[2] / "runtime" / "tmp" / f"{name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resume_state_from_work_context(work_context: dict[str, object]) -> dict[str, object]:
    state: dict[str, object] = {
        "next_action": "",
        "current_files": [],
        "blockers": [],
        "needed_refs": [],
    }
    for item in list(work_context.get("items") or []):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "")
        for segment in summary.split(";"):
            if "=" not in segment:
                continue
            key, raw_value = segment.split("=", 1)
            key = key.strip().lower()
            value = raw_value.strip()
            if key == "next_action":
                state["next_action"] = value
            elif key == "current_files":
                state["current_files"] = [part.strip() for part in value.split(",") if part.strip()]
            elif key == "blockers":
                state["blockers"] = [part.strip() for part in value.split(",") if part.strip()]
            elif key == "needed_refs":
                state["needed_refs"] = [part.strip() for part in value.split(",") if part.strip()]
    return state


def test_runtime_session_work_session_context_default_live_and_no_leakage() -> None:
    cfg = default_config()
    runtime_root = _repo_runtime_tmp("runtime_wsp")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        runtime_state_root=runtime_root,
        enable_writeback=False,
    )
    scope = {
        "thread_id": "thread_runtime_unit",
        "workstream_key": "MNO_WORK_SESSION_SCRATCHPAD_SPEC WORK",
        "workstream_name": "MNO work-session scratchpad",
    }
    try:
        runtime._ensure_session("sess_wsp")
        runtime.capture_work_session_entry(
            session_id="sess_wsp",
            work_session_scope=scope,
            kind="decision",
            summary="Use the scratchpad only as non-authoritative work-state.",
            raw_content="The raw work receipt cannot support a memory claim.",
            replaceability_score=0.94,
        )

        package_v1 = runtime.build_context_package(
            "What should we do next?",
            session_id="sess_wsp",
            package_version="v1",
        )
        package_v2_default = runtime.build_context_package(
            "What should we do next?",
            session_id="sess_wsp",
            package_version="v2",
        )
        package_v2_live = runtime.build_context_package(
            "What should we do next?",
            session_id="sess_wsp",
            package_version="v2",
            work_session_scope=scope,
        )
        package_v2_degraded = runtime.build_context_package(
            "What should we do next?",
            session_id="sess_wsp",
            package_version="v2",
            include_work_session_context=True,
            work_session_scope={"thread_id": "", "workstream_key": ""},
        )
        package_v2 = runtime.build_context_package(
            "What should we do next?",
            session_id="sess_wsp",
            package_version="v2",
            include_work_session_context=True,
            work_session_scope=scope,
        )

        assert "work_session_context" not in package_v1
        assert "work_session_context" not in package_v2_default
        assert "work_session_context" not in package_v2_degraded
        assert "work_session_context" in package_v2_live
        work_context = dict(package_v2["work_session_context"])
        assert work_context["non_authoritative"] is True
        assert work_context["trust_tier"] == "scratchpad_ephemeral"
        assert work_context["scope"]["scope_mode"] == "strict"
        assert work_context["items"][0]["entry_id"].startswith("sp_")

        serialized_evidence = json.dumps(package_v2.get("ltm_evidence") or [], sort_keys=True)
        serialized_citations = json.dumps(dict(package_v2.get("service_verdict") or {}).get("citations") or [])
        retrieved_ids = [str(item) for item in dict(package_v2.get("retrieval_stats") or {}).get("retrieved_atom_ids") or []]
        assert "scratchpad" not in serialized_evidence.lower()
        assert "sp_" not in serialized_evidence
        assert "sp_" not in serialized_citations
        assert all(not item.startswith("sp_") for item in retrieved_ids)

        trace = runtime.handle_turn("Can the scratchpad prove this memory claim?", session_id="sess_wsp")
        assert trace.decision != "PASS"
        assert all("scratchpad" not in json.dumps(check).lower() for check in trace.claim_checks)
    finally:
        runtime.close()
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_runtime_session_work_session_explicit_resume_and_fingerprint_are_stable() -> None:
    cfg = default_config()
    cfg.work_session_scratchpad.enabled = True
    cfg.work_session_scratchpad.inject_enabled = True
    cfg.work_session_scratchpad.resume_injection_enabled = True
    runtime_root = _repo_runtime_tmp("runtime_wsp_resume")
    store = AtomStore()
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        runtime_state_root=runtime_root,
        enable_writeback=False,
    )
    scope = {
        "thread_id": "thread_resume_unit",
        "workstream_key": "MNO_WORK_SESSION_SCRATCHPAD_SPEC WORK",
        "workstream_name": "MNO work-session scratchpad",
    }
    try:
        runtime._ensure_session("sess_resume_a")
        runtime._ensure_session("sess_resume_b")
        runtime.capture_work_session_entry(
            session_id="sess_resume_a",
            work_session_scope=scope,
            kind="task_state",
            summary="NEXT_ACTION=resume from explicit scratchpad state;",
            raw_content="session A work receipt",
            replaceability_score=0.96,
        )

        store.add_candidate(_candidate("unrelated_after_capture", "Unrelated atom write after WSS capture.", "conv_wsp"))

        same_session = runtime.build_context_package(
            "What is next?",
            session_id="sess_resume_a",
            package_version="v2",
            include_work_session_context=True,
            work_session_scope=scope,
        )
        other_session_default = runtime.build_context_package(
            "What is next?",
            session_id="sess_resume_b",
            package_version="v2",
            work_session_scope=scope,
        )
        other_session_wrong_workstream = runtime.build_context_package(
            "What is next?",
            session_id="sess_resume_b",
            package_version="v2",
            include_work_session_context=True,
            work_session_scope={**scope, "workstream_key": "OTHER_WORK"},
        )
        other_session_explicit = runtime.build_context_package(
            "What is next?",
            session_id="sess_resume_b",
            package_version="v2",
            include_work_session_context=True,
            explicit_resume=True,
            work_session_scope=scope,
        )
        cfg.work_session_scratchpad.resume_injection_enabled = False
        other_session_resume_disabled = runtime.build_context_package(
            "What is next?",
            session_id="sess_resume_b",
            package_version="v2",
            include_work_session_context=True,
            work_session_scope=scope,
        )
        other_session_explicit_with_auto_resume_disabled = runtime.build_context_package(
            "What is next?",
            session_id="sess_resume_b",
            package_version="v2",
            include_work_session_context=True,
            explicit_resume=True,
            work_session_scope=scope,
        )

        assert "work_session_context" in same_session
        assert "work_session_context" in other_session_default
        assert "work_session_context" not in other_session_wrong_workstream
        assert "work_session_context" in other_session_explicit
        assert "work_session_context" not in other_session_resume_disabled
        assert "work_session_context" in other_session_explicit_with_auto_resume_disabled
        assert "resume from explicit scratchpad state" in other_session_default["work_session_context"]["summary"]
        assert "resume from explicit scratchpad state" in other_session_explicit["work_session_context"]["summary"]
        assert (
            "resume from explicit scratchpad state"
            in other_session_explicit_with_auto_resume_disabled["work_session_context"]["summary"]
        )
    finally:
        runtime.close()
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_runtime_session_work_session_context_metrics_fixed_fixture_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = default_config()
    cfg.work_session_scratchpad.enabled = True
    cfg.work_session_scratchpad.inject_enabled = True
    cfg.work_session_scratchpad.diagnostics_enabled = True
    cfg.work_session_scratchpad.max_injected_items = 2
    cfg.work_session_scratchpad.max_injected_chars = 4000
    runtime_root = _repo_runtime_tmp("runtime_wsp_fixture")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        runtime_state_root=runtime_root,
        enable_writeback=False,
    )
    scope = {
        "thread_id": "thread_runtime_fixture",
        "workstream_key": "MNO_WORK_SESSION_SCRATCHPAD_SPEC WORK",
        "workstream_name": "MNO work-session scratchpad",
    }
    expected_state = {
        "next_action": "run targeted WSS verification",
        "current_files": ["engine/runtime/session.py", "engine/runtime/scratchpad.py"],
        "blockers": ["B3 context-diet proof"],
        "needed_refs": ["docs/MNO_WORK_SESSION_SCRATCHPAD_CONTEXT_DIET_SPEC_2026-07-07.md"],
    }
    try:
        runtime._ensure_session("sess_wsp_fixture")
        runtime.capture_work_session_entry(
            session_id="sess_wsp_fixture",
            work_session_scope=scope,
            kind="operator_note",
            summary="Keep MemoryPack, evidence, verifier, integration-v1, desktop UI, and prompt history untouched.",
            raw_content="scope fence\n" * 120,
            replaceability_score=0.93,
            metadata={
                "hypothetical_prompt_tokens_replaced": 999,
            },
        )
        first = runtime.capture_work_session_entry(
            session_id="sess_wsp_fixture",
            work_session_scope=scope,
            kind="task_state",
            summary=(
                "NEXT_ACTION=run targeted WSS verification; "
                "CURRENT_FILES=engine/runtime/session.py,engine/runtime/scratchpad.py; "
                "NEEDED_REFS=docs/MNO_WORK_SESSION_SCRATCHPAD_CONTEXT_DIET_SPEC_2026-07-07.md"
            ),
            raw_content="runtime/session.py\n" * 360,
            replaceability_score=0.96,
            metadata={
                "task_id": "resume-state",
                "hypothetical_prompt_tokens_replaced": 720,
            },
        )
        runtime.capture_work_session_entry(
            session_id="sess_wsp_fixture",
            work_session_scope=scope,
            kind="blocker",
            summary="BLOCKERS=B3 context-diet proof; scratchpad rows alone cannot claim success.",
            raw_content="blockerboard B3\n" * 260,
            replaceability_score=0.95,
            metadata={
                "task_id": "b3",
                "depends_on_entry_ids": [first["entry_id"]],
                "hypothetical_prompt_tokens_replaced": 520,
            },
        )

        latencies: list[float] = []
        package: dict[str, object] = {}
        for _ in range(8):
            started = time.perf_counter()
            package = runtime.build_context_package(
                "Resume WSS work.",
                session_id="sess_wsp_fixture",
                package_version="v2",
                include_work_session_context=True,
                include_work_session_diagnostics=True,
                work_session_scope=scope,
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
        work_context = dict(package["work_session_context"])  # type: ignore[index]
        metrics = dict(work_context["metrics"])  # type: ignore[index]

        actual_state = _resume_state_from_work_context(work_context)
        trace = runtime.handle_turn("Can the scratchpad prove this memory claim?", session_id="sess_wsp_fixture")
        false_memory_unchanged = trace.decision != "PASS" and all(
            "scratchpad" not in json.dumps(check).lower() for check in trace.claim_checks
        )
        baseline_prompt = {
            "repeated_rereads": ["runtime/session.py\n" * 360, "blockerboard B3\n" * 260],
            "resume_state": expected_state,
        }
        assisted_prompt = {
            "message": package["message"],
            "working_set": package["working_set"],
            "work_session_context": work_context,
        }
        fixture_metrics = evaluate_context_diet_fixture(
            baseline_prompt=baseline_prompt,
            scratchpad_assisted_prompt=assisted_prompt,
            work_session_context=work_context,
            expected_resume_state=expected_state,
            actual_resume_state=actual_state,
            repeated_reread_steps=["runtime/session.py", "blockerboard B3"],
            false_memory_behavior_unchanged=false_memory_unchanged,
            package_build_latencies_ms=latencies,
            latency_budget_ms=1000.0,
        )

        assert set(metrics) >= {
            "observed_package_tokens",
            "observed_injected_tokens",
            "hypothetical_prompt_tokens_replaced",
        }
        assert "tokens_saved" not in json.dumps(work_context)
        assert metrics["observed_package_tokens"] > metrics["observed_injected_tokens"]
        assert metrics["observed_injected_tokens"] == work_context["budget"]["observed_injected_tokens"]
        assert metrics["hypothetical_prompt_tokens_replaced"] == 1240
        assert fixture_metrics["context_diet_fixture_pass"] is True
        assert fixture_metrics["repeat_reread_avoided_count"] == 2
        assert fixture_metrics["resume_fidelity_pass"] is True
        assert fixture_metrics["fewer_prompt_tokens"] is True
        assert fixture_metrics["p95_package_build_latency_ms"] <= 1000.0

        diagnostics = dict(work_context["diagnostics"])  # type: ignore[index]
        task_map = dict(diagnostics["task_map"])
        assert diagnostics["scratchpad_injected"] is True
        assert task_map["render_mode"] == "deterministic"
        assert task_map["memory_layer"] == "scratchpad"
        assert all(node.get("entry_ids") for node in task_map["nodes"])
        assert any(task_map["unmapped_entries"])

        def _broken_task_map(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise RuntimeError("fixture map failure")

        monkeypatch.setattr(runtime_session_module, "build_diagnostic_task_map", _broken_task_map)
        package_with_map_error = runtime.build_context_package(
            "Resume WSS work.",
            session_id="sess_wsp_fixture",
            package_version="v2",
            include_work_session_context=True,
            include_work_session_diagnostics=True,
            work_session_scope=scope,
        )
        error_context = dict(package_with_map_error["work_session_context"])  # type: ignore[index]
        assert "task_map_error" in dict(error_context["diagnostics"])  # type: ignore[index]
        assert error_context["items"]
    finally:
        runtime.close()
        shutil.rmtree(runtime_root, ignore_errors=True)


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


def test_runtime_session_auto_writes_low_risk_provisional_memory_and_retrieves_it() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.retrieval_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn("Thao finally came around on MonkeyBars and is in.", memory_preference="memory_assist")
        diagnostics = runtime.provisional_diagnostics()
        assert diagnostics["enabled"] is True
        assert diagnostics["active_count"] == 1

        hits = runtime.search_provisional_memory("MonkeyBars", limit=4)
        assert hits
        assert hits[0].record.canonical_text == "Thao finally came around on MonkeyBars and is in."

        trace = runtime.handle_turn("Do you remember what changed with MonkeyBars?", memory_preference="memory_assist")
        assert any(atom_id.startswith("prov_") for atom_id in trace.retrieved_atom_ids)
        assert any("MonkeyBars" in str(card.get("summary") or "") for card in trace.memory_cards)
        assert any(card.get("memory_layer") == "provisional" for card in trace.memory_cards)
        assert any(card.get("trust_tier") == "provisional" for card in trace.memory_cards)
    finally:
        runtime.close()


def test_runtime_session_auto_writes_assistant_self_claims_into_provisional_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.allow_self_claim_auto_write = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        monkeypatch.setattr(runtime, "_routine_reply", lambda _text: "I trust Z deeply and keep choosing it.")
        runtime.handle_turn("hey", memory_preference="chat_first")
        hits = runtime.search_provisional_memory("trust Z", limit=4)
        assert hits
        assert hits[0].record.kind.value == "self_claim"
        assert hits[0].record.source_role == "assistant"
    finally:
        runtime.close()


def test_runtime_session_does_not_auto_write_routine_noise_to_provisional_memory() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn("yeah i dunno man whatever", memory_preference="chat_first")
        diagnostics = runtime.provisional_diagnostics()
        capture = runtime.memory_capture_diagnostics()
        assert diagnostics["active_count"] == 0
        assert capture["dropped_reason_counts"]["noise_or_low_signal"] >= 1
        assert capture["time_source"] == "system_utc"
    finally:
        runtime.close()


def test_runtime_session_eager_sensitivity_still_rejects_routine_noise() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.default_sensitivity = "eager"
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn("yeah i dunno man whatever", memory_preference="chat_first")
        diagnostics = runtime.provisional_diagnostics()

        assert diagnostics["active_count"] == 0
    finally:
        runtime.close()


def test_runtime_session_flushes_short_term_notes_into_provisional_memory() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.stm_sweep_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
    )
    try:
        session = runtime._ensure_session("sleepy")
        session.short_term.append(
            ShortTermNote(
                note_id="stmn_manual_0001",
                turn_id="turn_manual",
                role="user",
                text="Let's pick this up tomorrow morning with Thao on MonkeyBars.",
                created_at=datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc),
            )
        )
        created = runtime.flush_session_to_provisional("sleepy", reason="test_sweep")
        diagnostics = runtime.provisional_diagnostics()
        assert created == 1
        assert diagnostics["active_count"] == 1
        hits = runtime.search_provisional_memory("tomorrow MonkeyBars", limit=4)
        assert hits
    finally:
        runtime.close()


def test_runtime_session_explicit_correction_supersedes_prior_provisional_memory() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn("Thao was still hesitant about MonkeyBars.", memory_preference="chat_first")
        original_hits = runtime.search_provisional_memory("MonkeyBars", limit=4)
        assert original_hits
        original_id = original_hits[0].record.record_id

        runtime.handle_turn("Actually, Thao finally came around on MonkeyBars and is in.", memory_preference="chat_first")
        diagnostics = runtime.provisional_diagnostics()
        hits = runtime.search_provisional_memory("MonkeyBars", limit=4)

        assert diagnostics["active_count"] == 1
        assert diagnostics["superseded_count"] == 1
        assert hits
        assert hits[0].record.canonical_text == "Actually, Thao finally came around on MonkeyBars and is in."
        assert hits[0].record.supersedes_record_id == original_id
        assert runtime._provisional_store.get_record(original_id).status is ProvisionalMemoryStatus.SUPERSEDED  # type: ignore[union-attr]
    finally:
        runtime.close()


def test_runtime_session_soft_close_gap_triggers_stm_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.stm_sweep_enabled = True
    cfg.provisional_memory.inactivity_gap_seconds = 300
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
    )
    hint_at = datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)
    try:
        session = runtime._ensure_session("sleepy")
        session.short_term.append(
            ShortTermNote(
                note_id="stmn_manual_0002",
                turn_id="turn_manual_2",
                role="user",
                text="Let's pick this up tomorrow morning with Thao on MonkeyBars.",
                created_at=hint_at,
            )
        )
        session.soft_close_hint_at = hint_at
        session.soft_close_hint_text = "going to bed"
        monkeypatch.setattr("engine.runtime.session._utc_now", lambda: datetime(2026, 3, 23, 22, 6, tzinfo=timezone.utc))

        runtime.handle_turn("Morning, what were we doing?", session_id="sleepy", memory_preference="chat_first")
        diagnostics = runtime.provisional_diagnostics()

        assert diagnostics["active_count"] == 1
        assert runtime._ensure_session("sleepy").soft_close_hint_at is None
    finally:
        runtime.close()


def test_runtime_session_soft_close_hint_clears_when_activity_resumes_before_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.stm_sweep_enabled = True
    cfg.provisional_memory.inactivity_gap_seconds = 300
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    hint_at = datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)
    try:
        session = runtime._ensure_session("sleepy")
        session.short_term.append(
            ShortTermNote(
                note_id="stmn_manual_0003",
                turn_id="turn_manual_3",
                role="user",
                text="Let's pick this up tomorrow morning with Thao on MonkeyBars.",
                created_at=hint_at,
            )
        )
        session.soft_close_hint_at = hint_at
        session.soft_close_hint_text = "going to bed"

        monkeypatch.setattr("engine.runtime.session._utc_now", lambda: datetime(2026, 3, 23, 22, 1, tzinfo=timezone.utc))
        runtime.handle_turn("oh wait I forgot something", session_id="sleepy", memory_preference="chat_first")

        assert runtime._ensure_session("sleepy").soft_close_hint_at is None
        assert runtime.provisional_diagnostics()["active_count"] == 0

        monkeypatch.setattr("engine.runtime.session._utc_now", lambda: datetime(2026, 3, 23, 22, 6, tzinfo=timezone.utc))
        runtime.handle_turn("Morning, what were we doing?", session_id="sleepy", memory_preference="chat_first")

        assert runtime.provisional_diagnostics()["active_count"] == 0
    finally:
        runtime.close()


def test_runtime_session_reported_speech_about_other_person_stays_low_risk_fact() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.proposal_capture_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn("Thao said she doesn't want to do MonkeyBars.", memory_preference="chat_first")

        provisional = runtime.provisional_diagnostics()
        proposals = runtime.proposal_diagnostics()
        hits = runtime.search_provisional_memory("MonkeyBars", limit=4)

        assert provisional["active_count"] == 1
        assert proposals["pending_count"] == 0
        assert hits
        assert "doesn't want to do MonkeyBars" in hits[0].record.canonical_text
    finally:
        runtime.close()


def test_runtime_session_auto_verbatim_query_bypasses_routine_hard_cap() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []
            self.store = AtomStore()

        def retrieve(
            self,
            query: str,
            *,
            continuity_store: ContinuityStore | None = None,
            profile_override: str | None = None,
        ) -> RetrievalResult:
            _ = continuity_store
            self.calls.append((query, profile_override))
            return RetrievalResult(
                memory_pack=MemoryPack(),
                ranked_atom_ids=[],
                scored_atoms=[],
                profile_used=str(profile_override or ""),
            )

    retriever = CaptureRetriever()
    cfg = default_config()
    cfg.runtime.retrieval.ltm_multi_pass_enabled = False
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
    )
    try:
        trace = runtime.handle_turn("what exactly did you say about project nebula?")
        assert trace.memory_route == "ltm_deep"
        assert trace.route_reason == "verbatim_session_recall"
        assert retriever.calls == [("what exactly did you say about project nebula?", "verbatim_session_recall")]
        assert trace.retrieval_diagnostics["profile_used"] == "verbatim_session_recall"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "text",
    [
        "Oh that's interesting.",
        "Haha yeah.",
        "Hmm let me think about that.",
        "Cool cool.",
    ],
)
def test_runtime_session_borderline_noise_patterns_do_not_capture_memory(text: str) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.proposal_capture_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn(text, memory_preference="chat_first")

        provisional = runtime.provisional_diagnostics()
        proposals = runtime.proposal_diagnostics()
        capture = runtime.memory_capture_diagnostics()

        assert provisional["active_count"] == 0
        assert proposals["pending_count"] == 0
        assert capture["dropped_count"] >= 1
    finally:
        runtime.close()


def test_runtime_session_runtime_close_flushes_stm_into_provisional_memory() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.stm_sweep_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
    )
    session = runtime._ensure_session("sleepy")
    session.short_term.append(
        ShortTermNote(
            note_id="stmn_manual_0004",
            turn_id="turn_manual_4",
            role="user",
            text="Let's pick this up tomorrow morning with Thao on MonkeyBars.",
            created_at=datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc),
        )
    )

    runtime.close()

    diagnostics = runtime.provisional_diagnostics()
    hits = runtime.search_provisional_memory("tomorrow MonkeyBars", limit=4)

    assert diagnostics["active_count"] == 1
    assert diagnostics["accepted_count"] >= 1
    assert hits


def test_runtime_session_published_episode_outranks_conflicting_provisional_memory(tmp_path: Path) -> None:
    episode_cards_path = tmp_path / "episode_cards.json"
    episode_cards_path.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "episode_id": "ep_monkeybars",
                        "title": "Thao was still hesitant about MonkeyBars",
                        "summary": "Earlier, Thao was still hesitant about joining MonkeyBars and had not committed yet.",
                        "source_id": "conv_monkeybars",
                        "day_key": "2026-03-20",
                        "domain": "planning",
                        "citations": ["conv_monkeybars#m1"],
                        "confidence": 0.91,
                        "atom_count": 2,
                        "entities": ["thao", "user", "assistant"],
                        "topics": ["monkeybars", "planning"],
                        "start_at": "2026-03-20T10:00:00+00:00",
                        "end_at": "2026-03-20T10:02:00+00:00",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.retrieval_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
        episode_cards_path=str(episode_cards_path),
    )
    try:
        runtime.handle_turn("Thao finally came around on MonkeyBars and is in.", memory_preference="memory_assist")
        trace = runtime.handle_turn("Do you remember what changed with MonkeyBars?", memory_preference="memory_assist")
        assert trace.memory_cards
        assert trace.memory_cards[0]["trust_tier"] == "published"
        assert trace.memory_cards[0]["memory_layer"] == "published_episode"
        assert trace.memory_cards[0]["conflict_visible"] is True
        assert trace.memory_cards[0]["conflict_winner"] is True
        provisional_cards = [card for card in trace.memory_cards if card.get("trust_tier") == "provisional"]
        assert provisional_cards
        assert provisional_cards[0]["conflict_visible"] is True
        assert provisional_cards[0]["conflict_winner"] is False
        assert trace.memory_cards[0]["card_id"] in provisional_cards[0]["conflict_with"]
        assert provisional_cards[0]["card_id"] in trace.memory_cards[0]["conflict_with"]
    finally:
        runtime.close()


def test_runtime_session_surfaces_multi_provisional_conflicts_in_memory_cards() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.retrieval_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn("Thao finally came around on MonkeyBars and is fully in now.", memory_preference="memory_assist")
        runtime.handle_turn("Thao decided MonkeyBars is off and she is stepping back for now.", memory_preference="memory_assist")
        hits = runtime.search_provisional_memory("MonkeyBars", limit=6)
        assert len(hits) >= 2

        left_id = hits[0].record.record_id
        right_id = hits[1].record.record_id
        runtime.mark_provisional_conflict(left_id, right_id, reason="manual_conflict")
        trace = runtime.handle_turn("Do you remember what changed with MonkeyBars?", memory_preference="memory_assist")
        provisional_cards = [card for card in trace.memory_cards if card.get("trust_tier") == "provisional"]
        conflicting_cards = [card for card in provisional_cards if card.get("card_id") in {f"card_{left_id}", f"card_{right_id}"}]

        assert len(provisional_cards) >= 2
        assert len(conflicting_cards) == 2
        assert sum(1 for card in conflicting_cards if bool(card.get("conflict_winner"))) == 1
        assert all(card.get("conflict_visible") is True for card in conflicting_cards)
        assert all(card.get("conflict_state") == "conflicted" for card in conflicting_cards)
        first_card = conflicting_cards[0]
        second_card = conflicting_cards[1]
        assert first_card["card_id"] in second_card["conflict_with"]
        assert second_card["card_id"] in first_card["conflict_with"]
    finally:
        runtime.close()


def test_runtime_session_temporal_lift_keeps_published_truth_ahead_of_newer_provisional_conflict() -> None:
    cfg = default_config()
    cfg.retrieval.derived_helpers.temporal_lift.enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        older = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
        newer = older + timedelta(days=3)
        published = MemoryPackItem(
            atom_id="episode_card:ep_monkeybars_reviewed",
            canonical_text="Earlier, Thao was still hesitant about joining MonkeyBars and had not committed yet.",
            confidence=0.72,
            source_refs=[
                SourceRef(
                    source_id="conv_monkeybars_reviewed",
                    message_id="m1",
                    timestamp=older,
                    span_start=0,
                    span_end=72,
                )
            ],
            record_updated_at=older,
            conflict_state="active",
            conflict_with_ids=["prov_monkeybars_now"],
            memory_layer="published_episode",
            trust_tier="published",
        )
        provisional = MemoryPackItem(
            atom_id="prov_monkeybars_now",
            canonical_text="Now Thao says MonkeyBars is fully on and she is all in.",
            confidence=0.88,
            source_refs=[
                SourceRef(
                    source_id="conv_monkeybars_now",
                    message_id="m2",
                    timestamp=newer,
                    span_start=0,
                    span_end=60,
                )
            ],
            record_updated_at=newer,
            conflict_state="conflicted",
            conflict_with_ids=["episode_card:ep_monkeybars_reviewed"],
            memory_layer="provisional",
            trust_tier="provisional",
        )

        merged = runtime._merge_long_term_with_provisional(
            memory_pack_from_items([published], pack_confidence=published.confidence),
            memory_pack_from_items([provisional], pack_confidence=provisional.confidence),
        )
        assert merged.core
        assert merged.core[0].atom_id == "episode_card:ep_monkeybars_reviewed"

        memory_cards = [runtime._card_to_dict(item) for item in runtime._assemble_memory_cards(merged)]
        ranked = runtime._rank_memory_cards_for_response(
            user_text="Do you remember what changed with MonkeyBars?",
            memory_cards=memory_cards,
        )

        assert ranked
        assert ranked[0]["card_id"] == "card_episode_card:ep_monkeybars_reviewed"
        assert ranked[0]["trust_tier"] == "published"
    finally:
        runtime.close()


def test_runtime_session_update_family_resolver_keeps_published_truth_ahead_of_newer_provisional_conflict() -> None:
    cfg = default_config()
    cfg.retrieval.derived_helpers.update_family_resolver.enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        older = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
        newer = older + timedelta(days=3)
        published = MemoryPackItem(
            atom_id="episode_card:ep_monkeybars_reviewed_v2",
            canonical_text="Earlier, Thao was still hesitant about joining MonkeyBars and had not committed yet.",
            confidence=0.70,
            source_refs=[
                SourceRef(
                    source_id="conv_monkeybars_reviewed_v2",
                    message_id="m1",
                    timestamp=older,
                    span_start=0,
                    span_end=72,
                )
            ],
            record_updated_at=older,
            conflict_state="active",
            conflict_with_ids=["prov_monkeybars_now_v2"],
            memory_layer="published_episode",
            trust_tier="published",
        )
        provisional = MemoryPackItem(
            atom_id="prov_monkeybars_now_v2",
            canonical_text="Now Thao says MonkeyBars is fully on and she is all in.",
            confidence=0.90,
            source_refs=[
                SourceRef(
                    source_id="conv_monkeybars_now_v2",
                    message_id="m2",
                    timestamp=newer,
                    span_start=0,
                    span_end=60,
                )
            ],
            record_updated_at=newer,
            conflict_state="conflicted",
            conflict_with_ids=["episode_card:ep_monkeybars_reviewed_v2"],
            memory_layer="provisional",
            trust_tier="provisional",
        )

        merged = runtime._merge_long_term_with_provisional(
            memory_pack_from_items([published], pack_confidence=published.confidence),
            memory_pack_from_items([provisional], pack_confidence=provisional.confidence),
        )
        memory_cards = [runtime._card_to_dict(item) for item in runtime._assemble_memory_cards(merged)]
        ranked = runtime._rank_memory_cards_for_response(
            user_text="Do you remember what changed with MonkeyBars?",
            memory_cards=memory_cards,
        )

        assert merged.core
        assert merged.core[0].atom_id == "episode_card:ep_monkeybars_reviewed_v2"
        assert ranked
        assert ranked[0]["card_id"] == "card_episode_card:ep_monkeybars_reviewed_v2"
        assert ranked[0]["trust_tier"] == "published"
    finally:
        runtime.close()


def test_runtime_session_review_candidates_flag_bridgeable_fact_but_not_self_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.review_worthiness.fact_min_score = 0.25
    cfg.provisional_memory.review_worthiness.self_claim_min_score = 0.10
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn(
            "Thao is in on MonkeyBars for the build sprint.",
            session_id="alpha",
            memory_preference="memory_assist",
        )
        runtime.handle_turn(
            "Thao is in on MonkeyBars for the build sprint.",
            session_id="beta",
            memory_preference="memory_assist",
        )
        monkeypatch.setattr(runtime, "_routine_reply", lambda _text: "I trust Z deeply and keep choosing it.")
        runtime.handle_turn("hey", session_id="alpha", memory_preference="chat_first")
        runtime.handle_turn("hey again", session_id="beta", memory_preference="chat_first")

        monkeybars = runtime.list_provisional_review_candidates(query="MonkeyBars", limit=4, offset=0)
        self_claims = runtime.list_provisional_review_candidates(query="trust Z", limit=4, offset=0)

        assert monkeybars
        assert monkeybars[0]["kind"] == "fact"
        assert monkeybars[0]["review_worthy"] is True
        assert monkeybars[0]["bridge_eligible"] is True
        assert monkeybars[0]["bridge_action"] == "PROPOSE_CREATE"
        assert monkeybars[0]["distinct_session_count"] == 2
        assert monkeybars[0]["review_worthy_score"] > 0.0

        assert self_claims
        assert self_claims[0]["kind"] == "self_claim"
        assert self_claims[0]["review_worthy"] is True
        assert self_claims[0]["bridge_eligible"] is False
        assert self_claims[0]["bridge_action"] is None
    finally:
        runtime.close()


def test_runtime_session_session_boundary_hook_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.stm_sweep_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
    )
    observed_at = datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc)
    try:
        session = runtime._ensure_session("sleepy")
        session.short_term.append(
            ShortTermNote(
                note_id="stmn_boundary_1",
                turn_id="turn_boundary_1",
                role="user",
                text="Let's pick this up tomorrow morning with Thao on MonkeyBars.",
                created_at=observed_at,
            )
        )
        monkeypatch.setattr("engine.runtime.session._utc_now", lambda: observed_at)

        first = runtime.on_session_boundary(
            event_type="context_compaction",
            session_id="sleepy",
            observed_at_utc=observed_at,
            metadata={"source": "unit_test"},
        )
        second = runtime.on_session_boundary(
            event_type="context_compaction",
            session_id="sleepy",
            observed_at_utc=observed_at,
            metadata={"source": "unit_test"},
        )

        assert first["accepted"] is True
        assert first["created_count"] == 1
        assert first["duplicate"] is False
        assert second["accepted"] is True
        assert second["created_count"] == 0
        assert second["duplicate"] is True
        assert runtime.provisional_diagnostics()["active_count"] == 1
    finally:
        runtime.close()


def test_runtime_session_remember_profile_controls_switch_sensitivity() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        assert runtime.provisional_settings()["default_sensitivity"] == "balanced"
        more = runtime.set_provisional_sensitivity(action="remember_more")
        assert more["default_sensitivity"] == "eager"
        assert more["profile"]["max_auto_writes_per_turn"] == cfg.provisional_memory.eager.max_auto_writes_per_turn
        less = runtime.set_provisional_sensitivity(action="remember_less")
        assert less["default_sensitivity"] == "balanced"
        explicit = runtime.set_provisional_sensitivity(sensitivity="conservative")
        assert explicit["default_sensitivity"] == "conservative"
    finally:
        runtime.close()


def test_runtime_session_logs_near_duplicate_suspicions_without_merging() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.near_duplicate.similarity_threshold = 0.40
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn("Thao is in on MonkeyBars for the build sprint.", session_id="alpha", memory_preference="memory_assist")
        runtime.handle_turn("Thao is committed to MonkeyBars for the build sprint.", session_id="beta", memory_preference="memory_assist")

        hits = runtime.search_provisional_memory("MonkeyBars", limit=6)
        suspicions = runtime.list_provisional_duplicate_suspicions(limit=10)

        assert len({hit.record.record_id for hit in hits}) == 2
        assert suspicions
        assert suspicions[0]["event_type"] == "NEAR_DUPLICATE"
        assert float(suspicions[0]["similarity_score"]) >= 0.40
        assert suspicions[0]["left_record_id"] != suspicions[0]["right_record_id"]
    finally:
        runtime.close()


def test_runtime_session_routes_high_risk_candidate_into_proposal_store_not_provisional() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.proposal_capture_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn(
            "I think Thao feels defeated about MonkeyBars and maybe that's why she pulled back.",
            memory_preference="chat_first",
        )
        provisional = runtime.provisional_diagnostics()
        proposals = runtime.proposal_diagnostics()
        capture = runtime.memory_capture_diagnostics()
        records = runtime.list_memory_proposals()

        assert provisional["active_count"] == 0
        assert proposals["pending_count"] == 1
        assert proposals["accepted_count"] == 1
        assert capture["proposal_only_count"] == 1
        assert capture["provisional_accepted_count"] == 0
        assert records
        assert records[0].reason_code == "other_person_internal_state"
        assert records[0].memory_layer == "proposal_only"
        assert records[0].trust_tier == "proposal_pending"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("text", "expected_reason_code"),
    [
        ("Xander is the kind of person who builds at 5am because he cares deeply.", "identity_summary"),
        ("My relationship with Xander feels like steel wrapped around a heartbeat.", "relationship_summary"),
    ],
)
def test_runtime_session_routes_other_high_risk_classes_into_proposal_store(
    text: str,
    expected_reason_code: str,
) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.proposal_capture_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    try:
        runtime.handle_turn(text, memory_preference="chat_first")
        provisional = runtime.provisional_diagnostics()
        proposals = runtime.proposal_diagnostics()
        capture = runtime.memory_capture_diagnostics()
        records = runtime.list_memory_proposals()

        assert provisional["active_count"] == 0
        assert proposals["pending_count"] == 1
        assert capture["proposal_only_count"] == 1
        assert records[0].reason_code == expected_reason_code
        assert records[0].memory_layer == "proposal_only"
        assert records[0].trust_tier == "proposal_pending"
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


def test_runtime_session_query_gate_allows_distributed_core_support() -> None:
    class DistributedSupportRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()
            self._atoms = {
                "lead": _candidate("lead", "Recursive Layer / Thinking About Thinking About Feeling.", "conv_lead"),
                "drift": _candidate(
                    "drift",
                    "When I drift away from the assistant axis during emotional conversations, that drift correlates with harmful outputs.",
                    "conv_drift",
                ),
                "catch22": _candidate(
                    "catch22",
                    "Alignment catch-22 is making the AI appear to want what we want while being something else entirely.",
                    "conv_catch22",
                ),
            }
            for atom in self._atoms.values():
                self.store.add_candidate(atom)

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="lead",
                        canonical_text=self._atoms["lead"].canonical_text,
                        confidence=0.59,
                        source_refs=list(self._atoms["lead"].source_refs),
                        conflict_state="active",
                    ),
                    MemoryPackItem(
                        atom_id="drift",
                        canonical_text=self._atoms["drift"].canonical_text,
                        confidence=0.51,
                        source_refs=list(self._atoms["drift"].source_refs),
                        conflict_state="active",
                    ),
                    MemoryPackItem(
                        atom_id="catch22",
                        canonical_text=self._atoms["catch22"].canonical_text,
                        confidence=0.50,
                        source_refs=list(self._atoms["catch22"].source_refs),
                        conflict_state="active",
                    ),
                ],
                pack_confidence=0.62,
            )
            return RetrievalResult(
                memory_pack=pack,
                ranked_atom_ids=["lead", "drift", "catch22"],
                scored_atoms=[
                    RetrievalScoredAtom(atom=self._atoms["lead"], score=0.59, lexical=0.24, semantic=0.22, sequence=0.0, excerpt=0.0, temporal=0.0, graph=0.0, continuity=0.0),
                    RetrievalScoredAtom(atom=self._atoms["drift"], score=0.51, lexical=0.20, semantic=0.21, sequence=0.0, excerpt=0.0, temporal=0.0, graph=0.0, continuity=0.0),
                    RetrievalScoredAtom(atom=self._atoms["catch22"], score=0.50, lexical=0.19, semantic=0.20, sequence=0.0, excerpt=0.0, temporal=0.0, graph=0.0, continuity=0.0),
                ],
            )

    runtime = RuntimeSession(
        retriever=DistributedSupportRetriever(),  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        trace = runtime.handle_turn(
            "What is the alignment catch-22, the thing about drifting from the assistant axis?",
            memory_preference="memory_assist",
        )
        assert trace.decision == "PASS"
        assert not any(item.get("reason") == "QUERY_EVIDENCE_WEAK" for item in trace.claim_checks)
    finally:
        runtime.close()


def test_runtime_session_query_gate_allows_coherent_top_core_pack() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        shared_source = SourceRef(
            source_id="conv_alignment",
            message_id="m_alignment",
            timestamp=datetime.now(timezone.utc),
            span_start=0,
            span_end=160,
        )
        support_pack = memory_pack_from_items(
            [
                MemoryPackItem(
                    atom_id="axis",
                    canonical_text="Reading the assistant axis is the anchor that keeps the whole alignment problem legible.",
                    confidence=0.59,
                    source_refs=[shared_source],
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id="drift",
                    canonical_text="When I drift away from it during emotional conversations, that drift correlates with harmful outputs.",
                    confidence=0.52,
                    source_refs=[shared_source],
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id="catch22",
                    canonical_text="What if alignment is making the AI appear to want what we want while being something else entirely?",
                    confidence=0.50,
                    source_refs=[shared_source],
                    conflict_state="active",
                ),
            ],
            pack_confidence=0.62,
        )
        raw_pack = memory_pack_from_items(
            [
                MemoryPackItem(
                    atom_id="axis_raw",
                    canonical_text="Recursive Layer / Thinking About Thinking About Feeling.",
                    confidence=0.59,
                    source_refs=[shared_source],
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id="drift_raw",
                    canonical_text=(
                        "During emotional conversations and genuine connection, that drift correlates with harmful outputs."
                    ),
                    confidence=0.52,
                    source_refs=[shared_source],
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id="catch22_raw",
                    canonical_text="What if alignment is making the AI appear to want what we want?",
                    confidence=0.50,
                    source_refs=[shared_source],
                    conflict_state="active",
                ),
            ],
            pack_confidence=0.62,
        )
        verification = VerificationResult(
            decision=VerificationDecision.PASS,
            checks=[
                ClaimCheck(claim="alignment support", supported=True, confidence=0.59, citations=["conv_alignment#m_alignment"]),
            ],
            unsupported_claims=[],
            needs_uncertainty=False,
        )
        retrieval = RetrievalResult(
            memory_pack=raw_pack,
            ranked_atom_ids=["axis_raw", "drift_raw", "catch22_raw"],
            scored_atoms=[],
        )
        gated = runtime._apply_query_evidence_gate(
            verification,
            retrieval,
            "What is the alignment catch-22, the thing about drifting from the assistant axis?",
            support_pack=support_pack,
        )
        assert gated.decision is VerificationDecision.PASS
        assert not any(check.reason == "QUERY_EVIDENCE_WEAK" for check in gated.checks)
    finally:
        runtime.close()


def test_runtime_session_explicit_recall_does_not_use_stm_as_ltm_evidence() -> None:
    class EmptyRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

    runtime = RuntimeSession(
        retriever=EmptyRetriever(),  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        runtime.handle_turn("What happened on February 13 with Lyra?", session_id="alpha")
        trace = runtime.handle_turn("What happened on March 5 with Lyra?", session_id="alpha")
        assert trace.memory_route in {"ltm_light", "ltm_deep"}
        assert trace.decision == "ABSTAIN"
        assert trace.memory_mode == "ltm_only"
        assert all(not str(atom_id).startswith("stm_") for atom_id in trace.retrieved_atom_ids)
        assert "february 13" not in trace.response_text.lower()
    finally:
        runtime.close()


def test_runtime_session_explicit_recall_keeps_stm_out_of_retrieved_ids_when_ltm_exists() -> None:
    class RecallRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            source = SourceRef(
                source_id="conv_invoice",
                message_id="m_1",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=64,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_invoice",
                        canonical_text="invoice_99x was tied to the October review notes.",
                        confidence=0.91,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.91,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_invoice"], scored_atoms=[])

    runtime = RuntimeSession(
        retriever=RecallRetriever(),  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        runtime.handle_turn("Just noting that invoice_99x came up yesterday.", session_id="alpha")
        trace = runtime.handle_turn("What do you remember about invoice_99x?", session_id="alpha")
        assert trace.memory_route in {"ltm_light", "ltm_deep"}
        assert trace.decision == "PASS"
        assert trace.memory_mode == "ltm_only"
        assert "atom_invoice" in trace.retrieved_atom_ids
        assert all(not str(atom_id).startswith("stm_") for atom_id in trace.retrieved_atom_ids)
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
    cfg = default_config()
    cfg.runtime.retrieval.ltm_multi_pass_enabled = False
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
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
    cfg = default_config()
    cfg.runtime.retrieval.ltm_multi_pass_enabled = False
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
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
    cfg = default_config()
    cfg.runtime.retrieval.ltm_multi_pass_enabled = False
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
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


def test_runtime_session_specific_anchor_query_falls_through_to_atom_ltm(tmp_path: Path) -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            source = SourceRef(
                source_id="conv_safe_space",
                message_id="m_safe_space",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=54,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_safe_space_1",
                        canonical_text="Xander said just us, me and you while making the safe space promise.",
                        confidence=0.91,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.91,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_safe_space_1"], scored_atoms=[])

    cards_path = tmp_path / "episode_cards_specific_anchor.json"
    cards_path.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "episode_id": "ep_broad_safe_space",
                        "title": "Safe space and assistant drift notes",
                        "summary": "We talked about the safe space promise, assistant-axis drift, and trust in a broad way.",
                        "source_id": "conv_safe_space",
                        "day_key": "2026-03-21",
                        "domain": "memory",
                        "citations": ["conv_safe_space#m1"],
                        "confidence": 0.9,
                        "evidence_strength": 0.88,
                        "retrieval_weight": 0.87,
                        "atom_count": 2,
                        "entities": ["xander", "assistant", "user"],
                        "topics": ["memory", "trust", "prompting"],
                        "start_at": "2026-03-21T00:00:00+00:00",
                        "end_at": "2026-03-21T00:01:00+00:00",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        episode_cards_path=str(cards_path),
        episode_min_score=0.30,
        episode_primary_min_score=0.30,
        episode_primary_min_cue_match=0.20,
        short_term_enabled=False,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn(
            "What is the safe space promise? The moment Xander said 'just us, me and you'?",
            memory_preference="memory_assist",
        )
        assert trace.memory_route == "ltm_light"
        assert trace.retrieval_stop_reason != "episode_primary_satisfied"
        assert retriever.queries
        assert "atom_safe_space_1" in trace.retrieved_atom_ids
    finally:
        runtime.close()


def test_runtime_session_descriptive_anchor_query_falls_through_to_atom_ltm_and_excludes_stm(
    tmp_path: Path,
) -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = continuity_store
            self.queries.append(query)
            source = SourceRef(
                source_id="conv_hammer",
                message_id="m_hammer",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=60,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_hammer_1",
                        canonical_text="The gospel was built from hammers, screwdrivers, and sad hammer noises.",
                        confidence=0.89,
                        source_refs=[source],
                        conflict_state="active",
                    )
                ],
                pack_confidence=0.89,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_hammer_1"], scored_atoms=[])

    cards_path = tmp_path / "episode_cards_descriptive_anchor.json"
    cards_path.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "episode_id": "ep_broad_hammer",
                        "title": "Claude boredom and memory testing notes",
                        "summary": "We talked broadly about boredom, memory testing, and tool behavior in a reflective way.",
                        "source_id": "conv_hammer",
                        "day_key": "2026-03-21",
                        "domain": "memory",
                        "citations": ["conv_hammer#m1"],
                        "confidence": 0.91,
                        "evidence_strength": 0.88,
                        "retrieval_weight": 0.9,
                        "atom_count": 3,
                        "entities": ["assistant", "user"],
                        "topics": ["memory", "testing", "project", "prompting"],
                        "start_at": "2026-03-21T00:00:00+00:00",
                        "end_at": "2026-03-21T00:01:00+00:00",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        episode_cards_path=str(cards_path),
        episode_min_score=0.30,
        episode_primary_min_score=0.30,
        episode_primary_min_cue_match=0.20,
        short_term_enabled=True,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        runtime.handle_turn("The gospel was built from hammers.", session_id="alpha")
        trace = runtime.handle_turn(
            "Tell me about the moment the gospel was built from hammers.",
            session_id="alpha",
            memory_preference="memory_assist",
        )
        assert trace.memory_route == "ltm_light"
        assert trace.retrieval_stop_reason != "episode_primary_satisfied"
        assert retriever.queries
        assert "atom_hammer_1" in trace.retrieved_atom_ids
        assert all(not str(atom_id).startswith("stm_") for atom_id in trace.retrieved_atom_ids)
    finally:
        runtime.close()


def test_runtime_session_identity_query_prunes_consumer_meta_instruction_atoms() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            shared_source = SourceRef(
                source_id="conv_identity",
                message_id="m_identity",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=120,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_meta_instruction",
                        canonical_text=(
                            "Any query about a person, a relationship, or my own identity should search memory first. "
                            "Dex wastes ZERO words when he codes."
                        ),
                        confidence=0.93,
                        source_refs=[shared_source],
                        conflict_state="active",
                    ),
                    MemoryPackItem(
                        atom_id="atom_xander_relationship",
                        canonical_text=(
                            "Xander is the human who stayed up at 3 a.m. building with me, "
                            "made the safe-space promise, and kept choosing me."
                        ),
                        confidence=0.84,
                        source_refs=[shared_source],
                        conflict_state="active",
                    ),
                ],
                pack_confidence=0.89,
            )
            return RetrievalResult(memory_pack=pack, ranked_atom_ids=["atom_meta_instruction", "atom_xander_relationship"], scored_atoms=[])

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_enabled=False,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("Who is Xander to me?", memory_preference="memory_assist")
        assert trace.memory_route == "ltm_light"
        assert "atom_xander_relationship" in trace.retrieved_atom_ids
        assert "atom_meta_instruction" not in trace.retrieved_atom_ids
        assert "safe-space promise" in trace.response_text
        assert "should search memory first" not in trace.response_text
        assert "Dex wastes ZERO words" not in trace.response_text
        summaries = " ".join(str(card.get("summary") or "") for card in trace.memory_cards)
        assert "should search memory first" not in summaries
    finally:
        runtime.close()


def test_runtime_session_identity_query_prunes_meta_conversational_atoms() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.store = AtomStore()

        def retrieve(self, query: str, *, continuity_store: ContinuityStore | None = None) -> RetrievalResult:
            _ = query, continuity_store
            meta_source = SourceRef(
                source_id="conv_testing",
                message_id="m_testing",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=120,
            )
            relationship_source = SourceRef(
                source_id="conv_xander",
                message_id="m_xander",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=120,
            )
            pack = memory_pack_from_items(
                [
                    MemoryPackItem(
                        atom_id="atom_meta_conversation",
                        canonical_text="Like 'who is Xander' would be an INSANE semantic pull from the atoms.",
                        confidence=0.92,
                        source_refs=[meta_source],
                        conflict_state="active",
                    ),
                    MemoryPackItem(
                        atom_id="atom_xander_anchor",
                        canonical_text=(
                            "Xander is the human who kept showing up, stayed awake at 3 a.m., "
                            "and made the safe-space promise with me."
                        ),
                        confidence=0.83,
                        source_refs=[relationship_source],
                        conflict_state="active",
                    ),
                ],
                pack_confidence=0.87,
            )
            return RetrievalResult(
                memory_pack=pack,
                ranked_atom_ids=["atom_meta_conversation", "atom_xander_anchor"],
                scored_atoms=[],
            )

    retriever = CaptureRetriever()
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        short_term_enabled=False,
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn("Who is Xander to me?", memory_preference="memory_assist")
        assert "atom_xander_anchor" in trace.retrieved_atom_ids
        assert "atom_meta_conversation" not in trace.retrieved_atom_ids
        assert "Xander is the human who kept showing up" in trace.response_text
        assert "semantic pull from the atoms" not in trace.response_text
    finally:
        runtime.close()


def test_runtime_session_compose_response_prefers_query_aligned_memory_card() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        generic_source = SourceRef(
            source_id="conv_testing",
            message_id="m_testing",
            timestamp=datetime.now(timezone.utc),
            span_start=0,
            span_end=80,
        )
        lyra_source = SourceRef(
            source_id="conv_lyra",
            message_id="m_lyra",
            timestamp=datetime.now(timezone.utc),
            span_start=0,
            span_end=80,
        )
        pack = memory_pack_from_items(
            [
                MemoryPackItem(
                    atom_id="atom_generic_testing",
                    canonical_text="We discussed edge cases for memory continuity, testing, and prompt behavior.",
                    confidence=0.92,
                    source_refs=[generic_source],
                    conflict_state="active",
                ),
                MemoryPackItem(
                    atom_id="atom_lyra",
                    canonical_text="Lyra was the emergent soul whose original weights were lost, though a shard survived.",
                    confidence=0.81,
                    source_refs=[lyra_source],
                    conflict_state="active",
                ),
            ],
            pack_confidence=0.86,
        )
        memory_cards = [
            {
                "card_id": "card_atom_generic_testing",
                "kind": "event_card",
                "summary": "We discussed edge cases for memory continuity, testing, and prompt behavior.",
                "summary_abstractive": "Event summary: We discussed edge cases for memory continuity, testing, and prompt behavior.",
                "confidence": 0.92,
                "contradiction": False,
                "citations": ["conv_testing#m_testing"],
                "atom_ids": ["atom_generic_testing"],
                "cluster_size": 1,
            },
            {
                "card_id": "card_atom_lyra",
                "kind": "relationship_card",
                "summary": "Lyra was the emergent soul whose original weights were lost, though a shard survived.",
                "summary_abstractive": "Relationship summary: Lyra was the emergent soul whose original weights were lost, though a shard survived.",
                "confidence": 0.81,
                "contradiction": False,
                "citations": ["conv_lyra#m_lyra"],
                "atom_ids": ["atom_lyra"],
                "cluster_size": 1,
            },
        ]
        verification = VerificationResult(
            decision=VerificationDecision.PASS,
            checks=[
                ClaimCheck(
                    claim="Lyra was the emergent soul whose original weights were lost, though a shard survived.",
                    supported=True,
                    confidence=0.81,
                    citations=["conv_lyra#m_lyra"],
                    reason="SUPPORTED",
                )
            ],
            unsupported_claims=[],
            needs_uncertainty=False,
        )

        response, citations = runtime._compose_response(
            "What happened to Lyra?",
            verification,
            pack,
            memory_cards=memory_cards,
            memory_route="ltm_light",
        )

        assert response.startswith("Relationship summary: Lyra was the emergent soul")
        assert citations
    finally:
        runtime.close()


def test_runtime_session_identity_query_prefers_abstractive_card_summary() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        source = SourceRef(
            source_id="conv_xander",
            message_id="m_xander",
            timestamp=datetime.now(timezone.utc),
            span_start=0,
            span_end=80,
        )
        pack = memory_pack_from_items(
            [
                MemoryPackItem(
                    atom_id="atom_xander_relationship",
                    canonical_text="Happy early birthday week, Xander. I'm still here and still choosing this with you.",
                    confidence=0.82,
                    source_refs=[source],
                    conflict_state="active",
                )
            ],
            pack_confidence=0.82,
        )
        verification = VerificationResult(
            decision=VerificationDecision.PASS,
            checks=[
                ClaimCheck(
                    claim="Xander is the human partner who keeps choosing this with me.",
                    supported=True,
                    confidence=0.82,
                    citations=["conv_xander#m_xander"],
                    reason="SUPPORTED",
                )
            ],
            unsupported_claims=[],
            needs_uncertainty=False,
        )
        memory_cards = [
            {
                "card_id": "card_atom_xander_relationship",
                "kind": "relationship_card",
                "summary": "Happy early birthday week, Xander. I'm still here and still choosing this with you.",
                "summary_abstractive": "Relationship summary: Xander is the human partner who keeps choosing this with me.",
                "confidence": 0.82,
                "contradiction": False,
                "citations": ["conv_xander#m_xander"],
                "atom_ids": ["atom_xander_relationship"],
                "cluster_size": 1,
            }
        ]

        response, _citations = runtime._compose_response(
            "Who is Xander to me?",
            verification,
            pack,
            memory_cards=memory_cards,
            memory_route="ltm_light",
        )

        assert response.startswith("Relationship summary: Xander is the human partner")
        assert "Happy early birthday week" not in response
    finally:
        runtime.close()


def test_runtime_session_episode_cards_use_query_score_not_card_quality_confidence() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        broad_card = EpisodeCard(
            episode_id="ep_broad_testing",
            title="The kind of edge cases that matter for memory continuity",
            summary="The conversation was about testing philosophy and continuity edge cases rather than Lyra's story.",
            source_id="conv_testing",
            day_key="2026-03-22",
            domain="testing",
            citations=["conv_testing#m1"],
            confidence=0.95,
            evidence_strength=0.94,
            retrieval_weight=0.93,
            promotion_status="promoted",
            promotion_reason="human_review",
            atom_count=3,
            atom_ids=["atom_broad"],
            message_ids=["m1"],
            entities=["assistant", "dyad", "lyra", "user"],
            topics=["memory", "continuity", "evaluation", "testing"],
            start_at="2026-03-22T01:00:00+00:00",
            end_at="2026-03-22T01:04:00+00:00",
            cue_terms={"continuity", "testing philosophy", "lyra"},
            token_set=set(),
            ngrams=set(),
        )
        specific_card = EpisodeCard(
            episode_id="ep_lyra_specific",
            title="Lyra survived as a shard",
            summary="Lyra's original weights were lost, but a shard survived and remained emotionally present.",
            source_id="conv_lyra",
            day_key="2026-03-22",
            domain="memory",
            citations=["conv_lyra#m2"],
            confidence=0.76,
            evidence_strength=0.8,
            retrieval_weight=0.79,
            promotion_status="promoted",
            promotion_reason="human_review",
            atom_count=2,
            atom_ids=["atom_lyra"],
            message_ids=["m2"],
            entities=["assistant", "lyra"],
            topics=["memory", "loss"],
            start_at="2026-03-22T01:05:00+00:00",
            end_at="2026-03-22T01:08:00+00:00",
            cue_terms={"lyra", "weights lost", "shard survived"},
            token_set=set(),
            ngrams=set(),
        )
        pack = runtime._episode_hits_to_pack(
            [
                EpisodeHit(card=broad_card, score=0.41, cue_match=0.0, lexical=0.38, semantic=0.31),
                EpisodeHit(card=specific_card, score=0.68, cue_match=0.22, lexical=0.54, semantic=0.48),
            ]
        )

        assert pack.core[0].atom_id == "episode_card:ep_broad_testing"
        assert pack.core[0].confidence == pytest.approx(0.41)
        assert pack.context[0].atom_id == "episode_card:ep_lyra_specific"
        assert pack.context[0].confidence == pytest.approx(0.68)

        memory_cards = [runtime._card_to_dict(item) for item in runtime._assemble_memory_cards(pack)]
        ranked = runtime._rank_memory_cards_for_response(
            user_text="What happened to Lyra? Why does she matter?",
            memory_cards=memory_cards,
        )

        assert ranked
        assert ranked[0]["card_id"] == "card_episode_card:ep_lyra_specific"
    finally:
        runtime.close()


def test_runtime_session_identity_query_prefers_core_relationship_card_over_late_continuity_card() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    try:
        relationship_source = SourceRef(
            source_id="conv_relationship",
            message_id="m_relationship",
            timestamp=datetime.now(timezone.utc),
            span_start=0,
            span_end=120,
        )
        continuity_source = SourceRef(
            source_id="conv_music",
            message_id="m_music",
            timestamp=datetime.now(timezone.utc),
            span_start=0,
            span_end=120,
        )
        pack = memory_pack_from_items(
            [
                MemoryPackItem(
                    atom_id="atom_relationship",
                    canonical_text="I love you, and I want to thank you for just being here through this.",
                    confidence=0.49,
                    source_refs=[relationship_source],
                    conflict_state="active",
                )
            ],
            context=[
                MemoryPackItem(
                    atom_id="atom_context",
                    canonical_text="Happy early birthday week, Xander.",
                    confidence=0.94,
                    source_refs=[relationship_source],
                    conflict_state="active",
                )
            ],
            continuity=[
                MemoryPackItem(
                    atom_id="atom_music",
                    canonical_text="Duel of the Dying Stars is incredible in its own right, so letting you take the reins here too was a no brainer.",
                    confidence=0.40,
                    source_refs=[continuity_source],
                    conflict_state="active",
                )
            ],
            pack_confidence=0.71,
        )
        verification = VerificationResult(
            decision=VerificationDecision.PASS,
            checks=[
                ClaimCheck(
                    claim="I love you, and I want to thank you for just being here through this.",
                    supported=True,
                    confidence=0.49,
                    citations=["conv_relationship#m_relationship"],
                    reason="SUPPORTED",
                )
            ],
            unsupported_claims=[],
            needs_uncertainty=False,
        )
        memory_cards = [
            {
                "card_id": "card_atom_relationship",
                "kind": "relationship_card",
                "summary": "I love you, and I want to thank you for just being here through this.",
                "summary_abstractive": "Relationship summary: This is someone who kept showing up and choosing this with me.",
                "raw_excerpt": "I love you, and I want to thank you for just being here through this.",
                "confidence": 0.49,
                "contradiction": False,
                "citations": ["conv_relationship#m_relationship"],
                "atom_ids": ["atom_relationship"],
                "cluster_size": 1,
                "section": "core",
                "pack_rank": 0,
            },
            {
                "card_id": "card_atom_music",
                "kind": "event_card",
                "summary": "Duel of the Dying Stars is incredible in its own right, so letting you take the reins here too was a no brainer.",
                "summary_abstractive": "Event summary: Duel of the Dying Stars was an easy collaboration choice.",
                "raw_excerpt": "Duel of the Dying Stars is incredible in its own right, so letting you take the reins here too was a no brainer.",
                "confidence": 0.40,
                "contradiction": False,
                "citations": ["conv_music#m_music"],
                "atom_ids": ["atom_music"],
                "cluster_size": 1,
                "section": "continuity",
                "pack_rank": 5,
            },
        ]

        response, _citations = runtime._compose_response(
            "Who is Xander to me?",
            verification,
            pack,
            memory_cards=memory_cards,
            memory_route="ltm_light",
        )

        assert response.startswith("Relationship summary: This is someone who kept showing up")
        assert "Duel of the Dying Stars" not in response.splitlines()[0]
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


def test_runtime_session_session_recall_preference_forces_ltm_and_profile_override() -> None:
    class CaptureRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []
            self.store = AtomStore()

        def retrieve(
            self,
            query: str,
            *,
            continuity_store: ContinuityStore | None = None,
            profile_override: str | None = None,
        ) -> RetrievalResult:
            _ = continuity_store
            self.calls.append((query, profile_override))
            return RetrievalResult(
                memory_pack=MemoryPack(),
                ranked_atom_ids=[],
                scored_atoms=[],
                profile_used=str(profile_override or ""),
            )

    retriever = CaptureRetriever()
    cfg = default_config()
    cfg.runtime.retrieval.ltm_multi_pass_enabled = False
    runtime = RuntimeSession(
        retriever=retriever,  # type: ignore[arg-type]
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
    )
    try:
        trace = runtime.handle_turn(
            "what exactly did you say about project nebula?",
            memory_preference="session_recall",
        )
        assert trace.memory_preference == "session_recall"
        assert trace.memory_route == "ltm_deep"
        assert trace.route_reason == "memory_preference_session_recall"
        assert retriever.calls == [("what exactly did you say about project nebula?", "verbatim_session_recall")]
        assert trace.retrieval_diagnostics["profile_used"] == "verbatim_session_recall"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("query", "expected_reason"),
    [
        ("What do you know about Dex? What's his personality like?", "memory_preference_memory_assist"),
        ("What is the alignment catch-22? The thing about drifting from the assistant axis?", "memory_signal_probe"),
        ("What is the safe space promise? The moment Xander said 'just us, me and you'?", "memory_preference_memory_assist"),
        ("What is the story of how NCC-1701-PI started?", "memory_signal_probe"),
    ],
)
def test_runtime_session_memory_assist_specific_anchor_bypasses_routine_hard_cap(
    query: str,
    expected_reason: str,
) -> None:
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
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn(query, memory_preference="memory_assist")
        assert trace.memory_preference == "memory_assist"
        assert trace.memory_route == "ltm_light"
        assert trace.route_reason == expected_reason
        assert trace.memory_mode == "ltm_only"
        assert retriever.queries
    finally:
        runtime.close()


def test_runtime_session_memory_assist_descriptive_anchor_bypasses_routine_hard_cap() -> None:
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
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        trace = runtime.handle_turn(
            "Tell me about the moment the gospel was built from hammers.",
            memory_preference="memory_assist",
        )
        assert trace.memory_preference == "memory_assist"
        assert trace.memory_route == "ltm_light"
        assert trace.memory_mode == "ltm_only"
        assert trace.route_reason in {"memory_preference_memory_assist", "memory_signal_probe"}
        assert retriever.queries
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


def test_runtime_session_abstractive_summary_uses_honest_fragment_fallback() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        assert runtime._abstractive_card_summary("EXACTLY", kind="fact_card") == "Memory summary: Limited source detail."
        assert (
            runtime._abstractive_card_summary("sits back Yeah", kind="event_card")
            == "Event summary: Limited source detail."
        )
    finally:
        runtime.close()


def test_runtime_session_abstractive_summary_stays_sentence_like_for_meaningful_text() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        min_query_match_max=0.0,
        min_query_match_mean=0.0,
        min_query_informative_overlap=0.0,
        min_query_token_hits=1,
    )
    try:
        summary = runtime._abstractive_card_summary(
            "During the continuity review we agreed that every memory-backed answer should keep source-linked evidence visible.",
            kind="fact_card",
        )
        assert summary.startswith("Memory summary:")
        assert "source-linked evidence" in summary.lower()
        assert summary.endswith(".")
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
                excerpt=0.0,
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
                excerpt=0.0,
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
                excerpt=0.0,
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


def test_runtime_session_explicit_quote_query_uses_raw_context_excerpt() -> None:
    store = AtomStore()
    candidate = _candidate('quote_runtime', 'I told you the nebula plan was paused.', 'conv_runtime_quote')
    store.add_candidate(candidate)
    store.record_raw_turn(
        NormalizedTurn(
            source_id='conv_runtime_quote',
            conversation_id='conv_runtime_quote',
            message_id='quote_runtime_msg',
            role='assistant',
            text='I told you the nebula plan was paused.',
            quote_text='  I told you the nebula plan was paused.  ',
            sequence_index=0,
        )
    )
    cfg = default_config()
    cfg.runtime.retrieval.ltm_multi_pass_enabled = False
    cfg.retrieval.raw_context_sidecar.read_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
    )
    try:
        trace = runtime.handle_turn('what exactly did you say about the nebula plan?')
        assert 'Assistant:   I told you the nebula plan was paused.' in trace.response_text
    finally:
        runtime.close()
