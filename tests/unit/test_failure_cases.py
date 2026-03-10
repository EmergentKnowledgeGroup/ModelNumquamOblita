from __future__ import annotations

from pathlib import Path

from engine.runtime import load_failure_cases, must_pass_case_ids


def test_failure_case_loader_parses_case_table() -> None:
    path = Path("V3_FAILURE_CASE_LIBRARY.md")
    cases = load_failure_cases(path)
    assert len(cases) >= 25
    ids = {case.case_id for case in cases}
    assert "FC-20" in ids
    assert "FC-25" in ids


def test_failure_case_loader_parses_must_pass_subset() -> None:
    path = Path("V3_FAILURE_CASE_LIBRARY.md")
    must_pass = must_pass_case_ids(path)
    assert {"FC-04", "FC-08", "FC-20", "FC-25"} <= must_pass
