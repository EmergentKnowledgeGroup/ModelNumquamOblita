#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


DESKTOP_ROOT = Path(__file__).resolve().parent
CACHE_ROOT = DESKTOP_ROOT / ".runtime-cache" / "python-build-standalone"
OUTPUT_ROOT = DESKTOP_ROOT / "build" / "runtime" / "python"
RELEASE_TAG = "20260303"

ASSET_MAP = {
    "linux-x64": "cpython-3.12.13+20260303-x86_64-unknown-linux-gnu-install_only.tar.gz",
    "darwin-x64": "cpython-3.12.13+20260303-x86_64-apple-darwin-install_only.tar.gz",
    "darwin-arm64": "cpython-3.12.13+20260303-aarch64-apple-darwin-install_only.tar.gz",
    "win32-x64": "cpython-3.12.13+20260303-x86_64-pc-windows-msvc-install_only.tar.gz",
}


def _target_key() -> str:
    platform_key = platform.system().lower()
    if platform_key.startswith("linux"):
        return "linux-x64"
    if platform_key.startswith("darwin"):
        machine = platform.machine().lower()
        return "darwin-arm64" if "arm" in machine or "aarch64" in machine else "darwin-x64"
    if platform_key.startswith("windows"):
        return "win32-x64"
    raise SystemExit("unsupported host platform for automatic managed-runtime build")


def _asset_name(target: str) -> str:
    try:
        return ASSET_MAP[target]
    except KeyError as exc:
        raise SystemExit(f"unsupported managed-runtime target: {target}") from exc


def _asset_url(asset_name: str) -> str:
    return f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE_TAG}/{asset_name}"


def _download(asset_name: str) -> Path:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    archive_path = CACHE_ROOT / asset_name
    if archive_path.exists():
        return archive_path
    url = _asset_url(asset_name)
    with urllib.request.urlopen(url, timeout=180) as response, archive_path.open("wb") as output:
        shutil.copyfileobj(response, output)
    return archive_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.getmembers():
        member_path = (root / member.name).resolve()
        if member_path != root and root not in member_path.parents:
            raise SystemExit(f"managed runtime archive attempted path escape: {member.name}")
    archive.extractall(root)


def _extract_to_output(archive_path: Path, destination: Path) -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="mno-managed-runtime-"))
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            _safe_extract(archive, temp_root)
        source_root = temp_root / "python"
        if not source_root.exists():
            raise SystemExit(f"managed runtime archive did not produce the expected python/ directory: {archive_path}")
        terminfo_root = source_root / "share" / "terminfo"
        if terminfo_root.exists():
            shutil.rmtree(terminfo_root)
        shutil.copytree(source_root, destination, symlinks=True)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _runtime_metadata(asset_name: str, archive_path: Path) -> dict[str, str]:
    digest = _sha256_file(archive_path)
    return {
        "schema": "modelnumquamoblita.desktop.runtime_payload.v1",
        "release_tag": RELEASE_TAG,
        "asset_name": asset_name,
        "archive_sha256": digest,
        "runtime_version": "cpython-3.12.13+20260303",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the managed offline Python runtime bundle for the desktop shell.")
    parser.add_argument("--target", default="", help="Target key (linux-x64, darwin-x64, darwin-arm64, win32-x64). Default: current host.")
    parser.add_argument("--plan-only", action="store_true", help="Print the resolved asset and output paths without downloading.")
    args = parser.parse_args()

    target = str(args.target or "").strip() or _target_key()
    asset_name = _asset_name(target)
    payload = {
        "target": target,
        "release_tag": RELEASE_TAG,
        "asset_name": asset_name,
        "archive_url": _asset_url(asset_name),
        "output_root": str(OUTPUT_ROOT),
        "metadata_path": str((DESKTOP_ROOT / "build" / "runtime" / "metadata.json").resolve()),
    }
    if args.plan_only:
        print(json.dumps(payload, indent=2))
        return 0

    archive_path = _download(asset_name)
    _extract_to_output(archive_path, OUTPUT_ROOT)

    metadata_path = DESKTOP_ROOT / "build" / "runtime" / "metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(f"{json.dumps(_runtime_metadata(asset_name, archive_path), indent=2)}\n", encoding="utf-8")
    print(json.dumps({**payload, "archive_path": str(archive_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
