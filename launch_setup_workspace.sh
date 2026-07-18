#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_ARGV=()
BEST_SCORE=0

split_command_argv() {
  local input="$1" token="" quote="" char
  local -a parsed=()
  local i
  for ((i = 0; i < ${#input}; i++)); do
    char="${input:i:1}"
    if [[ -n "${quote}" ]]; then
      if [[ "${char}" == "${quote}" ]]; then
        quote=""
      elif [[ "${char}" == "\\" && "${quote}" == '"' && $((i + 1)) -lt ${#input} ]]; then
        i=$((i + 1)); token+="${input:i:1}"
      else
        token+="${char}"
      fi
    elif [[ "${char}" == '"' || "${char}" == "'" ]]; then
      quote="${char}"
    elif [[ "${char}" =~ [[:space:]] ]]; then
      if [[ -n "${token}" ]]; then parsed+=("${token}"); token=""; fi
    elif [[ "${char}" == "\\" && $((i + 1)) -lt ${#input} ]]; then
      i=$((i + 1)); token+="${input:i:1}"
    else
      token+="${char}"
    fi
  done
  [[ -z "${quote}" ]] || return 1
  [[ -z "${token}" ]] || parsed+=("${token}")
  ((${#parsed[@]} > 0)) || return 1
  MNO_SPLIT_ARGV=("${parsed[@]}")
}

probe_python() {
  local -a candidate=("$@")
  local executable="${candidate[0]}"
  if ! command -v "${executable}" >/dev/null 2>&1 && [[ ! -x "${executable}" ]]; then
    return 1
  fi
  local version
  version="$("${candidate[@]}" -c 'import sys, venv, xml.parsers.expat; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)" || return 1
  local major minor score
  IFS='.' read -r major minor <<<"${version}"
  [[ -n "${major}" && -n "${minor}" ]] || return 1
  if (( major < 3 || (major == 3 && minor < 12) )); then
    return 1
  fi
  score=$(( major * 100 + minor ))
  if (( score > BEST_SCORE )); then
    BEST_SCORE="${score}"
    PYTHON_ARGV=("${candidate[@]}")
  fi
}

if [[ -n "${MNO_PYTHON:-}" ]] && split_command_argv "${MNO_PYTHON}"; then
  probe_python "${MNO_SPLIT_ARGV[@]}" || true
fi
for candidate in python3.15 python3.14 python3.13 python3.12 /usr/bin/python3 python3 python; do
  probe_python "${candidate}" || true
done

if ((${#PYTHON_ARGV[@]} == 0)); then
  echo "setup failed: Python not found in PATH."
  exit 2
fi

"${PYTHON_ARGV[@]}" "${SCRIPT_DIR}/tools/run_setup_workspace.py" "$@"
