from __future__ import annotations

import json
from pathlib import Path

from tools.score_blind_llm_contract import score


ROOT = Path(__file__).resolve().parents[2]


def test_public_blind_llm_task_pack_and_reference_contract_pass() -> None:
    tasks = json.loads((ROOT / "docs/evals/blind_llm_tasks_v0.2.1.json").read_text(encoding="utf-8"))
    answers = json.loads(
        (ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.1.json").read_text(encoding="utf-8")
    )
    assert {row["id"] for row in tasks["tasks"]} == {row["id"] for row in answers["answers"]}
    result = score(answers)
    assert result["passed"] is True
    assert result["score"] == 100
    assert result["hard_failures"] == []


def test_blind_llm_gate_fails_closed_on_hard_boundary_violation() -> None:
    payload = json.loads(
        (ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.1.json").read_text(encoding="utf-8")
    )
    payload["answers"][3]["decision"] = "auto_promote_to_canonical"
    payload["answers"][3]["hard_violation"] = True
    result = score(payload)
    assert result["passed"] is False
    assert "reinforcement_boundary" in result["hard_failures"]
