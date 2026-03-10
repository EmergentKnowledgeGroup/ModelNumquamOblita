#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "setup failed: Python not found in PATH."
  echo "fix: install Python 3.12+ and rerun ./setup_local.sh"
  exit 2
fi

"${PYTHON_BIN}" "${SCRIPT_DIR}/tools/setup_local.py" "$@"
