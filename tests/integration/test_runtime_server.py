from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.config import default_config
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


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
        confidence=0.86,
        salience=0.7,
    )


def _json_get(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme}")
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_post(url: str, payload: dict) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme}")
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_post_error(url: str, payload: dict) -> tuple[int, dict]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme}")
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


def _text_get(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme}")
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _json_get_error(url: str) -> tuple[int, dict]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme}")
    try:
        with urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


def test_runtime_http_server_end_to_end() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity should always include citations.", "conv_2"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        state = _json_get(f"{base}/api/state")
        assert state["ok"] is True
        assert state["stats"]["stm_primary_turns"] == 0
        assert state["stats"]["hybrid_turns"] == 0
        assert state["stats"]["ltm_only_turns"] == 0
        assert state["stats"]["route_none_turns"] == 0
        assert state["stats"]["route_stm_only_turns"] == 0
        assert state["stats"]["route_ltm_light_turns"] == 0
        assert state["stats"]["route_ltm_deep_turns"] == 0
        assert state["stats"]["recognition_events"] == 0
        assert state["stats"]["recognition_rate"] == 0.0
        preview = _json_post(
            f"{base}/api/chat/route-preview",
            {"message": "Can you give me a quick status of invoice_99x?", "memory_preference": "chat_first"},
        )
        assert preview["ok"] is True
        assert preview["preview"]["route"] == "none"
        assert preview["preview"]["reason"] == "memory_preference_chat_first"
        assert preview["preview"]["memory_preference"] == "chat_first"
        assert preview["preview"]["memory_signal"] is True
        assert 0.0 <= float(preview["preview"]["memory_signal_score"]) <= 1.0
        chat = _json_post(f"{base}/api/chat", {"message": "What do you remember about continuity?"})
        assert chat["ok"] is True
        assert chat["turn"]["memory_mode"] in {"none", "stm_primary", "hybrid", "ltm_only"}
        assert chat["turn"]["memory_route"] in {"none", "stm_only", "ltm_light", "ltm_deep"}
        assert isinstance(chat["turn"]["route_reason"], str) and chat["turn"]["route_reason"]
        assert isinstance(chat["turn"]["retrieval_passes"], int)
        assert isinstance(chat["turn"]["retrieval_stop_reason"], str) and chat["turn"]["retrieval_stop_reason"]
        turn_id = chat["turn"]["turn_id"]
        chat_first = _json_post(
            f"{base}/api/chat",
            {
                "message": "Can you give me a quick status of invoice_99x?",
                "memory_preference": "chat_first",
            },
        )
        assert chat_first["turn"]["memory_preference"] == "chat_first"
        assert chat_first["turn"]["memory_route"] == "none"
        assert chat_first["turn"]["route_reason"] == "memory_preference_chat_first"
        for _ in range(20):
            turn = _json_get(f"{base}/api/turns/{turn_id}")
            if turn["turn"].get("writeback", {}).get("status") in {"done", "failed"}:
                break
            time.sleep(0.05)
        turns = _json_get(f"{base}/api/turns")
        assert turns["ok"] is True
        assert any(item["turn_id"] == turn_id for item in turns["turns"])
        state_after = _json_get(f"{base}/api/state")
        assert state_after["stats"]["turns"] == 2
        assert "recognition_events" in state_after["stats"]
        assert "recognition_rate" in state_after["stats"]
        assert (
            state_after["stats"]["stm_primary_turns"]
            + state_after["stats"]["hybrid_turns"]
            + state_after["stats"]["ltm_only_turns"]
        ) == 1
        assert (
            state_after["stats"]["route_none_turns"]
            + state_after["stats"]["route_stm_only_turns"]
            + state_after["stats"]["route_ltm_light_turns"]
            + state_after["stats"]["route_ltm_deep_turns"]
        ) == 2
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_http_server_uses_non_daemon_server_thread_defaults() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        enable_writeback=False,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    try:
        assert thread.daemon is False
        assert getattr(server, "daemon_threads", None) is True
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_health_exposes_binding_and_desktop_shutdown(tmp_path: Path) -> None:
    store = AtomStore()
    store.add_candidate(_candidate("h1", "Desktop shell runtime should report its binding cleanly.", "conv_h1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    runtime.episode_cards_path = str((tmp_path / "episode_cards.reviewed.json").resolve())
    Path(runtime.episode_cards_path).write_text(json.dumps({"schema": "numquamoblita.episode_cards.reviewed.v1", "cards": []}) + "\n", encoding="utf-8")
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    server.runtime_version = "0.1.0-test"
    server.runtime_launch_mode = "setup_mode"
    server.active_runtime_binding = {
        "store_path": str((tmp_path / "atoms.sqlite3").resolve()),
        "store_fingerprint": "runtime_store_sig",
        "episodes_path": runtime.episode_cards_path,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backend": "sqlite",
        "artifact_mode": "setup",
        "build_id": "",
    }
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        health = _json_get(f"{base}/api/runtime/health")
        assert health["ok"] is True
        assert health["service"] == "modelnumquamoblita-runtime"
        assert health["runtime_version"] == "0.1.0-test"
        assert health["launch_mode"] == "setup_mode"
        assert health["runtime_url"] == base
        assert health["binding"]["store_fingerprint"] == "runtime_store_sig"

        shutdown = _json_post(f"{base}/api/runtime/desktop/shutdown", {})
        assert shutdown["ok"] is True
        assert shutdown["status"] == "stopping"

        for _ in range(40):
            if thread.is_alive():
                time.sleep(0.05)
                continue
            break
        assert thread.is_alive() is False
        assert server.desktop_shutdown_requested is True
        assert server.socket.fileno() == -1
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_default_binding_uses_store_validation_fingerprint_contract(tmp_path: Path) -> None:
    store_path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(store_path)
    try:
        store.add_candidate(_candidate("bind_1", "Runtime binding should match wizard store fingerprints.", "conv_bind"))
        continuity = ContinuityStore()
        continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
        runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
        server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
        try:
            binding = dict(getattr(server, "active_runtime_binding", {}) or {})
            assert str(binding.get("store_fingerprint") or "").startswith("sqlite_store:v3:")
        finally:
            stop_runtime_server(server, thread, runtime=runtime)
    finally:
        store.close()


def test_runtime_http_server_session_endpoints_roundtrip() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        short_term_primary_score=0.35,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/chat/session/start", {"label": "alpha"})
        assert started["ok"] is True
        session_id = str(started["session"]["session_id"])
        assert session_id.startswith("sess_")
        renamed = _json_post(f"{base}/api/chat/session/{session_id}/label", {"label": "alpha-renamed"})
        assert renamed["ok"] is True
        assert renamed["session"]["label"] == "alpha-renamed"

        first = _json_post(
            f"{base}/api/chat/session/{session_id}/turn",
            {"message": "Project delta has three milestones and one blocker."},
        )
        second = _json_post(
            f"{base}/api/chat/session/{session_id}/turn",
            {"message": "Continue this thread about project delta blocker context."},
        )
        preview = _json_post(
            f"{base}/api/chat/route-preview",
            {"message": "Continue this thread about project delta blocker context.", "session_id": session_id},
        )
        package = _json_post(
            f"{base}/api/chat/context-package",
            {"message": "Continue this thread about project delta blocker context.", "session_id": session_id},
        )
        package_v2 = _json_post(
            f"{base}/api/chat/context-package",
            {"message": "Remember the blocker detail.", "session_id": session_id, "package_version": "v2"},
        )
        third = _json_post(
            f"{base}/api/chat",
            {"message": "Continue this thread about project delta blocker context.", "session_id": session_id},
        )
        assert first["turn"]["session_id"] == session_id
        assert second["turn"]["session_id"] == session_id
        assert third["turn"]["session_id"] == session_id
        assert second["turn"]["memory_route"] == "stm_only"
        assert second["turn"]["short_term_hits"] > 0
        assert preview["ok"] is True
        assert preview["preview"]["session_id"] == session_id
        assert preview["preview"]["route"] == "stm_only"
        assert preview["preview"]["predicted_memory_mode"] == "stm_primary"
        assert preview["preview"]["will_query_ltm"] is False
        assert preview["preview"]["stm_hit_count"] > 0
        assert 0.0 <= float(preview["preview"]["stm_best_score"]) <= 1.0
        assert float(preview["preview"]["stm_primary_threshold"]) >= 0.0
        assert package["ok"] is True
        assert package["package"]["package_version"] == "v1"
        assert package["package"]["working_set"]["session_id"] == session_id
        assert package["package"]["working_set"]["short_term_notes"] > 0
        assert package["package"]["working_set"]["short_term_hits"] > 0
        assert package["package"]["ltm_query_plan"]["predicted_memory_mode"] == "stm_primary"
        assert package["package"]["ltm_query_plan"]["will_query_ltm"] is False
        assert package["package"]["responder_guidance"]["require_citations"] is True
        assert package["package"]["responder_guidance"]["render_citations"] is False

        assert package_v2["ok"] is True
        assert package_v2["package"]["package_version"] == "v2"
        assert "ltm_evidence" in package_v2["package"]
        assert "service_verdict" in package_v2["package"]
        assert package_v2["package"]["responder_guidance"]["render_citations"] is False
        assert "timing_ms" in package_v2["package"]
        assert "evidence_sections_present" in package_v2["package"]
        assert "evidence_time_window" in package_v2["package"]
        assert "episode_evidence_present" in package_v2["package"]["retrieval_stats"]

        history = _json_get(f"{base}/api/chat/session/{session_id}/history")
        assert history["ok"] is True
        assert len(history["history"]) == 3
        assert all(item["session_id"] == session_id for item in history["history"])

        telemetry = _json_get(f"{base}/api/chat/session/{session_id}/telemetry")
        assert telemetry["ok"] is True
        assert telemetry["telemetry"]["turn_count"] == 3
        assert sum(telemetry["telemetry"]["route_counts"].values()) == 3
        assert telemetry["telemetry"]["memory_preference_counts"]["auto"] == 3
        assert telemetry["telemetry"]["memory_preference_counts"]["chat_first"] == 0
        assert telemetry["telemetry"]["memory_preference_counts"]["memory_assist"] == 0

        missing_history_status, missing_history_payload = _json_get_error(
            f"{base}/api/chat/session/does-not-exist/history"
        )
        assert missing_history_status == 404
        assert missing_history_payload["error"] == "session not found"

        missing_telemetry_status, missing_telemetry_payload = _json_get_error(
            f"{base}/api/chat/session/does-not-exist/telemetry"
        )
        assert missing_telemetry_status == 404
        assert missing_telemetry_payload["error"] == "session not found"
        missing_preview_status, missing_preview_payload = _json_post_error(
            f"{base}/api/chat/route-preview",
            {"message": "Continue this thread", "session_id": "does-not-exist"},
        )
        assert missing_preview_status == 404
        assert missing_preview_payload["error"] == "session not found"
        missing_package_status, missing_package_payload = _json_post_error(
            f"{base}/api/chat/context-package",
            {"message": "Continue this thread", "session_id": "does-not-exist"},
        )
        assert missing_package_status == 404
        assert missing_package_payload["error"] == "session not found"

        sessions = _json_get(f"{base}/api/chat/sessions")
        assert sessions["ok"] is True
        assert any(item["session_id"] == session_id for item in sessions["sessions"])
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_http_server_quicknote_and_whats_new_roundtrip() -> None:
    unique = str(time.time_ns())
    assistant_id = f"claude_{unique}"
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status0 = _json_get(f"{base}/api/memory/quicknote/status?assistant_id={assistant_id}&session_id=sess_a")
        assert status0["ok"] is True
        assert status0["status"]["pending_count"] == 0

        proposed = _json_post(
            f"{base}/api/memory/quicknote/propose",
            {
                "assistant_id": assistant_id,
                "session_id": "sess_a",
                "text": f"Remember that citation context defaults to ±3. [{unique}]",
                "importance": "high",
                "tags": ["citations", "defaults"],
            },
        )
        assert proposed["ok"] is True
        assert proposed["accepted"] is True

        status1 = _json_get(f"{base}/api/memory/quicknote/status?assistant_id={assistant_id}&session_id=sess_a")
        assert status1["status"]["pending_count"] == 1

        first_delta = None
        for _ in range(20):
            candidate = _json_get(f"{base}/api/explore/whats-new?assistant_id={assistant_id}")
            assert candidate["ok"] is True
            if candidate["cursor"]["advanced"] is True and candidate["changes"]["added_count"] >= 1:
                first_delta = candidate
                break
            time.sleep(0.05)
        assert first_delta is not None

        second_delta = _json_get(f"{base}/api/explore/whats-new?assistant_id={assistant_id}")
        assert second_delta["ok"] is True
        assert second_delta["changes"]["added_count"] == 0

        _json_post(
            f"{base}/api/memory/quicknote/propose",
            {
                "assistant_id": assistant_id,
                "session_id": "sess_a",
                "text": f"Remember that deep review can use ±5 context windows. [{unique}]",
                "importance": "normal",
                "tags": ["citations"],
            },
        )
        peek_delta = _json_get(f"{base}/api/explore/whats-new?assistant_id={assistant_id}&peek_only=true")
        assert peek_delta["ok"] is True
        assert peek_delta["cursor"]["advanced"] is False
        assert peek_delta["changes"]["added_count"] >= 1

        advanced_delta = _json_get(f"{base}/api/explore/whats-new?assistant_id={assistant_id}")
        assert advanced_delta["ok"] is True
        assert advanced_delta["cursor"]["advanced"] is True
        assert advanced_delta["changes"]["added_count"] >= 1

        flushed = _json_post(
            f"{base}/api/memory/quicknote/flush",
            {"assistant_id": assistant_id, "session_id": "sess_a", "reason": "manual"},
        )
        assert flushed["ok"] is True
        assert flushed["flushed_count"] >= 1

        status2 = _json_get(f"{base}/api/memory/quicknote/status?assistant_id={assistant_id}&session_id=sess_a")
        assert status2["status"]["pending_count"] == 0

        usage_guide = _json_get(f"{base}/api/system/usage-guide")
        assert usage_guide["ok"] is True
        assert usage_guide["guide"]["version"] == "quicknote.v1"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_http_context_package_work_session_context_is_live_with_strict_scope() -> None:
    runtime_root = Path(__file__).resolve().parents[2] / "runtime" / "tmp" / f"http_wsp_{uuid.uuid4().hex}"
    runtime_root.mkdir(parents=True, exist_ok=True)
    cfg = default_config()
    cfg.work_session_scratchpad.enabled = True
    cfg.work_session_scratchpad.inject_enabled = True
    cfg.work_session_scratchpad.diagnostics_enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        runtime_state_root=runtime_root,
        enable_writeback=False,
    )
    scope = {
        "thread_id": "thread_http_context",
        "workstream_key": "MNO_WORK_SESSION_SCRATCHPAD_SPEC WORK",
        "workstream_name": "MNO work-session scratchpad",
    }
    runtime._ensure_session("sess_http_wsp")
    runtime.capture_work_session_entry(
        session_id="sess_http_wsp",
        work_session_scope=scope,
        kind="task_state",
        summary="B1 and B2 are resolved before source edits.",
        raw_content="This is a local work receipt, not evidence.",
        replaceability_score=0.93,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        default_payload = _json_post(
            f"{base}/api/chat/context-package",
            {"message": "What is next?", "session_id": "sess_http_wsp", "package_version": "v2"},
        )
        assert default_payload["ok"] is True
        assert "work_session_context" not in default_payload["package"]

        degraded_payload = _json_post(
            f"{base}/api/chat/context-package",
            {
                "message": "What is next?",
                "session_id": "sess_http_wsp",
                "package_version": "v2",
                "include_work_session_context": True,
                "work_session_scope": {"thread_id": "", "workstream_key": ""},
            },
        )
        assert "work_session_context" not in degraded_payload["package"]

        opt_in_payload = _json_post(
            f"{base}/api/chat/context-package",
            {
                "message": "What is next?",
                "session_id": "sess_http_wsp",
                "package_version": "v2",
                "work_session_scope": scope,
            },
        )
        context = dict(opt_in_payload["package"]["work_session_context"])
        assert context["non_authoritative"] is True
        assert context["trust_tier"] == "scratchpad_ephemeral"
        assert context["items"][0]["entry_id"].startswith("sp_")
        assert "diagnostics" not in context
        assert "sp_" not in json.dumps(opt_in_payload["package"].get("ltm_evidence") or [])
        assert "sp_" not in json.dumps(opt_in_payload["package"].get("service_verdict") or {})

        diagnostics_payload = _json_post(
            f"{base}/api/chat/context-package",
            {
                "message": "What is next?",
                "session_id": "sess_http_wsp",
                "package_version": "v2",
                "include_work_session_diagnostics": True,
                "work_session_scope": scope,
            },
        )
        diagnostic_context = dict(diagnostics_payload["package"]["work_session_context"])
        diagnostics = dict(diagnostic_context["diagnostics"])
        assert diagnostics["scratchpad_injected"] is True
        assert diagnostics["task_map"]["render_mode"] == "deterministic"
        assert diagnostics["task_map"]["nodes"][0]["entry_ids"][0].startswith("sp_")
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_runtime_http_server_methodology_lifecycle_roundtrip() -> None:
    unique = str(time.time_ns())
    store = AtomStore()
    store.add_candidate(_candidate("c1", "Evidence first; never fabricate unsupported memory facts.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        listed0 = _json_get(f"{base}/api/methodology/records")
        assert listed0["ok"] is True
        initial_total = int(listed0["total"])

        created = _json_post(
            f"{base}/api/methodology/create",
            {
                "trigger_condition": f"When recall asks for legal timeline precision [{unique}]",
                "action": "Prefer citation-grounded response and abstain when support is weak.",
                "rationale": "Protect trust metrics on high-stakes requests.",
                "actor": "dex",
            },
        )
        assert created["ok"] is True
        record = dict(created["record"])
        methodology_id = str(record["methodology_id"])
        assert methodology_id.startswith("meth_")
        assert record["status"] == "draft"
        assert record["approval_state"] == "pending"

        listed1 = _json_get(f"{base}/api/methodology/records")
        assert listed1["ok"] is True
        assert int(listed1["total"]) >= initial_total + 1

        reviewed = _json_post(
            f"{base}/api/methodology/review",
            {"methodology_id": methodology_id, "decision": "approve", "reviewer": "dex"},
        )
        assert reviewed["ok"] is True
        assert dict(reviewed["record"])["approval_state"] == "approved"

        started = _json_post(
            f"{base}/api/methodology/canary/start",
            {"methodology_id": methodology_id, "actor": "dex", "auto_rollback": True},
        )
        assert started["ok"] is True
        assert dict(started["record"])["status"] == "canary"

        evaluated = _json_post(
            f"{base}/api/methodology/canary/evaluate",
            {"methodology_id": methodology_id, "actor": "dex"},
        )
        assert evaluated["ok"] is True
        assert dict(evaluated["comparison"]).get("risk_label") in {"low", "medium", "high"}

        activated = _json_post(
            f"{base}/api/methodology/activate",
            {"methodology_id": methodology_id, "actor": "dex"},
        )
        assert activated["ok"] is True
        assert str(activated["active_methodology_id"]) == methodology_id

        for idx in range(3):
            correction = _json_post(
                f"{base}/api/methodology/corrections/record",
                {
                    "assistant_id": "claude",
                    "session_id": "sess_corr",
                    "actor": "dex",
                    "text": f"Correction pattern: avoid speculative timeline framing [{unique}]",
                },
            )
            assert correction["ok"] is True
            assert int(dict(correction["cluster"]).get("count") or 0) >= idx + 1

        clusters = _json_get(f"{base}/api/methodology/corrections/clusters?limit=5")
        assert clusters["ok"] is True
        cluster_rows = list(clusters["clusters"])
        assert cluster_rows
        assert int(dict(cluster_rows[0]).get("count") or 0) >= 3

        maintenance = _json_post(
            f"{base}/api/methodology/maintenance/evaluate",
            {"actor": "dex", "force": True},
        )
        assert maintenance["ok"] is True
        assert bool(dict(maintenance["evaluation"]).get("triggered")) is True

        readout = _json_get(f"{base}/api/methodology/readout")
        assert readout["ok"] is True
        assert str(dict(readout["readout"]).get("active_methodology_id") or "") == methodology_id

        rolled_back = _json_post(
            f"{base}/api/methodology/rollback",
            {"methodology_id": methodology_id, "actor": "dex", "reason": "manual verification"},
        )
        assert rolled_back["ok"] is True
        assert str(rolled_back["rolled_back_methodology_id"]) == methodology_id

        listed_with_retired = _json_get(f"{base}/api/methodology/records?status=all&include_retired=true")
        assert listed_with_retired["ok"] is True
        assert any(str(dict(row).get("methodology_id") or "") == methodology_id for row in list(listed_with_retired["records"]))

        listed_without_retired = _json_get(f"{base}/api/methodology/records?status=all&include_retired=false")
        assert listed_without_retired["ok"] is True
        assert all(str(dict(row).get("methodology_id") or "") != methodology_id for row in list(listed_without_retired["records"]))
        assert listed_without_retired["include_retired"] is False

        fetched = _json_get(f"{base}/api/methodology/records/{quote(methodology_id)}")
        assert fetched["ok"] is True
        assert str(dict(fetched["record"]).get("status") or "") in {"retired", "active"}
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_http_server_citation_context_window_defaults_and_override() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "First continuity note.", "conv_ctx"))
    store.add_candidate(_candidate("c2", "Second continuity note.", "conv_ctx"))
    store.add_candidate(_candidate("c3", "Third continuity note.", "conv_ctx"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        default_payload = _json_get(f"{base}/api/archive/citation/{quote('conv_ctx#c2_msg', safe='')}")
        assert default_payload["ok"] is True
        assert int(default_payload.get("context_window") or 0) == 3
        default_matches = list(default_payload.get("matches") or [])
        assert default_matches
        assert any(bool(dict(row).get("is_target")) for row in default_matches)

        expanded_payload = _json_get(f"{base}/api/archive/citation/{quote('conv_ctx#c2_msg', safe='')}?context_window=5")
        assert expanded_payload["ok"] is True
        assert int(expanded_payload.get("context_window") or 0) == 5
        expanded_matches = list(expanded_payload.get("matches") or [])
        assert len(expanded_matches) >= len(default_matches)
        assert any(int(dict(row).get("distance") or 0) >= 0 for row in expanded_matches)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_http_server_exposes_phase6_chat_shell_cards_and_reason_catalog() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        html = _text_get(f"{base}/")
        assert "id=\"sessionSelect\"" in html
        assert "id=\"btnSessionStart\"" in html
        assert "id=\"settingAutoRefresh\"" in html
        assert "id=\"settingMemoryPreference\"" in html
        assert "id=\"btnRoutePreview\"" in html
        assert "id=\"btnContextPreview\"" in html
        assert "id=\"contextPanel\"" in html
        assert "id=\"routePreview\"" in html
        assert "id=\"chatLog\"" in html
        assert "id=\"btnSimpleMode\"" in html
        assert "id=\"btnAdvancedMode\"" in html
        assert "id=\"btnDesktopHome\"" in html
        assert "id=\"modeHint\"" in html
        assert "id=\"memoryKind\"" in html
        assert "id=\"memoryContradiction\"" in html
        assert "id=\"memoryNeighborhoodDepth\"" in html
        assert "id=\"memoryNeighborhoodShared\"" in html
        assert "id=\"btnMemoryNeighborhoodRefresh\"" in html
        assert "id=\"memoryNeighborhoodMeta\"" in html
        assert "id=\"memoryNeighborhoodSvg\"" in html
        assert "id=\"memoryNeighborhoodList\"" in html
        assert "id=\"ledgerList\"" in html
        assert "id=\"btnLedgerRefresh\"" in html
        assert "id=\"wizardShell\"" in html
        assert "id=\"btnWizardStartNew\"" in html
        assert "id=\"btnWizardRestore\"" in html
        assert "id=\"wizardArchivePath\"" in html
        assert "id=\"wizardReviewMeta\"" in html
        assert "id=\"wizardReviewPageSize\"" in html
        assert "id=\"wizardReviewList\"" in html
        assert "id=\"btnWizardReviewFacetToggle\"" in html
        assert "id=\"wizardReviewFacetMenu\"" in html
        assert "id=\"wizardReviewActorFilters\"" in html
        assert "id=\"wizardReviewTopicFilters\"" in html
        assert "id=\"wizardReviewEditorDialog\"" in html
        assert "id=\"btnWizardReviewEditorPrev\"" in html
        assert "id=\"btnWizardReviewEditorNext\"" in html
        assert "id=\"btnWizardReviewEditorApprove\"" in html
        assert "id=\"btnWizardReviewEditorReject\"" in html
        assert "id=\"btnWizardReviewEditorActorsToggle\"" in html
        assert "id=\"btnWizardReviewEditorTopicsToggle\"" in html
        assert "id=\"wizardReviewEditorActorsMenu\"" in html
        assert "id=\"wizardReviewEditorTopicsMenu\"" in html
        assert "id=\"wizardReviewActorSummary\"" in html
        assert "id=\"wizardReviewTopicSummary\"" in html
        assert "id=\"wizardDraftCurationPanel\"" in html
        assert "id=\"btnWizardDraftCurationRefresh\"" in html
        assert "id=\"btnWizardDraftCurationForceRelease\"" in html
        assert "id=\"wizardDraftCurationList\"" in html
        assert "id=\"wizardDraftCurationProposalDialog\"" in html
        assert 'id="btnWizardDraftCurationPromoteAll"' in html
        assert "id=\"btnWizardDraftCurationReject\"" in html
        assert "id=\"btnWizardDraftCurationPromote\"" in html
        assert "id=\"wizardDraftCurationMcpScope\"" in html
        assert "id=\"btnWizardDraftCurationMcpRefresh\"" in html
        assert "id=\"btnWizardDraftCurationMcpExport\"" in html
        assert "id=\"wizardPublishSummary\"" in html
        assert "id=\"btnWizardReviewPrev\"" in html
        assert "id=\"btnWizardReviewNext\"" in html
        assert "id=\"wizardVerifyLinks\"" in html
        assert "id=\"btnWizardGoLive\"" in html
        assert "id=\"wizardOperateState\"" in html
        assert "id=\"btnWizardOperateChat\"" in html
        assert "id=\"wizardGoLiveConfig\"" in html
        assert 'id="wizardImportResult" class="wizard-card-result" role="status" aria-live="polite"' in html
        assert re.search(
            r'id="wizardReviewMeta" class="[^"]*wizard-card-result[^"]*" role="status" aria-live="polite" tabindex="-1"',
            html,
        )
        assert 'id="wizardGoLiveResult" class="wizard-card-result" role="status" aria-live="polite"' in html
        assert "Developer tools (unsafe, local only)" in html
        assert "Start here. The normal path needs no terminal" in html
        assert "Publish Reviewed Memory Set" in html
        assert ("Connect assistant/agent / MCP" in html) or ("Set Up Assistant/Agent / MCP" in html) or ("Set Up Claude / MCP" in html)
        assert "Open Chat Test" in html
        assert "Memory label" in html
        assert "What this memory is about" in html
        assert "Weekend garage cleanup" in html
        assert re.search(
            r'<article class="wizard-card" data-wizard-step="2">.*?<div class="wizard-card-title-group">.*?<h3>Review</h3>.*?data-dialog-open="wizardReviewDialog"',
            html,
            re.S,
        )
        assert re.search(
            r'<article class="wizard-card" data-wizard-step="3">.*?<div class="wizard-card-title-group">.*?<h3>Publish</h3>.*?data-dialog-open="wizardPublishDialog"',
            html,
            re.S,
        )
        assert re.search(
            r'<article class="wizard-card" data-wizard-step="4">.*?<div class="wizard-card-title-group">.*?<h3>Verify</h3>.*?data-dialog-open="wizardVerifyDialog"',
            html,
            re.S,
        )
        assert re.search(
            r'<article class="wizard-card wizard-card-activate" data-wizard-step="5">.*?<div class="wizard-card-title-group">.*?<h3>Activate</h3>.*?data-dialog-open="wizardActivateDialog"',
            html,
            re.S,
        )
        assert re.search(
            r'<article class="wizard-card" data-wizard-step="6">.*?<div class="wizard-card-title-group">.*?<h3>Operate</h3>.*?data-dialog-open="wizardOperateDialog"',
            html,
            re.S,
        )
        assert re.search(r'<h3>Import</h3>.*?data-dialog-open="wizardImportDialog"', html, re.S)
        assert re.search(r'Build style</span>\s*<button id="btnWizardBuildPolicyInfo"', html, re.S)
        assert "3 per page" in html
        assert "6 per page" in html
        assert "12 per page" not in html
        assert "24 per page" not in html
        assert "48 per page" not in html
        assert "id=\"whyPanel\"" in html
        assert "id=\"archiveViewer\"" in html
        assert "id=\"btnMemoryScopeEpisodes\"" in html
        assert "id=\"episodeList\"" in html
        assert "id=\"episodeDetail\"" in html
        assert "id=\"btnProposalCreateDelete\"" in html
        assert "id=\"btnProposalCreateEdit\"" in html
        assert "id=\"writebackEnabled\"" in html
        assert "id=\"btnHealthRun\"" in html
        assert "id=\"btnPackagingLoad\"" in html
        assert "id=\"methodologyId\"" in html
        assert "id=\"methodologyActor\"" in html
        assert "id=\"btnMethodologyCreate\"" in html
        assert "id=\"btnMethodologyApprove\"" in html
        assert "id=\"btnMethodologyCanaryStart\"" in html
        assert "id=\"btnMethodologyCanaryEval\"" in html
        assert "id=\"btnMethodologyActivate\"" in html
        assert "id=\"btnMethodologyRollback\"" in html
        assert "id=\"btnMethodologyRecordCorrection\"" in html
        assert "id=\"btnMethodologyMaintenanceEval\"" in html
        assert "id=\"btnMethodologyRefresh\"" in html
        assert "id=\"methodologyReadoutMeta\"" in html
        assert "id=\"methodologyActionMeta\"" in html

        js = _text_get(f"{base}/assets/app.js")
        assert "/api/chat/sessions" in js
        assert "/api/chat/session/" in js
        assert "/api/chat/route-preview" in js
        assert "/api/chat/context-package" in js
        assert "/api/runtime/telemetry/turns" in js
        assert "memory route" in js
        assert "/api/memory/cards" in js
        assert "/api/memory/graph/neighbors?" in js
        assert "nq.settings.uiMode" in js
        assert "simple-mode" in js
        assert "plain summary" in js
        assert "Approve proposal" in js
        assert "Loading bounded neighborhood" in js
        assert "/api/wizard/start" in js
        assert "/api/wizard/restore-last-published" in js
        assert "/api/wizard/import/run" in js
        assert "/api/wizard/review/compile" in js
        assert "/api/wizard/review/cards?" in js
        assert "/api/wizard/verify/run" in js
        assert "/api/wizard/draft-curation/status" in js
        assert "/api/wizard/draft-curation/mcp/status" in js
        assert "/api/wizard/draft-curation/mcp/install" in js
        assert "/api/wizard/draft-curation/mcp/export" in js
        assert "/api/wizard/draft-curation/proposals?" in js
        assert "/api/wizard/draft-curation/cards/" in js
        assert "/api/wizard/draft-curation/session/release" in js
        assert "wizardReviewEditorDialog" in js
        assert "wizardDraftCurationProposalDialog" in js
        assert "wizardDraftCurationMcpScope" in js
        assert ("Connect assistant/agent to this draft" in js) or ("Connect Claude to this draft" in js)
        assert "btnWizardReviewFacetToggle" in js
        assert "filter_facets" in js
        assert "await validateWizardImport();" in js
        assert 'els.wizardArchiveFile.value = "";' in js
        assert "wizardImportPending" in js
        assert 'Creating Store...' in js
        assert "if (state.wizardImportPending) {" in js
        assert "wizardVisibleStage" in js
        assert "wizardStageIsReachable" in js
        assert "requestCloseWizardReviewEditor" in js
        assert 'card.review_decision || "pending"' in js
        assert "status=pending&page=1&page_size=${pageSize}" in js
        assert "Start Fresh creates a new setup run." in js
        assert "Restore Last Good Copy swaps the current published pointer" in js
        assert "Verification is stale and must run again." in js
        assert "Moving left, right, or closing the editor saves changes automatically." in js
        assert "/api/runtime/provider/config" in js
        assert "/api/memory/episodes" in js
        assert "/api/memory/atoms/" in js
        assert "/api/turns/" in js
        assert "/api/runtime/health" in js
        assert "/api/runtime/writeback/policy" in js
        assert "/api/runtime/packaging/instructions" in js
        assert "/api/memory/proposals/create-delete" in js
        assert "/api/methodology/readout" in js
        assert "/api/methodology/records?status=all&limit=20&offset=0" in js
        assert "/api/methodology/corrections/clusters?limit=10" in js
        assert "/api/methodology/maintenance/history?limit=5" in js
        assert "/api/methodology/create" in js
        assert "/api/methodology/review" in js
        assert "/api/methodology/canary/start" in js
        assert "await ensureTabData(\"setup\", { force: true });" in js
        assert "const initialTab = activeTabId();" in js
        assert "if (initialTab !== \"setup\") {" in js
        assert "await Promise.all([refreshMemory(), refreshProposals(), refreshEpisodes()]);" not in js
        assert "/api/methodology/canary/evaluate" in js
        assert "/api/methodology/activate" in js
        assert "/api/methodology/rollback" in js
        assert "/api/methodology/corrections/record" in js
        assert "/api/methodology/maintenance/evaluate" in js
        assert "async function refreshSetupTabData()" in js
        assert "includeReview: false" in js
        assert "includeInputOptions: false" in js
        assert "includeActivation: false" in js
        assert "includeRemap: false" in js
        assert "function activeMemoryTabKey()" in js
        assert "refreshVisibleWizardStageData" in js
        assert 'if (visibleStage === "activate") {' in js
        assert 'visibleStage === "activate" || visibleStage === "operate"' not in js
        assert 'const cacheKey = normalized === "memory" ? activeMemoryTabKey() : normalized;' in js

        bootstrap_start = js.index("async function bootstrap() {")
        bootstrap_end = js.index("bootstrap().catch((error) => {")
        bootstrap_chunk = js[bootstrap_start:bootstrap_end]
        assert "await ensureTabData(\"setup\", { force: true });" in bootstrap_chunk
        assert "await ensureTabData(initialTab, { force: true });" in bootstrap_chunk
        assert "await Promise.all([refreshMemory(), refreshEpisodes(), refreshProposals()]);" not in bootstrap_chunk
        assert "await refreshSessionAndState();" not in bootstrap_chunk
        assert "await refreshWhyPanel();" not in bootstrap_chunk
        assert "await refreshOpsDeck();" not in bootstrap_chunk

        css = _text_get(f"{base}/assets/styles.css")
        assert ".session-shell" in css
        assert ".route-chip" in css
        assert ".context-shell" in css
        assert ".context-viewer" in css
        assert ".badge" in css
        assert ".memory-flag" in css
        assert ".memory-graph-grid" in css
        assert ".memory-neighborhood-panel" in css
        assert ".memory-neighborhood-row" in css
        assert ".ledger-shell" in css
        assert ".ui-mode-bar" in css
        assert "body.simple-mode .settings-panel" in css
        assert ".wizard-activation-inline-actions" in css

        boot_html = (Path(__file__).resolve().parents[2] / "app" / "desktop" / "boot.html").read_text(encoding="utf-8")
        assert 'id="btnBootInlineRepair"' in boot_html
        boot_css = (Path(__file__).resolve().parents[2] / "app" / "desktop" / "boot.css").read_text(encoding="utf-8")
        assert "overflow-wrap: anywhere" in boot_css
        assert ".wizard-shell" in css
        assert ".btn.wizard-primary-action" in css
        assert ".wizard-stage-zone" in css
        assert ".wizard-review-item:focus-visible" in css
        assert ".wizard-review-filter-menu" in css
        assert ".wizard-review-modal-shell" in css
        assert ".wizard-review-picker-menu" in css
        assert ".wizard-guidance-action" in css
        assert ".wizard-review-filter-anchor > .wizard-review-filter-menu" in css
        assert ".wizard-draft-curation" in css
        assert ".wizard-draft-curation-connect" in css
        assert ".wizard-draft-curation-mcp-targets" in css
        assert ".wizard-draft-proposal-shell" in css
        assert ".wizard-draft-context-grid" in css
        assert ".wizard-page-pill" in css
        assert ".wizard-stage.tone-stale" in css
        assert ".wizard-stage.tone-blocked" in css
        assert ".wizard-stage.tone-unsafe" in css
        assert ".btn.wizard-action-disabled" in css
        assert ".why-shell" in css
        assert ".archive-shell" in css
        assert ".memory-scope-tabs" in css
        assert ".ops-shell" in css
        assert "body.simple-mode .wizard-danger-zone" in css

        reasons = _json_get(f"{base}/api/runtime/decision-reasons")
        assert reasons["ok"] is True
        assert "ltm_deep" in reasons["routes"]
        assert "chat_first" in reasons["memory_preferences"]
        assert "memory_assist" in reasons["memory_preferences"]
        assert "explicit_memory_request" in reasons["reasons"]
        assert "casual_prompt_no_recall" in reasons["reasons"]
        assert "ambiguous_low_signal_skip" in reasons["reasons"]
        assert "memory_signal_probe" in reasons["reasons"]
        assert "memory_preference_chat_first" in reasons["reasons"]
        assert "memory_preference_memory_assist" in reasons["reasons"]

        telemetry_summary = _json_get(f"{base}/api/runtime/telemetry/summary?limit=50")
        assert telemetry_summary["ok"] is True
        assert telemetry_summary["limit"] == 50
        summary = telemetry_summary["summary"]
        assert "route_counts" in summary
        assert "memory_preference_counts" in summary
        assert "mode_counts" in summary
        assert "warning_code_counts" in summary

        telemetry_turns = _json_get(f"{base}/api/runtime/telemetry/turns?limit=10")
        assert telemetry_turns["ok"] is True
        assert telemetry_turns["limit"] == 10
        assert isinstance(telemetry_turns["turns"], list)
        assert isinstance(telemetry_turns["warn_turns"], int)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_http_server_sanitizes_context_package_internal_error() -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)

    def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("internal-sensitive-detail")

    runtime.build_context_package = _boom  # type: ignore[assignment]
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status, payload = _json_post_error(
            f"{base}/api/chat/context-package",
            {"message": "What should I remember?"},
        )
        assert status == 500
        assert payload["error"] == "context package failed"
        assert "internal-sensitive-detail" not in payload["error"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_http_server_wizard_invalid_run_id_returns_not_found() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        enable_writeback=False,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status, payload = _json_get_error(f"{base}/api/wizard/review/cards?run_id=wizard_bad$char")
        assert status == 404
        assert payload["error"] == "wizard run not found"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_hcr_ui_uses_accessible_dom_labels_and_guards_run_state() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    app_js = (repo_root / "engine" / "runtime" / "ui" / "app.js").read_text(encoding="utf-8")
    styles = (repo_root / "engine" / "runtime" / "ui" / "styles.css").read_text(encoding="utf-8")

    assert 'heading.textContent = "Curation Room"' in app_js
    assert 'kicker.textContent = "Run-bound review"' in app_js
    assert ".wizard-head h2::after" not in styles
    assert ".wizard-kicker::after" not in styles

    guard = 'if (state.hcrMode && (!payload.has_state || String(payload.current_run_id || "").trim() !== state.hcrRunId))'
    assert app_js.index(guard) < app_js.index("state.wizardState = payload.state || null;", app_js.index("async function refreshWizardReviewSummary"))
