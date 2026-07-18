#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_BIN=""
BEST_SCORE=0

probe_python() {
  local candidate="$1"
  if ! command -v "${candidate}" >/dev/null 2>&1 && [[ ! -x "${candidate}" ]]; then
    return 1
  fi
  local version
  version="$("${candidate}" -c 'import sys, venv, xml.parsers.expat; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)" || return 1
  local major minor score
  IFS='.' read -r major minor <<<"${version}"
  [[ -n "${major}" && -n "${minor}" ]] || return 1
  if (( major < 3 || (major == 3 && minor < 12) )); then
    return 1
  fi
  score=$(( major * 100 + minor ))
  if (( score > BEST_SCORE )); then
    BEST_SCORE="${score}"
    PYTHON_BIN="${candidate}"
  fi
}

for candidate in "${MNO_PYTHON:-}" python3.15 python3.14 python3.13 python3.12 /usr/bin/python3 python3 python; do
  [[ -n "${candidate}" ]] || continue
  probe_python "${candidate}" || true
done

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "setup failed: Python not found in PATH."
  exit 2
fi

"${PYTHON_BIN}" "${SCRIPT_DIR}/tools/run_setup_workspace.py" "$@"
