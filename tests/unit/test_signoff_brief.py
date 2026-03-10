from __future__ import annotations

from engine.runtime.signoff_brief import render_signoff_brief


def test_render_signoff_brief_pass() -> None:
    md, txt = render_signoff_brief(
        decision="PASS",
        profile="safe",
        reasons=[],
        eval_summary={
            "decision_accuracy": 0.95,
            "citation_hit_rate": 0.99,
            "false_memory_rate": 0.01,
            "p95_latency_ms": 1000.0,
        },
        load_summary={
            "latency_p95_ms": 1200.0,
            "turns": 10,
            "failed_turns": 0,
        },
    )
    assert "decision: `PASS`" in md
    assert "decision: PASS" in txt
    assert "Reasons and next actions" in md
    assert "- none" in md


def test_render_signoff_brief_fail_includes_actions() -> None:
    md, txt = render_signoff_brief(
        decision="FAIL",
        profile="safe",
        reasons=["eval_case_coverage_insufficient", "unmapped_reason_code"],
        eval_summary={},
        load_summary={},
    )
    assert "decision: `FAIL`" in md
    assert "eval_case_coverage_insufficient" in md
    assert "Increase `--eval-cases`" in md
    assert "unmapped_reason_code" in txt
