#!/usr/bin/env python3
"""Launch a run-bound, draft-only MCP surface for a headless curation agent."""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import sys
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.mcp import AuthConfig, MCPServer, RuntimeApiClient, ServerConfig, run_http_server, run_stdio_server


def _loopback_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host == "localhost":
        return True
    try:
        return bool(ipaddress.ip_address(host).is_loopback)
    except ValueError:
        return False


def _loopback_host(value: str) -> bool:
    host = str(value or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return bool(ipaddress.ip_address(host).is_loopback)
    except ValueError:
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a run-bound, draft-only NumquamOblita curation MCP server.")
    parser.add_argument("--runtime-base-url", required=True, help="Existing local runtime API base URL.")
    parser.add_argument("--run-id", required=True, help="Wizard run ID this curation room is bound to.")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="Transport mode.")
    parser.add_argument("--timeout-s", type=float, default=20.0, help="Runtime API timeout in seconds.")
    parser.add_argument("--http-host", default="127.0.0.1", help="HTTP bind host when --transport=http.")
    parser.add_argument("--http-port", type=int, default=8765, help="HTTP bind port when --transport=http.")
    parser.add_argument("--viewer-token", default="", help="Viewer auth token (required for HTTP transport).")
    parser.add_argument("--operator-token", default="", help="Optional operator auth token.")
    parser.add_argument("--admin-token", default="", help="Optional admin auth token.")
    parser.add_argument("--plan-only", action="store_true", help="Print resolved non-mutating launch configuration and exit.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not _loopback_url(args.runtime_base_url):
        print("error=HCR runtime URL must be loopback-only", file=sys.stderr)
        return 2
    if args.transport == "http" and not _loopback_host(args.http_host):
        print("error=HCR HTTP transport must bind to loopback", file=sys.stderr)
        return 2
    auth = AuthConfig(
        default_role="viewer",
        viewer_token=str(args.viewer_token),
        operator_token=str(args.operator_token),
        admin_token=str(args.admin_token),
    )
    if args.transport == "http" and not auth.require_auth:
        print("error=HTTP curation MCP requires at least one auth token", file=sys.stderr)
        return 2
    config = ServerConfig(
        runtime_base_url=str(args.runtime_base_url),
        transport=str(args.transport),
        http_bind_host=str(args.http_host),
        http_bind_port=int(args.http_port),
        timeout_s=float(args.timeout_s),
        mutations_enabled=True,
        auth=auth,
        tool_profile="headless_curation",
        bound_wizard_run_id=str(args.run_id),
    )
    if args.plan_only:
        print(f"runtime_base_url={config.runtime_base_url}")
        print(f"run_id={config.bound_wizard_run_id}")
        print(f"transport={config.transport}")
        print(f"tool_profile={config.tool_profile}")
        print("mutations_enabled=true")
        print(f"auth_required={str(auth.require_auth).lower()}")
        return 0

    server = MCPServer(config=config, api_client=RuntimeApiClient(base_url=config.runtime_base_url, timeout_s=config.timeout_s))
    try:
        if config.transport == "http":
            return run_http_server(server, host=config.http_bind_host, port=config.http_bind_port)
        return run_stdio_server(server, stdin_buffer=sys.stdin.buffer, stdout_buffer=sys.stdout.buffer)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

