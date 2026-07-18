from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from tools import report_issue
from tools.report_issue import build_ticket
from engine.contracts import SourceRef
from engine.memory.provisional_store import ProvisionalMemoryCandidate, ProvisionalMemoryKind, SqliteProvisionalMemoryStore


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


def test_build_ticket_rejects_nonfinite_or_negative_timeout(tmp_path: Path) -> None:
    for value in (-1, float("inf"), float("nan")):
        try:
            build_ticket(_args(tmp_path / str(value), timeout=value))
        except ValueError as exc:
            assert "finite non-negative" in str(exc)
        else:
            raise AssertionError(f"expected timeout rejection for {value!r}")


def test_submit_rejects_nondefault_repository_before_creating_ticket(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_issue.argparse.ArgumentParser,
        "parse_args",
        lambda _self: _args(Path("unused"), repository="attacker/repo", submit=True),
    )
    assert report_issue.main() == 2
    assert json.loads(capsys.readouterr().out)["error"] == "UNSUPPORTED_SUBMISSION_REPOSITORY"


def test_submit_timeout_is_structured_and_uses_validated_timeout(monkeypatch, tmp_path: Path, capsys) -> None:
    args = _args(tmp_path, repository=report_issue.DEFAULT_REPOSITORY, submit=True, timeout=1.25)
    monkeypatch.setattr(report_issue.argparse.ArgumentParser, "parse_args", lambda _self: args)
    monkeypatch.setattr(report_issue.shutil, "which", lambda _name: "gh")

    def _timeout(*_args, **kwargs):
        assert kwargs["timeout"] == 1.25
        raise subprocess.TimeoutExpired(cmd="gh issue create", timeout=kwargs["timeout"])

    monkeypatch.setattr(report_issue.subprocess, "run", _timeout)
    assert report_issue.main() == 2
    assert json.loads(capsys.readouterr().out)["error"] == "GITHUB_SUBMISSION_TIMEOUT"


def test_temporal_report_diagnostics_are_aggregate_only_and_never_include_memory_text(tmp_path: Path) -> None:
    store_path = tmp_path / "private.provisional.sqlite3"
    store = SqliteProvisionalMemoryStore(store_path)
    record_id = store.upsert_candidate(
        ProvisionalMemoryCandidate(
            kind=ProvisionalMemoryKind.EVENT_NOTE,
            canonical_text="do not expose this private reminder text",
            source_refs=[SourceRef(source_id="source", message_id="message")], source_role="user", session_id="session",
        ), reason="test",
    ).record_id
    store.schedule_temporal(
        record_id, "principal", "runtime", temporal_kind="reminder",
        due_window_start_utc="2026-07-18T12:00:00+00:00", due_window_end_utc="2026-07-18T13:00:00+00:00",
        timezone_name="UTC", precision="exact", original_expression="also private", idempotency_key="report-test", expected_revision=0,
    )
    store.close()
    ticket_dir, ticket = build_ticket(_args(tmp_path / "out", temporal_store=str(store_path)))
    diagnostics = ticket["temporal_diagnostics"]
    assert diagnostics["counts"]["state_events"] == 1
    assert diagnostics["reason_codes"] == ["TEMPORAL_DIAGNOSTICS_AVAILABLE"]
    rendered = (ticket_dir / "ticket.json").read_text(encoding="utf-8")
    assert "do not expose this private reminder text" not in rendered
    assert "also private" not in rendered


def test_temporal_report_does_not_discover_a_store_without_explicit_opt_in(tmp_path: Path) -> None:
    _ticket_dir, ticket = build_ticket(_args(tmp_path))
    assert ticket["temporal_diagnostics"]["counts"] == {}
    assert ticket["temporal_diagnostics"]["reason_codes"] == ["TEMPORAL_STORE_NOT_REQUESTED"]
