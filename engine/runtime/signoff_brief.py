from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


REASON_MAP = {
    "eval_case_coverage_insufficient": (
        "Not enough evaluation cases ran to trust this signoff.",
        "Increase `--eval-cases` or lower `--min-eval-cases` only for explicit pilot runs.",
    ),
    "eval_supported_case_coverage_insufficient": (
        "Supported recall coverage is too low.",
        "Increase supported truthset rows so retrieval quality can be validated.",
    ),
    "eval_unsupported_case_coverage_insufficient": (
        "Unsupported trap coverage is too low.",
        "Add more unsupported trap rows to test abstain behavior.",
    ),
    "load_turn_coverage_insufficient": (
        "Load harness did not produce enough successful turns.",
        "Increase load budget or reduce gating floor with `--min-load-turns` for controlled checks.",
    ),
    "load_failed_turn_rate_exceeded": (
        "Too many load turns failed.",
        "Inspect `load_samples.json` for failing turns and re-run after fixing runtime stability.",
    ),
    "false_memory_rate_exceeded": (
        "False-memory rate is above the allowed threshold.",
        "Improve abstain behavior or retrieval precision before release.",
    ),
    "citation_hit_rate_below_floor": (
        "Citation hit rate is below the safety floor.",
        "Improve evidence retrieval so supported recalls include citations.",
    ),
    "eval_p95_latency_exceeded": (
        "Eval latency is above profile budget.",
        "Tune retrieval budget and run with smaller scan budget if needed.",
    ),
    "load_p95_latency_exceeded": (
        "Load latency is above profile budget.",
        "Tune runtime path and reduce expensive retrieval expansion.",
    ),
}


def _fmt_pct(value: float) -> str:
    return f"{value * 100.0:.2f}%"


def render_signoff_brief(
    *,
    decision: str,
    profile: str,
    reasons: list[str],
    eval_summary: dict[str, Any],
    load_summary: dict[str, Any],
) -> tuple[str, str]:
    generated_at = datetime.now(timezone.utc).isoformat()
    status = "PASS" if str(decision).upper() == "PASS" else "FAIL"

    md_lines = [
        "# Signoff Brief",
        "",
        f"- generated_at: `{generated_at}`",
        f"- profile: `{profile}`",
        f"- decision: `{status}`",
        "",
        "## What this means",
    ]
    txt_lines = [
        "SIGNOFF BRIEF",
        "",
        f"generated_at: {generated_at}",
        f"profile: {profile}",
        f"decision: {status}",
        "",
        "What this means:",
    ]

    if status == "PASS":
        md_lines.append("- Runtime quality/performance gates passed for this profile.")
        txt_lines.append("- Runtime quality/performance gates passed for this profile.")
    else:
        md_lines.append("- At least one safety or quality gate failed. Do not ship this snapshot yet.")
        txt_lines.append("- At least one safety or quality gate failed. Do not ship this snapshot yet.")

    md_lines.extend(
        [
            "",
            "## Key metrics",
            f"- decision_accuracy: `{_fmt_pct(float(eval_summary.get('decision_accuracy') or 0.0))}`",
            f"- citation_hit_rate: `{_fmt_pct(float(eval_summary.get('citation_hit_rate') or 0.0))}`",
            f"- false_memory_rate: `{_fmt_pct(float(eval_summary.get('false_memory_rate') or 0.0))}`",
            f"- eval_p95_latency_ms: `{float(eval_summary.get('p95_latency_ms') or 0.0):.2f}`",
            f"- load_p95_latency_ms: `{float(load_summary.get('latency_p95_ms') or 0.0):.2f}`",
            f"- load_turns: `{int(load_summary.get('turns') or 0)}`",
            f"- load_failed_turns: `{int(load_summary.get('failed_turns') or 0)}`",
        ]
    )
    txt_lines.extend(
        [
            "",
            "Key metrics:",
            f"- decision_accuracy: {_fmt_pct(float(eval_summary.get('decision_accuracy') or 0.0))}",
            f"- citation_hit_rate: {_fmt_pct(float(eval_summary.get('citation_hit_rate') or 0.0))}",
            f"- false_memory_rate: {_fmt_pct(float(eval_summary.get('false_memory_rate') or 0.0))}",
            f"- eval_p95_latency_ms: {float(eval_summary.get('p95_latency_ms') or 0.0):.2f}",
            f"- load_p95_latency_ms: {float(load_summary.get('latency_p95_ms') or 0.0):.2f}",
            f"- load_turns: {int(load_summary.get('turns') or 0)}",
            f"- load_failed_turns: {int(load_summary.get('failed_turns') or 0)}",
        ]
    )

    md_lines.extend(["", "## Reasons and next actions"])
    txt_lines.extend(["", "Reasons and next actions:"])
    if reasons:
        for reason in reasons:
            message, action = REASON_MAP.get(
                reason,
                ("Gate failed with an unmapped reason code.", "Inspect signoff_manifest.json and related artifacts."),
            )
            md_lines.append(f"- `{reason}`: {message} Next: {action}")
            txt_lines.append(f"- {reason}: {message} Next: {action}")
    else:
        md_lines.append("- none")
        txt_lines.append("- none")

    return "\n".join(md_lines).rstrip() + "\n", "\n".join(txt_lines).rstrip() + "\n"
