#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("manifest must be a JSON object")
    return payload


def _resolve_input_path(raw_path: str, *, base_dir: Path) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _render_markdown(payload: dict[str, Any], *, decision: str, reasons: list[str]) -> str:
    handoff = payload.get("signing_handoff") or {}
    lines = [
        "# MNO Signing Handoff Report",
        "",
        f"- decision: `{decision}`",
        f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`",
        f"- manifest_schema: `{str(payload.get('schema') or '')}`",
        f"- signing_owner: `{str(payload.get('signing_owner') or '')}`",
        "",
        "## Handoff",
        f"- signing_status: `{str(handoff.get('signing_status') or '')}`",
        f"- signer_identity: `{str(handoff.get('signer_identity') or '')}`",
        f"- candidate_path: `{str(handoff.get('candidate_path') or '')}`",
        f"- artifact_hash_sha256: `{str(handoff.get('artifact_hash_sha256') or '')}`",
        f"- signed_artifact_path: `{str(handoff.get('signed_artifact_path') or '')}`",
        f"- signed_artifact_hash_sha256: `{str(handoff.get('signed_artifact_hash_sha256') or '')}`",
        f"- integrity_match: `{str(handoff.get('integrity_match'))}`",
        f"- signature_reference: `{str(handoff.get('signature_reference') or '')}`",
        f"- certificate_fingerprint: `{str(handoff.get('certificate_fingerprint') or '')}`",
    ]
    lines.append("")
    lines.append("## Reasons")
    if reasons:
        lines.extend([f"- {item}" for item in reasons])
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Record/validate signing handoff for MNO release candidates.")
    parser.add_argument("--manifest", required=True, help="Path to MNO release candidate manifest JSON.")
    parser.add_argument("--status", choices=["signed", "rejected", "pending"], default="signed")
    parser.add_argument("--signer-identity", default="", help="Signer identity for signed/rejected states.")
    parser.add_argument("--signed-artifact", default="", help="Path to signed artifact (defaults to candidate_path).")
    parser.add_argument("--signature-reference", default="", help="Reference to detached signature or signing ticket.")
    parser.add_argument("--certificate-fingerprint", default="", help="Certificate fingerprint used for signing.")
    parser.add_argument("--allow-hash-mismatch", action="store_true", help="Allow signed hash to differ from original hash.")
    parser.add_argument("--out-manifest", default="", help="Optional output manifest path. Defaults to in-place update.")
    parser.add_argument("--out-dir", default="", help="Optional report directory. Defaults beside output manifest.")
    args = parser.parse_args()

    manifest_path = Path(str(args.manifest)).expanduser().resolve()
    if not manifest_path.exists():
        print(f"error=manifest_not_found:{manifest_path}")
        return 2

    try:
        payload = _read_manifest(manifest_path)
    except Exception as exc:
        print(f"error=manifest_read_failed:{exc}")
        return 2

    handoff = payload.get("signing_handoff")
    if not isinstance(handoff, dict):
        handoff = {}
        payload["signing_handoff"] = handoff

    status = str(args.status)
    signer_identity = str(args.signer_identity or "").strip()

    reasons: list[str] = []
    if status in {"signed", "rejected"} and not signer_identity:
        reasons.append("missing_signer_identity")

    base_dir = manifest_path.parent
    candidate_path_raw = str(handoff.get("candidate_path") or "").strip()
    original_hash = str(handoff.get("artifact_hash_sha256") or "").strip()
    if status == "signed" and not original_hash:
        reasons.append("missing_original_artifact_hash")

    signed_artifact_raw = str(args.signed_artifact or "").strip() or candidate_path_raw
    signed_artifact_path = _resolve_input_path(signed_artifact_raw, base_dir=base_dir)

    signed_hash = ""
    if status == "signed":
        if signed_artifact_path is None or not signed_artifact_path.exists() or not signed_artifact_path.is_file():
            reasons.append("signed_artifact_not_found")
        else:
            signed_hash = _sha256(signed_artifact_path)

    integrity_match: bool | None = None
    if status == "signed" and original_hash and signed_hash:
        integrity_match = original_hash == signed_hash
        if not integrity_match and not bool(args.allow_hash_mismatch):
            reasons.append("artifact_hash_mismatch")

    handoff.update(
        {
            "signing_status": status,
            "signer_identity": signer_identity,
            "signed_artifact_path": str(signed_artifact_path) if signed_artifact_path is not None else "",
            "signed_artifact_hash_sha256": signed_hash,
            "integrity_match": integrity_match,
            "signature_reference": str(args.signature_reference or "").strip(),
            "certificate_fingerprint": str(args.certificate_fingerprint or "").strip(),
            "signed_at": datetime.now(timezone.utc).isoformat() if status == "signed" else None,
        }
    )

    decision = "PASS"
    if status != "signed":
        decision = "FAIL"
    if reasons:
        decision = "FAIL"

    payload["signing_handoff_decision"] = decision

    out_manifest = Path(str(args.out_manifest)).expanduser().resolve() if str(args.out_manifest).strip() else manifest_path
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    out_dir = (
        Path(str(args.out_dir)).expanduser().resolve()
        if str(args.out_dir).strip()
        else (out_manifest.parent / "signing_reports")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_json = out_dir / f"mno_signing_handoff_{stamp}.json"
    report_md = out_dir / f"mno_signing_handoff_{stamp}.md"
    report_payload = {
        "decision": decision,
        "manifest": str(out_manifest),
        "status": status,
        "reasons": reasons,
        "signing_owner": str(payload.get("signing_owner") or ""),
        "signing_handoff": handoff,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report_json.write_text(json.dumps(report_payload, indent=2) + "\n", encoding="utf-8")
    report_md.write_text(_render_markdown(payload, decision=decision, reasons=reasons), encoding="utf-8")

    print(f"decision={decision}")
    print(f"manifest_json={out_manifest}")
    print(f"report_json={report_json}")
    print(f"report_md={report_md}")
    print(f"signing_status={status}")
    if reasons:
        print(f"reasons={','.join(reasons)}")
        return 2
    print("reasons=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
