from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "run_pr_workflow.py"
    spec = importlib.util.spec_from_file_location("run_pr_workflow", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_command_includes_expected_args(tmp_path: Path) -> None:
    workflow = _load_module()
    args = workflow.argparse.Namespace(
        repo="owner/repo",
        pr=77,
        gate_timeout_sec=123,
        gate_poll_sec=17,
        check_signal_settle_sec=121,
        auto_nudge_after_sec=456,
        require_submitted_review=True,
        nudge_comment_body="@coderabbitai review",
        allow_no_review=False,
        disable_auto_nudge=False,
        once=False,
    )
    cmd = workflow._gate_command(args, repo_root=tmp_path)
    joined = " ".join(cmd)
    assert "--repo owner/repo" in joined
    assert "--pr 77" in joined
    assert "--timeout-sec 123" in joined
    assert "--poll-sec 17" in joined
    assert "--check-signal-settle-sec 121" in joined
    assert "--auto-nudge-after-sec 456" in joined
    assert "--require-submitted-review" in joined


def test_gate_command_includes_optional_flags(tmp_path: Path) -> None:
    workflow = _load_module()
    args = workflow.argparse.Namespace(
        repo="owner/repo",
        pr=78,
        gate_timeout_sec=300,
        gate_poll_sec=15,
        check_signal_settle_sec=60,
        auto_nudge_after_sec=0,
        require_submitted_review=False,
        nudge_comment_body="@coderabbitai review",
        allow_no_review=True,
        disable_auto_nudge=True,
        once=True,
    )
    cmd = workflow._gate_command(args, repo_root=tmp_path)
    assert "--allow-no-review" in cmd
    assert "--require-submitted-review" not in cmd
    assert "--disable-auto-nudge" in cmd
    assert "--once" in cmd


def test_main_runs_comment_gate_and_merge(tmp_path: Path) -> None:
    workflow = _load_module()
    calls: list[list[str]] = []
    workflow._coderabbit_review_count = lambda **_: 0

    def _fake_run(cmd: list[str], **kwargs: Path) -> int:
        _ = kwargs.get("cwd")
        calls.append(cmd)
        return 0

    workflow._run = _fake_run
    code = workflow.main(
        [
            "--repo",
            "owner/repo",
            "--pr",
            "88",
            "--repo-root",
            str(tmp_path),
            "--request-review-comment",
            "--merge",
        ]
    )
    assert code == 0
    assert len(calls) == 3
    assert calls[0][:4] == ["gh", "pr", "comment", "88"]
    assert calls[1][0].endswith("python") or calls[1][0].endswith("python3")
    assert "pr_feedback_gate.py" in str(calls[1][1])
    assert calls[2][:4] == ["gh", "pr", "merge", "88"]


def test_main_returns_gate_failure_code(tmp_path: Path) -> None:
    workflow = _load_module()
    calls: list[list[str]] = []
    workflow._coderabbit_review_count = lambda **_: 0

    def _fake_run(cmd: list[str], **kwargs: Path) -> int:
        _ = kwargs.get("cwd")
        calls.append(cmd)
        if "pr_feedback_gate.py" in " ".join(cmd):
            return 3
        return 0

    workflow._run = _fake_run
    code = workflow.main(
        [
            "--repo",
            "owner/repo",
            "--pr",
            "89",
            "--repo-root",
            str(tmp_path),
            "--merge",
        ]
    )
    assert code == 3
    assert len(calls) == 2
    primary, fallback = calls
    assert "pr_feedback_gate.py" in " ".join(primary)
    assert "--allow-no-review" not in primary
    assert "pr_feedback_gate.py" in " ".join(fallback)
    assert "--allow-no-review" in fallback
    assert "--once" in fallback


def test_main_uses_fallback_when_primary_gate_times_out(tmp_path: Path) -> None:
    workflow = _load_module()
    calls: list[list[str]] = []
    workflow._coderabbit_review_count = lambda **_: 1

    def _fake_run(cmd: list[str], **kwargs: Path) -> int:
        _ = kwargs.get("cwd")
        calls.append(cmd)
        command = " ".join(cmd)
        if "pr_feedback_gate.py" in command and "--allow-no-review" not in cmd:
            return 3
        if "pr_feedback_gate.py" in command and "--allow-no-review" in cmd:
            return 0
        return 0

    workflow._run = _fake_run
    code = workflow.main(
        [
            "--repo",
            "owner/repo",
            "--pr",
            "90",
            "--repo-root",
            str(tmp_path),
            "--gate-mode",
            "initial",
            "--fallback-on-timeout",
        ]
    )
    assert code == 0
    assert len(calls) == 2
    assert any("--allow-no-review" in call for call in calls)
    assert any("--once" in call for call in calls)
    reports = sorted(tmp_path.glob("runtime/reports/pr_workflow_pr90_*.json"))
    assert reports


def test_main_does_not_fallback_without_flag(tmp_path: Path) -> None:
    workflow = _load_module()
    calls: list[list[str]] = []
    workflow._coderabbit_review_count = lambda **_: 0

    def _fake_run(cmd: list[str], **kwargs: Path) -> int:
        _ = kwargs.get("cwd")
        calls.append(cmd)
        if "pr_feedback_gate.py" in " ".join(cmd):
            return 3
        return 0

    workflow._run = _fake_run
    code = workflow.main(
        [
            "--repo",
            "owner/repo",
            "--pr",
            "91",
            "--repo-root",
            str(tmp_path),
            "--no-fallback-on-timeout",
        ]
    )
    assert code == 3
    assert len(calls) == 1


def test_resolve_gate_args_auto_uses_initial_mode_when_no_reviews(tmp_path: Path) -> None:
    workflow = _load_module()
    workflow._coderabbit_review_count = lambda **_: 0
    args = workflow.argparse.Namespace(
        repo="owner/repo",
        pr=92,
        gate_mode="auto",
        gate_timeout_sec=900,
        gate_poll_sec=30,
        check_signal_settle_sec=180,
        auto_nudge_after_sec=600,
        require_submitted_review=True,
        nudge_comment_body="@coderabbitai review",
        allow_no_review=False,
        disable_auto_nudge=False,
        once=False,
        fallback_on_timeout=True,
        fallback_timeout_sec=120,
        allow_check_signal=False,
        post_fix_no_resubmit=False,
        report_dir="runtime/reports",
    )
    gate_args, metadata = workflow._resolve_gate_args(args, repo_root=tmp_path)
    assert metadata["gate_mode_effective"] == "initial"
    assert gate_args.require_submitted_review is True
    assert gate_args.allow_no_review is False
    assert gate_args.once is False


def test_resolve_gate_args_auto_uses_post_fix_mode_when_reviews_exist(tmp_path: Path) -> None:
    workflow = _load_module()
    workflow._coderabbit_review_count = lambda **_: 2
    args = workflow.argparse.Namespace(
        repo="owner/repo",
        pr=93,
        gate_mode="auto",
        gate_timeout_sec=900,
        gate_poll_sec=30,
        check_signal_settle_sec=180,
        auto_nudge_after_sec=600,
        require_submitted_review=True,
        nudge_comment_body="@coderabbitai review",
        allow_no_review=False,
        disable_auto_nudge=False,
        once=False,
        fallback_on_timeout=True,
        fallback_timeout_sec=120,
        allow_check_signal=False,
        post_fix_no_resubmit=False,
        report_dir="runtime/reports",
    )
    gate_args, metadata = workflow._resolve_gate_args(args, repo_root=tmp_path)
    assert metadata["gate_mode_effective"] == "post-fix"
    assert gate_args.require_submitted_review is False
    assert gate_args.allow_no_review is True
    assert gate_args.once is True
    assert gate_args.disable_auto_nudge is True
    assert int(gate_args.auto_nudge_after_sec) == 0
    assert int(gate_args.gate_timeout_sec) == 120


def test_coderabbit_review_count_returns_none_when_gh_missing(tmp_path: Path) -> None:
    workflow = _load_module()

    def _missing(*args, **kwargs):  # noqa: ANN001, ANN002
        raise FileNotFoundError("gh not installed")

    workflow.subprocess.run = _missing
    assert workflow._coderabbit_review_count(pr=1, repo_root=tmp_path) is None


def test_coderabbit_review_count_returns_none_on_timeout(tmp_path: Path) -> None:
    workflow = _load_module()

    def _timeout(*args, **kwargs):  # noqa: ANN001, ANN002
        raise subprocess.TimeoutExpired(cmd="gh pr view", timeout=workflow.GH_METADATA_TIMEOUT_SEC)

    workflow.subprocess.run = _timeout
    assert workflow._coderabbit_review_count(pr=1, repo_root=tmp_path) is None
