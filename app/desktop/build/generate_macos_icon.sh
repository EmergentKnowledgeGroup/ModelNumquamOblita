#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PNG_PATH="${SCRIPT_DIR}/icon-1024.png"
ICONSET_PATH="${SCRIPT_DIR}/icon.iconset"
ICNS_PATH="${SCRIPT_DIR}/icon.icns"

if [[ "$(uname -s)" != "Darwin" ]]; then
  if [[ -f "${ICNS_PATH}" ]]; then
    echo "macOS icon generation skipped on non-macOS host; using existing icon.icns."
    exit 0
  fi
  echo "macOS icon generation skipped on non-macOS host; icon.icns is missing." >&2
  exit 0
fi

swift "${SCRIPT_DIR}/generate_macos_icon.swift" "${PNG_PATH}"
rm -rf "${ICONSET_PATH}" "${ICNS_PATH}"
mkdir -p "${ICONSET_PATH}"

cp "${PNG_PATH}" "${ICONSET_PATH}/icon_512x512@2x.png"
sips -z 16 16 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_16x16.png" >/dev/null
sips -z 32 32 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_32x32.png" >/dev/null
sips -z 64 64 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_128x128.png" >/dev/null
sips -z 256 256 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_256x256.png" >/dev/null
sips -z 512 512 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "${PNG_PATH}" --out "${ICONSET_PATH}/icon_512x512.png" >/dev/null

iconutil -c icns "${ICONSET_PATH}" -o "${ICNS_PATH}"
