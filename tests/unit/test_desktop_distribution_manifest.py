from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_JSON = REPO_ROOT / "app" / "desktop" / "package.json"


def test_desktop_distribution_never_copies_live_runtime_tree() -> None:
    payload = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    resources = list((payload.get("build") or {}).get("extraResources") or [])
    sources = {str(item.get("from") or "").replace("\\", "/") for item in resources}

    assert "../../runtime" not in sources
    assert "build/runtime/python" in sources
    assert sources <= {
        "../../engine",
        "../../tools",
        "../../pyproject.toml",
        "build/runtime/python",
    }


def test_desktop_asset_build_is_platform_gated_in_node() -> None:
    payload = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = payload.get("scripts") or {}

    assert scripts.get("desktop:build-assets") == "node build-assets.cjs"
    assert "bash" not in str(scripts.get("desktop:pack:dir") or "").lower()
