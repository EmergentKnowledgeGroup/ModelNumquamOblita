#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Release Trust Gate",
        "",
        f"- generated_at: `{str(report.get('generated_at') or '')}`",
        f"- decision: `{str(report.get('decision') or 'FAIL')}`",
        f"- pilot_manifest: `{str(report.get('pilot_manifest') or '')}`",
        f"- signoff_manifest: `{str(report.get('signoff_manifest') or '')}`",
        f"- require_trust_regression: `{bool(report.get('require_trust_regression'))}`",
        "",
        "## Reasons",
    ]
    reasons = [str(item) for item in list(report.get("reasons") or []) if str(item).strip()]
    if reasons:
        lines.extend([f"- {item}" for item in reasons])
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Block release when trust gates fail.")
    parser.add_argument("--pilot-manifest", required=True, help="Path to pilot_manifest.json")
    parser.add_argument("--out-dir", default="", help="Optional output directory for release gate report")
    parser.add_argument(
        "--require-trust-regression",
        action="store_true",
        help="Require trust_regression.enabled=true and trust_regression.decision=PASS.",
    )
    args = parser.parse_args()

    pilot_manifest_path = Path(args.pilot_manifest).expanduser().resolve()
    if not pilot_manifest_path.exists():
        print(f"error=pilot manifest not found: {pilot_manifest_path}")
        return 2

    pilot_manifest = _read_json(pilot_manifest_path)
    artifacts = pilot_manifest.get("artifacts") or {}
    signoff_dir_raw = str((artifacts if isinstance(artifacts, dict) else {}).get("signoff_dir") or "").strip()
    signoff_manifest_path = (Path(signoff_dir_raw) / "signoff_manifest.json").resolve() if signoff_dir_raw else None

    reasons: list[str] = []
    pilot_decision = str(pilot_manifest.get("decision") or "").strip().upper()
    if pilot_decision != "PASS":
        reasons.append("pilot_manifest_decision_not_pass")

    signoff_manifest: dict[str, Any] = {}
    if signoff_manifest_path is None or not signoff_manifest_path.exists():
        reasons.append("signoff_manifest_missing")
    else:
        signoff_manifest = _read_json(signoff_manifest_path)
        signoff_decision = str(signoff_manifest.get("decision") or "").strip().upper()
        if signoff_decision != "PASS":
            reasons.append("signoff_manifest_decision_not_pass")

    trust_regression = pilot_manifest.get("trust_regression")
    trust = trust_regression if isinstance(trust_regression, dict) else {}
    if bool(args.require_trust_regression):
        if not bool(trust.get("enabled")):
            reasons.append("trust_regression_not_enabled")
        trust_decision = str(trust.get("decision") or "").strip().upper()
        if trust_decision != "PASS":
            reasons.append("trust_regression_decision_not_pass")

    decision = "PASS" if not reasons else "FAIL"
    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if str(args.out_dir or "").strip()
        else pilot_manifest_path.parent / "release_gate"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reasons": reasons,
        "pilot_manifest": str(pilot_manifest_path),
        "signoff_manifest": str(signoff_manifest_path or ""),
        "require_trust_regression": bool(args.require_trust_regression),
        "pilot_decision": pilot_decision,
        "signoff_decision": str(signoff_manifest.get("decision") or ""),
        "trust_regression": trust,
    }
    report_json = out_dir / "release_gate_report.json"
    report_md = out_dir / "release_gate_report.md"
    report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report_md.write_text(_render_markdown(report), encoding="utf-8")

    print(f"decision={decision}")
    print(f"report_json={report_json}")
    print(f"report_md={report_md}")
    if reasons:
        print(f"reasons={','.join(reasons)}")
    else:
        print("reasons=none")
    return 0 if decision == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
