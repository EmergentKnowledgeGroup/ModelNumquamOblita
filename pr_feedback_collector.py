#!/usr/bin/env python3
"""
Collect and summarize PR feedback (optimized for CodeRabbit) via GitHub CLI.

Outputs:
- JSON: structured feedback with counts and categorized items
- Markdown: human-readable summary with links
- Raw GraphQL dump (optional) for audit/debug

Usage:
  python pr_feedback_collector.py --repo OWNER/REPO --pr 1 \
      --out runtime/reports --authors coderabbitai --save-raw

Requires:
- GitHub CLI (`gh`) installed & authenticated
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


GRAPHQL_QUERY = (
    """
query($owner:String!, $name:String!, $pr:Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      number
      title
      state
      baseRefName
      headRefName
      headRefOid
      reviewThreads(first: 100) {
        pageInfo {
          hasNextPage
        }
        nodes {
          isResolved
          comments(first: 100) {
            pageInfo {
              hasNextPage
            }
            nodes {
              author { login }
              body
              createdAt
              path
              position
              originalPosition
              diffHunk
              url
            }
          }
        }
      }
      comments(first: 100) {
        pageInfo {
          hasNextPage
        }
        nodes {
          author { login }
          body
          createdAt
          url
        }
      }
      reviews(first: 100) {
        pageInfo {
          hasNextPage
        }
        nodes {
          author { login }
          body
          state
          submittedAt
          id
          url
        }
      }
    }
  }
}
"""
    .strip()
)


def sh(cmd: List[str], input_text: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=input_text.encode("utf-8") if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def ensure_gh() -> None:
    c = sh(["gh", "--version"])  # type: ignore[list-item]
    if c.returncode != 0:
        sys.exit("ERROR: GitHub CLI (gh) is not installed or not on PATH.")
    a = sh(["gh", "auth", "status"])  # type: ignore[list-item]
    if a.returncode != 0:
        sys.exit("ERROR: gh is not authenticated. Run `gh auth login` and retry.")


def gh_fetch_pr(owner: str, name: str, pr: int) -> Dict[str, Any]:
    # Pass query via -f query=... and variables as -F typed fields
    cmd = [
        "gh",
        "api",
        "graphql",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"pr={pr}",
        "-f",
        f"query={GRAPHQL_QUERY}",
    ]
    r = sh(cmd)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", errors="replace"))
        sys.exit("ERROR: gh GraphQL query failed.")
    try:
        payload = json.loads(r.stdout.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Failed to decode gh output as JSON: {exc}\n")
        sys.exit(1)
    if not isinstance(payload, dict):
        sys.stderr.write("ERROR: gh GraphQL response was not a JSON object.\n")
        sys.exit(1)
    if payload.get("errors") or payload.get("data") is None:
        error_payload: Any = payload.get("errors") if payload.get("errors") else payload
        sys.stderr.write(json.dumps(error_payload, ensure_ascii=False, indent=2))
        sys.stderr.write("\n")
        sys.exit("ERROR: gh GraphQL response contained errors.")
    return payload


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def is_by_author(login: Optional[str], authors: Iterable[str]) -> bool:
    if not login:
        return False
    lower = login.lower()
    return any(lower == a.lower() for a in authors)


def parse_coderabbit_nitpicks(review_body_md: str) -> List[Dict[str, Any]]:
    """Parse CodeRabbit nitpicks from the review body.

    Tries a fast regex extraction first; if it fails, falls back to a
    line-based state machine tolerant of minor formatting differences.
    """
    items: List[Dict[str, Any]] = []
    # Fast-path regex
    m = re.search(
        r"<summary>🧹 Nitpick comments \((\d+)\)</summary><blockquote>(.*?)</blockquote>\s*</details>",
        review_body_md,
        re.S,
    )
    if m:
        body = m.group(2)
        for file_block in re.finditer(
            r"<details>\s*<summary>([^<]+)\s*\((\d+)\)</summary><blockquote>(.*?)</blockquote>\s*</details>",
            body,
            re.S,
        ):
            filename = file_block.group(1).strip()
            file_body = file_block.group(3)
            for ln in re.finditer(r"`([0-9]+(?:-[0-9]+)?)`:\s*\*\*(.*?)\*\*", file_body):
                items.append({
                    "file": filename,
                    "lines": ln.group(1),
                    "title": norm(ln.group(2)),
                })
        if items:
            return items

    # Fallback: line-oriented parser
    cur_file: Optional[str] = None
    in_nit = False
    depth = 0
    for raw in review_body_md.splitlines():
        line = raw.strip()
        if not in_nit:
            if "<summary>🧹 Nitpick comments " in line:
                in_nit = True
                depth = 1
            continue
        # Within nit section
        if line == "<details>":
            depth += 1
            continue
        if line == "</blockquote></details>":
            depth -= 1
            if depth == 0:
                break
            continue
        fm = re.match(r"<summary>([^<]+)\s*\((\d+)\)</summary>", line)
        if fm:
            cur_file = fm.group(1).strip()
            continue
        im = re.match(r"`([0-9]+(?:-[0-9]+)?)`:\s*\*\*(.*?)\*\*", line)
        if im and cur_file:
            items.append({
                "file": cur_file,
                "lines": im.group(1),
                "title": norm(im.group(2)),
            })
    return items


def parse_coderabbit_header(review_body_md: str) -> Dict[str, Optional[int]]:
    """Parse CodeRabbit header counts from a review body.

    Returns {actionable, outside_diff, duplicate, nitpick} where values may be None.
    """
    def _find_int(pattern: str) -> Optional[int]:
        m = re.search(pattern, review_body_md, re.I)
        if m:
            try:
                return int(m.group(1))
            except Exception:  # noqa: BLE001
                return None
        return None

    actionable = _find_int(r"Actionable comments posted:\s*(\d+)")
    outside = _find_int(r"Outside diff range comments\s*\((\d+)\)")
    duplicate = _find_int(r"Duplicate comments\s*\((\d+)\)")
    nitpick = _find_int(r"Nitpick comments\s*\((\d+)\)")

    return {
        "actionable": actionable,
        "outside_diff": outside,
        "duplicate": duplicate,
        "nitpick": nitpick,
    }


def parse_coderabbit_outside_block(review_body_md: str) -> List[Dict[str, str]]:
    """Extract filenames listed under the Outside Diff section (best effort)."""
    items: List[Dict[str, str]] = []
    m = re.search(
        r"<summary>[^<]*Outside diff[^<]*</summary><blockquote>(.*?)</blockquote>",
        review_body_md,
        re.S | re.I,
    )
    if not m:
        return items
    block = m.group(1)
    for raw in block.splitlines():
        s = raw.strip()
        if not s:
            continue
        mm = re.match(r"(.+?)\s*\((\d+)\)$", s)
        if mm:
            items.append({"file": mm.group(1).strip(), "count": mm.group(2)})
    return items


def categorize_feedback(
    pr_data: Dict[str, Any], authors: List[str], *, match_cr_header: bool = True
) -> Dict[str, Any]:
    data = pr_data.get("data") if isinstance(pr_data, dict) else None
    if not isinstance(data, dict):
        sys.exit("ERROR: GraphQL response missing `data` payload.")
    repository = data.get("repository")
    if not isinstance(repository, dict):
        sys.exit("ERROR: Repository not found.")
    pr = repository.get("pullRequest")
    if not isinstance(pr, dict):
        sys.exit("ERROR: Pull request not found.")

    warnings: List[str] = []
    if bool(pr.get("reviewThreads", {}).get("pageInfo", {}).get("hasNextPage")):
        warnings.append("WARNING: reviewThreads truncated at 100 items.")
    if bool(pr.get("comments", {}).get("pageInfo", {}).get("hasNextPage")):
        warnings.append("WARNING: top-level PR comments truncated at 100 items.")
    if bool(pr.get("reviews", {}).get("pageInfo", {}).get("hasNextPage")):
        warnings.append("WARNING: PR reviews truncated at 100 items.")
    thread_comment_truncated = False
    for thread in pr.get("reviewThreads", {}).get("nodes", []):
        if bool((thread.get("comments") or {}).get("pageInfo", {}).get("hasNextPage")):
            thread_comment_truncated = True
            break
    if thread_comment_truncated:
        warnings.append("WARNING: at least one review thread comments list is truncated at 100 items.")
    for message in warnings:
        sys.stderr.write(f"{message}\n")

    actionable_all: List[Dict[str, Any]] = []
    outside_all: List[Dict[str, Any]] = []
    nitpicks_all: List[Dict[str, Any]] = []

    # Inline review comments (threaded) across the PR
    for th in pr.get("reviewThreads", {}).get("nodes", []):
        for c in th.get("comments", {}).get("nodes", []):
            author = (c.get("author") or {}).get("login")
            if not is_by_author(author, authors):
                continue
            item = {
                "kind": "inline",
                "author": author,
                "body": c.get("body") or "",
                "path": c.get("path"),
                "position": c.get("position"),
                "url": c.get("url"),
            }
            if c.get("position") is None:
                outside_all.append(item)
            else:
                actionable_all.append(item)

    # PR top-level comments
    for c in pr.get("comments", {}).get("nodes", []):
        author = (c.get("author") or {}).get("login")
        if not is_by_author(author, authors):
            continue
        outside_all.append(
            {
                "kind": "pr_comment",
                "author": author,
                "body": c.get("body") or "",
                "url": c.get("url"),
            }
        )

    # Reviews (summary comments) — collect all, prefer latest for header
    reviews = [r for r in pr.get("reviews", {}).get("nodes", []) if is_by_author((r.get("author") or {}).get("login"), authors)]
    reviews_sorted = sorted(reviews, key=lambda r: r.get("submittedAt") or "")
    latest_review = reviews_sorted[-1] if reviews_sorted else None
    latest_header = {"actionable": None, "outside_diff": None, "duplicate": None, "nitpick": None}
    latest_outside_files: List[Dict[str, str]] = []

    for r in reviews_sorted:
        body = r.get("body") or ""
        # Gather nitpicks from each review body
        nits = parse_coderabbit_nitpicks(body)
        if nits:
            nitpicks_all.extend(nits)
        # Track header counts and outside-diff files for the latest review
        if r is latest_review:
            latest_header = parse_coderabbit_header(body)
            latest_outside_files = parse_coderabbit_outside_block(body)

    # Deduplicate
    def _norm_txt(s: Optional[str]) -> str:
        return norm(s or "")

    seen_a: set[tuple] = set()
    actionable: List[Dict[str, Any]] = []
    for it in actionable_all:
        key = (
            str(it.get("url") or "").strip(),
            str(it.get("path") or "").strip(),
            str(it.get("position") or ""),
            _norm_txt(it.get("body")),
        )
        if key in seen_a:
            continue
        seen_a.add(key)
        actionable.append(it)

    seen_o: set[tuple] = set()
    outside: List[Dict[str, Any]] = []
    for it in outside_all:
        key = (
            str(it.get("url") or "").strip(),
            str(it.get("path") or "").strip(),
            str(it.get("position") or ""),
            _norm_txt(it.get("body")),
        )
        if key in seen_o:
            continue
        seen_o.add(key)
        outside.append(it)

    seen_n: set[tuple] = set()
    nitpicks: List[Dict[str, Any]] = []
    for it in nitpicks_all:
        key = (it.get("file"), it.get("lines"), it.get("title"))
        if key in seen_n:
            continue
        seen_n.add(key)
        nitpicks.append(it)

    aggregated_counts = {
        "actionable": len(actionable),
        "outside_diff": len(outside),
        "nitpick": len(nitpicks),
    }

    # Prefer CodeRabbit's latest header counts if available
    counts = dict(aggregated_counts)
    if match_cr_header and latest_review:
        for k in ("actionable", "outside_diff", "nitpick"):
            v = latest_header.get(k)
            if isinstance(v, int):
                counts[k] = v

    return {
        "meta": {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "state": pr.get("state"),
            "base": pr.get("baseRefName"),
            "head": pr.get("headRefName"),
            "headRefOid": pr.get("headRefOid"),
            "latest_review": {
                "id": latest_review.get("id") if latest_review else None,
                "url": latest_review.get("url") if latest_review else None,
                "submittedAt": latest_review.get("submittedAt") if latest_review else None,
            },
        },
        "counts": counts,
        "aggregated_counts": aggregated_counts,
        "actionable": actionable,
        "outside_diff": outside,
        "nitpick": nitpicks,
        "cr_header_counts": latest_header,
        "cr_outside_files": latest_outside_files,
    }


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_markdown(path: Path, summary: Dict[str, Any], repo: str, pr_num: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    m = summary["meta"]
    c = summary["counts"]
    lines: List[str] = []
    lines.append(f"# PR Review Summary — {repo} PR #{pr_num}")
    lines.append("")
    lines.append(f"Title: {m.get('title')}  ")
    lines.append(f"State: {m.get('state')}  Branch: {m.get('head')} → {m.get('base')}")
    lines.append("")
    agg = summary.get("aggregated_counts", {})
    crh = summary.get("cr_header_counts", {})
    lines.append(
        f"Counts (CR header): actionable={c['actionable']} outside-diff={c['outside_diff']} nitpick={c['nitpick']}"
    )
    lines.append(
        f"Aggregated (dedup across all CR reviews): actionable={agg.get('actionable', 0)} outside-diff={agg.get('outside_diff', 0)} nitpick={agg.get('nitpick', 0)}"
    )
    if any(v is not None for v in crh.values()):
        lines.append(
            f"Header detail: actionable={crh.get('actionable')} outside-diff={crh.get('outside_diff')} duplicate={crh.get('duplicate')} nitpick={crh.get('nitpick')}"
        )
    lines.append("")

    def _short(s: str) -> str:
        s = norm(s)
        return (s[:180] + "…") if len(s) > 180 else s

    # Actionable
    lines.append("## Actionable")
    if summary["actionable"]:
        for i, it in enumerate(summary["actionable"], start=1):
            loc = (
                f"{it.get('path')}:{it.get('position')}"
                if it.get("path")
                else ""
            )
            lines.append(
                f"- {i}. {loc} {_short(it.get('body') or '')} [link]({it.get('url')})"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    # Outside-diff
    lines.append("## Outside-Diff")
    if summary["outside_diff"]:
        for i, it in enumerate(summary["outside_diff"], start=1):
            loc = (
                f"{it.get('path')}:{it.get('position')}"
                if it.get("path")
                else ""
            )
            lines.append(
                f"- {i}. {loc} {_short(it.get('body') or '')} [link]({it.get('url')})"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    # Nitpick
    lines.append("## Nitpick (from latest CodeRabbit review body)")
    if summary["nitpick"]:
        for i, it in enumerate(summary["nitpick"], start=1):
            lines.append(
                f"- {i}. {it.get('file')}:{it.get('lines')} — {it.get('title')}"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", type=int, required=True, help="PR number")
    ap.add_argument(
        "--authors",
        default="coderabbitai",
        help="Comma-separated reviewer logins to include (default: coderabbitai)",
    )
    ap.add_argument(
        "--out",
        default="runtime/reports",
        help="Output directory (default: runtime/reports)",
    )
    ap.add_argument(
        "--save-raw",
        action="store_true",
        help="Save raw GraphQL JSON response for audit",
    )
    args = ap.parse_args()

    ensure_gh()
    try:
        owner, name = args.repo.split("/", 1)
    except ValueError:
        sys.exit("--repo must be in OWNER/NAME form")

    pr_json = gh_fetch_pr(owner, name, args.pr)
    author_list = [s.strip() for s in args.authors.split(",") if s.strip()]
    if not author_list:
        sys.stderr.write("WARNING: No valid authors specified; no feedback will be collected.\n")
    summary = categorize_feedback(pr_json, author_list)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"{owner}_{name}_pr{args.pr}_{stamp}"

    json_path = out_dir / f"{base}_summary.json"
    md_path = out_dir / f"{base}_summary.md"
    write_json(json_path, summary)
    write_markdown(md_path, summary, args.repo, args.pr)

    if args.save_raw:
        raw_path = out_dir / f"{base}_raw.json"
        write_json(raw_path, pr_json)

    # Also emit a lightweight index for easy discovery
    index = out_dir / "latest_pr_feedback.json"
    write_json(index, {
        "repo": args.repo,
        "pr": args.pr,
        "generated_at_utc": stamp,
        "summary_json": str(json_path),
        "summary_md": str(md_path),
        "raw_json": str(raw_path) if args.save_raw else None,
        "counts": summary.get("counts"),
        "meta": summary.get("meta"),
    })

    print(f"[OK] Wrote: {json_path}")
    print(f"[OK] Wrote: {md_path}")
    if args.save_raw:
        print(f"[OK] Wrote: {out_dir / (base + '_raw.json')}")
    print(f"[OK] Index: {index}")


if __name__ == "__main__":
    main()
