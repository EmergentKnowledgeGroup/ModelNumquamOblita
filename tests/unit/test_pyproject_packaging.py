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


def test_llm_and_agent_docs_require_capability_refresh_before_each_mutating_operation() -> None:
    llms = (REPO_ROOT / "LLMS.md").read_text(encoding="utf-8")
    agent = (REPO_ROOT / "docs" / "AGENT_INTEGRATION.md").read_text(encoding="utf-8")
    assert "Before using every write or maintenance operation, call `integration.capabilities.get`" in llms
    assert "Before every write or maintenance operation, inspect `integration.capabilities.get`" in agent
    for field in ("authorized", "available", "reason"):
        assert field in llms
        assert field in agent
