#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import runpy
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "tools" / "run_claude_live_mcp.py"

if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    runpy.run_path(str(TARGET), run_name="__main__")
