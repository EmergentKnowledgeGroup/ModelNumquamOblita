from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "run_mcp_server.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_mcp_server", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load run_mcp_server module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_review_apply_token_is_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    assert module._review_apply_token({"NO_INTEGRATION_REVIEW_APPLY_TOKEN": " human-secret "}) == "human-secret"

    monkeypatch.setattr(sys, "argv", ["run_mcp_server.py", "--review-apply-token", "argv-secret"])
    with pytest.raises(SystemExit) as exc_info:
        module._parse_args()
    assert exc_info.value.code == 2
