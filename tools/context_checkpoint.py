#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA = "impressio.context_checkpoint.v1"
LATEST_SCHEMA = "impressio.context_checkpoint.latest.v2"


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _git_value(*, repo_root: Path, args: list[str], fallback: str) -> str:
    try:
        proc = _run(["git", *args], cwd=repo_root)
    except OSError:
        return fallback
    if proc.returncode != 0:
        return fallback
    value = str(proc.stdout or "").strip()
    return value or fallback


def _sanitize_label(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    safe = safe.strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe or "checkpoint"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_track_name(value: str, *, fallback: str = "CURRENT") -> str:
    track = str(value or "").strip()
    return track or fallback


def _coerce_checkpoint_entry(raw: dict[str, Any], *, track: str) -> dict[str, Any]:
    entry = dict(raw)
    entry["track"] = _normalize_track_name(str(entry.get("track") or track), fallback=track)
    entry["step"] = str(entry.get("step") or "").strip()
    entry["note"] = str(entry.get("note") or "").strip()
    entry["branch"] = str(entry.get("branch") or "").strip()
    head = str(entry.get("head") or entry.get("head_short") or "").strip()
    entry["head"] = head
    entry["head_short"] = str(entry.get("head_short") or head).strip()
    validation = entry.get("validation")
    if not str(validation or "").strip():
        validations = entry.get("validations")
        if isinstance(validations, list):
            compact = [str(item).strip() for item in validations if str(item).strip()]
            validation = ", ".join(compact)
        elif isinstance(validations, str):
            validation = validations
    entry["validation"] = str(validation or "").strip()
    entry["next_cmd"] = str(entry.get("next_cmd") or "").strip()
    recorded_at = str(entry.get("recorded_at") or entry.get("updated_at") or "").strip()
    if recorded_at:
        entry["recorded_at"] = recorded_at
    return entry


def _coerce_latest_payload(raw: dict[str, Any]) -> dict[str, Any]:
    tracks_raw = raw.get("tracks")
    if isinstance(tracks_raw, dict):
        tracks: dict[str, dict[str, Any]] = {}
        for name, payload in tracks_raw.items():
            if isinstance(payload, dict):
                track_name = _normalize_track_name(str(name), fallback="CURRENT")
                tracks[track_name] = _coerce_checkpoint_entry(payload, track=track_name)
        current = _normalize_track_name(str(raw.get("current_track") or ""), fallback="")
        if not current or current not in tracks:
            current = next(iter(tracks.keys()), "")
        return {
            "schema": LATEST_SCHEMA,
            "current_track": current,
            "updated_at": str(raw.get("updated_at") or "").strip(),
            "tracks": tracks,
        }

    # Legacy single-entry checkpoint support.
    track = _normalize_track_name(str(raw.get("track") or ""), fallback="CURRENT")
    return {
        "schema": LATEST_SCHEMA,
        "current_track": track,
        "updated_at": str(raw.get("updated_at") or "").strip(),
        "tracks": {track: _coerce_checkpoint_entry(raw, track=track)},
    }


def _load_latest_payload(*, checkpoint_dir: Path) -> dict[str, Any]:
    latest_json = checkpoint_dir / "LATEST.json"
    if not latest_json.is_file():
        return {"schema": LATEST_SCHEMA, "current_track": "", "updated_at": "", "tracks": {}}
    raw = json.loads(latest_json.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid checkpoint: {latest_json}: expected object")
    return _coerce_latest_payload(raw)


def _format_markdown_value(value: Any) -> str:
    if isinstance(value, list):
        compact = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(compact)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _render_track_section(*, heading: str, payload: dict[str, Any], include_track_line: bool) -> list[str]:
    lines = [f"## {heading}"]
    if include_track_line:
        lines.append(f"- track: {payload.get('track', '')}")
    ordered_keys = ["step", "note", "branch", "head", "next_cmd", "validation", "recorded_at"]
    seen: set[str] = set()
    for key in ordered_keys:
        if key in payload and str(payload.get(key) or "").strip():
            lines.append(f"- {key}: {_format_markdown_value(payload.get(key))}")
            seen.add(key)
    for key, value in payload.items():
        if key in seen or key in {"schema", "head_short", "track"}:
            continue
        text = _format_markdown_value(value).strip()
        if text:
            lines.append(f"- {key}: {text}")
    return lines


def _render_latest_md(*, latest_payload: dict[str, Any]) -> str:
    lines = ["# LATEST Checkpoint", ""]
    tracks = latest_payload.get("tracks")
    if not isinstance(tracks, dict) or not tracks:
        lines.append("## CURRENT")
        lines.append("- track: ")
        lines.append("- step: ")
        lines.append("- note: ")
        lines.append("- branch: ")
        lines.append("- head: ")
        lines.append("- next_cmd: ")
        return "\n".join(lines) + "\n"

    current_track = _normalize_track_name(str(latest_payload.get("current_track") or ""), fallback="")
    current_payload = tracks.get(current_track) if current_track else None
    if not isinstance(current_payload, dict):
        current_track = next(iter(tracks.keys()))
        current_payload = tracks[current_track]
    lines.extend(_render_track_section(heading="CURRENT", payload=current_payload, include_track_line=True))

    for name, payload in tracks.items():
        if name == current_track:
            continue
        if not isinstance(payload, dict):
            continue
        lines.append("")
        lines.extend(_render_track_section(heading=name, payload=payload, include_track_line=False))
    return "\n".join(lines) + "\n"


def _write_checkpoint(
    *,
    repo_root: Path,
    checkpoint_dir: Path,
    step: str,
    note: str,
    next_cmd: str,
    label: str,
    track: str,
    set_current: bool,
    validation: str,
    extra: dict[str, Any],
) -> tuple[Path, Path]:
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    branch = _git_value(repo_root=repo_root, args=["branch", "--show-current"], fallback="unknown")
    head_short = _git_value(repo_root=repo_root, args=["rev-parse", "--short", "HEAD"], fallback="unknown")
    filename = f"context_checkpoint_{stamp}_{_sanitize_label(label)}"
    md_path = checkpoint_dir / f"{filename}.md"
    json_path = checkpoint_dir / f"{filename}.json"

    track_name = _normalize_track_name(track)
    payload: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "track": track_name,
        "step": str(step).strip(),
        "note": str(note).strip(),
        "branch": branch,
        "head_short": head_short,
        "head": head_short,
        "validation": str(validation).strip(),
        "next_cmd": str(next_cmd).strip(),
        "recorded_at": _now().isoformat(),
    }
    reserved = set(payload.keys())
    safe_extra = {key: value for key, value in extra.items() if key and key not in reserved}
    payload.update(safe_extra)

    md_lines = [
        "# Checkpoint",
        f"- track: {payload['track']}",
        f"- step: {payload['step']}",
        f"- note: {payload['note']}",
        f"- branch: {payload['branch']}",
        f"- head: {payload['head']}",
        f"- validation: {payload['validation']}",
        f"- next_cmd: {payload['next_cmd']}",
        f"- recorded_at: {payload['recorded_at']}",
    ]
    for key, value in safe_extra.items():
        md_lines.append(f"- {key}: {value}")

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    latest_payload = _load_latest_payload(checkpoint_dir=checkpoint_dir)
    tracks = latest_payload.get("tracks")
    if not isinstance(tracks, dict):
        tracks = {}
    tracks[track_name] = _coerce_checkpoint_entry(payload, track=track_name)
    latest_payload["tracks"] = tracks
    if set_current or not _normalize_track_name(str(latest_payload.get("current_track") or ""), fallback=""):
        latest_payload["current_track"] = track_name
    latest_payload["updated_at"] = _now().isoformat()
    current_track = _normalize_track_name(str(latest_payload.get("current_track") or ""), fallback="")
    current_payload = tracks.get(current_track) if current_track else None
    if not isinstance(current_payload, dict):
        current_track = next(iter(tracks.keys()), "")
        current_payload = tracks.get(current_track) if current_track else None
        latest_payload["current_track"] = current_track
    if isinstance(current_payload, dict):
        for key in ("step", "note", "branch", "head", "head_short", "validation", "next_cmd"):
            latest_payload[key] = current_payload.get(key, "")
    latest_json_path = checkpoint_dir / "LATEST.json"
    latest_md_path = checkpoint_dir / "LATEST.md"
    latest_json_path.write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_md_path.write_text(_render_latest_md(latest_payload=latest_payload), encoding="utf-8")
    return md_path, json_path


def _parse_extra(values: list[str]) -> dict[str, str]:
    extra: dict[str, str] = {}
    for item in values:
        text = str(item or "").strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if not key:
            continue
        extra[key] = value.strip()
    return extra


def _cmd_snapshot(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    checkpoint_dir = repo_root / "runtime" / "checkpoints"
    extra = _parse_extra(args.extra or [])
    try:
        md_path, json_path = _write_checkpoint(
            repo_root=repo_root,
            checkpoint_dir=checkpoint_dir,
            step=args.step,
            note=args.note,
            next_cmd=args.next_cmd,
            label=args.label,
            track=args.track,
            set_current=bool(args.set_current),
            validation=args.validation,
            extra=extra,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error=failed to write checkpoint: {exc}")
        return 2
    print(f"checkpoint_md={md_path}")
    print(f"checkpoint_json={json_path}")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    checkpoint_dir = repo_root / "runtime" / "checkpoints"
    latest_json = checkpoint_dir / "LATEST.json"
    latest_md = checkpoint_dir / "LATEST.md"
    if not latest_json.is_file():
        print(f"error=no checkpoint found: {latest_json}")
        return 2
    try:
        payload = json.loads(latest_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error=invalid checkpoint: {latest_json}: {exc}")
        return 2
    if not isinstance(payload, dict):
        print(f"error=invalid checkpoint: {latest_json}: expected object")
        return 2
    try:
        latest_payload = _coerce_latest_payload(payload)
    except ValueError as exc:
        print(f"error={exc}")
        return 2

    tracks = latest_payload.get("tracks")
    if not isinstance(tracks, dict) or not tracks:
        print(f"error=invalid checkpoint: {latest_json}: no tracks found")
        return 2
    requested = _normalize_track_name(str(getattr(args, "track", "") or ""), fallback="")
    selected = requested or _normalize_track_name(str(latest_payload.get("current_track") or ""), fallback="")
    if not selected:
        selected = next(iter(tracks.keys()))
    if selected not in tracks:
        available = ", ".join(tracks.keys())
        print(f"error=track not found: {selected} (available: {available})")
        return 2
    entry = _coerce_checkpoint_entry(tracks[selected], track=selected)
    print(f"track={selected}")
    print(f"step={entry.get('step', '')}")
    print(f"note={entry.get('note', '')}")
    print(f"branch={entry.get('branch', '')}")
    print(f"head={entry.get('head', '')}")
    print(f"next_cmd={entry.get('next_cmd', '')}")
    print(f"available_tracks={','.join(tracks.keys())}")
    if bool(args.live):
        if latest_md.is_file():
            print(latest_md.read_text(encoding="utf-8").rstrip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write and restore execution checkpoints.")
    parser.add_argument("--repo-root", default=".", help="repository root (default: current directory)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snap = subparsers.add_parser("snapshot", help="write a checkpoint and update LATEST files")
    snap.add_argument("--step", required=True)
    snap.add_argument("--note", required=True)
    snap.add_argument("--next-cmd", required=True)
    snap.add_argument("--label", default="checkpoint")
    snap.add_argument("--track", default="CURRENT", help="workstream/agent track label")
    snap.add_argument(
        "--set-current",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="set this track as CURRENT in LATEST (use --no-set-current to preserve existing CURRENT)",
    )
    snap.add_argument("--validation", default="pending")
    snap.add_argument("--extra", action="append", default=[], help="additional key=value pairs")
    snap.set_defaults(func=_cmd_snapshot)

    resume = subparsers.add_parser("resume", help="print latest checkpoint summary")
    resume.add_argument("--track", default="", help="track label to resume")
    resume.add_argument("--live", action="store_true", help="print full latest markdown checkpoint")
    resume.set_defaults(func=_cmd_resume)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
