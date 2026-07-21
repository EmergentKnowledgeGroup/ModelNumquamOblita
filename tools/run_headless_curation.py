#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.runtime.server import RUNTIME_ROOT


HCR_STATUS_SCHEMA = "numquamoblita.hcr.status.v1"


class HeadlessCurationError(RuntimeError):
    pass


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized == "localhost":
        return True
    try:
        return bool(ipaddress.ip_address(normalized).is_loopback)
    except ValueError:
        return False


def _api_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_s: float = 900.0,
) -> dict[str, Any]:
    raw = None
    headers: dict[str, str] = {}
    if payload is not None:
        raw = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib_request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=raw,
        headers=headers,
        method=method,
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_s) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = str(parsed.get("error") or parsed.get("message") or detail)
        except (json.JSONDecodeError, AttributeError):
            message = detail or str(exc)
        raise HeadlessCurationError(f"HCR request failed ({exc.code}): {message}") from exc
    except (OSError, urllib_error.URLError, json.JSONDecodeError) as exc:
        raise HeadlessCurationError(f"HCR request failed: {exc}") from exc
    if not isinstance(decoded, dict):
        raise HeadlessCurationError("HCR returned a non-object response")
    return decoded


def _prepare_run(
    base_url: str,
    *,
    input_path: Path | None,
    store_path: Path | None,
    output_store: Path | None,
    run_id: str,
    policy_preset: str,
    request_fn: Callable[..., dict[str, Any]] = _api_request,
) -> dict[str, Any]:
    if run_id:
        started = request_fn(
            base_url,
            "/api/wizard/start",
            method="POST",
            payload={"mode": "resume", "run_id": run_id},
        )
        resolved = str(started.get("run_id") or "").strip()
        if resolved != run_id:
            raise HeadlessCurationError(f"requested run {run_id!r} but runtime resumed {resolved!r}")
    else:
        started = request_fn(base_url, "/api/wizard/start", method="POST", payload={"mode": "new"})
        resolved = str(started.get("run_id") or "").strip()
        if not resolved:
            raise HeadlessCurationError("runtime did not return a wizard run_id")
        selected = input_path or store_path
        if selected is None:
            raise HeadlessCurationError("a new HCR run requires --input or --store")
        request_payload = {"run_id": resolved, "input_path": str(selected)}
        validation = request_fn(
            base_url,
            "/api/wizard/import/validate",
            method="POST",
            payload=request_payload,
        )
        if not bool(validation.get("is_valid")) or str(validation.get("status") or "").lower() == "blocked":
            issues = "; ".join(str(item) for item in list(validation.get("issues") or []) if str(item).strip())
            raise HeadlessCurationError(issues or "selected HCR input did not pass validation")
        import_payload = dict(request_payload)
        if input_path is not None and output_store is not None:
            import_payload["store_path"] = str(output_store)
        imported = request_fn(
            base_url,
            "/api/wizard/import/run",
            method="POST",
            payload=import_payload,
        )
        imported_store = str(imported.get("store_path") or "").strip()
        if not imported_store:
            raise HeadlessCurationError("HCR import did not return a store path")
        request_fn(
            base_url,
            "/api/wizard/build/run",
            method="POST",
            payload={
                "run_id": resolved,
                "store_path": imported_store,
                "policy_preset": policy_preset,
            },
        )
    return request_fn(
        base_url,
        f"/api/wizard/hcr/status?run_id={quote(resolved, safe='')}",
    )


def _runtime_command(args: argparse.Namespace, setup_store: Path) -> list[str]:
    command = [
        sys.executable,
        "-u",
        "-m",
        "tools.run_live_runtime",
        "--setup-mode",
        "--setup-store",
        str(setup_store),
        "--host",
        str(args.host),
        "--port",
        str(int(args.port)),
    ]
    if float(args.max_seconds) > 0:
        command.extend(["--max-seconds", str(float(args.max_seconds))])
    return command


def _read_runtime_url(process: subprocess.Popen[str]) -> tuple[str, list[str]]:
    captured: list[str] = []
    if process.stdout is None:
        raise HeadlessCurationError("runtime output pipe is unavailable")
    while True:
        line = process.stdout.readline()
        if line == "":
            code = process.poll()
            raise HeadlessCurationError(
                f"setup runtime exited before publishing its URL (exit={code}): {' | '.join(captured[-8:])}"
            )
        clean = line.rstrip("\r\n")
        captured.append(clean)
        if clean.startswith("runtime_url="):
            return clean.split("=", 1)[1].strip(), captured


def _stream_output(process: subprocess.Popen[str]) -> None:
    if process.stdout is None:
        return
    for line in process.stdout:
        print(line.rstrip("\r\n"), flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or resume a generic local MNO Headless Curation Room (HCR)."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", default="", help="Raw archive file or folder to import before curation.")
    source.add_argument("--store", default="", help="Existing imported MNO sqlite/json store to curate.")
    source.add_argument("--run-id", default="", help="Existing wizard run to resume exactly.")
    parser.add_argument("--output-store", default="", help="Destination sqlite store for --input imports.")
    parser.add_argument("--policy", choices=("strict", "balanced", "assist"), default="strict")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--setup-store", default="", help="Local sqlite used only to host setup/HCR state.")
    parser.add_argument("--no-open", action="store_true", help="Print the HCR URL without opening a browser.")
    parser.add_argument("--plan-only", action="store_true", help="Validate arguments and print a non-mutating launch plan.")
    parser.add_argument("--max-seconds", type=float, default=0.0, help="Stop the local HCR server after N seconds (0 = until stopped).")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not _is_loopback_host(args.host):
        print("error_code=HCR_LOOPBACK_REQUIRED")
        print("error_message=HCR is local-only; use localhost, 127.0.0.1, or ::1.")
        return 2
    if args.output_store and not args.input:
        print("error=--output-store requires --input")
        return 2

    input_path = Path(args.input).expanduser().resolve() if args.input else None
    store_path = Path(args.store).expanduser().resolve() if args.store else None
    output_store = Path(args.output_store).expanduser().resolve() if args.output_store else None
    for label, path in (("input", input_path), ("store", store_path)):
        if path is not None and not path.exists():
            print(f"error={label} path not found: {path}")
            return 2
    setup_store = (
        Path(args.setup_store).expanduser().resolve()
        if args.setup_store
        else (RUNTIME_ROOT / "hcr" / "setup_mode.sqlite3").resolve()
    )

    plan = {
        "schema": "numquamoblita.hcr.launch-plan.v1",
        "mode": "resume" if args.run_id else "prepare",
        "input_path": str(input_path or ""),
        "store_path": str(store_path or ""),
        "output_store": str(output_store or ""),
        "run_id": str(args.run_id or ""),
        "policy": str(args.policy),
        "host": str(args.host),
        "port": int(args.port),
        "setup_store": str(setup_store),
        "browser_open": not bool(args.no_open),
    }
    if args.plan_only:
        print(json.dumps(plan, sort_keys=True))
        return 0

    if not args.run_id and input_path is None and store_path is None:
        print("error=a new HCR run requires --input or --store; use --run-id to resume")
        return 2

    setup_store.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    process = subprocess.Popen(
        _runtime_command(args, setup_store),
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    try:
        runtime_url, startup_lines = _read_runtime_url(process)
        parsed = urlparse(runtime_url)
        if not _is_loopback_host(parsed.hostname or ""):
            raise HeadlessCurationError("setup runtime returned a non-loopback URL")
        for line in startup_lines:
            print(line, flush=True)
        output_thread = threading.Thread(target=_stream_output, args=(process,), name="mno-hcr-output", daemon=True)
        output_thread.start()
        status = _prepare_run(
            runtime_url,
            input_path=input_path,
            store_path=store_path,
            output_store=output_store,
            run_id=str(args.run_id or "").strip(),
            policy_preset=str(args.policy),
        )
        if str(status.get("schema") or "") != HCR_STATUS_SCHEMA:
            raise HeadlessCurationError("runtime returned an unsupported HCR status schema")
        curation_url = str(status.get("curation_url") or "").strip()
        if not curation_url:
            raise HeadlessCurationError("runtime did not return a curation URL")
        print(f"hcr_status_json={json.dumps(status, separators=(',', ':'), sort_keys=True)}", flush=True)
        print(f"curation_url={curation_url}", flush=True)
        if not args.no_open:
            opened = bool(webbrowser.open(curation_url, new=2))
            print(f"browser_opened={str(opened).lower()}", flush=True)
        return int(process.wait())
    except KeyboardInterrupt:
        return 130
    except HeadlessCurationError as exc:
        print(f"error_code=HCR_START_FAILED\nerror_message={exc}", file=sys.stderr, flush=True)
        return 2
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
