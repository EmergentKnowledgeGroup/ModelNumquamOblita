from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_packages_runnable_engine_and_cli_surfaces() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    find_cfg = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
    )
    assert find_cfg.get("include") == ["engine*", "tools*"]
    scripts = pyproject.get("project", {}).get("scripts", {})
    assert scripts == {
        "mno-runtime": "tools.run_live_runtime:main",
        "mno-mcp": "tools.run_mcp_server:main",
        "mno-agent-mcp": "tools.run_claude_live_mcp:main",
        "mno-setup": "tools.setup_local:main",
        "mno-import": "tools.import_memories:main",
        "mno-report": "tools.report_issue:main",
    }
    runtime_data = pyproject.get("tool", {}).get("setuptools", {}).get("package-data", {}).get("engine.runtime", [])
    assert "ui/*" in runtime_data
    assert "resources/*.md" in runtime_data
