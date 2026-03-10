from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DriftDelta:
    metric: str
    baseline: float
    candidate: float
    delta: float
    regression: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DriftReport:
    generated_at: str
    baseline_path: str
    candidate_path: str
    decision: str
    regressions: list[str]
    deltas: list[DriftDelta]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "baseline_path": self.baseline_path,
            "candidate_path": self.candidate_path,
            "decision": self.decision,
            "regressions": list(self.regressions),
            "deltas": [item.to_dict() for item in self.deltas],
        }


def _value(payload: dict[str, Any], key: str) -> float:
    return float(payload.get(key) or 0.0)


def compare_eval_summaries(*, baseline: dict[str, Any], candidate: dict[str, Any]) -> DriftReport:
    required_metrics = {
        "decision_accuracy",
        "citation_hit_rate",
        "retrieval_hit_rate",
        "abstain_precision",
        "false_memory_rate",
        "p95_latency_ms",
    }
    missing_baseline = sorted(metric for metric in required_metrics if metric not in baseline)
    missing_candidate = sorted(metric for metric in required_metrics if metric not in candidate)
    if missing_baseline or missing_candidate:
        details: list[str] = []
        if missing_baseline:
            details.append(f"baseline missing: {', '.join(missing_baseline)}")
        if missing_candidate:
            details.append(f"candidate missing: {', '.join(missing_candidate)}")
        raise ValueError("; ".join(details))

    deltas: list[DriftDelta] = []

    def _append(metric: str, *, maximize: bool, tolerance: float, note: str) -> None:
        base = _value(baseline, metric)
        cand = _value(candidate, metric)
        delta = cand - base
        if maximize:
            regression = delta < -abs(tolerance)
        else:
            regression = delta > abs(tolerance)
        deltas.append(
            DriftDelta(
                metric=metric,
                baseline=base,
                candidate=cand,
                delta=delta,
                regression=regression,
                note=note,
            )
        )

    _append(
        "decision_accuracy",
        maximize=True,
        tolerance=0.02,
        note="Lower than baseline by more than 0.02 is a regression.",
    )
    _append(
        "citation_hit_rate",
        maximize=True,
        tolerance=0.01,
        note="Lower than baseline by more than 0.01 is a regression.",
    )
    _append(
        "retrieval_hit_rate",
        maximize=True,
        tolerance=0.03,
        note="Lower than baseline by more than 0.03 is a regression.",
    )
    _append(
        "abstain_precision",
        maximize=True,
        tolerance=0.03,
        note="Lower than baseline by more than 0.03 is a regression.",
    )
    _append(
        "false_memory_rate",
        maximize=False,
        tolerance=0.01,
        note="Higher than baseline by more than 0.01 is a regression.",
    )
    _append(
        "p95_latency_ms",
        maximize=False,
        tolerance=max(50.0, _value(baseline, "p95_latency_ms") * 0.20),
        note="Higher than baseline by >20% (or 50ms minimum) is a regression.",
    )

    regressions = [item.metric for item in deltas if item.regression]
    decision = "FAIL" if regressions else "PASS"
    return DriftReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        baseline_path="",
        candidate_path="",
        decision=decision,
        regressions=regressions,
        deltas=deltas,
    )


def write_drift_report(
    *,
    out_dir: str | Path,
    report: DriftReport,
    baseline_path: str | Path,
    candidate_path: str | Path,
) -> tuple[Path, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    report.baseline_path = str(baseline_path)
    report.candidate_path = str(candidate_path)
    payload = report.to_dict()

    json_path = directory / "drift_report.json"
    md_path = directory / "drift_report.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Eval Drift Report",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- decision: `{payload['decision']}`",
        f"- baseline: `{payload['baseline_path']}`",
        f"- candidate: `{payload['candidate_path']}`",
        "",
        "## Regressions",
    ]
    if payload["regressions"]:
        lines.extend(f"- {metric}" for metric in payload["regressions"])
    else:
        lines.append("- none")

    lines.extend(["", "## Deltas"])
    for item in payload["deltas"]:
        lines.append(
            f"- {item['metric']}: baseline={item['baseline']:.4f}, "
            f"candidate={item['candidate']:.4f}, delta={item['delta']:.4f}, regression={item['regression']}"
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path


def load_summary(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("summary must be a JSON object")
    return payload
