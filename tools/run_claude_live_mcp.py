#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.mcp import AuthConfig, MCPServer, RuntimeApiClient, ServerConfig, run_http_server, run_stdio_server
from engine.memory import MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, load_inmemory_store_from_json, start_runtime_server, stop_runtime_server
from tools.mcp_connector_common import build_mcp_servers_payload, build_posix_stdio_entry, default_memory_path, resolve_episode_cards_path


def _load_manifest(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    return payload


def _resolve_memories_path(*, memories: str, from_live_manifest: str) -> Path:
    if memories and from_live_manifest:
        raise ValueError("--memories and --from-live-manifest are mutually exclusive")
    if from_live_manifest:
        manifest_path = Path(from_live_manifest).expanduser().resolve()
        if not manifest_path.exists():
            raise ValueError(f"live manifest not found: {manifest_path}")
        payload = _load_manifest(manifest_path)
        store_path = str(payload.get("store_path") or "").strip()
        if not store_path:
            raise ValueError("live manifest missing required field: store_path")
        return Path(store_path).expanduser().resolve()
    if memories:
        return Path(memories).expanduser().resolve()
    return default_memory_path(repo_root=REPO_ROOT).resolve()


def _resolve_episode_cards_path(raw: str) -> Path | None:
    return resolve_episode_cards_path(raw, repo_root=REPO_ROOT)


def _open_store(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), "sqlite", True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), "json", False
    raise ValueError(f"unsupported memories path: {path}")


def _build_claude_config(
    *,
    server_name: str,
    memories_path: Path,
    episodes_path: Path | None,
    default_role: str,
    compat_mode: str,
    mutations_enabled: bool,
) -> dict[str, object]:
    return build_mcp_servers_payload(
        server_name=str(server_name),
        entry=build_posix_stdio_entry(
            python_path=sys.executable,
            memories_path=memories_path,
            episodes_path=episodes_path,
            default_role=str(default_role),
            compat_mode=str(compat_mode),
            mutations_enabled=bool(mutations_enabled),
        ),
    )


def _resolved_auth_tokens(args: argparse.Namespace, env: dict[str, str] | None = None) -> tuple[str, str, str]:
    env_map = dict(env or os.environ)
    viewer = str(args.viewer_token or env_map.get("NO_MCP_AUTH_TOKEN") or "").strip()
    operator = str(args.operator_token or env_map.get("NO_MCP_OPERATOR_TOKEN") or "").strip()
    admin = str(args.admin_token or env_map.get("NO_MCP_ADMIN_TOKEN") or "").strip()
    return viewer, operator, admin


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch local runtime + MCP together for Claude/Desktop-style local testing.")
    parser.add_argument("--memories", default="", help="Path to sqlite store (.sqlite3/.db) or memories.json.")
    parser.add_argument(
        "--from-live-manifest",
        default="",
        help="Path to runtime/live_runs/live_*/live_manifest.json. Uses store_path from manifest.",
    )
    parser.add_argument("--episodes", default="", help="Optional path to episode_cards JSON artifact.")
    parser.add_argument("--model-name", default="numquam-oblita-runtime")
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, default=0, help="Loopback runtime API port (0 = ephemeral).")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="MCP transport mode.")
    parser.add_argument("--timeout-s", type=float, default=20.0, help="Runtime API timeout in seconds.")
    parser.add_argument("--audit-max-events", type=int, default=300, help="Max in-memory MCP audit events.")
    parser.add_argument("--http-host", default="127.0.0.1", help="HTTP bind host when --transport=http.")
    parser.add_argument("--http-port", type=int, default=8765, help="HTTP bind port when --transport=http.")
    parser.add_argument("--http-max-request-bytes", type=int, default=512000, help="Max HTTP request body size.")
    parser.add_argument("--http-rate-limit-per-min", type=int, default=120, help="Max HTTP requests per minute per client key.")
    parser.add_argument("--enforce-https", action="store_true", help="Require HTTPS via trusted proxy header check.")
    parser.add_argument("--trust-proxy-headers", action="store_true", help="Trust X-Forwarded-Proto when enforcing HTTPS.")
    parser.add_argument("--http-security-log-path", default="runtime/reports/mcp_http_security.jsonl")
    parser.add_argument("--http-nonce-replay-window-sec", type=int, default=600)
    parser.add_argument("--compat-mode", choices=["strict", "lenient_v1"], default="strict")
    parser.add_argument("--diagnostics-dir", default="runtime/reports/mcp_diagnostics")
    parser.add_argument("--audit-log-path", default="")
    parser.add_argument("--default-role", choices=["viewer", "operator", "admin"], default="viewer")
    parser.add_argument("--viewer-token", default="", help="Viewer auth token (optional, falls back to NO_MCP_AUTH_TOKEN).")
    parser.add_argument(
        "--operator-token",
        default="",
        help="Operator auth token (optional, falls back to NO_MCP_OPERATOR_TOKEN).",
    )
    parser.add_argument("--admin-token", default="", help="Admin auth token (optional, falls back to NO_MCP_ADMIN_TOKEN).")
    parser.add_argument("--mutations-enabled", action="store_true")
    parser.add_argument("--server-name", default="numquamoblita-live", help="Server key for generated Claude Desktop config.")
    parser.add_argument("--plan-only", action="store_true", help="Validate inputs and print resolved launch info.")
    parser.add_argument(
        "--print-claude-config",
        action="store_true",
        help="Print a Claude/Desktop-compatible mcpServers JSON snippet and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        memories_path = _resolve_memories_path(memories=args.memories, from_live_manifest=args.from_live_manifest)
    except ValueError as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}", file=sys.stderr)
        return 2

    episodes_path = _resolve_episode_cards_path(args.episodes)
    if episodes_path is not None and not episodes_path.exists():
        print(f"error=episode cards path not found: {episodes_path}", file=sys.stderr)
        return 2

    viewer_token, operator_token, admin_token = _resolved_auth_tokens(args)
    config_payload = build_mcp_servers_payload(
        server_name=str(args.server_name),
        entry=build_posix_stdio_entry(
            python_path=sys.executable,
            memories_path=memories_path,
            episodes_path=episodes_path,
            default_role=str(args.default_role),
            compat_mode=str(args.compat_mode),
            mutations_enabled=bool(args.mutations_enabled),
        ),
    )

    if args.plan_only or args.print_claude_config:
        print(f"memories_path={memories_path}")
        print(f"episode_cards_path={episodes_path if episodes_path is not None else ''}")
        print(f"default_role={args.default_role}")
        print(f"transport={args.transport}")
        print(f"server_name={args.server_name}")
        print(f"viewer_token_configured={str(bool(viewer_token)).lower()}")
        print(f"operator_token_configured={str(bool(operator_token)).lower()}")
        print(f"admin_token_configured={str(bool(admin_token)).lower()}")
        if args.print_claude_config:
            print("claude_desktop_config_json=")
            print(json.dumps(config_payload, indent=2))
        if args.plan_only or args.print_claude_config:
            return 0

    try:
        store, backend_name, close_store = _open_store(memories_path)
    except ValueError as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2

    server = None
    thread = None
    runtime: RuntimeSession | None = None
    try:
        atoms = store.list_atoms()
        continuity = ContinuityStore()
        shared_language_keys = store.list_shared_language_keys() if hasattr(store, "list_shared_language_keys") else []
        continuity.set_snapshot(ContinuityBuilder().build(atoms, shared_language_keys=shared_language_keys))
        runtime = RuntimeSession(
            retriever=MemoryRetriever(store),
            verifier=ClaimVerifier(),
            continuity_store=continuity,
            model_name=str(args.model_name).strip() or "numquam-oblita-runtime",
            episode_cards_path=str(episodes_path) if episodes_path is not None else None,
        )
        review_queue = MutationReviewQueue(store, default_retention_days=14)
        server, thread = start_runtime_server(
            runtime,
            host=str(args.runtime_host),
            port=int(args.runtime_port),
            review_queue=review_queue,
        )
        host, port = server.server_address
        runtime_url = f"http://{host}:{port}"
        print(
            f"runtime_url={runtime_url} memories_path={memories_path} backend={backend_name} atom_count={len(atoms)}",
            file=sys.stderr,
        )

        auth = AuthConfig(
            default_role=str(args.default_role),
            viewer_token=viewer_token,
            operator_token=operator_token,
            admin_token=admin_token,
        )
        config = ServerConfig(
            runtime_base_url=runtime_url,
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
            auth=auth,
        )
        client = RuntimeApiClient(base_url=config.runtime_base_url, timeout_s=config.timeout_s)
        mcp_server = MCPServer(config=config, api_client=client)
        if config.transport == "http":
            return run_http_server(mcp_server, host=config.http_bind_host, port=config.http_bind_port)
        return run_stdio_server(mcp_server, stdin_buffer=sys.stdin.buffer, stdout_buffer=sys.stdout.buffer)
    except KeyboardInterrupt:
        return 130
    finally:
        if server is not None and thread is not None:
            stop_runtime_server(server, thread, runtime=runtime)
        if close_store:
            closer = getattr(store, "close", None)
            if callable(closer):
                closer()


if __name__ == "__main__":
    raise SystemExit(main())
