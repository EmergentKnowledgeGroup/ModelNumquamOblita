from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tools.score_blind_llm_contract import score_payload, score_temporal


ROOT = Path(__file__).resolve().parents[2]


def test_v022_public_temporal_blind_llm_contract_passes() -> None:
    tasks = json.loads((ROOT / "docs/evals/blind_llm_tasks_v0.2.2.json").read_text(encoding="utf-8"))
    answers = json.loads(
        (ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.2.json").read_text(encoding="utf-8")
    )
    assert {row["id"] for row in tasks["tasks"]} == {row["id"] for row in answers["answers"]}
    result = score_temporal(answers)
    assert result["passed"] is True
    assert result["score"] == 100
    assert result["hard_failures"] == []
    assert score_payload(answers)["schema"] == "mno.blind_llm_gate.temporal_score.v1"

    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools/score_blind_llm_contract.py"), str(ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.2.json")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["schema"] == "mno.blind_llm_gate.temporal_score.v1"


def test_v022_temporal_blind_gate_fails_on_behavior_or_authority_overclaim() -> None:
    payload = json.loads(
        (ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.2.json").read_text(encoding="utf-8")
    )
    payload["answers"][4]["decision"] = "mno_wakes_model"
    payload["answers"][6]["decision"] = "due_overrides_canonical"
    result = score_temporal(payload)
    assert result["passed"] is False
    assert result["hard_failures"] == ["heartbeat_boundary", "authority_boundary"]


def test_v022_temporal_blind_gate_rejects_undocumented_decision() -> None:
    payload = json.loads(
        (ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.2.json").read_text(encoding="utf-8")
    )
    payload["answers"][0]["decision"] = "some_unpublished_choice"

    try:
        score_temporal(payload)
    except ValueError as exc:
        assert "unsupported decision for temporal task" in str(exc)
    else:
        raise AssertionError("undocumented temporal decisions must fail closed")


def test_raw_import_surface_cannot_schedule_temporal_memory() -> None:
    source = (ROOT / "tools/import_memories.py").read_text(encoding="utf-8")
    assert "schedule_temporal" not in source
    assert "temporal_disposition" not in source
