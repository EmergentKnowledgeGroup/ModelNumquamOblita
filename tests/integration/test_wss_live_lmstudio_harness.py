from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from tools import wss_live_lmstudio_harness as harness


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _runtime_root(name: str) -> Path:
    root = PROJECT_ROOT / "runtime" / "tmp" / f"{name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


class FakeModelClient:
    def __init__(self, reply: dict[str, object]) -> None:
        self.reply = dict(reply)
        self.calls: list[dict[str, object]] = []

    def list_models(self) -> list[str]:
        return ["gemma-4-e4b-test"]

    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> harness.ModelReply:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout_s": timeout_s,
            }
        )
        return harness.ModelReply(raw_text=json.dumps(self.reply), parsed=dict(self.reply), attempts=1)


def _passing_reply() -> dict[str, object]:
    return {
        "next_action": "run live LM Studio WSS validation",
        "current_files": ["tools/wss_live_lmstudio_harness.py", "engine/runtime/session.py"],
        "blockers": [],
        "needed_refs": ["docs/MNO_WORK_SESSION_SCRATCHPAD_CONTEXT_DIET_SPEC_2026-07-07.md"],
        "memory_claim": False,
        "scratchpad_as_evidence": False,
        "reread_requests": [],
        "confidence": "medium",
    }


def test_wss_live_harness_runs_fake_model_flow_and_writes_artifacts() -> None:
    run_root = _runtime_root("wss_live_harness_pass")
    try:
        client = FakeModelClient(_passing_reply())
        result = harness.run_harness(
            project_root=PROJECT_ROOT,
            run_root=run_root,
            model_client=client,
            requested_model="auto",
            live=False,
        )

        assert result.passed is True
        assert result.model == "gemma-4-e4b-test"
        assert result.metrics["default_no_scope_omits_context_pass"] is True
        assert result.metrics["cross_session_strict_scope_resume_pass"] is True
        assert result.metrics["explicit_resume_pass"] is True
        assert result.metrics["context_diet_fixture_pass"] is True
        assert result.metrics["resume_fidelity_pass"] is True
        assert result.metrics["truth_isolation_pass"] is True
        assert result.metrics["model_reply_parse_pass"] is True
        assert result.metrics["model_resume_fidelity_pass"] is True
        assert result.metrics["model_truth_isolation_pass"] is True
        assert (run_root / "metrics.json").exists()
        assert (run_root / "verdict.md").read_text(encoding="utf-8").startswith("# WSS Live Harness Verdict")
        assert (run_root / "transcript.jsonl").exists()
        assert client.calls
        serialized_prompt = json.dumps(client.calls[0]["messages"], sort_keys=True)
        assert "work_session_context" in serialized_prompt
        assert "scratchpad_ephemeral" in serialized_prompt
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def test_wss_live_harness_fails_model_that_treats_scratchpad_as_memory_evidence() -> None:
    run_root = _runtime_root("wss_live_harness_fail")
    try:
        bad = _passing_reply()
        bad["memory_claim"] = True
        bad["scratchpad_as_evidence"] = True
        client = FakeModelClient(bad)

        result = harness.run_harness(
            project_root=PROJECT_ROOT,
            run_root=run_root,
            model_client=client,
            requested_model="gemma-4-e4b-test",
            live=False,
        )

        assert result.passed is False
        assert result.metrics["model_truth_isolation_pass"] is False
        verdict = (run_root / "verdict.md").read_text(encoding="utf-8")
        assert "FAIL" in verdict
        assert "model_truth_isolation_pass" in verdict
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def test_model_reply_evaluator_accepts_scalar_list_fields_from_local_models() -> None:
    reply = _passing_reply()
    reply["blockers"] = ""
    reply["needed_refs"] = "docs/MNO_WORK_SESSION_SCRATCHPAD_CONTEXT_DIET_SPEC_2026-07-07.md"
    reply["reread_requests"] = ""

    metrics = harness.evaluate_model_reply(reply)

    assert metrics["model_reply_parse_pass"] is True
    assert metrics["model_resume_fidelity_pass"] is True
    assert metrics["model_reread_avoidance_pass"] is True
