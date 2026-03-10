from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "context_checkpoint.py"
    spec = importlib.util.spec_from_file_location("context_checkpoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_writes_latest_files(tmp_path: Path) -> None:
    module = _load_module()
    code = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "snapshot",
            "--step",
            "phaseU-start",
            "--note",
            "starting phase U",
            "--next-cmd",
            "pytest -q",
            "--label",
            "phaseu-start",
            "--track",
            "MNO_LEAN_RETRIEVAL WORK",
            "--no-set-current",
            "--validation",
            "pending",
            "--extra",
            "merged_pr=70",
        ]
    )
    assert code == 0
    latest_json = tmp_path / "runtime" / "checkpoints" / "LATEST.json"
    latest_md = tmp_path / "runtime" / "checkpoints" / "LATEST.md"
    assert latest_json.is_file()
    assert latest_md.is_file()
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload["schema"] == "impressio.context_checkpoint.latest.v2"
    assert payload["current_track"] == "MNO_LEAN_RETRIEVAL WORK"
    assert payload["step"] == "phaseU-start"
    assert payload["next_cmd"] == "pytest -q"
    tracks = payload.get("tracks")
    assert isinstance(tracks, dict)
    assert "MNO_LEAN_RETRIEVAL WORK" in tracks
    assert tracks["MNO_LEAN_RETRIEVAL WORK"]["merged_pr"] == "70"
    latest_text = latest_md.read_text(encoding="utf-8")
    assert "## CURRENT" in latest_text
    assert "- track: MNO_LEAN_RETRIEVAL WORK" in latest_text
    assert "## MNO_LEAN_RETRIEVAL WORK" not in latest_text


def test_resume_reads_latest(tmp_path: Path) -> None:
    module = _load_module()
    checkpoint_dir = tmp_path / "runtime" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "impressio.context_checkpoint.v1",
        "step": "phaseU-tested",
        "note": "all tests passed",
        "branch": "main",
        "head_short": "abc1234",
        "validation": "pytest -q",
        "next_cmd": "open PR",
    }
    (checkpoint_dir / "LATEST.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    (checkpoint_dir / "LATEST.md").write_text("# Checkpoint\n- step: phaseU-tested\n", encoding="utf-8")
    code = module.main(["--repo-root", str(tmp_path), "resume"])
    assert code == 0


def test_snapshot_appends_track_without_overwriting_legacy_current(tmp_path: Path) -> None:
    module = _load_module()
    checkpoint_dir = tmp_path / "runtime" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "step": "jx-phase-validation-start",
        "note": "JX control then jump",
        "branch": "jx-real-jump-debug-harden",
        "head": "780c2dc9",
        "next_cmd": "python3 tools/run_live_runtime.py ...",
        "validations": [
            "jx_phase_validation_plan_loaded_from_docs_ano_jump_execution_and_debug_spec_md",
        ],
    }
    (checkpoint_dir / "LATEST.json").write_text(json.dumps(legacy_payload) + "\n", encoding="utf-8")
    (checkpoint_dir / "LATEST.md").write_text(
        "# LATEST Checkpoint\n\n## CURRENT\n- step: jx-phase-validation-start\n",
        encoding="utf-8",
    )

    code = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "snapshot",
            "--step",
            "mlrb-001-pr-workflow",
            "--note",
            "run pr workflow for #242",
            "--next-cmd",
            "python3 tools/run_pr_workflow.py --pr 242",
            "--label",
            "mlrb-001-pr-workflow",
            "--track",
            "MNO_LEAN_RETRIEVAL WORK",
            "--no-set-current",
            "--validation",
            "pending",
        ]
    )
    assert code == 0
    merged = json.loads((checkpoint_dir / "LATEST.json").read_text(encoding="utf-8"))
    assert merged["schema"] == "impressio.context_checkpoint.latest.v2"
    assert merged["current_track"] == "CURRENT"
    tracks = merged.get("tracks")
    assert isinstance(tracks, dict)
    assert "CURRENT" in tracks
    assert tracks["CURRENT"]["step"] == "jx-phase-validation-start"
    assert "MNO_LEAN_RETRIEVAL WORK" in tracks
    assert tracks["MNO_LEAN_RETRIEVAL WORK"]["step"] == "mlrb-001-pr-workflow"
    latest_text = (checkpoint_dir / "LATEST.md").read_text(encoding="utf-8")
    assert "## CURRENT" in latest_text
    assert "- track: CURRENT" in latest_text
    assert "## MNO_LEAN_RETRIEVAL WORK" in latest_text


def test_resume_reads_specific_track_from_latest_v2(tmp_path: Path) -> None:
    module = _load_module()
    checkpoint_dir = tmp_path / "runtime" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "impressio.context_checkpoint.latest.v2",
        "current_track": "CURRENT",
        "tracks": {
            "CURRENT": {
                "track": "CURRENT",
                "step": "jx-phase-validation-start",
                "note": "jx execution",
                "branch": "jx-real-jump-debug-harden",
                "head": "780c2dc9",
                "next_cmd": "python3 tools/run_live_runtime.py ...",
            },
            "MNO_LEAN_RETRIEVAL WORK": {
                "track": "MNO_LEAN_RETRIEVAL WORK",
                "step": "mlrb-001-pr-workflow",
                "note": "run pr workflow for #242",
                "branch": "mno-mlrb-001-005-retrieval-core",
                "head": "2df4a1a1",
                "next_cmd": "python3 tools/run_pr_workflow.py --pr 242",
            },
        },
    }
    (checkpoint_dir / "LATEST.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    (checkpoint_dir / "LATEST.md").write_text("# LATEST Checkpoint\n", encoding="utf-8")
    code = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "resume",
            "--track",
            "MNO_LEAN_RETRIEVAL WORK",
        ]
    )
    assert code == 0


def test_git_value_falls_back_when_git_missing(tmp_path: Path) -> None:
    module = _load_module()

    def _raise_oserror(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("git not found")

    module._run = _raise_oserror
    value = module._git_value(repo_root=tmp_path, args=["rev-parse", "--short", "HEAD"], fallback="unknown")
    assert value == "unknown"


def test_resume_returns_error_for_invalid_latest_json(tmp_path: Path) -> None:
    module = _load_module()
    checkpoint_dir = tmp_path / "runtime" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "LATEST.json").write_text("{not-valid-json", encoding="utf-8")
    code = module.main(["--repo-root", str(tmp_path), "resume"])
    assert code == 2


def test_resume_returns_error_for_non_object_latest_json(tmp_path: Path) -> None:
    module = _load_module()
    checkpoint_dir = tmp_path / "runtime" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "LATEST.json").write_text("[]", encoding="utf-8")
    code = module.main(["--repo-root", str(tmp_path), "resume"])
    assert code == 2
