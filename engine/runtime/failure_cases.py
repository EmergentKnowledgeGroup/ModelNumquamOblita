from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FailureCase:
    case_id: str
    pattern: str
    detection_signal: str
    expected_safe_behavior: str
    owner: str
    immediate_action: str


_ROW_RE = re.compile(
    r"^\|\s*(FC-\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$"
)
_MUST_PASS_RE = re.compile(r"^-\s*(FC-\d+)\b")


def load_failure_cases(path: str | Path) -> list[FailureCase]:
    """Parse failure-case table rows from markdown library."""

    text = Path(path).read_text(encoding="utf-8")
    cases: list[FailureCase] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _ROW_RE.match(line)
        if not match:
            continue
        case_id, pattern, detection, expected, owner, action = match.groups()
        cases.append(
            FailureCase(
                case_id=case_id,
                pattern=pattern,
                detection_signal=detection,
                expected_safe_behavior=expected,
                owner=owner,
                immediate_action=action,
            )
        )
    return cases


def must_pass_case_ids(path: str | Path) -> set[str]:
    """Parse must-pass subset IDs from the viability gate section."""

    text = Path(path).read_text(encoding="utf-8")
    in_section = False
    ids: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.lower().startswith("## first-72-hours viability gate"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section:
            continue
        match = _MUST_PASS_RE.match(line)
        if match:
            ids.add(match.group(1))
    return ids
