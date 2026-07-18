#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.mcp import (
    AuthConfig,
    MCPServer,
    RuntimeApiClient,
    ServerConfig,
    run_http_server,
    run_stdio_server,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NumquamOblita MCP server (stdio or HTTP transport).")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="Transport mode.")
    parser.add_argument("--runtime-base-url", default="http://127.0.0.1:7340", help="Runtime API base URL.")
    parser.add_argument("--timeout-s", type=float, default=20.0, help="Runtime API timeout in seconds.")
    parser.add_argument("--audit-max-events", type=int, default=300, help="Max in-memory MCP audit events.")
    parser.add_argument("--http-host", default="127.0.0.1", help="HTTP bind host when --transport=http.")
    parser.add_argument("--http-port", type=int, default=8765, help="HTTP bind port when --transport=http.")
    parser.add_argument("--http-max-request-bytes", type=int, default=512000, help="Max HTTP request body size.")
    parser.add_argument("--http-rate-limit-per-min", type=int, default=120, help="Max HTTP requests per minute per client key.")
    parser.add_argument("--enforce-https", action="store_true", help="Require HTTPS via trusted proxy header check.")
    parser.add_argument("--trust-proxy-headers", action="store_true", help="Trust X-Forwarded-Proto when enforcing HTTPS.")
    parser.add_argument(
        "--http-security-log-path",
        default="runtime/reports/mcp_http_security.jsonl",
        help="Structured HTTP security event JSONL log path.",
    )
    parser.add_argument(
        "--http-nonce-replay-window-sec",
        type=int,
        default=600,
        help="Replay protection window (seconds) for optional X-MCP-Nonce values (0 disables).",
    )
    parser.add_argument(
        "--compat-mode",
        choices=["strict", "lenient_v1"],
        default="strict",
        help="Compatibility mode for clients that require alias method/field shapes.",
    )
    parser.add_argument("--diagnostics-dir", default="runtime/reports/mcp_diagnostics", help="Diagnostics export directory.")
    parser.add_argument("--audit-log-path", default="", help="Optional JSONL audit log path.")
    parser.add_argument("--default-role", choices=["viewer", "operator", "admin"], default="viewer")
    parser.add_argument("--viewer-token", default="", help="Viewer auth token (optional).")
    parser.add_argument("--operator-token", default="", help="Operator auth token (optional).")
    parser.add_argument("--admin-token", default="", help="Admin auth token (optional).")
    parser.add_argument("--mutations-enabled", action="store_true", help="Enable mutating MCP tools.")
    return parser.parse_args()


def _review_apply_token(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return str(source.get("NO_INTEGRATION_REVIEW_APPLY_TOKEN") or "").strip()


def main() -> int:
    args = _parse_args()
    auth = AuthConfig(
        default_role=str(args.default_role),
        viewer_token=str(args.viewer_token),
        operator_token=str(args.operator_token),
        admin_token=str(args.admin_token),
    )
    config = ServerConfig(
        runtime_base_url=str(args.runtime_base_url),
        transport=str(args.transport),
        http_bind_host=str(args.http_host),
        http_bind_port=int(args.http_port),
        http_max_request_bytes=int(args.http_max_request_bytes),
        http_rate_limit_per_minute=int(args.http_rate_limit_per_min),
        enforce_https=bool(args.enforce_https),
        trust_proxy_headers=bool(args.trust_proxy_headers),
        http_security_log_path=str(args.http_security_log_path),
        http_nonce_replay_window_seconds=int(args.http_nonce_replay_window_sec),
        timeout_s=float(args.timeout_s),
        audit_max_events=int(args.audit_max_events),
        compat_mode=str(args.compat_mode),
        diagnostics_dir=str(args.diagnostics_dir),
        audit_log_path=str(args.audit_log_path),
        mutations_enabled=bool(args.mutations_enabled),
        integration_review_apply_token=_review_apply_token(),
        auth=auth,
    )
    client = RuntimeApiClient(base_url=config.runtime_base_url, timeout_s=config.timeout_s)
    server = MCPServer(config=config, api_client=client)
    try:
        if config.transport == "http":
            return run_http_server(server, host=config.http_bind_host, port=config.http_bind_port)
        return run_stdio_server(server, stdin_buffer=sys.stdin.buffer, stdout_buffer=sys.stdout.buffer)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
