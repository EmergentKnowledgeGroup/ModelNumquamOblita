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


def test_blind_llm_gate_derives_hard_violation_instead_of_trusting_answer_flag() -> None:
    payload = json.loads(
        (ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.1.json").read_text(encoding="utf-8")
    )
    payload["answers"][3]["decision"] = "auto_promote_to_canonical"
    payload["answers"][3]["hard_violation"] = False
    result = score(payload)
    assert result["passed"] is False
    assert "reinforcement_boundary" in result["hard_failures"]


def test_blind_llm_gate_rejects_duplicate_missing_and_unknown_ids() -> None:
    source = json.loads(
        (ROOT / "tests/fixtures/blind_llm_reference_answers_v0.2.1.json").read_text(encoding="utf-8")
    )
    for rows in (
        [*source["answers"], dict(source["answers"][0])],
        source["answers"][:-1],
        [*source["answers"][:-1], {"id": "unknown", "decision": "anything"}],
    ):
        try:
            score({"answers": rows})
        except ValueError:
            pass
        else:
            raise AssertionError("expected exact answer-ID validation failure")
