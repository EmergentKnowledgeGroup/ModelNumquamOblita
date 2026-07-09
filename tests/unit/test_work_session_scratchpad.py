from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.config import WorkSessionScratchpadPolicy
from engine.runtime.scratchpad import (
    SCRATCHPAD_STATUSES,
    WorkSessionScratchpadStore,
    can_resume_scope,
    evaluate_context_diet_fixture,
    resolve_scope,
    resolve_scratchpad_root,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_root(name: str) -> Path:
    root = _project_root() / "runtime" / "tmp" / f"{name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _policy(**overrides: object) -> WorkSessionScratchpadPolicy:
    payload = {
        "enabled": True,
        "inject_enabled": True,
        "resume_injection_enabled": True,
        "diagnostics_enabled": False,
        "max_entries_per_scope": 200,
        "max_injected_items": 8,
        "max_injected_chars": 2400,
        "max_raw_ref_bytes": 2_000_000,
        "retention_days": 14,
        "min_replaceability_score": 0.70,
    }
    payload.update(overrides)
    return WorkSessionScratchpadPolicy(**payload)


def _strict_scope(session_id: str = "sess_a", workstream_key: str = "MNO_WORK_SESSION_SCRATCHPAD_SPEC WORK"):
    return resolve_scope(
        project_id=str(_project_root().resolve()),
        thread_id="thread_alpha",
        session_id=session_id,
        workstream_key=workstream_key,
        workstream_name=workstream_key,
        runtime_store_fingerprint="sqlite_store:v3:test",
    )


def test_scratchpad_store_creates_project_local_schema_and_entry() -> None:
    runtime_root = _runtime_root("scratchpad_store")
    try:
        store = WorkSessionScratchpadStore(
            project_root=_project_root(),
            runtime_state_root=runtime_root,
            policy=_policy(),
        )
        scope = _strict_scope()
        entry = store.add_entry(
            scope,
            kind="tool_result",
            summary="Read runtime package builder and found the v2 insertion point.",
            raw_content="Full tool output stays in a project-local raw ref.",
            replaceability_score=0.91,
        )

        assert store.db_path == runtime_root / "scratchpads" / "scratchpads.sqlite3"
        assert store.db_path.exists()
        assert entry.entry_id.startswith("sp_")
        assert entry.raw_ref.startswith("runtime/tmp/")
        assert (_project_root() / entry.raw_ref).exists()
        assert entry.degraded is False
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_scope_isolation_and_resume_contract_are_strict() -> None:
    base = _strict_scope(session_id="sess_a")
    other_session = _strict_scope(session_id="sess_b")
    other_workstream = _strict_scope(workstream_key="OTHER_WORK")
    degraded = resolve_scope(
        project_id=str(_project_root().resolve()),
        thread_id="",
        session_id="sess_a",
        workstream_key="",
        runtime_store_fingerprint="sqlite_store:v3:test",
    )

    assert base.scope_id != other_session.scope_id
    assert base.scope_id != other_workstream.scope_id
    assert degraded.scope_mode == "degraded"
    assert degraded.can_inject is False
    assert can_resume_scope(base, other_session, explicit_resume=True, policy=_policy()) is True
    assert can_resume_scope(base, other_workstream, explicit_resume=True, policy=_policy()) is False
    assert can_resume_scope(base, degraded, explicit_resume=True, policy=_policy()) is False
    assert can_resume_scope(base, other_session, explicit_resume=False, policy=_policy()) is True
    assert can_resume_scope(base, other_session, explicit_resume=True, policy=_policy(resume_injection_enabled=False)) is True
    assert can_resume_scope(base, other_session, explicit_resume=False, policy=_policy(resume_injection_enabled=False)) is False


def test_scratchpad_root_rejects_unsafe_paths() -> None:
    project = _project_root()
    boundary = project / "runtime"
    safe_root = resolve_scratchpad_root(project, boundary / "tmp" / "scratchpad_root_safe")
    assert safe_root == (boundary / "tmp" / "scratchpad_root_safe" / "scratchpads").resolve()
    if project.drive:
        extended_local = "\\\\?\\" + str(boundary / "tmp" / "scratchpad_root_extended")
        assert resolve_scratchpad_root(project, extended_local) == (
            boundary / "tmp" / "scratchpad_root_extended" / "scratchpads"
        ).resolve()

    with pytest.raises(ValueError, match="UNC"):
        resolve_scratchpad_root(project, r"\\server\share\mno-runtime")
    with pytest.raises(ValueError, match="runtime boundary"):
        resolve_scratchpad_root(project, boundary / ".." / "outside_runtime")
    if project.drive:
        other_drive = "C:" if project.drive.casefold() != "c:" else "Z:"
        with pytest.raises(ValueError, match="project drive"):
            resolve_scratchpad_root(project, f"{other_drive}\\mno-runtime")


def test_scratchpad_root_rejects_symlink_escape_when_supported() -> None:
    project = _project_root()
    runtime_tmp = _runtime_root("scratchpad_symlink")
    escape_target = project / "article"
    link = runtime_tmp / "link_escape"
    try:
        if not escape_target.exists():
            escape_target.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(escape_target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink unavailable in this environment: {exc}")
        with pytest.raises(ValueError, match="runtime boundary"):
            resolve_scratchpad_root(project, link)
    finally:
        shutil.rmtree(runtime_tmp, ignore_errors=True)


def test_raw_ref_failure_degrades_without_false_ref_promise() -> None:
    runtime_root = _runtime_root("scratchpad_degraded_raw")
    try:
        store = WorkSessionScratchpadStore(
            project_root=_project_root(),
            runtime_state_root=runtime_root,
            policy=_policy(max_raw_ref_bytes=8),
        )
        entry = store.add_entry(
            _strict_scope(),
            kind="tool_result",
            summary="oversized raw output",
            raw_content="x" * 64,
            replaceability_score=0.92,
        )
        assert entry.degraded is True
        assert entry.status == "degraded"
        assert entry.raw_ref == ""
        assert store.list_entries_for_injection(_strict_scope()) == []
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_schema_has_no_support_flag_and_statuses_exclude_promoted() -> None:
    runtime_root = _runtime_root("scratchpad_schema")
    try:
        store = WorkSessionScratchpadStore(
            project_root=_project_root(),
            runtime_state_root=runtime_root,
            policy=_policy(),
        )
        columns = set(store.schema_columns("scratchpad_entries"))
        assert "support_allowed" not in columns
        assert "promoted" not in SCRATCHPAD_STATUSES
        with pytest.raises(ValueError):
            store.schema_columns("scratchpad_entries); DROP TABLE scratchpad_entries; --")
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_retention_prunes_only_scratchpad_rows_and_refs() -> None:
    runtime_root = _runtime_root("scratchpad_retention")
    try:
        store = WorkSessionScratchpadStore(
            project_root=_project_root(),
            runtime_state_root=runtime_root,
            policy=_policy(),
        )
        entry = store.add_entry(
            _strict_scope(),
            kind="decision",
            summary="Keep WSS strict-scope live-on.",
            raw_content="Decision detail.",
            replaceability_score=0.95,
        )
        raw_path = _project_root() / entry.raw_ref
        unrelated = runtime_root / "scratchpads" / "unrelated.txt"
        unrelated.write_text("leave me alone", encoding="utf-8")
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with store._connect() as conn:
            conn.execute("UPDATE scratchpad_entries SET expires_at = ?", (expired,))
            conn.execute("UPDATE scratchpad_scopes SET expires_at = ?", (expired,))

        pruned = store.prune_expired()
        assert pruned["entries"] == 1
        assert pruned["refs"] == 1
        assert not raw_path.exists()
        assert unrelated.exists()
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_diagnostic_task_map_is_deterministic_and_keeps_unmapped_entries_visible() -> None:
    runtime_root = _runtime_root("scratchpad_task_map")
    try:
        store = WorkSessionScratchpadStore(
            project_root=_project_root(),
            runtime_state_root=runtime_root,
            policy=_policy(diagnostics_enabled=True),
        )
        scope = _strict_scope()
        parent = store.add_entry(
            scope,
            kind="task_state",
            summary="Current files are engine/runtime/session.py and engine/runtime/scratchpad.py.",
            raw_content="file-read output",
            replaceability_score=0.95,
            metadata={"task_id": "current-files"},
        )
        child = store.add_entry(
            scope,
            kind="blocker",
            summary="B3 requires a fixed context-diet fixture before success can be claimed.",
            raw_content="blockerboard slice",
            replaceability_score=0.95,
            metadata={"task_id": "b3-proof", "depends_on_entry_ids": [parent.entry_id]},
        )
        unmapped = store.add_entry(
            scope,
            kind="operator_note",
            summary="Keep desktop UI out of scope.",
            raw_content="operator note",
            replaceability_score=0.95,
        )

        first = store.build_diagnostic_task_map(scope)
        second = store.build_diagnostic_task_map(scope)

        assert first == second
        assert first["render_mode"] == "deterministic"
        assert first["memory_layer"] == "scratchpad"
        node_entry_ids = {
            entry_id
            for node in first["nodes"]
            for entry_id in list(node.get("entry_ids") or [])
        }
        assert {parent.entry_id, child.entry_id, unmapped.entry_id}.issubset(node_entry_ids)
        assert unmapped.entry_id in first["unmapped_entries"]
        assert {"from_entry_id": parent.entry_id, "to_entry_id": child.entry_id} in first["edges"]
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_context_diet_fixture_metrics_are_hypothetical_until_fidelity_passes() -> None:
    expected_state = {
        "next_action": "run targeted WSS tests",
        "current_files": ["engine/runtime/session.py", "engine/runtime/scratchpad.py"],
        "blockers": ["B3 context-diet proof"],
        "needed_refs": ["docs/MNO_WORK_SESSION_SCRATCHPAD_CONTEXT_DIET_SPEC_2026-07-07.md"],
    }
    baseline_prompt = {
        "rereads": ["runtime/session.py " * 240, "runtime/scratchpad.py " * 180],
        "resume_state": expected_state,
    }
    assisted_prompt = {
        "work_session_context": {
            "summary": "WSS P4/P5 active; run targeted WSS tests next.",
            "items": [
                {
                    "entry_id": "sp_fixture",
                    "summary": "Current files, B3 blocker, and needed spec refs are captured.",
                }
            ],
        },
        "resume_state": expected_state,
    }

    metrics = evaluate_context_diet_fixture(
        baseline_prompt=baseline_prompt,
        scratchpad_assisted_prompt=assisted_prompt,
        work_session_context=assisted_prompt["work_session_context"],
        expected_resume_state=expected_state,
        actual_resume_state=expected_state,
        repeated_reread_steps=["session", "scratchpad"],
        false_memory_behavior_unchanged=True,
        package_build_latencies_ms=[5.0, 6.0, 7.0],
        latency_budget_ms=100.0,
    )

    assert "tokens_saved" not in metrics
    assert metrics["observed_package_tokens"] == metrics["scratchpad_assisted_prompt_tokens"]
    assert metrics["observed_injected_tokens"] > 0
    assert metrics["hypothetical_prompt_tokens_replaced"] > metrics["observed_injected_tokens"]
    assert metrics["repeat_reread_avoided_count"] == 2
    assert metrics["resume_fidelity_pass"] is True
    assert metrics["context_diet_fixture_pass"] is True

    failed = evaluate_context_diet_fixture(
        baseline_prompt=baseline_prompt,
        scratchpad_assisted_prompt=assisted_prompt,
        work_session_context=assisted_prompt["work_session_context"],
        expected_resume_state=expected_state,
        actual_resume_state={**expected_state, "next_action": "different"},
        repeated_reread_steps=["session", "scratchpad"],
        false_memory_behavior_unchanged=True,
        package_build_latencies_ms=[5.0],
        latency_budget_ms=100.0,
    )
    assert failed["resume_fidelity_pass"] is False
    assert failed["repeat_reread_avoided_count"] == 0
    assert failed["context_diet_fixture_pass"] is False
