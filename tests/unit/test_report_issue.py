from __future__ import annotations

import argparse
from pathlib import Path

from tools.report_issue import build_ticket


def _args(tmp_path: Path, **overrides):
    values = {
        "title": "Runtime exits unexpectedly", "summary": "The local runtime stopped.",
        "steps": "1. Start runtime\n2. Send request", "expected": "Runtime remains healthy.",
        "actual": "Runtime exited.", "agent_notes": "Reproduced twice.", "log": [], "check": "none",
        "timeout": 5.0, "output_dir": str(tmp_path), "repository": "owner/repo", "submit": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_ticket_builds_bounded_local_report_without_sweeping_runtime(tmp_path: Path) -> None:
    ticket_dir, ticket = build_ticket(_args(tmp_path))
    assert ticket["schema"] == "mno.support_ticket.v1"
    assert (ticket_dir / "issue.md").is_file()
    assert (ticket_dir / "ticket.json").is_file()
    assert list((ticket_dir / "attachments").iterdir()) == []
    assert "memory stores" in (ticket_dir / "issue.md").read_text(encoding="utf-8")


def test_explicit_log_is_redacted_and_size_bounded(tmp_path: Path) -> None:
    log = tmp_path / "runtime.log"
    secret = "api_key=abcdefghijklmnop123456"
    log.write_text("before\n" + secret + "\nafter\n", encoding="utf-8")
    ticket_dir, ticket = build_ticket(_args(tmp_path / "out", log=[str(log)]))
    attachment = next((ticket_dir / "attachments").iterdir())
    text = attachment.read_text(encoding="utf-8")
    assert secret not in text
    assert "REDACTED" in text
    assert ticket["logs"][0]["included"] is True


def test_quick_check_uses_installed_product_smoke_without_source_test_paths(tmp_path: Path) -> None:
    _ticket_dir, ticket = build_ticket(_args(tmp_path, check="quick"))
    assert len(ticket["checks"]) == 1
    assert ticket["checks"][0]["status"] == "passed"
    assert ticket["checks"][0]["argv"][1] == "-c"
    assert "pytest" not in ticket["checks"][0]["argv"]
