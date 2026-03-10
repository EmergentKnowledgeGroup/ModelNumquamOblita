from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


def _load_gate_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "pr_feedback_gate.py"
    spec = importlib.util.spec_from_file_location("pr_feedback_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unresolved_actionable_count_ignores_resolved_threads(tmp_path: Path) -> None:
    gate = _load_gate_module()
    raw_path = tmp_path / "raw.json"
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "thread_1",
                                "isResolved": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 10,
                                            "url": "https://example.com/1",
                                        }
                                    ]
                                },
                            },
                            {
                                "id": "thread_2",
                                "isResolved": True,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 22,
                                            "url": "https://example.com/2",
                                        }
                                    ]
                                },
                            },
                        ]
                    }
                }
            }
        }
    }
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = {"raw_json": str(raw_path)}
    assert gate._unresolved_actionable_count(snapshot) == 1


def test_unresolved_actionable_count_ignores_addressed_threads(tmp_path: Path) -> None:
    gate = _load_gate_module()
    raw_path = tmp_path / "raw.json"
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "thread_1",
                                "isResolved": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 10,
                                            "url": "https://example.com/1",
                                            "body": "Potential issue. ✅ Addressed in commit abc123",
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = {"raw_json": str(raw_path)}
    assert gate._unresolved_actionable_count(snapshot) == 0


def test_unresolved_actionable_count_ignores_outdated_threads(tmp_path: Path) -> None:
    gate = _load_gate_module()
    raw_path = tmp_path / "raw.json"
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "thread_1",
                                "isResolved": False,
                                "isOutdated": True,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 10,
                                            "url": "https://example.com/1",
                                            "body": "Potential issue still open",
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = {"raw_json": str(raw_path)}
    assert gate._unresolved_actionable_count(snapshot) == 0


def test_unresolved_actionable_count_prefers_latest_inline_timestamp(tmp_path: Path) -> None:
    gate = _load_gate_module()
    raw_path = tmp_path / "raw.json"
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "thread_1",
                                "isResolved": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 11,
                                            "url": "https://example.com/1",
                                            "createdAt": "2026-02-10T10:00:00Z",
                                            "body": "✅ Addressed in commit f00dbabe",
                                        },
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 10,
                                            "url": "https://example.com/1",
                                            "createdAt": "2026-02-10T09:00:00Z",
                                            "body": "Potential issue still open",
                                        },
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = {"raw_json": str(raw_path)}
    assert gate._unresolved_actionable_count(snapshot) == 0


def test_gate_state_requires_fresh_review() -> None:
    gate = _load_gate_module()
    snapshot = {"counts": {"actionable": 0, "outside_diff": 0, "nitpick": 0}}
    review = {
        "cr_review_count": 1,
        "review_is_fresh": False,
        "head_sha": "abc123456789",
        "head_age_sec": 420,
    }
    ok, message = gate._gate_state(snapshot=snapshot, review=review, require_review=True)
    assert ok is False
    assert "waiting for fresh CodeRabbit review" in message


def test_gate_state_allows_successful_check_signal_without_review() -> None:
    gate = _load_gate_module()
    snapshot = {"counts": {"actionable": 0, "outside_diff": 0, "nitpick": 0}}
    review = {
        "cr_review_count": 0,
        "has_review_signal": True,
        "review_signal_source": "check",
        "review_is_fresh": True,
        "check_present": True,
        "check_success": True,
    }
    ok, message = gate._gate_state(
        snapshot=snapshot,
        review=review,
        require_review=True,
        check_signal_settle_sec=0,
    )
    assert ok is True
    assert "review_signal=check" in message


def test_gate_state_waits_for_check_signal_settle_window() -> None:
    gate = _load_gate_module()
    snapshot = {"counts": {"actionable": 0, "outside_diff": 0, "nitpick": 0}}
    review = {
        "cr_review_count": 0,
        "has_review_signal": True,
        "review_signal_source": "check",
        "review_is_fresh": True,
        "check_present": True,
        "check_success": True,
    }
    ok, message = gate._gate_state(
        snapshot=snapshot,
        review=review,
        require_review=True,
        check_signal_settle_sec=120,
        check_signal_elapsed_sec=45,
    )
    assert ok is False
    assert "check-only review signal settling" in message


def test_gate_state_allows_successful_check_signal_with_stale_review() -> None:
    gate = _load_gate_module()
    snapshot = {"counts": {"actionable": 0, "outside_diff": 1, "nitpick": 0}}
    review = {
        "cr_review_count": 1,
        "has_review_signal": True,
        "review_signal_source": "check",
        "review_is_fresh": True,
        "check_present": True,
        "check_success": True,
    }
    ok, message = gate._gate_state(
        snapshot=snapshot,
        review=review,
        require_review=True,
        check_signal_settle_sec=120,
        check_signal_elapsed_sec=300,
    )
    assert ok is True
    assert "review_signal=check" in message


def test_gate_state_requires_submitted_review_when_enabled() -> None:
    gate = _load_gate_module()
    snapshot = {"counts": {"actionable": 0, "outside_diff": 0, "nitpick": 0}}
    review = {
        "cr_review_count": 0,
        "has_review_signal": True,
        "review_signal_source": "check",
        "review_is_fresh": True,
        "check_present": True,
        "check_success": True,
    }
    ok, message = gate._gate_state(
        snapshot=snapshot,
        review=review,
        require_review=True,
        require_submitted_review=True,
    )
    assert ok is False
    assert "waiting for submitted CodeRabbit review" in message


def test_gate_state_requires_fresh_submitted_review_when_enabled() -> None:
    gate = _load_gate_module()
    snapshot = {"counts": {"actionable": 0, "outside_diff": 0, "nitpick": 0}}
    review = {
        "cr_review_count": 1,
        "submitted_review_is_fresh": False,
        "has_review_signal": True,
        "review_signal_source": "check",
        "review_is_fresh": True,
        "check_present": True,
        "check_success": True,
        "head_sha": "deadbeefcafebabe",
    }
    ok, message = gate._gate_state(
        snapshot=snapshot,
        review=review,
        require_review=True,
        require_submitted_review=True,
    )
    assert ok is False
    assert "fresh submitted CodeRabbit review" in message


def test_gate_state_uses_unresolved_actionable_over_collector_count(tmp_path: Path) -> None:
    gate = _load_gate_module()
    raw_path = tmp_path / "raw.json"
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "thread_1",
                                "isResolved": True,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 10,
                                            "url": "https://example.com/1",
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = {
        "counts": {"actionable": 2, "outside_diff": 0, "nitpick": 0},
        "raw_json": str(raw_path),
    }
    review = {"cr_review_count": 1, "review_is_fresh": True}
    ok, message = gate._gate_state(snapshot=snapshot, review=review, require_review=True)
    assert ok is True
    assert "pass:" in message


def test_gate_state_prefers_live_unresolved_actionable_when_available() -> None:
    gate = _load_gate_module()
    snapshot = {"counts": {"actionable": 4, "outside_diff": 0, "nitpick": 0}}
    review = {"cr_review_count": 1, "review_is_fresh": True}
    ok, message = gate._gate_state(
        snapshot=snapshot,
        review=review,
        require_review=True,
        live_unresolved_actionable=0,
    )
    assert ok is True
    assert "pass:" in message


def test_live_unresolved_actionable_count_ignores_outdated_threads(tmp_path: Path) -> None:
    gate = _load_gate_module()
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "isResolved": False,
                                "isOutdated": True,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 12,
                                            "body": "Potential issue",
                                            "createdAt": "2026-02-10T10:00:00Z",
                                            "url": "https://example.com/t1",
                                        }
                                    ]
                                },
                            },
                            {
                                "isResolved": False,
                                "isOutdated": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "coderabbitai"},
                                            "position": 8,
                                            "body": "Potential issue",
                                            "createdAt": "2026-02-10T11:00:00Z",
                                            "url": "https://example.com/t2",
                                        }
                                    ]
                                },
                            },
                        ]
                    }
                }
            }
        }
    }

    def _fake_run(cmd: list[str], *, cwd: Path):
        _ = (cmd, cwd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    gate._run = _fake_run
    count = gate._live_unresolved_actionable_count(
        repo="owner/repo",
        pr=78,
        repo_root=tmp_path,
    )
    assert count == 1


def test_acquire_process_lock_rejects_active_holder(tmp_path: Path) -> None:
    gate = _load_gate_module()
    lock_path = tmp_path / "gate.lock.json"
    lock_path.write_text(
        json.dumps({"pid": 1234, "pr": 99}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    gate._pid_is_alive = lambda pid: int(pid) == 1234
    ok, holder = gate._acquire_process_lock(lock_path=lock_path, pr=99)
    assert ok is False
    assert holder == 1234


def test_acquire_process_lock_reclaims_stale_holder(tmp_path: Path) -> None:
    gate = _load_gate_module()
    lock_path = tmp_path / "gate.lock.json"
    lock_path.write_text(
        json.dumps({"pid": 987654, "pr": 88}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    gate._pid_is_alive = lambda pid: False
    ok, holder = gate._acquire_process_lock(lock_path=lock_path, pr=88)
    assert ok is True
    assert isinstance(holder, int) and holder > 0
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert int(payload.get("pid", 0)) == holder
    gate._release_process_lock(lock_path=lock_path)
    assert not lock_path.exists()


def test_maybe_trigger_review_nudge_posts_once_per_head(tmp_path: Path) -> None:
    gate = _load_gate_module()
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], *, cwd: Path):
        _ = cwd
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    gate._run = _fake_run
    state_path = tmp_path / "nudge_state.json"
    review = {
        "has_review_signal": False,
        "review_is_fresh": False,
        "head_sha": "abc123",
    }
    first = gate._maybe_trigger_review_nudge(
        pr=99,
        repo_root=tmp_path,
        review=review,
        require_submitted_review=False,
        elapsed_sec=420,
        nudge_after_sec=300,
        state_path=state_path,
        comment_body="@coderabbitai review",
    )
    assert first.get("nudged") is True
    assert len(calls) == 1
    assert state_path.is_file()

    second = gate._maybe_trigger_review_nudge(
        pr=99,
        repo_root=tmp_path,
        review=review,
        require_submitted_review=False,
        elapsed_sec=520,
        nudge_after_sec=300,
        state_path=state_path,
        comment_body="@coderabbitai review",
    )
    assert second.get("nudged") is False
    assert second.get("reason") == "already_nudged_for_head"
    assert len(calls) == 1


def test_maybe_trigger_review_nudge_skips_when_fresh_signal(tmp_path: Path) -> None:
    gate = _load_gate_module()
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], *, cwd: Path):
        _ = cwd
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    gate._run = _fake_run
    state_path = tmp_path / "nudge_state.json"
    review = {
        "has_review_signal": True,
        "review_is_fresh": True,
        "head_sha": "abc123",
    }
    result = gate._maybe_trigger_review_nudge(
        pr=101,
        repo_root=tmp_path,
        review=review,
        require_submitted_review=False,
        elapsed_sec=720,
        nudge_after_sec=300,
        state_path=state_path,
        comment_body="@coderabbitai review",
    )
    assert result.get("nudged") is False
    assert result.get("reason") == "fresh_signal_present"
    assert not calls


def test_maybe_trigger_review_nudge_fires_when_submitted_review_required(tmp_path: Path) -> None:
    gate = _load_gate_module()
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], *, cwd: Path):
        _ = cwd
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    gate._run = _fake_run
    state_path = tmp_path / "nudge_state.json"
    review = {
        "has_review_signal": True,
        "review_is_fresh": True,
        "cr_review_count": 0,
        "head_sha": "abc123",
    }
    result = gate._maybe_trigger_review_nudge(
        pr=102,
        repo_root=tmp_path,
        review=review,
        require_submitted_review=True,
        elapsed_sec=720,
        nudge_after_sec=300,
        state_path=state_path,
        comment_body="@coderabbitai review",
    )
    assert result.get("nudged") is True
    assert calls


def test_maybe_trigger_review_nudge_fires_when_submitted_review_is_stale(tmp_path: Path) -> None:
    gate = _load_gate_module()
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], *, cwd: Path):
        _ = cwd
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    gate._run = _fake_run
    state_path = tmp_path / "nudge_state.json"
    review = {
        "has_review_signal": True,
        "review_is_fresh": True,
        "cr_review_count": 1,
        "submitted_review_is_fresh": False,
        "head_sha": "abc123",
    }
    result = gate._maybe_trigger_review_nudge(
        pr=103,
        repo_root=tmp_path,
        review=review,
        require_submitted_review=True,
        elapsed_sec=720,
        nudge_after_sec=300,
        state_path=state_path,
        comment_body="@coderabbitai review",
    )
    assert result.get("nudged") is True
    assert calls
