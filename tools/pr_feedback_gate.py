#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _find_collector(explicit: str | None, *, repo_root: Path) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"collector not found: {path}")

    candidates = [
        repo_root / "tools" / "pr_feedback_collector.py",
        repo_root.parent / "pr_feedback_collector.py",
        Path("/mnt/z/openAIdata/pr_feedback_collector.py"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("unable to locate pr_feedback_collector.py; pass --collector")


def _collector_pass(
    *,
    repo: str,
    pr: int,
    collector: Path,
    out_dir: Path,
    repo_root: Path,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(collector),
        "--repo",
        repo,
        "--pr",
        str(pr),
        "--out",
        str(out_dir),
        "--authors",
        "coderabbitai",
        "--save-raw",
    ]
    proc = _run(cmd, cwd=repo_root)
    if proc.returncode != 0:
        raise RuntimeError(
            "collector failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    latest_path = out_dir / "latest_pr_feedback.json"
    if not latest_path.is_file():
        raise RuntimeError(f"collector did not produce {latest_path}")
    return json.loads(latest_path.read_text(encoding="utf-8"))


def _parse_iso8601(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pid_is_alive(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def _acquire_process_lock(*, lock_path: Path, pr: int) -> tuple[bool, int | None]:
    current_pid = int(os.getpid())
    if lock_path.is_file():
        lock_payload = _read_json(lock_path)
        lock_pid = int(lock_payload.get("pid", 0) or 0)
        if _pid_is_alive(lock_pid):
            return False, lock_pid
    _write_json(
        lock_path,
        {
            "pr": int(pr),
            "pid": current_pid,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return True, current_pid


def _release_process_lock(*, lock_path: Path) -> None:
    if lock_path.is_file():
        try:
            lock_path.unlink()
        except Exception:
            pass


def _unresolved_actionable_count(snapshot: dict[str, Any]) -> int | None:
    raw_path = Path(str(snapshot.get("raw_json") or "")).expanduser()
    if not raw_path.is_file():
        return None
    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    threads = payload.get("data", {}).get("repository", {}).get("pullRequest", {}).get("reviewThreads", {}).get("nodes", [])
    if not isinstance(threads, list):
        return None
    unresolved_threads: set[str] = set()
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        if bool(thread.get("isResolved")):
            continue
        # GitHub marks threads as outdated when the referenced diff lines no longer
        # apply on current head. Those should not block merge once addressed.
        if bool(thread.get("isOutdated")):
            continue
        thread_id = str(thread.get("id") or "")
        comments = (thread.get("comments") or {}).get("nodes") or []
        inline_bot_comments: list[tuple[float, int, dict[str, Any]]] = []
        for idx, comment in enumerate(comments):
            if not isinstance(comment, dict):
                continue
            author = str(((comment.get("author") or {}).get("login") or "")).strip().lower()
            if author != "coderabbitai":
                continue
            if comment.get("position") is None:
                continue
            created_at = _parse_iso8601(comment.get("createdAt"))
            created_ts = created_at.timestamp() if created_at is not None else float("-inf")
            inline_bot_comments.append((created_ts, idx, comment))
        if not inline_bot_comments:
            continue

        latest_inline = max(inline_bot_comments, key=lambda item: (item[0], item[1]))[2]
        body = str(latest_inline.get("body") or "")
        if "addressed in commit" in body.lower():
            continue

        thread_key = thread_id or str(latest_inline.get("url") or "")
        if thread_key:
            unresolved_threads.add(thread_key)
    return len(unresolved_threads)


def _live_unresolved_actionable_count(*, repo: str, pr: int, repo_root: Path) -> int | None:
    owner, sep, name = str(repo).partition("/")
    if not owner or not sep or not name:
        return None
    cmd = [
        "gh",
        "api",
        "graphql",
        "-f",
        "query="
        + (
            "query($owner:String!,$name:String!,$number:Int!){"
            "repository(owner:$owner,name:$name){"
            "pullRequest(number:$number){"
            "reviewThreads(first:100){"
            "nodes{"
            "isResolved "
            "isOutdated "
            "comments(first:50){nodes{author{login} position body createdAt url}}"
            "}"
            "}"
            "}"
            "}"
            "}"
        ),
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={int(pr)}",
    ]
    proc = _run(cmd, cwd=repo_root)
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:
        return None
    threads = (
        payload.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    if not isinstance(threads, list):
        return None
    unresolved = 0
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        if bool(thread.get("isResolved")):
            continue
        if bool(thread.get("isOutdated")):
            continue
        comments = (thread.get("comments") or {}).get("nodes") or []
        inline_bot_comments: list[tuple[float, int, dict[str, Any]]] = []
        for idx, comment in enumerate(comments):
            if not isinstance(comment, dict):
                continue
            author = str(((comment.get("author") or {}).get("login") or "")).strip().lower()
            if author != "coderabbitai":
                continue
            if comment.get("position") is None:
                continue
            created_at = _parse_iso8601(comment.get("createdAt"))
            created_ts = created_at.timestamp() if created_at is not None else float("-inf")
            inline_bot_comments.append((created_ts, idx, comment))
        if not inline_bot_comments:
            continue
        latest_inline = max(inline_bot_comments, key=lambda item: (item[0], item[1]))[2]
        body = str(latest_inline.get("body") or "")
        if "addressed in commit" in body.lower():
            continue
        unresolved += 1
    return int(unresolved)


def _coderabbit_review_info(*, pr: int, repo_root: Path) -> dict[str, Any]:
    cmd = [
        "gh",
        "pr",
        "view",
        str(pr),
        "--json",
        "reviews,state,number,headRefOid,commits",
        "--jq",
        (
            "{"
            "number:.number,"
            "state:.state,"
            "head_sha:.headRefOid,"
            "last_commit_at:(.commits[-1].committedDate // .commits[-1].commit.committedDate),"
            "cr_reviews:[.reviews[] | select(.author.login==\"coderabbitai\") | {state:.state,submittedAt:.submittedAt}],"
            "cr_review_count:([.reviews[] | select(.author.login==\"coderabbitai\")] | length),"
            "latest_cr_review_at:([.reviews[] | select(.author.login==\"coderabbitai\")][-1].submittedAt // null)"
            "}"
        ),
    ]
    proc = _run(cmd, cwd=repo_root)
    if proc.returncode != 0:
        raise RuntimeError(f"failed to query PR review state\n{proc.stderr}")
    payload = json.loads(proc.stdout or "{}")
    payload.setdefault("cr_review_count", 0)
    payload.setdefault("cr_reviews", [])
    payload.setdefault("head_sha", "")
    payload.setdefault("last_commit_at", None)
    payload.setdefault("latest_cr_review_at", None)
    last_commit_at = _parse_iso8601(payload.get("last_commit_at"))
    latest_review_at = _parse_iso8601(payload.get("latest_cr_review_at"))
    is_fresh = False
    if last_commit_at is not None and latest_review_at is not None:
        is_fresh = latest_review_at >= last_commit_at
    payload["submitted_review_is_fresh"] = bool(is_fresh)
    payload["review_is_fresh"] = bool(is_fresh)
    payload["head_age_sec"] = (
        int((datetime.now(timezone.utc) - last_commit_at).total_seconds())
        if last_commit_at is not None
        else None
    )
    payload["has_review_signal"] = bool(payload.get("cr_review_count", 0) > 0)
    payload["review_signal_source"] = "review" if payload["has_review_signal"] else "none"
    check = _coderabbit_check_info(pr=pr, repo_root=repo_root)
    payload["check_present"] = bool(check.get("present"))
    payload["check_success"] = bool(check.get("success"))
    payload["check_state"] = str(check.get("state") or "")
    if payload["check_success"] and not payload["review_is_fresh"]:
        payload["has_review_signal"] = True
        payload["review_is_fresh"] = True
        payload["review_signal_source"] = "check"
    return payload


def _coderabbit_check_info(*, pr: int, repo_root: Path) -> dict[str, Any]:
    cmd = [
        "gh",
        "pr",
        "checks",
        str(pr),
        "--json",
        "name,state,bucket",
    ]
    proc = _run(cmd, cwd=repo_root)
    if proc.returncode != 0:
        return {"present": False, "success": False, "state": ""}
    try:
        rows = json.loads(proc.stdout or "[]")
    except Exception:
        return {"present": False, "success": False, "state": ""}
    if not isinstance(rows, list):
        return {"present": False, "success": False, "state": ""}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip().lower()
        if name != "coderabbit":
            continue
        state = str(row.get("state") or "").strip().upper()
        bucket = str(row.get("bucket") or "").strip().lower()
        success = state == "SUCCESS" or bucket == "pass"
        return {"present": True, "success": success, "state": state or bucket.upper()}
    return {"present": False, "success": False, "state": ""}


def _maybe_trigger_review_nudge(
    *,
    pr: int,
    repo_root: Path,
    review: dict[str, Any],
    require_submitted_review: bool,
    elapsed_sec: float,
    nudge_after_sec: int,
    state_path: Path,
    comment_body: str,
) -> dict[str, Any]:
    if int(nudge_after_sec) <= 0:
        return {"nudged": False, "reason": "disabled"}
    if float(elapsed_sec) < float(max(1, int(nudge_after_sec))):
        return {"nudged": False, "reason": "waiting_threshold"}
    has_signal = bool(review.get("has_review_signal"))
    review_is_fresh = bool(review.get("review_is_fresh"))
    review_count = int(review.get("cr_review_count", 0) or 0)
    submitted_review_is_fresh = bool(review.get("submitted_review_is_fresh", review_is_fresh))
    if has_signal and review_is_fresh:
        if not require_submitted_review:
            return {"nudged": False, "reason": "fresh_signal_present"}
        if review_count > 0 and submitted_review_is_fresh:
            return {"nudged": False, "reason": "fresh_signal_present"}
        # strict mode: keep nudging until a submitted review is fresh on current head.

    head_sha = str(review.get("head_sha") or "").strip()
    state = _read_json(state_path)
    last_nudged_head = str(state.get("last_nudged_head") or "").strip()
    if head_sha and head_sha == last_nudged_head:
        return {"nudged": False, "reason": "already_nudged_for_head", "head_sha": head_sha}

    cmd = ["gh", "pr", "comment", str(pr), "--body", str(comment_body)]
    proc = _run(cmd, cwd=repo_root)
    if proc.returncode != 0:
        return {
            "nudged": False,
            "reason": "nudge_failed",
            "stderr": str(proc.stderr or "").strip(),
        }

    payload = {
        "last_nudged_at": datetime.now(timezone.utc).isoformat(),
        "last_nudged_pr": int(pr),
        "last_nudged_head": head_sha,
        "comment_body": str(comment_body),
    }
    _write_json(state_path, payload)
    return {"nudged": True, "reason": "nudged", "head_sha": head_sha}


def _gate_state(
    *,
    snapshot: dict[str, Any],
    review: dict[str, Any],
    require_review: bool,
    require_submitted_review: bool = False,
    check_signal_settle_sec: int = 0,
    check_signal_elapsed_sec: float | None = None,
    live_unresolved_actionable: int | None = None,
) -> tuple[bool, str]:
    counts = snapshot.get("counts", {}) or {}
    collector_actionable = int(counts.get("actionable", 0) or 0)
    unresolved_actionable = (
        int(live_unresolved_actionable)
        if live_unresolved_actionable is not None
        else _unresolved_actionable_count(snapshot)
    )
    actionable = int(unresolved_actionable) if unresolved_actionable is not None else collector_actionable
    outside_diff = int(counts.get("outside_diff", 0) or 0)
    nitpick = int(counts.get("nitpick", 0) or 0)
    review_count = int(review.get("cr_review_count", 0) or 0)
    review_is_fresh = bool(review.get("review_is_fresh"))
    submitted_review_is_fresh = bool(review.get("submitted_review_is_fresh", review_is_fresh))
    has_review_signal = bool(review.get("has_review_signal", review_count > 0))
    review_signal_source = str(review.get("review_signal_source") or "none")
    head_sha = str(review.get("head_sha") or "").strip()
    head_age_sec = review.get("head_age_sec")
    age_hint = ""
    if isinstance(head_age_sec, int) and head_age_sec >= 0:
        age_hint = f", head_age_sec={head_age_sec}"

    if require_review and require_submitted_review and review_count <= 0:
        return (
            False,
            (
                "pending: waiting for submitted CodeRabbit review "
                f"(actionable={actionable}, outside_diff={outside_diff}, nitpick={nitpick})"
            ),
        )
    if require_review and require_submitted_review and not submitted_review_is_fresh:
        return (
            False,
            (
                "pending: waiting for fresh submitted CodeRabbit review on current head "
                f"(head={head_sha[:12] or 'unknown'}{age_hint}, actionable={actionable}, outside_diff={outside_diff}, nitpick={nitpick})"
            ),
        )
    if require_review and not has_review_signal:
        return (
            False,
            (
                f"pending: no submitted CodeRabbit review yet "
                f"(actionable={actionable}, outside_diff={outside_diff}, nitpick={nitpick})"
            ),
        )
    if require_review and not review_is_fresh:
        return (
            False,
            (
                "pending: waiting for fresh CodeRabbit review on current head "
                f"(source={review_signal_source}, head={head_sha[:12] or 'unknown'}{age_hint}, actionable={actionable}, "
                f"outside_diff={outside_diff}, nitpick={nitpick})"
            ),
        )
    if (
        require_review
        and review_signal_source == "check"
        and review_count <= 0
        and int(max(0, int(check_signal_settle_sec))) > 0
    ):
        elapsed = float(check_signal_elapsed_sec or 0.0)
        remaining = int(max(0.0, float(check_signal_settle_sec) - elapsed))
        if remaining > 0:
            return (
                False,
                (
                    "pending: check-only review signal settling "
                    f"(remaining_sec={remaining}, actionable={actionable}, outside_diff={outside_diff}, nitpick={nitpick})"
                ),
            )
    if actionable > 0:
        return (
            False,
            (
                f"blocked: actionable={actionable} "
                f"(collector_actionable={collector_actionable}) "
                f"(outside_diff={outside_diff}, nitpick={nitpick})"
            ),
        )
    return (
        True,
        (
            "pass: actionable=0 "
            f"(outside_diff={outside_diff}, nitpick={nitpick}, cr_reviews={review_count}, "
            f"review_signal={review_signal_source})"
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hard gate for PR merge: require CodeRabbit review + actionable=0.",
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument("--repo-root", default=".", help="repository root path")
    parser.add_argument("--collector", default=None, help="path to pr_feedback_collector.py")
    parser.add_argument("--out", default="runtime/reports", help="collector output directory")
    parser.add_argument("--timeout-sec", type=int, default=900, help="poll timeout seconds")
    parser.add_argument("--poll-sec", type=int, default=20, help="poll interval seconds")
    parser.add_argument(
        "--require-review",
        dest="require_review",
        action="store_true",
        default=True,
        help="require at least one submitted CodeRabbit review",
    )
    parser.add_argument(
        "--allow-no-review",
        dest="require_review",
        action="store_false",
        help="do not require a submitted CodeRabbit review (still enforces actionable=0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one check pass and exit without polling",
    )
    parser.add_argument(
        "--auto-nudge-after-sec",
        type=int,
        default=300,
        help="after this many seconds with no fresh review signal, post @coderabbitai review once per head sha (0 disables)",
    )
    parser.add_argument(
        "--disable-auto-nudge",
        action="store_true",
        help="disable auto-nudge behavior",
    )
    parser.add_argument(
        "--nudge-comment-body",
        default="@coderabbitai review",
        help="comment body used when auto-nudging review",
    )
    parser.add_argument(
        "--check-signal-settle-sec",
        type=int,
        default=180,
        help="minimum settle window for check-only review signals before pass",
    )
    parser.add_argument(
        "--require-submitted-review",
        action="store_true",
        help="require a fresh submitted CodeRabbit review on current head (do not accept check-only signal)",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    out_dir = (repo_root / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    collector = _find_collector(args.collector, repo_root=repo_root)
    state_path = out_dir / f"pr_feedback_gate_pr{int(args.pr)}_state.json"
    lock_path = out_dir / f"pr_feedback_gate_pr{int(args.pr)}.lock.json"
    auto_nudge_after = 0 if bool(args.disable_auto_nudge) else int(args.auto_nudge_after_sec)
    lock_ok, lock_pid = _acquire_process_lock(lock_path=lock_path, pr=int(args.pr))
    if not lock_ok:
        print(
            json.dumps(
                {
                    "attempt": 0,
                    "pr": args.pr,
                    "status": "busy",
                    "message": f"another pr_feedback_gate process is active for this PR (pid={lock_pid})",
                    "lock_path": str(lock_path),
                    "active_pid": lock_pid,
                },
                ensure_ascii=False,
            )
        )
        return 4

    start = time.time()
    attempt = 0
    check_signal_started_at: float | None = None
    check_signal_head = ""
    try:
        while True:
            attempt += 1
            snapshot = _collector_pass(
                repo=args.repo,
                pr=args.pr,
                collector=collector,
                out_dir=out_dir,
                repo_root=repo_root,
            )
            review = _coderabbit_review_info(pr=args.pr, repo_root=repo_root)
            live_unresolved_actionable = _live_unresolved_actionable_count(
                repo=args.repo,
                pr=int(args.pr),
                repo_root=repo_root,
            )
            review_signal_source = str(review.get("review_signal_source") or "none")
            review_count = int(review.get("cr_review_count", 0) or 0)
            review_is_fresh = bool(review.get("review_is_fresh"))
            head_sha = str(review.get("head_sha") or "").strip()
            is_check_only_fresh = (
                review_signal_source == "check"
                and review_count <= 0
                and review_is_fresh
            )
            if is_check_only_fresh:
                if check_signal_head != head_sha:
                    check_signal_head = head_sha
                    check_signal_started_at = time.time()
            else:
                check_signal_head = ""
                check_signal_started_at = None
            check_signal_elapsed_sec = (
                max(0.0, time.time() - check_signal_started_at)
                if check_signal_started_at is not None
                else 0.0
            )
            check_signal_settle_sec = int(max(0, int(args.check_signal_settle_sec)))
            check_signal_remaining_sec = int(
                max(0.0, float(check_signal_settle_sec) - float(check_signal_elapsed_sec))
            )

            ok, message = _gate_state(
                snapshot=snapshot,
                review=review,
                require_review=bool(args.require_review),
                require_submitted_review=bool(args.require_submitted_review),
                check_signal_settle_sec=check_signal_settle_sec,
                check_signal_elapsed_sec=check_signal_elapsed_sec,
                live_unresolved_actionable=live_unresolved_actionable,
            )
            nudge_info = _maybe_trigger_review_nudge(
                pr=int(args.pr),
                repo_root=repo_root,
                review=review,
                require_submitted_review=bool(args.require_submitted_review),
                elapsed_sec=time.time() - start,
                nudge_after_sec=auto_nudge_after,
                state_path=state_path,
                comment_body=str(args.nudge_comment_body),
            )
            print(
                json.dumps(
                    {
                        "attempt": attempt,
                        "pr": args.pr,
                        "status": "pass" if ok else "wait",
                        "message": message,
                        "summary_json": snapshot.get("summary_json"),
                        "review_count": review_count,
                        "review_signal_source": review_signal_source,
                        "check_present": bool(review.get("check_present")),
                        "check_success": bool(review.get("check_success")),
                        "review_is_fresh": review_is_fresh,
                        "head_sha": head_sha,
                        "last_commit_at": review.get("last_commit_at"),
                        "latest_cr_review_at": review.get("latest_cr_review_at"),
                        "pr_state": review.get("state"),
                        "auto_nudge_after_sec": int(auto_nudge_after),
                        "live_unresolved_actionable": live_unresolved_actionable,
                        "require_submitted_review": bool(args.require_submitted_review),
                        "check_signal_settle_sec": check_signal_settle_sec,
                        "check_signal_elapsed_sec": round(float(check_signal_elapsed_sec), 3),
                        "check_signal_remaining_sec": int(check_signal_remaining_sec),
                        "nudged": bool(nudge_info.get("nudged")),
                        "nudge_reason": str(nudge_info.get("reason") or ""),
                    },
                    ensure_ascii=False,
                )
            )
            if ok:
                return 0
            if args.once:
                return 2
            if (time.time() - start) >= max(1, int(args.timeout_sec)):
                print(f"timeout: gate did not pass within {args.timeout_sec}s")
                return 3
            time.sleep(max(1, int(args.poll_sec)))
    finally:
        _release_process_lock(lock_path=lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
