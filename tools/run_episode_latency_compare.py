#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _run(command: list[str], *, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fp:
        fp.write(f"[{datetime.now(timezone.utc).isoformat()}] command={' '.join(command)}\n")
        fp.flush()
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip("\n")
            print(text)
            fp.write(text + "\n")
            fp.flush()
        return int(proc.wait())


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_episode_cards() -> Path | None:
    episodes_dir = REPO_ROOT / "runtime" / "episodes"
    if not episodes_dir.exists():
        return None
    candidates = sorted(episodes_dir.glob("episode_cards_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    fallback = episodes_dir / "episode_cards.json"
    if fallback.exists():
        return fallback
    return None


def _write_md(path: Path, payload: dict[str, Any]) -> None:
    baseline = payload["baseline"]
    episodic = payload["episodic"]
    delta = payload["delta"]
    lines = [
        "# Episode Latency Compare",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- memories: `{payload['memories_path']}`",
        f"- truthset: `{payload['truthset_path']}`",
        f"- episode_cards: `{payload['episode_cards_path']}`",
        "",
        "## Baseline (episodes disabled)",
        f"- cases: `{baseline.get('cases')}`",
        f"- avg_latency_ms: `{float(baseline.get('avg_latency_ms') or 0.0):.2f}`",
        f"- p95_latency_ms: `{float(baseline.get('p95_latency_ms') or 0.0):.2f}`",
        "",
        "## Episodic (episodes enabled)",
        f"- cases: `{episodic.get('cases')}`",
        f"- avg_latency_ms: `{float(episodic.get('avg_latency_ms') or 0.0):.2f}`",
        f"- p95_latency_ms: `{float(episodic.get('p95_latency_ms') or 0.0):.2f}`",
        "",
        "## Delta",
        f"- avg_latency_delta_ms: `{float(delta.get('avg_latency_ms') or 0.0):.2f}`",
        f"- p95_latency_delta_ms: `{float(delta.get('p95_latency_ms') or 0.0):.2f}`",
        "",
        "## Episodic memory-mode breakdown",
    ]
    mode_counts = episodic.get("memory_mode_case_counts") or {}
    mode_avg = episodic.get("memory_mode_avg_latency_ms") or {}
    mode_p95 = episodic.get("memory_mode_p95_latency_ms") or {}
    for key in sorted(mode_counts.keys()):
        lines.append(
            f"- {key}: count=`{int(mode_counts.get(key) or 0)}` "
            f"avg_ms=`{float(mode_avg.get(key) or 0.0):.2f}` "
            f"p95_ms=`{float(mode_p95.get(key) or 0.0):.2f}`"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare eval latency with episodes disabled vs enabled.")
    parser.add_argument("--memories", required=True, help="Path to sqlite/json memories artifact.")
    parser.add_argument("--episode-cards", default="", help="Path to episode cards JSON.")
    parser.add_argument("--build-episodes", action="store_true", help="Build episode cards when not supplied.")
    parser.add_argument("--requested-cases", type=int, default=120)
    parser.add_argument("--scan-budget", type=int, default=600000)
    parser.add_argument("--fixture-mode", choices=["basic", "trust-v2", "trust-v3"], default="trust-v3")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--batch-pause-ms", type=int, default=100)
    parser.add_argument("--out-dir", default="", help="Output directory (default runtime/evals/episode_compare_<stamp>).")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2

    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if str(args.out_dir).strip()
        else REPO_ROOT / "runtime" / "evals" / f"episode_compare_{_stamp()}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "logs"
    baseline_dir = out_dir / "baseline"
    episodic_dir = out_dir / "episodic"

    python_exe = sys.executable
    episode_cards_path = Path(args.episode_cards).expanduser().resolve() if str(args.episode_cards).strip() else _default_episode_cards()

    if episode_cards_path is None and args.build_episodes:
        generated = out_dir / "episode_cards.json"
        rc = _run(
            [
                python_exe,
                str(REPO_ROOT / "tools" / "build_episode_cards.py"),
                "--memories",
                str(memories_path),
                "--out",
                str(generated),
            ],
            log_path=logs_dir / "01_build_episode_cards.log",
        )
        if rc != 0:
            print("error=build episode cards failed")
            return 2
        episode_cards_path = generated

    if episode_cards_path is None or not episode_cards_path.exists():
        print("error=episode cards path missing; provide --episode-cards or set --build-episodes")
        return 2

    baseline_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_truthset_eval.py"),
        "--memories",
        str(memories_path),
        "--requested-cases",
        str(max(1, int(args.requested_cases))),
        "--scan-budget",
        str(max(1, int(args.scan_budget))),
        "--fixture-mode",
        str(args.fixture_mode),
        "--batch-size",
        str(max(0, int(args.batch_size))),
        "--batch-pause-ms",
        str(max(0, int(args.batch_pause_ms))),
        "--out-dir",
        str(baseline_dir),
        "--disable-episodes",
    ]
    if _run(baseline_cmd, log_path=logs_dir / "02_baseline.log") != 0:
        print("error=baseline eval failed")
        return 2

    truthset_path = baseline_dir / "truthset.generated.jsonl"
    if not truthset_path.exists():
        print(f"error=missing baseline truthset: {truthset_path}")
        return 2

    episodic_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_truthset_eval.py"),
        "--memories",
        str(memories_path),
        "--truthset",
        str(truthset_path),
        "--requested-cases",
        str(max(1, int(args.requested_cases))),
        "--scan-budget",
        str(max(1, int(args.scan_budget))),
        "--fixture-mode",
        str(args.fixture_mode),
        "--batch-size",
        str(max(0, int(args.batch_size))),
        "--batch-pause-ms",
        str(max(0, int(args.batch_pause_ms))),
        "--out-dir",
        str(episodic_dir),
        "--episode-cards",
        str(episode_cards_path),
    ]
    if _run(episodic_cmd, log_path=logs_dir / "03_episodic.log") != 0:
        print("error=episodic eval failed")
        return 2

    baseline_summary = _read_json(baseline_dir / "summary.json")
    episodic_summary = _read_json(episodic_dir / "summary.json")
    compare = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "memories_path": str(memories_path),
        "episode_cards_path": str(episode_cards_path),
        "truthset_path": str(truthset_path),
        "baseline": baseline_summary,
        "episodic": episodic_summary,
        "delta": {
            "avg_latency_ms": float(episodic_summary.get("avg_latency_ms") or 0.0)
            - float(baseline_summary.get("avg_latency_ms") or 0.0),
            "p95_latency_ms": float(episodic_summary.get("p95_latency_ms") or 0.0)
            - float(baseline_summary.get("p95_latency_ms") or 0.0),
        },
    }

    compare_json = out_dir / "episode_latency_compare.json"
    compare_md = out_dir / "episode_latency_compare.md"
    compare_json.write_text(json.dumps(compare, indent=2) + "\n", encoding="utf-8")
    _write_md(compare_md, compare)

    print("decision=PASS")
    print(f"compare_json={compare_json}")
    print(f"compare_md={compare_md}")
    print(f"baseline_summary_json={baseline_dir / 'summary.json'}")
    print(f"episodic_summary_json={episodic_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
