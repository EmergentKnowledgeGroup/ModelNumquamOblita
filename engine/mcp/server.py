from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
import posixpath
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4


ROLE_ORDER = {
    "viewer": 0,
    "operator": 1,
    "admin": 2,
}

COMPAT_MODES = {
    "strict",
    "lenient_v1",
}

COMPAT_METHOD_ALIASES = {
    "tools.list": "tools/list",
    "tools.call": "tools/call",
    "resources.list": "resources/list",
    "resources.read": "resources/read",
    "prompts.list": "prompts/list",
    "prompts.get": "prompts/get",
}


class RuntimeApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class MCPRequestError(RuntimeError):
    def __init__(self, code: int, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = data if isinstance(data, dict) else None


def _utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _stdio_trace_log(payload: dict[str, Any]) -> None:
    target = str(os.environ.get("NO_MCP_STDIO_TRACE") or "").strip()
    if not target:
        return
    try:
        path = Path(target).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _sha256_short(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def _canonical_graph_link_key(source: str, target: str, kind: str) -> tuple[str, str, str]:
    left, right = sorted((str(source), str(target)))
    return left, right, str(kind)


def _ensure_role(value: str) -> str:
    role = str(value or "").strip().lower()
    if role not in ROLE_ORDER:
        raise ValueError(f"unsupported role: {value}")
    return role


@dataclass(slots=True)
class AuthConfig:
    default_role: str = "viewer"
    viewer_token: str = ""
    operator_token: str = ""
    admin_token: str = ""

    def __post_init__(self) -> None:
        self.default_role = _ensure_role(self.default_role)
        self.viewer_token = str(self.viewer_token or "").strip()
        self.operator_token = str(self.operator_token or "").strip()
        self.admin_token = str(self.admin_token or "").strip()

    @property
    def require_auth(self) -> bool:
        return bool(self.viewer_token or self.operator_token or self.admin_token)

    def resolve_role(self, auth_token: str | None) -> str:
        if not self.require_auth:
            return self.default_role
        token = str(auth_token or "").strip()
        if not token:
            raise MCPRequestError(-32001, "auth token is required")
        if self.admin_token and token == self.admin_token:
            return "admin"
        if self.operator_token and token == self.operator_token:
            return "operator"
        if self.viewer_token and token == self.viewer_token:
            return "viewer"
        raise MCPRequestError(-32001, "invalid auth token")


@dataclass(slots=True)
class ServerConfig:
    runtime_base_url: str = "http://127.0.0.1:7340"
    transport: str = "stdio"
    http_bind_host: str = "127.0.0.1"
    http_bind_port: int = 8765
    http_max_request_bytes: int = 512_000
    http_rate_limit_per_minute: int = 120
    enforce_https: bool = False
    trust_proxy_headers: bool = False
    http_security_log_path: str = "runtime/reports/mcp_http_security.jsonl"
    http_nonce_replay_window_seconds: int = 600
    timeout_s: float = 20.0
    audit_max_events: int = 300
    protocol_version: str = "2025-03-26"
    toolset_version: str = "phase8.v1"
    server_version: str = "0.1.0"
    compat_mode: str = "strict"
    diagnostics_dir: str = "runtime/reports/mcp_diagnostics"
    audit_log_path: str = ""
    max_text_chars: int = 560
    max_list_limit: int = 120
    max_graph_nodes: int = 180
    max_graph_links: int = 360
    max_neighbor_expansion_requests: int = 18
    max_citation_matches: int = 20
    max_why_evidence_items: int = 15
    mutations_enabled: bool = False
    integration_schema_version: str = "integration.v1"
    integration_viewer_token: str = ""
    integration_operator_token: str = ""
    integration_admin_token: str = ""
    auth: AuthConfig = field(default_factory=AuthConfig)

    def __post_init__(self) -> None:
        self.runtime_base_url = str(self.runtime_base_url or "").strip().rstrip("/")
        if not self.runtime_base_url:
            raise ValueError("runtime_base_url is required")
        self.transport = str(self.transport or "stdio").strip().lower() or "stdio"
        if self.transport not in {"stdio", "http"}:
            raise ValueError("transport must be one of: stdio, http")
        self.http_bind_host = str(self.http_bind_host or "127.0.0.1").strip() or "127.0.0.1"
        self.http_bind_port = max(1, min(65535, int(self.http_bind_port)))
        self.http_max_request_bytes = max(1024, int(self.http_max_request_bytes))
        self.http_rate_limit_per_minute = max(1, int(self.http_rate_limit_per_minute))
        self.enforce_https = bool(self.enforce_https)
        self.trust_proxy_headers = bool(self.trust_proxy_headers)
        self.http_security_log_path = str(self.http_security_log_path or "").strip()
        self.http_nonce_replay_window_seconds = max(0, int(self.http_nonce_replay_window_seconds))
        parsed = urlparse(self.runtime_base_url)
        scheme = str(parsed.scheme or "").strip().lower()
        if scheme not in {"http", "https"}:
            raise ValueError(f"runtime_base_url scheme must be http or https, got: {scheme or '<empty>'}")
        self.timeout_s = float(self.timeout_s)
        self.audit_max_events = max(50, int(self.audit_max_events))
        self.compat_mode = str(self.compat_mode or "strict").strip().lower() or "strict"
        if self.compat_mode not in COMPAT_MODES:
            allowed = ", ".join(sorted(COMPAT_MODES))
            raise ValueError(f"compat_mode must be one of: {allowed}")
        self.diagnostics_dir = str(self.diagnostics_dir or "runtime/reports/mcp_diagnostics").strip()
        self.audit_log_path = str(self.audit_log_path or "").strip()
        self.max_text_chars = max(16, int(self.max_text_chars))
        self.max_list_limit = max(1, int(self.max_list_limit))
        self.max_graph_nodes = max(1, int(self.max_graph_nodes))
        self.max_graph_links = max(1, int(self.max_graph_links))
        self.max_neighbor_expansion_requests = max(1, int(self.max_neighbor_expansion_requests))
        self.max_citation_matches = max(1, int(self.max_citation_matches))
        self.max_why_evidence_items = max(1, int(self.max_why_evidence_items))
        self.mutations_enabled = bool(self.mutations_enabled)
        self.integration_schema_version = str(self.integration_schema_version or "integration.v1").strip() or "integration.v1"
        integration_defaults_disabled = str(os.getenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "")).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        integration_defaults_enabled = str(os.getenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", "")).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not self.integration_viewer_token and integration_defaults_enabled and not integration_defaults_disabled:
            self.integration_viewer_token = str(
                os.getenv("NO_INTEGRATION_VIEWER_TOKEN", "local-integration-viewer-token") or ""
            ).strip()
        if not self.integration_operator_token and integration_defaults_enabled and not integration_defaults_disabled:
            self.integration_operator_token = str(
                os.getenv("NO_INTEGRATION_OPERATOR_TOKEN", "local-integration-operator-token") or ""
            ).strip()
        if not self.integration_admin_token and integration_defaults_enabled and not integration_defaults_disabled:
            self.integration_admin_token = str(
                os.getenv("NO_INTEGRATION_ADMIN_TOKEN", "local-integration-admin-token") or ""
            ).strip()


class RuntimeApiClient:
    def __init__(self, *, base_url: str, timeout_s: float = 20.0) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout_s = float(timeout_s)

    def get_json(self, path: str, *, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        _status, payload = self.request_json(
            "GET",
            path,
            query=query,
            payload=None,
            headers=None,
            allow_error_status=False,
        )
        return payload

    def post_json(self, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        _status, body = self.request_json(
            "POST",
            path,
            query=None,
            payload=payload,
            headers=None,
            allow_error_status=False,
        )
        return body

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        allow_error_status: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        from urllib.parse import urlencode

        path_text = str(path or "").strip()
        if not path_text.startswith("/"):
            raise RuntimeApiError("runtime_api_invalid_path", detail="path must start with '/'")
        decoded_path = unquote(path_text)
        normalized_path = posixpath.normpath(decoded_path)
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        if "://" in decoded_path or "://" in normalized_path:
            raise RuntimeApiError("runtime_api_invalid_path", detail="absolute url paths are not allowed")
        if decoded_path.startswith("/..") or "/../" in decoded_path or decoded_path.endswith("/.."):
            raise RuntimeApiError("runtime_api_invalid_path", detail="path traversal sequence is not allowed")
        if normalized_path.startswith("/..") or "/../" in normalized_path or normalized_path.endswith("/.."):
            raise RuntimeApiError("runtime_api_invalid_path", detail="path traversal sequence is not allowed")

        tail = ""
        if query:
            compact = {k: v for k, v in query.items() if v is not None and v != ""}
            if compact:
                tail = f"?{urlencode(compact)}"

        url = f"{self.base_url}{normalized_path}{tail}"
        data: bytes | None = None
        if payload is not None:
            data = json.dumps(dict(payload), ensure_ascii=True).encode("utf-8")
        req = urllib_request.Request(url, data=data, method=str(method).upper())
        req.add_header("Accept", "application/json")
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        for key, value in dict(headers or {}).items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            req.add_header(key_text, str(value or "").strip())

        status_code = 0
        content_type = ""
        body = b""
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_s) as resp:
                status_code = int(getattr(resp, "status", 200) or 200)
                content_type = str(resp.headers.get("content-type", "")).lower()
                body = resp.read()
        except HTTPError as exc:
            status_code = int(exc.code)
            content_type = str(getattr(exc, "headers", {}).get("content-type", "")).lower()
            body = exc.read() if hasattr(exc, "read") else b""
            if not allow_error_status:
                detail = body.decode("utf-8", errors="replace")[:1200].strip()
                raise RuntimeApiError(
                    "runtime_api_http_error",
                    status_code=status_code,
                    detail=detail,
                ) from exc
        except URLError as exc:
            raise RuntimeApiError("runtime_api_connection_error", detail=str(exc)) from exc

        text = body.decode("utf-8", errors="replace")
        if "application/json" in content_type:
            try:
                payload_obj = json.loads(text or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeApiError("runtime_api_invalid_json", detail=str(exc)) from exc
            if isinstance(payload_obj, dict):
                return status_code, payload_obj
        elif text.strip().startswith("{") and text.strip().endswith("}"):
            try:
                payload_obj = json.loads(text or "{}")
            except json.JSONDecodeError:
                payload_obj = None
            if isinstance(payload_obj, dict):
                return status_code, payload_obj
        raise RuntimeApiError("runtime_api_non_json_response", detail=text[:1200].strip())


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    permission: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]


def _validate_json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate_args(args: dict[str, Any], schema: Mapping[str, Any]) -> None:
    schema_type = str(schema.get("type") or "object").strip().lower()
    if schema_type != "object":
        raise MCPRequestError(-32603, "tool schema must be object")
    if not isinstance(args, dict):
        raise MCPRequestError(-32602, "tool arguments must be an object")

    properties = schema.get("properties")
    required = schema.get("required")
    additional = schema.get("additionalProperties", True)

    prop_map: dict[str, Any] = dict(properties) if isinstance(properties, Mapping) else {}
    required_keys = [str(item) for item in list(required or []) if str(item).strip()]
    for key in required_keys:
        if key not in args:
            raise MCPRequestError(-32602, f"missing required argument: {key}")

    if additional is False:
        allowed = set(prop_map.keys())
        extra = [key for key in args.keys() if key not in allowed]
        if extra:
            raise MCPRequestError(-32602, f"unexpected arguments: {', '.join(sorted(extra))}")

    for key, prop in prop_map.items():
        if key not in args:
            continue
        if not isinstance(prop, Mapping):
            continue
        expected_type = str(prop.get("type") or "").strip().lower()
        if expected_type and not _validate_json_type(args[key], expected_type):
            raise MCPRequestError(-32602, f"argument '{key}' must be {expected_type}")
        enum = prop.get("enum")
        if isinstance(enum, list) and enum and args[key] not in enum:
            raise MCPRequestError(-32602, f"argument '{key}' must be one of: {', '.join(str(item) for item in enum)}")


def _role_allows(current_role: str, required_role: str) -> bool:
    return ROLE_ORDER.get(str(current_role), -1) >= ROLE_ORDER.get(str(required_role), 999)


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return max(minimum, min(maximum, parsed))


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _coerce_mode(value: Any, *, default: str = "compact") -> str:
    mode = str(value or "").strip().lower() or default
    if mode not in {"compact", "full"}:
        return default
    return mode


def _normalize_string_list(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if isinstance(value, str):
        rows = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        rows = [str(item).strip() for item in value]
    else:
        rows = []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row:
            continue
        clipped = row[:max_chars].strip()
        key = clipped.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clipped)
        if len(out) >= max_items:
            break
    return out


class MCPServer:
    def __init__(self, *, config: ServerConfig, api_client: RuntimeApiClient) -> None:
        self.config = config
        self.api_client = api_client
        self._initialized = False
        self._initialized_clients: set[str] = set()
        self._session_role = config.auth.default_role
        self._client_info: dict[str, Any] = {}
        self._audit: deque[dict[str, Any]] = deque(maxlen=config.audit_max_events)
        self._http_security_events: deque[dict[str, Any]] = deque(maxlen=max(200, config.audit_max_events))
        self._state_lock = threading.Lock()
        self._http_security_log_lock = threading.Lock()
        self._rate_windows: dict[str, deque[float]] = {}
        self._nonce_registry: dict[str, dict[str, float]] = {}
        self._tools = self._build_tools()
        self._prompts = self._build_prompts()

    def _build_tools(self) -> dict[str, ToolSpec]:
        no_args_schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        list_schema = {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": [],
            "additionalProperties": False,
        }
        tools = [
            ToolSpec(
                name="capabilities.get",
                description="Return MCP server capabilities, permissions, limits, and enabled tools.",
                input_schema=no_args_schema,
                permission="viewer",
                handler=self._tool_capabilities_get,
            ),
            ToolSpec(
                name="integration.context.build",
                description="Build canonical integration.v1 context package via runtime integration API.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "principal": {"type": "object"},
                        "message": {"type": "string"},
                        "message_window": {"type": "object"},
                        "retrieval": {"type": "object"},
                        "risk_signal": {"type": "string", "enum": ["low", "medium", "high"]},
                        "memory_preference": {"type": "string", "enum": ["auto", "chat_first", "memory_assist"]},
                        "retrieval_query": {"type": "string"},
                    },
                    "required": ["session_id", "run_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_integration_context_build,
            ),
            ToolSpec(
                name="integration.context.why",
                description="Explain integration evidence handles via runtime integration API.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "principal": {"type": "object"},
                        "evidence_ids": {"type": "array"},
                        "expand_citations": {"type": "boolean"},
                    },
                    "required": ["session_id", "run_id", "evidence_ids"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_integration_context_why,
            ),
            ToolSpec(
                name="integration.writeback.propose",
                description="Create integration mutation proposal via runtime integration API.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "principal": {"type": "object"},
                        "idempotency_key": {"type": "string"},
                        "mutation": {"type": "object"},
                        "evidence": {"type": "array"},
                    },
                    "required": ["session_id", "run_id", "idempotency_key", "mutation", "evidence"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_integration_writeback_propose,
            ),
            ToolSpec(
                name="integration.writeback.resolve",
                description="Resolve integration mutation proposal via runtime integration API.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "principal": {"type": "object"},
                        "proposal_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["approve", "reject"]},
                        "decided_by": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["session_id", "proposal_id", "decision", "decided_by"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_integration_writeback_resolve,
            ),
            ToolSpec(
                name="integration.capabilities.get",
                description="Get integration contract capabilities (canonical integration.v1 envelope).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_integration_capabilities_get,
            ),
            ToolSpec(
                name="integration.health.get",
                description="Get integration health status (canonical integration.v1 envelope).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_integration_health_get,
            ),
            ToolSpec(
                name="ops.health",
                description="Run runtime health checks and return status details.",
                input_schema=no_args_schema,
                permission="viewer",
                handler=self._tool_ops_health,
            ),
            ToolSpec(
                name="ops.get_provider_config",
                description="Return runtime provider configuration snapshot.",
                input_schema=no_args_schema,
                permission="admin",
                handler=self._tool_ops_get_provider_config,
            ),
            ToolSpec(
                name="ops.export_diagnostics",
                description="Export MCP diagnostics bundle with audit summary and capabilities.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_recent_turns": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="admin",
                handler=self._tool_ops_export_diagnostics,
            ),
            ToolSpec(
                name="ops.set_policy",
                description="Patch selected MCP runtime policy knobs (admin only).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "policy_patch": {"type": "object"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["policy_patch"],
                    "additionalProperties": False,
                },
                permission="admin",
                handler=self._tool_ops_set_policy,
            ),
            ToolSpec(
                name="memory.list_episodes",
                description="List episode memories with bounded pagination and optional status/search filters.",
                input_schema={
                    **list_schema,
                    "properties": {
                        **dict(list_schema["properties"]),
                        "status": {"type": "string", "enum": ["all", "approved", "disabled"]},
                    },
                },
                permission="viewer",
                handler=self._tool_memory_list_episodes,
            ),
            ToolSpec(
                name="memory.get_episode",
                description="Get one episode by episode_id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "episode_id": {"type": "string"},
                    },
                    "required": ["episode_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_memory_get_episode,
            ),
            ToolSpec(
                name="memory.list_atoms",
                description="List memory atoms/cards with bounded pagination and optional filters.",
                input_schema={
                    "type": "object",
                    "properties": {
                        **dict(list_schema["properties"]),
                        "status": {"type": "string"},
                        "kind": {"type": "string", "enum": ["all", "fact_card", "event_card", "relationship_card"]},
                        "contradiction": {"type": "string", "enum": ["all", "true", "false"]},
                        "view": {"type": "string", "enum": ["default", "definition"]},
                        "mode": {"type": "string", "enum": ["compact", "full"]},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_memory_list_atoms,
            ),
            ToolSpec(
                name="memory.get_atom",
                description="Get one memory atom by atom_id with provenance and graph context.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "atom_id": {"type": "string"},
                        "mode": {"type": "string", "enum": ["compact", "full"]},
                        "neighbor_limit": {"type": "integer"},
                    },
                    "required": ["atom_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_memory_get_atom,
            ),
            ToolSpec(
                name="memory.graph_map",
                description="Get a bounded memory graph snapshot for visualization.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "status": {"type": "string"},
                        "kind": {"type": "string", "enum": ["all", "fact_card", "event_card", "relationship_card"]},
                        "contradiction": {"type": "string", "enum": ["all", "true", "false"]},
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_memory_graph_map,
            ),
            ToolSpec(
                name="memory.graph_neighbors",
                description="Get bounded neighbors for a node (depth 1-2) for graph exploration.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string"},
                        "depth": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "node_limit": {"type": "integer"},
                        "link_limit": {"type": "integer"},
                        "include_shared_language": {"type": "boolean"},
                        "include_root_detail": {"type": "boolean"},
                    },
                    "required": ["node_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_memory_graph_neighbors,
            ),
            ToolSpec(
                name="memory.quicknote.status",
                description="Return quicknote buffer/cap status for assistant/session scope.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "assistant_id": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_memory_quicknote_status,
            ),
            ToolSpec(
                name="memory.quicknote.propose",
                description="Propose one lightweight memory note for persistent review/apply flow.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "assistant_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "importance": {"type": "string", "enum": ["low", "normal", "high", "critical"]},
                        "tags": {"type": "array"},
                        "context_pressure": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_memory_quicknote_propose,
            ),
            ToolSpec(
                name="memory.quicknote.propose_batch",
                description="Propose multiple quicknotes in one bounded call.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "notes": {"type": "array"},
                        "assistant_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "importance": {"type": "string", "enum": ["low", "normal", "high", "critical"]},
                        "tags": {"type": "array"},
                        "context_pressure": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["notes"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_memory_quicknote_propose_batch,
            ),
            ToolSpec(
                name="memory.quicknote.flush",
                description="Flush pending quicknotes for assistant/session scope.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "assistant_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "reason": {
                            "type": "string",
                            "enum": ["manual", "inactivity_timeout", "session_rollover", "cap_reached", "context_pressure_high", "operator_reset"],
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_memory_quicknote_flush,
            ),
            ToolSpec(
                name="explore.start_here",
                description="Return zero-seed memory exploration snapshot (people/projects/topics/arcs/unresolved).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_start_here,
            ),
            ToolSpec(
                name="explore.orient",
                description="Return one-call wake-up orientation snapshot (what matters, who matters, recent focus).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_orient,
            ),
            ToolSpec(
                name="explore.expand_anchor",
                description="Expand one exploration anchor into connected atoms and next-hop anchors.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "anchor_id": {"type": "string"},
                        "anchor_type": {"type": "string", "enum": ["person", "project", "topic", "event", "unknown"]},
                        "limit": {"type": "integer"},
                        "hop_depth": {"type": "integer"},
                        "mode": {"type": "string", "enum": ["compact", "full"]},
                        "include_next_hops": {"type": "boolean"},
                    },
                    "required": ["anchor_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_expand_anchor,
            ),
            ToolSpec(
                name="explore.peek",
                description="Return lightweight exploration snippets for an anchor (low-token).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "anchor_id": {"type": "string"},
                        "anchor_type": {"type": "string", "enum": ["person", "project", "topic", "event", "unknown"]},
                        "limit": {"type": "integer"},
                        "mode": {"type": "string", "enum": ["compact", "full"]},
                    },
                    "required": ["anchor_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_peek,
            ),
            ToolSpec(
                name="explore.anchor_brief",
                description="Return one-paragraph anchor summary with bounded evidence snippets and confidence.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "anchor_id": {"type": "string"},
                        "anchor_type": {"type": "string", "enum": ["person", "project", "topic", "event", "unknown"]},
                        "limit": {"type": "integer"},
                    },
                    "required": ["anchor_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_anchor_brief,
            ),
            ToolSpec(
                name="explore.get_preferences",
                description="List exploration preference signals currently active.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_get_preferences,
            ),
            ToolSpec(
                name="explore.set_preference",
                description="Set or clear exploration preference for one anchor (pin/more/less/ignore/clear).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "anchor_id": {"type": "string"},
                        "anchor_type": {"type": "string", "enum": ["person", "project", "topic", "event", "unknown"]},
                        "action": {"type": "string", "enum": ["pin", "more", "less", "ignore", "clear"]},
                    },
                    "required": ["anchor_id", "action"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_set_preference,
            ),
            ToolSpec(
                name="explore.whats_new",
                description="Return compact memory changes since assistant last check-in (server-side cursor).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "assistant_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "peek_only": {"type": "boolean"},
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_explore_whats_new,
            ),
            ToolSpec(
                name="system.usage_guide",
                description="Return compact usage guidance for low-token memory workflow.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_system_usage_guide,
            ),
            ToolSpec(
                name="methodology.list",
                description="List methodology records with status filter and pagination.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["all", "draft", "canary", "active", "retired"]},
                        "mode": {"type": "string", "enum": ["compact", "full"]},
                        "include_retired": {"type": "boolean"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_methodology_list,
            ),
            ToolSpec(
                name="methodology.get",
                description="Get one methodology record by methodology_id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "methodology_id": {"type": "string"},
                    },
                    "required": ["methodology_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_methodology_get,
            ),
            ToolSpec(
                name="methodology.readout",
                description="Return operator readout for methodology status, canary state, and trigger history.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_methodology_readout,
            ),
            ToolSpec(
                name="methodology.list_correction_clusters",
                description="List correction clusters used for friction-to-fix proposal generation.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_methodology_list_correction_clusters,
            ),
            ToolSpec(
                name="methodology.create_draft",
                description="Create a draft methodology record (review-gated).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "trigger_condition": {"type": "string"},
                        "action": {"type": "string"},
                        "rationale": {"type": "string"},
                        "provenance_refs": {"type": "array"},
                        "supersedes_id": {"type": "string"},
                        "metadata": {"type": "object"},
                        "actor": {"type": "string"},
                    },
                    "required": ["trigger_condition", "action", "rationale"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_create_draft,
            ),
            ToolSpec(
                name="methodology.review",
                description="Approve or reject a draft methodology record.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "methodology_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["approve", "reject"]},
                        "reviewer": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["methodology_id", "decision", "reviewer"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_review,
            ),
            ToolSpec(
                name="methodology.start_canary",
                description="Move an approved methodology record to canary with baseline capture.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "methodology_id": {"type": "string"},
                        "auto_rollback": {"type": "boolean"},
                        "actor": {"type": "string"},
                    },
                    "required": ["methodology_id"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_start_canary,
            ),
            ToolSpec(
                name="methodology.evaluate_canary",
                description="Evaluate canary methodology quality against baseline and auto-rollback rules.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "methodology_id": {"type": "string"},
                        "actor": {"type": "string"},
                    },
                    "required": ["methodology_id"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_evaluate_canary,
            ),
            ToolSpec(
                name="methodology.activate",
                description="Activate an approved methodology record.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "methodology_id": {"type": "string"},
                        "actor": {"type": "string"},
                    },
                    "required": ["methodology_id"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_activate,
            ),
            ToolSpec(
                name="methodology.rollback",
                description="Rollback a methodology record and restore prior active version when available.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "methodology_id": {"type": "string"},
                        "reason": {"type": "string"},
                        "actor": {"type": "string"},
                    },
                    "required": ["methodology_id"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_rollback,
            ),
            ToolSpec(
                name="methodology.record_correction",
                description="Record a user correction and generate draft methodology candidate after repeated clusters.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "assistant_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "actor": {"type": "string"},
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_record_correction,
            ),
            ToolSpec(
                name="methodology.evaluate_maintenance",
                description="Run condition-based maintenance trigger evaluation.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "force": {"type": "boolean"},
                        "actor": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_methodology_evaluate_maintenance,
            ),
            ToolSpec(
                name="chat.start_session",
                description="Start a new runtime chat session.",
                input_schema={
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_chat_start_session,
            ),
            ToolSpec(
                name="chat.rename_session",
                description="Rename an existing chat session label.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["session_id", "label"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_chat_rename_session,
            ),
            ToolSpec(
                name="chat.list_sessions",
                description="List runtime chat sessions with bounded pagination.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_chat_list_sessions,
            ),
            ToolSpec(
                name="chat.session_history",
                description="Fetch bounded history for one chat session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": ["session_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_chat_session_history,
            ),
            ToolSpec(
                name="chat.turn",
                description="Send one chat turn through runtime memory routing and verifier policy.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "message": {"type": "string"},
                        "memory_preference": {"type": "string", "enum": ["auto", "chat_first", "memory_assist"]},
                        "retrieval_query": {"type": "string"},
                        "high_risk": {"type": "boolean"},
                        "peek": {"type": "boolean"},
                        "include_why": {"type": "boolean"},
                    },
                    "required": ["message"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_chat_turn,
            ),
            ToolSpec(
                name="chat.route_preview",
                description="Preview chat memory route decision without creating a turn.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "message": {"type": "string"},
                        "memory_preference": {"type": "string", "enum": ["auto", "chat_first", "memory_assist"]},
                        "high_risk": {"type": "boolean"},
                    },
                    "required": ["message"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_chat_route_preview,
            ),
            ToolSpec(
                name="chat.build_context_package",
                description="Build context package v2 for responder audit/debug flows.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "message": {"type": "string"},
                        "memory_preference": {"type": "string", "enum": ["auto", "chat_first", "memory_assist"]},
                        "retrieval_query": {"type": "string"},
                        "high_risk": {"type": "boolean"},
                        "package_version": {"type": "string", "enum": ["v2"]},
                        "render_citations": {"type": "boolean"},
                    },
                    "required": ["message"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_chat_build_context_package,
            ),
            ToolSpec(
                name="why.explain_turn",
                description="Explain a stored turn with bounded evidence rows and optional citations.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "turn_id": {"type": "string"},
                        "include_citations": {"type": "boolean"},
                    },
                    "required": ["turn_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_why_explain_turn,
            ),
            ToolSpec(
                name="evidence.resolve_citation",
                description="Resolve a citation token into bounded evidence matches.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "citation_token": {"type": "string"},
                        "max_matches": {"type": "integer"},
                        "context_window": {"type": "integer"},
                    },
                    "required": ["citation_token"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_evidence_resolve_citation,
            ),
            ToolSpec(
                name="memory.disable_episode",
                description="Disable an episode from retrieval eligibility.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "episode_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["episode_id"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_memory_disable_episode,
            ),
            ToolSpec(
                name="memory.enable_episode",
                description="Re-enable an episode for retrieval eligibility.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "episode_id": {"type": "string"},
                    },
                    "required": ["episode_id"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_memory_enable_episode,
            ),
            ToolSpec(
                name="memory.edit_episode",
                description="Edit selected episode fields with optional dry-run preview.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "episode_id": {"type": "string"},
                        "patch": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "summary": {"type": "string"},
                                "tags": {"type": "array"},
                                "actors": {"type": "array"},
                                "cue_terms": {"type": "array"},
                            },
                            "required": [],
                            "additionalProperties": False,
                        },
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["episode_id", "patch"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_memory_edit_episode,
            ),
            ToolSpec(
                name="memory.undo_last_change",
                description="Undo last episode edit change with bounded metadata output.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["episode_edits", "proposals", "all"]},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_memory_undo_last_change,
            ),
            ToolSpec(
                name="proposals.list",
                description="List mutation proposals with bounded pagination.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["open", "approved", "rejected", "all"]},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_proposals_list,
            ),
            ToolSpec(
                name="proposals.create_edit",
                description="Create an edit proposal for a target atom with optional dry-run.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target_id": {"type": "string"},
                        "patch": {"type": "object"},
                        "reason": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["target_id", "patch", "reason"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_proposals_create_edit,
            ),
            ToolSpec(
                name="proposals.create_delete",
                description="Create a delete proposal for a target atom with optional dry-run.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target_id": {"type": "string"},
                        "reason": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["target_id", "reason"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_proposals_create_delete,
            ),
            ToolSpec(
                name="proposals.approve",
                description="Approve an existing proposal (apply optional).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "note": {"type": "string"},
                        "apply": {"type": "boolean"},
                    },
                    "required": ["proposal_id"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_proposals_approve,
            ),
            ToolSpec(
                name="proposals.reject",
                description="Reject an existing proposal with reason note.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["proposal_id", "note"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_proposals_reject,
            ),
            ToolSpec(
                name="wizard.start_or_resume",
                description="Start a new wizard run or resume an existing run.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["new", "resume"]},
                        "run_id": {"type": "string"},
                    },
                    "required": ["mode"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_start_or_resume,
            ),
            ToolSpec(
                name="wizard.validate_archive",
                description="Validate an archive descriptor for import readiness.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "archive_descriptor": {"type": "object"},
                    },
                    "required": ["archive_descriptor"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_validate_archive,
            ),
            ToolSpec(
                name="wizard.import_run",
                description="Run archive import into memory store (supports dry_run).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "archive_descriptor": {"type": "object"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["archive_descriptor"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_import_run,
            ),
            ToolSpec(
                name="wizard.build_episodes",
                description="Build draft episode cards for a wizard run (supports dry_run).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "store_descriptor": {"type": "object"},
                        "policy_preset": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_build_episodes,
            ),
            ToolSpec(
                name="wizard.draft_curation_status",
                description="Read draft-curation status, lease state, and context policy for the current build.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_status,
            ),
            ToolSpec(
                name="wizard.draft_curation_cards",
                description="List draft cards with Claude suggestion state for the current build. Compact mode is the default for model triage; use full mode for nested card/proposal payloads.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "mode": {"type": "string", "enum": ["compact", "full"]},
                        "proposal_status": {"type": "string", "enum": ["all", "pending", "accepted", "rejected", "promoted", "stale", "none"]},
                        "q": {"type": "string"},
                        "page": {"type": "integer"},
                        "page_size": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_cards,
            ),
            ToolSpec(
                name="wizard.draft_curation_get_card",
                description="Read one draft card, its current suggestion, and bounded local context for curation.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "episode_id": {"type": "string"},
                        "include_context": {"type": "boolean"},
                        "context_window": {"type": "integer"},
                    },
                    "required": ["episode_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_get_card,
            ),
            ToolSpec(
                name="wizard.draft_curation_proposals",
                description="List existing Claude draft-curation proposals for the current build.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["all", "pending", "accepted", "rejected", "promoted", "stale"]},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_proposals,
            ),
            ToolSpec(
                name="wizard.draft_curation_session_start",
                description="Acquire or resume a single active draft-curation lease for the current build.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "owner_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "model_identity": {"type": "string"},
                        "ttl_seconds": {"type": "integer"},
                        "force_release": {"type": "boolean"},
                    },
                    "required": ["owner_id", "session_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_session_start,
            ),
            ToolSpec(
                name="wizard.draft_curation_session_heartbeat",
                description="Refresh the active draft-curation lease while Claude is still working.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "owner_id": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["owner_id", "session_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_session_heartbeat,
            ),
            ToolSpec(
                name="wizard.draft_curation_session_release",
                description="Release a draft-curation lease without promoting any suggestions.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "owner_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "force_release": {"type": "boolean"},
                        "note": {"type": "string"},
                    },
                    "required": ["owner_id", "session_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_session_release,
            ),
            ToolSpec(
                name="wizard.draft_curation_proposal_upsert",
                description="Save or update one draft-only Claude suggestion for a single episode card.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "episode_id": {"type": "string"},
                        "owner_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "model_identity": {"type": "string"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "actors": {"type": "array", "items": {"type": "string"}},
                        "topic_tags": {"type": "array", "items": {"type": "string"}},
                        "cue_terms": {"type": "array", "items": {"type": "string"}},
                        "decision_suggestion": {"type": "string", "enum": ["", "approved", "edited", "rejected", "pending"]},
                        "ranking_hint": {"type": "object"},
                        "retrieval_cues": {"type": "array", "items": {"type": "string"}},
                        "rationale": {"type": "string"},
                    },
                    "required": ["episode_id", "owner_id", "session_id"],
                    "additionalProperties": False,
                },
                permission="viewer",
                handler=self._tool_wizard_draft_curation_proposal_upsert,
            ),
            ToolSpec(
                name="wizard.review_list",
                description="List review cards for a wizard run with filters.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "q": {"type": "string"},
                        "status": {"type": "string", "enum": ["all", "pending", "approved", "edited", "rejected"]},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_review_list,
            ),
            ToolSpec(
                name="wizard.review_update",
                description="Apply batched review decisions for wizard cards (supports dry_run).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "updates": {"type": "array"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["updates"],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_review_update,
            ),
            ToolSpec(
                name="wizard.compile_reviewed",
                description="Compile reviewed cards into published reviewed set (supports dry_run).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "reviewer": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_compile_reviewed,
            ),
            ToolSpec(
                name="wizard.verify",
                description="Run wizard verification checks and return actionable links.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_verify,
            ),
            ToolSpec(
                name="wizard.go_live",
                description="Mark wizard pipeline run ready for live runtime (admin).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="admin",
                handler=self._tool_wizard_go_live,
            ),
            ToolSpec(
                name="wizard.restore_last_published",
                description="Restore previous published pointers (admin).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="admin",
                handler=self._tool_wizard_restore_last_published,
            ),
            ToolSpec(
                name="wizard.organizer_inventory",
                description="Build organizer inventory + typing snapshot for a wizard run.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_inventory,
            ),
            ToolSpec(
                name="wizard.organizer_dedupe",
                description="Generate organizer dedupe proposals for a wizard run.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_dedupe,
            ),
            ToolSpec(
                name="wizard.organizer_conflicts",
                description="Generate organizer contradiction and ambiguity queues.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_conflicts,
            ),
            ToolSpec(
                name="wizard.organizer_package",
                description="Assemble organizer proposal package (safe/review operations).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_package,
            ),
            ToolSpec(
                name="wizard.organizer_apply",
                description="Apply organizer safe operations with rollback checkpoint (supports dry_run).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_apply,
            ),
            ToolSpec(
                name="wizard.organizer_verify",
                description="Verify organizer quality delta and queue status.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_verify,
            ),
            ToolSpec(
                name="wizard.organizer_restore_last",
                description="Restore the previous organizer apply snapshot.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_restore_last,
            ),
            ToolSpec(
                name="wizard.organizer_run",
                description="Run organizer pipeline in one call and return compact summary (optional apply).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "apply_changes": {"type": "boolean"},
                        "dry_run": {"type": "boolean"},
                        "include_stage_payloads": {"type": "boolean"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                permission="operator",
                handler=self._tool_wizard_organizer_run,
            ),
        ]
        return {tool.name: tool for tool in tools}

    def _compat_mode_enabled(self) -> bool:
        return self.config.compat_mode == "lenient_v1"

    def _normalize_method(self, method: str) -> str:
        if not self._compat_mode_enabled():
            return method
        return COMPAT_METHOD_ALIASES.get(method, method)

    def _build_prompts(self) -> dict[str, dict[str, Any]]:
        return {
            "memory_safe_recall": {
                "name": "memory_safe_recall",
                "description": "Ask a recall question with strict abstain behavior when evidence is weak.",
                "template": (
                    "Recall only what is supported by evidence. If support is weak or conflicting, abstain and ask one clarifying question."
                ),
            },
            "abstain_then_clarify": {
                "name": "abstain_then_clarify",
                "description": "Canonical abstain then one-question clarification policy.",
                "template": (
                    "If you cannot support a claim, say you do not have that memory and ask a single focused clarifying question."
                ),
            },
            "citation_discipline": {
                "name": "citation_discipline",
                "description": "Keep citations internal unless explicitly requested.",
                "template": (
                    "Use citation tokens internally for validation. Include visible citations only when explicitly requested by the caller."
                ),
            },
        }

    def _record_audit(
        self,
        *,
        method: str,
        status: str,
        request_id: Any,
        started: float,
        error_code: int | None = None,
    ) -> None:
        row = {
            "timestamp": _utc_iso(),
            "method": str(method or ""),
            "status": str(status or "ok"),
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "request_id": request_id,
            "role": self._session_role,
            "error_code": int(error_code) if error_code is not None else None,
        }
        self._audit.append(row)
        self._append_audit_log(row)

    def _append_audit_log(self, row: Mapping[str, Any]) -> None:
        log_path = str(self.config.audit_log_path or "").strip()
        if not log_path:
            return
        try:
            target = Path(log_path).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dict(row), ensure_ascii=True, separators=(",", ":")) + "\n")
        except Exception:
            return

    def _http_security_log_target(self, *, ensure_parent: bool = False) -> Path | None:
        log_path = str(self.config.http_security_log_path or "").strip()
        if not log_path:
            return None
        try:
            target = Path(log_path).expanduser().resolve()
            if ensure_parent:
                target.parent.mkdir(parents=True, exist_ok=True)
            return target
        except Exception:
            return None

    def _record_http_security_event(
        self,
        *,
        path: str,
        status_code: int,
        outcome: str,
        reason: str,
        client_ip: str,
        auth_token: str | None,
        client_key: str | None,
        request_bytes: int,
        observed_proto: str,
        nonce: str | None,
    ) -> None:
        row = {
            "timestamp": _utc_iso(),
            "transport": "http",
            "path": str(path or ""),
            "status_code": int(status_code),
            "outcome": str(outcome or ""),
            "reason": str(reason or ""),
            "client_ip": str(client_ip or ""),
            "client_key_hash": _sha256_short(str(client_key or "")),
            "auth_token_hash": _sha256_short(str(auth_token or "")),
            "request_bytes": max(0, int(request_bytes)),
            "observed_proto": str(observed_proto or "http"),
            "nonce_hash": _sha256_short(str(nonce or "")),
            "enforce_https": bool(self.config.enforce_https),
            "http_rate_limit_per_minute": int(self.config.http_rate_limit_per_minute),
            "http_max_request_bytes": int(self.config.http_max_request_bytes),
            "nonce_replay_window_seconds": int(self.config.http_nonce_replay_window_seconds),
        }
        with self._http_security_log_lock:
            self._http_security_events.append(row)
            target = self._http_security_log_target(ensure_parent=True)
            if target is None:
                return
            try:
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
            except Exception:
                return

    def allow_http_request(self, *, client_key: str) -> bool:
        now = time.monotonic()
        with self._state_lock:
            stale_after_s = 60.0
            bucket = self._rate_windows.setdefault(client_key, deque())
            while bucket and (now - bucket[0]) > stale_after_s:
                bucket.popleft()
            stale_keys: list[str] = []
            for key, window in self._rate_windows.items():
                if key == client_key:
                    continue
                if not window:
                    stale_keys.append(key)
                    continue
                if (now - window[-1]) > stale_after_s:
                    stale_keys.append(key)
            for key in stale_keys:
                self._rate_windows.pop(key, None)
            if len(bucket) >= self.config.http_rate_limit_per_minute:
                return False
            bucket.append(now)
            return True

    def allow_http_nonce(self, *, client_key: str, nonce: str | None) -> bool:
        nonce_text = str(nonce or "").strip()
        if not nonce_text:
            return True
        window_s = max(0, int(self.config.http_nonce_replay_window_seconds))
        if window_s <= 0:
            return True
        now = time.monotonic()
        with self._state_lock:
            bucket = self._nonce_registry.setdefault(client_key, {})
            stale = [nonce_value for nonce_value, expiry in bucket.items() if expiry <= now]
            for nonce_value in stale:
                bucket.pop(nonce_value, None)
            expiry = bucket.get(nonce_text)
            if expiry is not None and expiry > now:
                return False
            bucket[nonce_text] = now + float(window_s)
            if not bucket:
                self._nonce_registry.pop(client_key, None)
            return True

    def _remote_hardening_checklist(self) -> dict[str, Any]:
        tls_pass = bool(self.config.enforce_https)
        limits_pass = bool(
            int(self.config.http_rate_limit_per_minute) >= 1 and int(self.config.http_max_request_bytes) >= 1024
        )
        log_target = self._http_security_log_target(ensure_parent=True)
        structured_logs_pass = bool(log_target is not None and os.access(log_target.parent, os.W_OK))
        replay_pass = bool(int(self.config.http_nonce_replay_window_seconds) > 0)
        pen_test = {
            "token_leakage": {
                "pass": True,
                "control": "HTTP security logs store auth/client hashes only (no raw bearer tokens).",
            },
            "ssrf": {
                "pass": True,
                "control": "Runtime API path guard blocks absolute URLs and traversal segments.",
            },
            "path_traversal": {
                "pass": True,
                "control": "Service endpoint is fixed to /mcp and diagnostics/log paths are server-resolved.",
            },
            "replay": {
                "pass": replay_pass,
                "control": "Optional X-MCP-Nonce replay window rejects duplicate nonces per client key.",
            },
        }
        pen_test_pass = all(bool(dict(item).get("pass")) for item in pen_test.values())
        checklist_pass = bool(tls_pass and limits_pass and structured_logs_pass and pen_test_pass)
        return {
            "checklist_pass": checklist_pass,
            "tls": {
                "pass": tls_pass,
                "enforce_https": bool(self.config.enforce_https),
                "trust_proxy_headers": bool(self.config.trust_proxy_headers),
                "recommendation": "run behind a TLS terminator/reverse proxy and set enforce_https=true",
            },
            "limits": {
                "pass": limits_pass,
                "http_rate_limit_per_minute": int(self.config.http_rate_limit_per_minute),
                "http_max_request_bytes": int(self.config.http_max_request_bytes),
            },
            "structured_logs": {
                "pass": structured_logs_pass,
                "http_security_log_path": str(self.config.http_security_log_path or ""),
                "recent_event_count": len(self._http_security_events),
            },
            "pen_test": {
                "pass": pen_test_pass,
                "items": pen_test,
            },
        }

    def _resource_payload(self, uri: str) -> dict[str, Any]:
        if uri == "resource://capabilities":
            return self._tool_capabilities_get({})
        if uri == "resource://audit/summary":
            rows = list(self._audit)
            error_count = len([row for row in rows if str(row.get("status") or "") == "error"])
            return {
                "generated_at": _utc_iso(),
                "event_count": len(rows),
                "error_count": error_count,
                "recent_events": rows[-50:],
            }
        raise MCPRequestError(-32602, f"unknown resource uri: {uri}")

    @staticmethod
    def _integration_request_id(raw: Any) -> str:
        request_id = str(raw or "").strip()
        if request_id:
            return request_id
        return f"req_{uuid4().hex[:24]}"

    def _integration_token_for_session_role(self) -> str:
        viewer = str(self.config.integration_viewer_token or "").strip()
        operator = str(self.config.integration_operator_token or "").strip()
        admin = str(self.config.integration_admin_token or "").strip()
        if self._session_role == "admin":
            return admin
        if self._session_role == "operator":
            return operator
        return viewer

    def _integration_headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        token = self._integration_token_for_session_role()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key).strip()
        return headers

    def _integration_post(
        self,
        *,
        path: str,
        args: dict[str, Any],
        data: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        principal = dict(args.get("principal") or {}) if isinstance(args.get("principal"), Mapping) else {}
        payload = {
            "schema_version": self.config.integration_schema_version,
            "request_id": self._integration_request_id(args.get("request_id")),
            "session_id": str(args.get("session_id") or "").strip(),
            "run_id": str(args.get("run_id") or "").strip(),
            "principal": principal,
            "data": dict(data),
        }
        _status, response = self.api_client.request_json(
            "POST",
            path,
            query=None,
            payload=payload,
            headers=self._integration_headers(idempotency_key=idempotency_key),
            allow_error_status=True,
        )
        if not isinstance(response, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid integration payload")
        return dict(response)

    def _integration_get(self, *, path: str, args: dict[str, Any]) -> dict[str, Any]:
        query = {
            "schema_version": self.config.integration_schema_version,
            "request_id": self._integration_request_id(args.get("request_id")),
        }
        _status, response = self.api_client.request_json(
            "GET",
            path,
            query=query,
            payload=None,
            headers=self._integration_headers(),
            allow_error_status=True,
        )
        if not isinstance(response, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid integration payload")
        return dict(response)

    def _tool_integration_context_build(self, args: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if "message" in args:
            data["message"] = str(args.get("message") or "")
        if "message_window" in args and isinstance(args.get("message_window"), Mapping):
            data["message_window"] = dict(args.get("message_window") or {})
        if "retrieval" in args and isinstance(args.get("retrieval"), Mapping):
            data["retrieval"] = dict(args.get("retrieval") or {})
        if "risk_signal" in args:
            data["risk_signal"] = str(args.get("risk_signal") or "")
        if "memory_preference" in args:
            data["memory_preference"] = str(args.get("memory_preference") or "")
        if "retrieval_query" in args:
            data["retrieval_query"] = str(args.get("retrieval_query") or "")
        return self._integration_post(
            path="/api/integration/v1/context/build",
            args=args,
            data=data,
        )

    def _tool_integration_context_why(self, args: dict[str, Any]) -> dict[str, Any]:
        evidence_ids_raw = args.get("evidence_ids")
        if not isinstance(evidence_ids_raw, list) or not evidence_ids_raw:
            raise MCPRequestError(-32602, "evidence_ids must be a non-empty array")
        data: dict[str, Any] = {
            "evidence_ids": [str(item or "").strip() for item in evidence_ids_raw if str(item or "").strip()],
            "expand_citations": bool(args.get("expand_citations", False)),
        }
        return self._integration_post(
            path="/api/integration/v1/context/why",
            args=args,
            data=data,
        )

    def _tool_integration_writeback_propose(self, args: dict[str, Any]) -> dict[str, Any]:
        idempotency_key = str(args.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise MCPRequestError(-32602, "idempotency_key is required")
        mutation = dict(args.get("mutation") or {}) if isinstance(args.get("mutation"), Mapping) else None
        if mutation is None:
            raise MCPRequestError(-32602, "mutation must be an object")
        evidence_raw = args.get("evidence")
        if not isinstance(evidence_raw, list):
            raise MCPRequestError(-32602, "evidence must be an array")
        return self._integration_post(
            path="/api/integration/v1/writeback/propose",
            args=args,
            data={
                "mutation": mutation,
                "evidence": list(evidence_raw),
            },
            idempotency_key=idempotency_key,
        )

    def _tool_integration_writeback_resolve(self, args: dict[str, Any]) -> dict[str, Any]:
        proposal_id = str(args.get("proposal_id") or "").strip()
        decision = str(args.get("decision") or "").strip()
        decided_by = str(args.get("decided_by") or "").strip()
        if not proposal_id or not decision or not decided_by:
            raise MCPRequestError(-32602, "proposal_id, decision, and decided_by are required")
        data = {
            "proposal_id": proposal_id,
            "decision": decision,
            "decided_by": decided_by,
        }
        if "reason" in args:
            data["reason"] = str(args.get("reason") or "")
        return self._integration_post(
            path="/api/integration/v1/writeback/resolve",
            args=args,
            data=data,
        )

    def _tool_integration_capabilities_get(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._integration_get(path="/api/integration/v1/capabilities", args=args)

    def _tool_integration_health_get(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._integration_get(path="/api/integration/v1/health", args=args)

    def _tool_capabilities_get(self, _args: dict[str, Any]) -> dict[str, Any]:
        remote_hardening = self._remote_hardening_checklist()
        return {
            "server": {
                "name": "numquamoblita-mcp",
                "protocol_version": self.config.protocol_version,
                "toolset_version": self.config.toolset_version,
                "transport": self.config.transport,
                "supported_transports": ["stdio", "http"],
                "compat_mode": self.config.compat_mode,
            },
            "runtime": {
                "base_url": self.config.runtime_base_url,
                "timeout_s": self.config.timeout_s,
            },
            "auth": {
                "require_auth": self.config.auth.require_auth,
                "session_role": self._session_role,
                "default_role": self.config.auth.default_role,
            },
            "limits": {
                "audit_max_events": self.config.audit_max_events,
                "max_text_chars": self.config.max_text_chars,
                "max_list_limit": self.config.max_list_limit,
                "max_graph_nodes": self.config.max_graph_nodes,
                "max_graph_links": self.config.max_graph_links,
                "max_neighbor_expansion_requests": self.config.max_neighbor_expansion_requests,
                "max_citation_matches": self.config.max_citation_matches,
                "max_why_evidence_items": self.config.max_why_evidence_items,
                "mutations_enabled": self.config.mutations_enabled,
                "http_rate_limit_per_minute": self.config.http_rate_limit_per_minute,
                "http_max_request_bytes": self.config.http_max_request_bytes,
                "enforce_https": self.config.enforce_https,
                "http_nonce_replay_window_seconds": self.config.http_nonce_replay_window_seconds,
            },
            "enabled_tools": sorted(self._tools.keys()),
            "compatibility": {
                "method_aliases_enabled": self._compat_mode_enabled(),
                "method_aliases": dict(COMPAT_METHOD_ALIASES) if self._compat_mode_enabled() else {},
                "field_aliases_enabled": self._compat_mode_enabled(),
            },
            "remote_hardening": remote_hardening,
            "resources": [
                "resource://capabilities",
                "resource://audit/summary",
            ],
            "prompts": sorted(self._prompts.keys()),
        }

    def _tool_ops_health(self, _args: dict[str, Any]) -> dict[str, Any]:
        payload = self.api_client.get_json("/api/runtime/health")
        return payload

    def _tool_ops_get_provider_config(self, _args: dict[str, Any]) -> dict[str, Any]:
        payload = self.api_client.get_json("/api/runtime/provider/config")
        provider = payload.get("provider_config")
        if not isinstance(provider, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid provider_config payload")
        return dict(provider)

    def _tool_ops_export_diagnostics(self, args: dict[str, Any]) -> dict[str, Any]:
        include_recent_turns = bool(args.get("include_recent_turns"))
        with self._http_security_log_lock:
            security_events = list(self._http_security_events)[-200:]
        bundle = {
            "generated_at": _utc_iso(),
            "capabilities": self._tool_capabilities_get({}),
            "audit_summary": self._resource_payload("resource://audit/summary"),
            "remote_hardening": self._remote_hardening_checklist(),
            "http_security_events": security_events,
        }
        if include_recent_turns:
            try:
                turns = self.api_client.get_json("/api/turns")
                rows = [row for row in list(turns.get("turns") or []) if isinstance(row, Mapping)]
                bundle["recent_turns"] = rows[-20:]
            except Exception:
                bundle["recent_turns"] = []
        diagnostics_root = Path(self.config.diagnostics_dir).expanduser().resolve()
        diagnostics_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        bundle_path = diagnostics_root / f"mcp_diag_{stamp}.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        return {
            "ok": True,
            "bundle_descriptor": {
                "path": str(bundle_path),
                "event_count": int(dict(bundle.get("audit_summary") or {}).get("event_count") or 0),
            },
        }

    def _tool_ops_set_policy(self, args: dict[str, Any]) -> dict[str, Any]:
        patch = dict(args.get("policy_patch") or {}) if isinstance(args.get("policy_patch"), Mapping) else {}
        if not patch:
            raise MCPRequestError(-32602, "policy_patch must include at least one key")
        current = {
            "mutations_enabled": self.config.mutations_enabled,
            "http_rate_limit_per_minute": self.config.http_rate_limit_per_minute,
            "http_max_request_bytes": self.config.http_max_request_bytes,
            "enforce_https": self.config.enforce_https,
            "http_nonce_replay_window_seconds": self.config.http_nonce_replay_window_seconds,
            "max_list_limit": self.config.max_list_limit,
            "max_graph_nodes": self.config.max_graph_nodes,
            "max_graph_links": self.config.max_graph_links,
            "max_citation_matches": self.config.max_citation_matches,
            "max_why_evidence_items": self.config.max_why_evidence_items,
        }
        updated = dict(current)
        if "mutations_enabled" in patch:
            updated["mutations_enabled"] = bool(patch.get("mutations_enabled"))
        if "http_rate_limit_per_minute" in patch:
            updated["http_rate_limit_per_minute"] = max(1, int(patch.get("http_rate_limit_per_minute") or 1))
        if "http_max_request_bytes" in patch:
            updated["http_max_request_bytes"] = max(1024, int(patch.get("http_max_request_bytes") or 1024))
        if "enforce_https" in patch:
            updated["enforce_https"] = bool(patch.get("enforce_https"))
        if "http_nonce_replay_window_seconds" in patch:
            updated["http_nonce_replay_window_seconds"] = max(0, int(patch.get("http_nonce_replay_window_seconds") or 0))
        if "max_list_limit" in patch:
            updated["max_list_limit"] = max(1, int(patch.get("max_list_limit") or 1))
        if "max_graph_nodes" in patch:
            updated["max_graph_nodes"] = max(1, int(patch.get("max_graph_nodes") or 1))
        if "max_graph_links" in patch:
            updated["max_graph_links"] = max(1, int(patch.get("max_graph_links") or 1))
        if "max_citation_matches" in patch:
            updated["max_citation_matches"] = max(1, int(patch.get("max_citation_matches") or 1))
        if "max_why_evidence_items" in patch:
            updated["max_why_evidence_items"] = max(1, int(patch.get("max_why_evidence_items") or 1))
        dry_run = bool(args.get("dry_run"))
        if not dry_run:
            self.config.mutations_enabled = bool(updated["mutations_enabled"])
            self.config.http_rate_limit_per_minute = int(updated["http_rate_limit_per_minute"])
            self.config.http_max_request_bytes = int(updated["http_max_request_bytes"])
            self.config.enforce_https = bool(updated["enforce_https"])
            self.config.http_nonce_replay_window_seconds = int(updated["http_nonce_replay_window_seconds"])
            self.config.max_list_limit = int(updated["max_list_limit"])
            self.config.max_graph_nodes = int(updated["max_graph_nodes"])
            self.config.max_graph_links = int(updated["max_graph_links"])
            self.config.max_citation_matches = int(updated["max_citation_matches"])
            self.config.max_why_evidence_items = int(updated["max_why_evidence_items"])
        return {"ok": True, "applied": not dry_run, "policy": updated}

    def _clip_text(self, value: Any, *, max_chars: int | None = None) -> str:
        text = str(value or "").strip()
        limit = int(max_chars if max_chars is not None else self.config.max_text_chars)
        if len(text) <= limit:
            return text
        if limit <= 1:
            return text[:limit]
        return f"{text[: limit - 1]}…"

    def _episode_summary(self, row: Mapping[str, Any]) -> dict[str, Any]:
        topic_tags = _normalize_string_list(row.get("topic_tags"), max_items=24, max_chars=80)
        tags = _normalize_string_list(topic_tags + _normalize_string_list(row.get("tags"), max_items=24, max_chars=80), max_items=24, max_chars=80)
        return {
            "episode_id": str(row.get("episode_id") or "").strip(),
            "title": self._clip_text(row.get("title"), max_chars=160),
            "summary": self._clip_text(row.get("summary"), max_chars=self.config.max_text_chars),
            "status": str(row.get("promotion_status") or "approved").strip().lower() or "approved",
            "tags": tags,
            "actors": _normalize_string_list(row.get("actors"), max_items=20, max_chars=80),
            "topic_tags": topic_tags,
            "updated_at": str(row.get("updated_at") or row.get("timestamp_end") or row.get("generated_at") or "").strip(),
        }

    def _episode_detail(self, row: Mapping[str, Any]) -> dict[str, Any]:
        summary = self._episode_summary(row)
        summary.update(
            {
                "domain": str(row.get("domain") or "").strip(),
                "source_id": str(row.get("source_id") or "").strip(),
                "day_key": str(row.get("day_key") or "").strip(),
                "timestamp_start": str(row.get("timestamp_start") or "").strip(),
                "timestamp_end": str(row.get("timestamp_end") or "").strip(),
                "cue_terms": _normalize_string_list(row.get("cue_terms"), max_items=40, max_chars=80),
                "citations": _normalize_string_list(row.get("citations"), max_items=40, max_chars=120),
                "linked_atom_ids": _normalize_string_list(row.get("linked_atom_ids"), max_items=60, max_chars=120),
                "promotion_reason": self._clip_text(row.get("promotion_reason"), max_chars=200),
                "confidence": float(row.get("confidence") or 0.0),
                "evidence_strength": float(row.get("evidence_strength") or 0.0),
                "retrieval_weight": float(row.get("retrieval_weight") or 0.0),
            }
        )
        return summary

    @staticmethod
    def _card_atom_id(card: Mapping[str, Any]) -> str:
        atom_id = str(card.get("atom_id") or "").strip()
        if atom_id:
            return atom_id
        card_id = str(card.get("card_id") or "").strip()
        if card_id.startswith("card_"):
            return card_id[5:]
        return card_id

    def _atom_summary_from_card(self, card: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "atom_id": self._card_atom_id(card),
            "card_id": str(card.get("card_id") or "").strip(),
            "kind": str(card.get("kind") or "").strip(),
            "status": str(card.get("atom_status") or "").strip(),
            "excerpt": self._clip_text(card.get("summary"), max_chars=self.config.max_text_chars),
            "citations": _normalize_string_list(card.get("citations"), max_items=24, max_chars=120),
            "citation_count": int(card.get("citation_count") or 0),
            "contradiction": bool(card.get("contradiction")),
            "confidence": float(card.get("confidence") or 0.0),
            "evidence_strength": float(card.get("evidence_strength") or 0.0),
            "retrieval_weight": float(card.get("retrieval_weight") or 0.0),
            "updated_at": str(card.get("updated_at") or "").strip(),
        }

    def _sanitize_source_refs(self, value: Any) -> list[dict[str, Any]]:
        rows = list(value) if isinstance(value, list) else []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            out.append(
                {
                    "source_id": str(row.get("source_id") or "").strip(),
                    "message_id": str(row.get("message_id") or "").strip(),
                    "timestamp": str(row.get("timestamp") or "").strip(),
                }
            )
            if len(out) >= 40:
                break
        return out

    def _sanitize_graph_links(self, value: Any, *, max_items: int) -> list[dict[str, Any]]:
        rows = list(value) if isinstance(value, list) else []
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            source = str(row.get("source") or "").strip()
            target = str(row.get("target") or "").strip()
            kind = str(row.get("kind") or "").strip()
            if not source or not target:
                continue
            key = (source, target, kind)
            if key in seen:
                continue
            seen.add(key)
            out.append({"source": source, "target": target, "kind": kind})
            if len(out) >= max_items:
                break
        return out

    def _sanitize_atom_payload(self, atom: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "atom_id": str(atom.get("atom_id") or "").strip(),
            "canonical_text": self._clip_text(atom.get("canonical_text"), max_chars=self.config.max_text_chars),
            "status": str(atom.get("status") or "").strip(),
            "entities": _normalize_string_list(atom.get("entities"), max_items=30, max_chars=80),
            "topics": _normalize_string_list(atom.get("topics"), max_items=30, max_chars=80),
            "confidence": float(atom.get("confidence") or 0.0),
            "salience": float(atom.get("salience") or 0.0),
            "updated_at": str(atom.get("updated_at") or "").strip(),
            "source_refs": self._sanitize_source_refs(atom.get("source_refs")),
        }

    def _sanitize_provenance_events(self, value: Any) -> list[dict[str, Any]]:
        rows = list(value) if isinstance(value, list) else []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            out.append(
                {
                    "event_id": str(row.get("event_id") or "").strip(),
                    "kind": str(row.get("event_kind") or row.get("kind") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "reason_code": str(row.get("reason_code") or "").strip(),
                }
            )
            if len(out) >= 40:
                break
        return out

    @staticmethod
    def _next_hop_key(row: Mapping[str, Any]) -> tuple[str, str]:
        anchor_type = str(row.get("anchor_type") or "unknown").strip().lower() or "unknown"
        anchor_id = str(row.get("anchor_id") or "").strip().lower()
        if not anchor_id:
            anchor_id = str(row.get("label") or "").strip().lower()
        return anchor_type, anchor_id

    def _dedupe_next_hops(self, rows: list[Mapping[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        chosen: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            key = self._next_hop_key(row)
            if not key[1]:
                continue
            score = float(row.get("score") or 0.0)
            confidence = float(row.get("confidence") or 0.0)
            candidate = {
                "anchor_id": str(row.get("anchor_id") or "").strip(),
                "label": self._clip_text(row.get("label"), max_chars=120),
                "anchor_type": str(row.get("anchor_type") or "unknown").strip(),
                "score": score,
                "confidence": confidence,
                "preferred_action": str(row.get("preferred_action") or "").strip(),
            }
            existing = chosen.get(key)
            if existing is None:
                chosen[key] = candidate
                continue
            current_rank = (
                float(existing.get("score") or 0.0),
                float(existing.get("confidence") or 0.0),
                str(existing.get("label") or "").lower(),
            )
            candidate_rank = (
                score,
                confidence,
                str(candidate.get("label") or "").lower(),
            )
            if candidate_rank > current_rank:
                chosen[key] = candidate
        deduped = list(chosen.values())
        deduped.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                float(item.get("confidence") or 0.0),
                str(item.get("label") or "").lower(),
            ),
            reverse=True,
        )
        return deduped[:limit]

    def _anchor_evidence_sentence(self, value: Any, *, max_chars: int = 220) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = re.sub(r"^#+\s*", "", cleaned)
        cleaned = re.sub(r"^(memory|event|relationship)\s+summary:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip("`*|-: ")
        if not cleaned:
            return ""
        words = cleaned.split()
        if len(words) > 24:
            cleaned = " ".join(words[:24])
        cleaned = self._clip_text(cleaned, max_chars=max_chars)
        if cleaned and cleaned[-1] not in ".!?":
            cleaned = f"{cleaned}."
        return cleaned

    def _anchor_summary_candidate_score(self, text: str, *, label: str, source_kind: str) -> tuple[float, int, int]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return (-1.0, 0, 0)
        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9']+", cleaned.lower())
            if token
            not in {
                "a",
                "an",
                "and",
                "are",
                "as",
                "at",
                "for",
                "from",
                "i",
                "in",
                "is",
                "it",
                "its",
                "of",
                "on",
                "or",
                "that",
                "the",
                "this",
                "to",
                "was",
                "we",
                "were",
                "with",
                "you",
            }
        ]
        informative_count = len(tokens)
        label_tokens = {token for token in re.findall(r"[A-Za-z0-9']+", str(label or "").lower()) if len(token) >= 3}
        label_hits = len(label_tokens.intersection(tokens))
        copula_bonus = 0.12 if re.search(r"\b(is|was|are|were|became|becomes|remains|means)\b", cleaned, flags=re.IGNORECASE) else 0.0
        connected_bonus = 0.08 if source_kind == "connected" else 0.0
        exclaim_penalty = min(0.20, 0.05 * cleaned.count("!"))
        laughter_penalty = 0.22 if re.search(r"\b(?:ha){2,}|lol|lmao\b", cleaned, flags=re.IGNORECASE) else 0.0
        uppercase_penalty = 0.16 if len(cleaned) >= 12 and cleaned.upper() == cleaned else 0.0
        score = min(0.30, 0.02 * informative_count) + min(0.18, 0.09 * label_hits) + copula_bonus + connected_bonus
        score -= exclaim_penalty + laughter_penalty + uppercase_penalty
        return score, informative_count, -len(cleaned)

    def _anchor_summary_text(
        self,
        *,
        label: str,
        snippets: list[Mapping[str, Any]],
        connected: list[Mapping[str, Any]],
        next_hops: list[Mapping[str, Any]],
    ) -> str:
        candidates: list[tuple[str, str]] = []
        for row in snippets:
            sentence = self._anchor_evidence_sentence(row.get("snippet"), max_chars=220)
            if sentence:
                candidates.append((sentence, "snippet"))
        for row in connected:
            sentence = self._anchor_evidence_sentence(row.get("summary"), max_chars=220)
            if sentence:
                candidates.append((sentence, "connected"))

        lead = ""
        if candidates:
            lead = max(
                candidates,
                key=lambda item: self._anchor_summary_candidate_score(item[0], label=label, source_kind=item[1]),
            )[0]
        if not lead and candidates:
            lead = candidates[0][0]
        if not lead:
            lead = "Insufficient support for a grounded brief."

        labels: list[str] = []
        seen_labels: set[str] = set()
        for row in next_hops[:3]:
            hop_label = self._clip_text(row.get("label"), max_chars=60)
            if not hop_label:
                continue
            normalized = hop_label.lower()
            if normalized == str(label or "").strip().lower() or normalized in seen_labels:
                continue
            seen_labels.add(normalized)
            labels.append(hop_label)
        if labels:
            if len(labels) == 1:
                lead = f"{lead} Linked to {labels[0]}."
            elif len(labels) == 2:
                lead = f"{lead} Linked to {labels[0]} and {labels[1]}."
            else:
                lead = f"{lead} Linked to {labels[0]}, {labels[1]}, and {labels[2]}."
        return self._clip_text(f"{label}: {lead}".strip(), max_chars=320)

    def _build_anchor_brief_payload(self, *, anchor_id: str, anchor_type: str, limit: int) -> dict[str, Any]:
        expanded = self._tool_explore_expand_anchor(
            {
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "limit": max(4, limit),
                "hop_depth": 1,
                "mode": "compact",
                "include_next_hops": True,
            }
        )
        peek = self._tool_explore_peek(
            {
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "limit": max(4, limit),
                "mode": "compact",
            }
        )
        anchor = dict(expanded.get("anchor") or peek.get("anchor") or {})
        snippets = [row for row in list(peek.get("snippets") or []) if isinstance(row, Mapping)]
        connected = [row for row in list(expanded.get("connected_atoms") or []) if isinstance(row, Mapping)]
        next_hops = [row for row in list(expanded.get("next_hops") or []) if isinstance(row, Mapping)]
        evidence_confidence: list[float] = []
        citation_refs: list[str] = []
        for row in snippets[:limit]:
            evidence_confidence.append(float(row.get("confidence") or 0.0))
            source_ref = str(row.get("source_ref") or "").strip()
            if source_ref and source_ref not in citation_refs:
                citation_refs.append(source_ref)
        mean_confidence = sum(evidence_confidence) / len(evidence_confidence) if evidence_confidence else 0.0
        lead_label = self._clip_text(anchor.get("label") or anchor_id, max_chars=120)
        summary = self._anchor_summary_text(
            label=lead_label,
            snippets=snippets,
            connected=connected,
            next_hops=next_hops,
        )
        return {
            "status": str(expanded.get("status") or peek.get("status") or "insufficient_support").strip().lower(),
            "anchor": anchor,
            "summary": summary,
            "confidence": round(float(mean_confidence), 4),
            "top_snippets": snippets[:limit],
            "next_hops": next_hops[:limit],
            "citation_refs": citation_refs[:limit],
            "guardrails": dict(expanded.get("guardrails") or peek.get("guardrails") or {}),
        }

    def _shared_language_keys_compact(self, value: Any) -> list[dict[str, Any]]:
        rows = list(value) if isinstance(value, list) else []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            out.append(
                {
                    "key_id": str(row.get("key_id") or "").strip(),
                    "phrase": self._clip_text(row.get("phrase"), max_chars=80),
                    "confidence": float(row.get("confidence") or 0.0),
                }
            )
            if len(out) >= 12:
                break
        return out

    def _neighbor_summaries(
        self,
        *,
        relation_map: Mapping[str, set[str]],
        limit: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for neighbor_id in list(relation_map.keys())[:limit]:
            try:
                payload = self.api_client.get_json(f"/api/memory/atom/{quote(neighbor_id, safe='')}")
            except Exception:
                continue
            atom_raw = payload.get("atom")
            if not isinstance(atom_raw, Mapping):
                continue
            relation_labels = sorted(item for item in relation_map.get(neighbor_id, set()) if item)
            relation_kind = "+".join(relation_labels) if relation_labels else "related"
            rows.append(
                {
                    "atom_id": str(atom_raw.get("atom_id") or neighbor_id).strip(),
                    "relation_kind": relation_kind,
                    "summary": self._clip_text(atom_raw.get("canonical_text"), max_chars=180),
                    "confidence": float(atom_raw.get("confidence") or 0.0),
                }
            )
        return rows

    def _require_mutations_enabled(self) -> None:
        if not bool(self.config.mutations_enabled):
            raise MCPRequestError(-32002, "mutation tools are disabled by server policy")

    def _tool_memory_list_episodes(self, args: dict[str, Any]) -> dict[str, Any]:
        q = str(args.get("q") or "").strip()
        status = str(args.get("status") or "all").strip().lower() or "all"
        if status not in {"all", "approved", "disabled"}:
            raise MCPRequestError(-32602, "status must be one of: all, approved, disabled")
        limit = _coerce_int(
            args.get("limit"),
            default=40,
            minimum=1,
            maximum=self.config.max_list_limit,
        )
        offset = _coerce_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000)
        payload = self.api_client.get_json(
            "/api/memory/episodes",
            query={"q": q or None, "status": status},
        )
        rows = [row for row in list(payload.get("episodes") or []) if isinstance(row, Mapping)]
        total = len(rows)
        page_rows = rows[offset : offset + limit]
        episodes = [self._episode_summary(row) for row in page_rows]
        return {
            "episodes": episodes,
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(episodes) < total,
        }

    def _tool_memory_get_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        episode_id = str(args.get("episode_id") or "").strip()
        if not episode_id:
            raise MCPRequestError(-32602, "episode_id is required")
        payload = self.api_client.get_json("/api/memory/episodes", query={"status": "all"})
        rows = [row for row in list(payload.get("episodes") or []) if isinstance(row, Mapping)]
        target = None
        for row in rows:
            if str(row.get("episode_id") or "").strip() == episode_id:
                target = row
                break
        if target is None:
            raise MCPRequestError(-32004, f"episode not found: {episode_id}")
        return {"episode": self._episode_detail(target)}

    def _tool_memory_list_atoms(self, args: dict[str, Any]) -> dict[str, Any]:
        q = str(args.get("q") or "").strip()
        status = str(args.get("status") or "all").strip().lower() or "all"
        kind = str(args.get("kind") or "all").strip().lower() or "all"
        contradiction = str(args.get("contradiction") or "all").strip().lower() or "all"
        view = str(args.get("view") or "default").strip().lower() or "default"
        if view not in {"default", "definition"}:
            view = "default"
        mode = _coerce_mode(args.get("mode"), default="compact")
        default_limit = 8 if view == "definition" else 40
        limit = _coerce_int(
            args.get("limit"),
            default=default_limit,
            minimum=1,
            maximum=self.config.max_list_limit,
        )
        offset = _coerce_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000)
        payload = self.api_client.get_json(
            "/api/memory/cards",
            query={
                "q": q or None,
                "status": status,
                "kind": kind,
                "contradiction": contradiction,
                "limit": limit,
                "offset": offset,
            },
        )
        cards = [row for row in list(payload.get("cards") or []) if isinstance(row, Mapping)]
        if view == "definition":
            rows: list[dict[str, Any]] = []
            top_citations: list[str] = []
            confidences: list[float] = []
            for card in cards:
                citation_refs = _normalize_string_list(card.get("citations"), max_items=6, max_chars=120)
                source_ref = citation_refs[0] if citation_refs else ""
                confidence = float(card.get("confidence") or 0.0)
                confidences.append(confidence)
                for citation in citation_refs:
                    if citation not in top_citations:
                        top_citations.append(citation)
                    if len(top_citations) >= 5:
                        break
                row: dict[str, Any] = {
                    "atom_id": self._card_atom_id(card),
                    "kind": str(card.get("kind") or "").strip(),
                    "status": str(card.get("atom_status") or "").strip(),
                    "snippet": self._clip_text(card.get("summary"), max_chars=180),
                    "confidence": confidence,
                    "citation_count": int(card.get("citation_count") or 0),
                    "source_ref": source_ref,
                }
                if mode == "full":
                    row["excerpt"] = self._clip_text(card.get("summary"), max_chars=self.config.max_text_chars)
                    row["citations"] = citation_refs
                rows.append(row)
            mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            query_term = q or "term"
            lead = str(rows[0].get("snippet") or "").strip() if rows else ""
            summary = f"{query_term}: {lead}" if lead else f"{query_term}: insufficient support for a grounded definition."
            return {
                "view": view,
                "mode": mode,
                "query_term": query_term,
                "definition": {
                    "term": query_term,
                    "summary": self._clip_text(summary, max_chars=320),
                    "confidence": round(float(mean_confidence), 4),
                    "support_count": len(rows),
                    "top_citations": top_citations[:5],
                },
                "atoms": rows,
                "offset": int(payload.get("offset") or offset),
                "limit": int(payload.get("limit") or limit),
                "total": int(payload.get("total") or len(rows)),
                "has_more": bool(payload.get("has_more")),
            }
        atoms = [self._atom_summary_from_card(card) for card in cards]
        return {
            "view": view,
            "atoms": atoms,
            "offset": int(payload.get("offset") or offset),
            "limit": int(payload.get("limit") or limit),
            "total": int(payload.get("total") or len(atoms)),
            "has_more": bool(payload.get("has_more")),
        }

    def _tool_memory_get_atom(self, args: dict[str, Any]) -> dict[str, Any]:
        atom_id = str(args.get("atom_id") or "").strip()
        if not atom_id:
            raise MCPRequestError(-32602, "atom_id is required")
        mode = _coerce_mode(args.get("mode"), default="compact")
        neighbor_limit = _coerce_int(
            args.get("neighbor_limit"),
            default=5,
            minimum=1,
            maximum=12,
        )
        payload = self.api_client.get_json(f"/api/memory/atom/{quote(atom_id, safe='')}")
        atom_raw = payload.get("atom")
        graph_raw = payload.get("graph")
        if not isinstance(atom_raw, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid atom payload")
        graph = dict(graph_raw) if isinstance(graph_raw, Mapping) else {}
        conflicts = _normalize_string_list(graph.get("conflicts"), max_items=60, max_chars=120)
        constellation_neighbors = _normalize_string_list(
            graph.get("constellation_neighbors"),
            max_items=60,
            max_chars=120,
        )
        arc_neighbors = _normalize_string_list(graph.get("arc_neighbors"), max_items=60, max_chars=120)
        relation_map: dict[str, set[str]] = {}
        for neighbor_id in constellation_neighbors:
            relation_map.setdefault(neighbor_id, set()).add("constellation")
        for neighbor_id in arc_neighbors:
            relation_map.setdefault(neighbor_id, set()).add("arc")
        if mode == "full":
            graph_payload: dict[str, Any] = {
                "conflicts": conflicts,
                "constellation_neighbors": constellation_neighbors,
                "arc_neighbors": arc_neighbors,
                "shared_language_keys": list(graph.get("shared_language_keys") or [])[:40],
            }
        else:
            graph_payload = {
                "conflicts": conflicts[:24],
                "neighbor_count": len(relation_map),
                "neighbor_summaries": self._neighbor_summaries(
                    relation_map=relation_map,
                    limit=neighbor_limit,
                ),
                "shared_language_keys": self._shared_language_keys_compact(graph.get("shared_language_keys")),
            }
        return {
            "atom": self._sanitize_atom_payload(atom_raw),
            "provenance_events": self._sanitize_provenance_events(payload.get("provenance_events")),
            "mode": mode,
            "graph": graph_payload,
        }

    def _tool_memory_graph_map(self, args: dict[str, Any]) -> dict[str, Any]:
        q = str(args.get("q") or "").strip()
        status = str(args.get("status") or "all").strip().lower() or "all"
        kind = str(args.get("kind") or "all").strip().lower() or "all"
        contradiction = str(args.get("contradiction") or "all").strip().lower() or "all"
        limit = _coerce_int(
            args.get("limit"),
            default=80,
            minimum=1,
            maximum=self.config.max_graph_nodes,
        )
        payload = self.api_client.get_json(
            "/api/memory/graph-map",
            query={
                "q": q or None,
                "status": status,
                "kind": kind,
                "contradiction": contradiction,
                "limit": limit,
            },
        )
        raw_nodes = [row for row in list(payload.get("nodes") or []) if isinstance(row, Mapping)]
        nodes = [
            {
                "atom_id": str(row.get("atom_id") or "").strip(),
                "card_id": str(row.get("card_id") or "").strip(),
                "kind": str(row.get("kind") or "").strip(),
                "status": str(row.get("atom_status") or "").strip(),
                "summary": self._clip_text(row.get("summary"), max_chars=self.config.max_text_chars),
                "citation_count": int(row.get("citation_count") or 0),
                "contradiction": bool(row.get("contradiction")),
            }
            for row in raw_nodes[: self.config.max_graph_nodes]
        ]
        raw_links = self._sanitize_graph_links(payload.get("links"), max_items=self.config.max_graph_links)
        total = int(payload.get("total") or len(raw_nodes))
        truncated = bool(payload.get("truncated")) or len(raw_nodes) > len(nodes) or len(raw_links) < len(list(payload.get("links") or []))
        return {
            "nodes": nodes,
            "links": raw_links,
            "total": total,
            "truncated": truncated,
            "node_limit": self.config.max_graph_nodes,
            "link_limit": self.config.max_graph_links,
        }

    def _normalize_graph_neighbors_payload(
        self,
        payload: Mapping[str, Any],
        *,
        node_id: str,
        depth: int,
        node_limit: int,
        link_limit: int,
    ) -> dict[str, Any]:
        node_raw = payload.get("node")
        node: dict[str, Any]
        if isinstance(node_raw, Mapping):
            node = dict(node_raw)
        else:
            node = {"atom_id": node_id}
        node_atom_id = str(node.get("atom_id") or node_id).strip() or node_id
        node["atom_id"] = node_atom_id

        neighbors: list[dict[str, Any]] = []
        for row in list(payload.get("neighbors") or []):
            if not isinstance(row, Mapping):
                continue
            atom_id = str(row.get("atom_id") or row.get("node_id") or "").strip()
            if not atom_id or atom_id == node_atom_id:
                continue
            item = dict(row)
            item["atom_id"] = atom_id
            item.setdefault("node_id", atom_id)
            neighbors.append(item)

        links: list[dict[str, Any]] = []
        for row in list(payload.get("links") or []):
            if not isinstance(row, Mapping):
                continue
            source = str(row.get("source") or "").strip()
            target = str(row.get("target") or "").strip()
            kind = str(row.get("kind") or "").strip()
            if not source or not target or not kind:
                continue
            links.append({"source": source, "target": target, "kind": kind})

        truncation_raw = payload.get("truncation")
        truncation = dict(truncation_raw) if isinstance(truncation_raw, Mapping) else {}
        return {
            "node": node,
            "neighbors": neighbors,
            "links": links,
            "depth": int(payload.get("depth") or depth),
            "node_limit": int(payload.get("node_limit") or node_limit),
            "link_limit": int(payload.get("link_limit") or link_limit),
            "requests_used": int(payload.get("requests_used") or 0),
            "truncated": bool(payload.get("truncated")),
            "truncation": truncation,
        }

    def _legacy_graph_neighbors_payload(
        self,
        *,
        node_id: str,
        depth: int,
        node_limit: int,
        link_limit: int,
        include_shared_language: bool,
        include_root_detail: bool,
    ) -> dict[str, Any]:
        requests_used = 0
        pending = [node_id]
        visited_atoms = {node_id}
        neighbors: dict[str, dict[str, Any]] = {}
        links: list[dict[str, Any]] = []
        seen_links: set[tuple[str, str, str]] = set()
        root_atom: Mapping[str, Any] | None = None
        node_limit_hit = False
        link_limit_hit = False
        request_budget_hit = False
        dropped_shared_language = False

        for layer_index in range(depth):
            if not pending:
                break
            next_pending: list[str] = []
            for index, current in enumerate(pending):
                if requests_used >= self.config.max_neighbor_expansion_requests:
                    if index < len(pending):
                        request_budget_hit = True
                    break
                payload = self.api_client.get_json("/api/memory/graph", query={"atom_id": current})
                requests_used += 1
                atom_raw = payload.get("atom")
                if root_atom is None and isinstance(atom_raw, Mapping):
                    root_atom = atom_raw
                for row in list(payload.get("links") or []):
                    if not isinstance(row, Mapping):
                        continue
                    source = str(row.get("source") or "").strip()
                    target = str(row.get("target") or "").strip()
                    kind = str(row.get("kind") or "").strip()
                    neighbor_id = target if source == current else source
                    if not source or not target or not kind or neighbor_id == node_id:
                        continue
                    if neighbor_id.startswith("slk:"):
                        if include_shared_language:
                            # Legacy graph surfaces expose shared-language key nodes rather than
                            # the concrete atom neighbors returned by the native endpoint.
                            dropped_shared_language = True
                        continue
                    link_key = _canonical_graph_link_key(source, target, kind)
                    is_new_link = link_key not in seen_links
                    if is_new_link and len(links) >= self.config.max_graph_links:
                        link_limit_hit = True
                        continue
                    if neighbor_id not in neighbors:
                        if len(neighbors) >= node_limit:
                            node_limit_hit = True
                            continue
                        neighbors[neighbor_id] = {
                            "atom_id": neighbor_id,
                            "node_id": neighbor_id,
                            "distance": layer_index + 1,
                            "via_edge_kind": kind,
                        }
                    if neighbor_id not in neighbors:
                        continue
                    if is_new_link:
                        seen_links.add(link_key)
                        links.append({"source": source, "target": target, "kind": kind})
                    if neighbor_id not in visited_atoms:
                        visited_atoms.add(neighbor_id)
                        next_pending.append(neighbor_id)
            pending = next_pending
            if request_budget_hit:
                break
            if requests_used >= self.config.max_neighbor_expansion_requests and pending:
                request_budget_hit = True
                break

        neighbor_rows = list(neighbors.values())[:node_limit]
        allowed_ids = {node_id}.union(str(row.get("atom_id") or "") for row in neighbor_rows)
        filtered_links = [
            row
            for row in links
            if str(row.get("source") or "") in allowed_ids and str(row.get("target") or "") in allowed_ids
        ]
        node_payload = self._sanitize_atom_payload(root_atom or {"atom_id": node_id}) if include_root_detail else {"atom_id": node_id}
        return {
            "node": node_payload,
            "neighbors": neighbor_rows,
            "links": filtered_links[:link_limit],
            "depth": depth,
            "node_limit": node_limit,
            "link_limit": link_limit,
            "requests_used": requests_used,
            "truncated": (
                node_limit_hit
                or link_limit_hit
                or len(filtered_links) > link_limit
                or request_budget_hit
            ),
            "truncation": {
                "node_limit_hit": node_limit_hit,
                "link_limit_hit": link_limit_hit or len(filtered_links) > link_limit,
                "request_budget_hit": request_budget_hit,
                "dropped_shared_language": dropped_shared_language,
            },
        }

    def _tool_memory_graph_neighbors(self, args: dict[str, Any]) -> dict[str, Any]:
        node_id = str(args.get("node_id") or "").strip()
        if not node_id:
            raise MCPRequestError(-32602, "node_id is required")
        depth = _coerce_int(args.get("depth"), default=1, minimum=1, maximum=2)
        node_limit = _coerce_int(
            args.get("node_limit", args.get("limit")),
            default=60,
            minimum=1,
            maximum=self.config.max_graph_nodes,
        )
        link_limit = _coerce_int(
            args.get("link_limit"),
            default=min(120, self.config.max_graph_links),
            minimum=1,
            maximum=self.config.max_graph_links,
        )
        include_shared_language = _coerce_bool(args.get("include_shared_language"), default=False)
        include_root_detail = _coerce_bool(args.get("include_root_detail"), default=True)

        request_json = getattr(self.api_client, "request_json", None)
        if callable(request_json):
            try:
                status_code, payload = request_json(
                    "GET",
                    "/api/memory/graph/neighbors",
                    query={
                        "atom_id": node_id,
                        "depth": depth,
                        "limit": node_limit,
                        "node_limit": node_limit,
                        "link_limit": link_limit,
                        "include_shared_language": str(include_shared_language).lower(),
                        "include_root_detail": str(include_root_detail).lower(),
                    },
                    allow_error_status=True,
                )
            except RuntimeApiError as exc:
                if exc.status_code not in {404, 405, 501}:
                    raise
            else:
                if status_code < 400:
                    return self._normalize_graph_neighbors_payload(
                        payload,
                        node_id=node_id,
                        depth=depth,
                        node_limit=node_limit,
                        link_limit=link_limit,
                    )
                if status_code not in {404, 405, 501}:
                    detail = str(payload.get("error") or "").strip()
                    raise RuntimeApiError("runtime_api_http_error", status_code=status_code, detail=detail)
        return self._legacy_graph_neighbors_payload(
            node_id=node_id,
            depth=depth,
            node_limit=node_limit,
            link_limit=link_limit,
            include_shared_language=include_shared_language,
            include_root_detail=include_root_detail,
        )

    def _tool_memory_quicknote_status(self, args: dict[str, Any]) -> dict[str, Any]:
        assistant_id = str(args.get("assistant_id") or "").strip() or None
        session_id = str(args.get("session_id") or "").strip() or None
        payload = self.api_client.get_json(
            "/api/memory/quicknote/status",
            query={
                "assistant_id": assistant_id,
                "session_id": session_id,
            },
        )
        status = payload.get("status")
        if not isinstance(status, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid quicknote status payload")
        return {
            "status": dict(status),
            "policy": dict(payload.get("policy") or {}),
            "config": dict(payload.get("config") or {}),
        }

    def _tool_memory_quicknote_propose(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        text = str(args.get("text") or "").strip()
        if not text:
            raise MCPRequestError(-32602, "text is required")
        payload: dict[str, Any] = {
            "text": text,
        }
        assistant_id = str(args.get("assistant_id") or "").strip()
        session_id = str(args.get("session_id") or "").strip()
        importance = str(args.get("importance") or "").strip().lower()
        context_pressure = str(args.get("context_pressure") or "").strip().lower()
        tags = _normalize_string_list(args.get("tags"), max_items=12, max_chars=64)
        if assistant_id:
            payload["assistant_id"] = assistant_id
        if session_id:
            payload["session_id"] = session_id
        if importance:
            payload["importance"] = importance
        if context_pressure:
            payload["context_pressure"] = context_pressure
        if tags:
            payload["tags"] = tags
        response = self.api_client.post_json("/api/memory/quicknote/propose", payload)
        return dict(response)

    def _tool_memory_quicknote_propose_batch(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        notes_raw = args.get("notes")
        if not isinstance(notes_raw, list) or not notes_raw:
            raise MCPRequestError(-32602, "notes must be a non-empty array")
        notes: list[dict[str, Any]] = []
        for row in notes_raw[: self.config.max_list_limit]:
            if not isinstance(row, Mapping):
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            item: dict[str, Any] = {"text": text}
            importance = str(row.get("importance") or "").strip().lower()
            if importance:
                item["importance"] = importance
            tags = _normalize_string_list(row.get("tags"), max_items=12, max_chars=64)
            if tags:
                item["tags"] = tags
            notes.append(item)
        if not notes:
            raise MCPRequestError(-32602, "notes must include at least one item with text")
        payload: dict[str, Any] = {"notes": notes}
        assistant_id = str(args.get("assistant_id") or "").strip()
        session_id = str(args.get("session_id") or "").strip()
        importance = str(args.get("importance") or "").strip().lower()
        context_pressure = str(args.get("context_pressure") or "").strip().lower()
        tags = _normalize_string_list(args.get("tags"), max_items=12, max_chars=64)
        if assistant_id:
            payload["assistant_id"] = assistant_id
        if session_id:
            payload["session_id"] = session_id
        if importance:
            payload["importance"] = importance
        if context_pressure:
            payload["context_pressure"] = context_pressure
        if tags:
            payload["tags"] = tags
        response = self.api_client.post_json("/api/memory/quicknote/propose-batch", payload)
        return dict(response)

    def _tool_memory_quicknote_flush(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload: dict[str, Any] = {}
        assistant_id = str(args.get("assistant_id") or "").strip()
        session_id = str(args.get("session_id") or "").strip()
        reason = str(args.get("reason") or "").strip().lower()
        if assistant_id:
            payload["assistant_id"] = assistant_id
        if session_id:
            payload["session_id"] = session_id
        if reason:
            payload["reason"] = reason
        response = self.api_client.post_json("/api/memory/quicknote/flush", payload)
        return dict(response)

    def _tool_explore_start_here(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _coerce_int(args.get("limit"), default=12, minimum=1, maximum=self.config.max_list_limit)
        payload = self.api_client.get_json("/api/explore/start-here", query={"limit": limit})
        buckets_raw = dict(payload.get("buckets") or {}) if isinstance(payload.get("buckets"), Mapping) else {}
        buckets: dict[str, list[dict[str, Any]]] = {}
        for key in ("people", "projects", "topics", "arcs", "unresolved"):
            rows = [row for row in list(buckets_raw.get(key) or []) if isinstance(row, Mapping)]
            buckets[key] = [
                {
                    "anchor_id": str(row.get("anchor_id") or "").strip(),
                    "label": self._clip_text(row.get("label"), max_chars=120),
                    "anchor_type": str(row.get("anchor_type") or "unknown").strip(),
                    "score": float(row.get("score") or 0.0),
                    "confidence": float(row.get("confidence") or 0.0),
                    "support_count": int(row.get("support_count") or 0),
                    "preferred_action": str(row.get("preferred_action") or "").strip(),
                }
                for row in rows
            ]
        return {
            "status": str(payload.get("status") or "insufficient_support").strip().lower(),
            "buckets": buckets,
            "stats": dict(payload.get("stats") or {}),
            "guardrails": dict(payload.get("guardrails") or {}),
        }

    def _tool_explore_orient(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _coerce_int(args.get("limit"), default=5, minimum=1, maximum=12)
        payload = self.api_client.get_json("/api/explore/start-here", query={"limit": max(12, limit)})
        buckets_raw = dict(payload.get("buckets") or {}) if isinstance(payload.get("buckets"), Mapping) else {}

        def _bucket(name: str, *, cap: int) -> list[dict[str, Any]]:
            rows = [row for row in list(buckets_raw.get(name) or []) if isinstance(row, Mapping)]
            out: list[dict[str, Any]] = []
            for row in rows[:cap]:
                out.append(
                    {
                        "anchor_id": str(row.get("anchor_id") or "").strip(),
                        "label": self._clip_text(row.get("label"), max_chars=120),
                        "anchor_type": str(row.get("anchor_type") or "unknown").strip(),
                        "score": float(row.get("score") or 0.0),
                        "confidence": float(row.get("confidence") or 0.0),
                        "support_count": int(row.get("support_count") or 0),
                        "preferred_action": str(row.get("preferred_action") or "").strip(),
                    }
                )
            return out

        people = _bucket("people", cap=limit)
        projects = _bucket("projects", cap=limit)
        topics = _bucket("topics", cap=limit)
        unresolved = _bucket("unresolved", cap=limit)
        combined = people + projects + topics
        combined.sort(
            key=lambda row: (
                float(row.get("score") or 0.0),
                float(row.get("confidence") or 0.0),
                int(row.get("support_count") or 0),
            ),
            reverse=True,
        )
        what_matters = combined[:limit]
        brief_cap = min(3, len(what_matters))
        anchor_briefs: list[dict[str, Any]] = []
        brief_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for row in what_matters[:brief_cap]:
            anchor_id = str(row.get("anchor_id") or "").strip()
            anchor_type = str(row.get("anchor_type") or "unknown").strip().lower() or "unknown"
            if not anchor_id:
                continue
            brief_payload = self._build_anchor_brief_payload(anchor_id=anchor_id, anchor_type=anchor_type, limit=2)
            brief_summary = str(brief_payload.get("summary") or "").strip()
            brief_row = {
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "label": self._clip_text(row.get("label"), max_chars=120),
                "brief": brief_summary,
                "confidence": float(brief_payload.get("confidence") or 0.0),
                "citation_refs": list(brief_payload.get("citation_refs") or []),
            }
            anchor_briefs.append(brief_row)
            brief_by_key[(anchor_type, anchor_id)] = brief_row

        def _attach_briefs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for row in rows:
                updated = dict(row)
                key = (
                    str(updated.get("anchor_type") or "unknown").strip().lower() or "unknown",
                    str(updated.get("anchor_id") or "").strip(),
                )
                brief_row = brief_by_key.get(key)
                if brief_row is not None:
                    updated["brief"] = str(brief_row.get("brief") or "").strip()
                out.append(updated)
            return out

        people = _attach_briefs(people)
        projects = _attach_briefs(projects)
        topics = _attach_briefs(topics)
        what_matters = _attach_briefs(what_matters)
        session_focus: dict[str, Any] = {}
        try:
            sessions_payload = self.api_client.get_json("/api/chat/sessions")
            session_rows = [row for row in list(sessions_payload.get("sessions") or []) if isinstance(row, Mapping)]
            if session_rows:
                top = session_rows[0]
                session_focus = {
                    "session_id": str(top.get("session_id") or "").strip(),
                    "label": self._clip_text(top.get("label"), max_chars=120),
                    "updated_at": str(top.get("updated_at") or "").strip(),
                    "turn_count": int(top.get("turn_count") or 0),
                }
        except Exception:
            session_focus = {}
        summary_parts: list[str] = []
        if anchor_briefs:
            summary_parts.append(
                "Anchor briefs: "
                + " ".join(
                    self._clip_text(str(row.get("brief") or "").strip(), max_chars=180)
                    for row in anchor_briefs[:2]
                    if str(row.get("brief") or "").strip()
                )
            )
        elif what_matters:
            labels = ", ".join(str(row.get("label") or "") for row in what_matters[:3] if str(row.get("label") or "").strip())
            if labels:
                summary_parts.append(f"Top anchors: {labels}.")
        if unresolved:
            unresolved_labels = ", ".join(str(row.get("label") or "") for row in unresolved[:2] if str(row.get("label") or "").strip())
            if unresolved_labels:
                summary_parts.append(f"Open threads: {unresolved_labels}.")
        if session_focus:
            summary_parts.append(f"Recent focus: {str(session_focus.get('label') or '').strip()}.")
        summary = " ".join(part for part in summary_parts if part).strip() or "Insufficient support for orientation summary."
        return {
            "status": str(payload.get("status") or "insufficient_support").strip().lower(),
            "summary": self._clip_text(summary, max_chars=320),
            "what_matters_now": what_matters,
            "people": people,
            "projects": projects,
            "topics": topics,
            "unresolved": unresolved,
            "anchor_briefs": anchor_briefs,
            "recent_focus": session_focus,
            "stats": dict(payload.get("stats") or {}),
            "guardrails": dict(payload.get("guardrails") or {}),
        }

    def _tool_explore_expand_anchor(self, args: dict[str, Any]) -> dict[str, Any]:
        anchor_id = str(args.get("anchor_id") or "").strip()
        if not anchor_id:
            raise MCPRequestError(-32602, "anchor_id is required")
        anchor_type = str(args.get("anchor_type") or "topic").strip().lower() or "topic"
        if anchor_type not in {"person", "project", "topic", "event", "unknown"}:
            anchor_type = "topic"
        limit = _coerce_int(args.get("limit"), default=10, minimum=1, maximum=self.config.max_list_limit)
        hop_depth = _coerce_int(args.get("hop_depth"), default=1, minimum=1, maximum=3)
        mode = _coerce_mode(args.get("mode"), default="compact")
        include_next_hops_raw = args.get("include_next_hops")
        include_next_hops = True if include_next_hops_raw is None else bool(include_next_hops_raw)
        payload = self.api_client.get_json(
            "/api/explore/expand",
            query={
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "limit": limit,
                "hop_depth": hop_depth,
            },
        )
        connected = [row for row in list(payload.get("connected_atoms") or []) if isinstance(row, Mapping)]
        next_hops = [row for row in list(payload.get("next_hops") or []) if isinstance(row, Mapping)]
        if mode == "full":
            connected_rows = [
                {
                    "atom_id": str(row.get("atom_id") or "").strip(),
                    "card_id": str(row.get("card_id") or "").strip(),
                    "summary": self._clip_text(row.get("summary"), max_chars=220),
                    "confidence": float(row.get("confidence") or 0.0),
                    "contradiction": bool(row.get("contradiction")),
                    "source_ref": str(row.get("source_ref") or "").strip(),
                }
                for row in connected
            ]
        else:
            connected_rows = [
                {
                    "atom_id": str(row.get("atom_id") or "").strip(),
                    "summary": self._clip_text(row.get("summary"), max_chars=160),
                    "confidence": float(row.get("confidence") or 0.0),
                    "source_ref": str(row.get("source_ref") or "").strip(),
                }
                for row in connected
            ]
        deduped_hops = self._dedupe_next_hops(next_hops, limit=limit) if include_next_hops else []
        return {
            "status": str(payload.get("status") or "insufficient_support").strip().lower(),
            "mode": mode,
            "anchor": dict(payload.get("anchor") or {}),
            "connected_atoms": connected_rows,
            "next_hops": deduped_hops,
            "truncated": bool(payload.get("truncated")),
            "next_hop_count": len(deduped_hops),
            "guardrails": dict(payload.get("guardrails") or {}),
        }

    def _tool_explore_peek(self, args: dict[str, Any]) -> dict[str, Any]:
        anchor_id = str(args.get("anchor_id") or "").strip()
        if not anchor_id:
            raise MCPRequestError(-32602, "anchor_id is required")
        anchor_type = str(args.get("anchor_type") or "topic").strip().lower() or "topic"
        if anchor_type not in {"person", "project", "topic", "event", "unknown"}:
            anchor_type = "topic"
        limit = _coerce_int(args.get("limit"), default=5, minimum=1, maximum=12)
        mode = _coerce_mode(args.get("mode"), default="compact")
        payload = self.api_client.get_json(
            "/api/explore/peek",
            query={
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "limit": limit,
            },
        )
        snippets = [row for row in list(payload.get("snippets") or []) if isinstance(row, Mapping)]
        if mode == "full":
            snippet_rows = [
                {
                    "atom_id": str(row.get("atom_id") or "").strip(),
                    "card_id": str(row.get("card_id") or "").strip(),
                    "snippet": self._clip_text(row.get("snippet"), max_chars=220),
                    "raw_excerpt": self._clip_text(row.get("raw_excerpt"), max_chars=320),
                    "confidence": float(row.get("confidence") or 0.0),
                    "source_id": str(row.get("source_id") or "").strip(),
                    "source_ref": str(row.get("source_ref") or "").strip(),
                }
                for row in snippets
            ]
        else:
            snippet_rows = [
                {
                    "atom_id": str(row.get("atom_id") or "").strip(),
                    "card_id": str(row.get("card_id") or "").strip(),
                    "snippet": self._clip_text(row.get("snippet"), max_chars=220),
                    "confidence": float(row.get("confidence") or 0.0),
                    "source_id": str(row.get("source_id") or "").strip(),
                    "source_ref": str(row.get("source_ref") or "").strip(),
                }
                for row in snippets
            ]
        return {
            "status": str(payload.get("status") or "insufficient_support").strip().lower(),
            "mode": mode,
            "anchor": dict(payload.get("anchor") or {}),
            "snippets": snippet_rows,
            "count": len(snippet_rows),
            "truncated": bool(payload.get("truncated")),
            "guardrails": dict(payload.get("guardrails") or {}),
        }

    def _tool_explore_anchor_brief(self, args: dict[str, Any]) -> dict[str, Any]:
        anchor_id = str(args.get("anchor_id") or "").strip()
        if not anchor_id:
            raise MCPRequestError(-32602, "anchor_id is required")
        anchor_type = str(args.get("anchor_type") or "topic").strip().lower() or "topic"
        if anchor_type not in {"person", "project", "topic", "event", "unknown"}:
            anchor_type = "topic"
        limit = _coerce_int(args.get("limit"), default=3, minimum=1, maximum=6)
        return self._build_anchor_brief_payload(anchor_id=anchor_id, anchor_type=anchor_type, limit=limit)

    def _tool_explore_get_preferences(self, args: dict[str, Any]) -> dict[str, Any]:
        _ = args
        payload = self.api_client.get_json("/api/explore/preferences")
        rows = [row for row in list(payload.get("preferences") or []) if isinstance(row, Mapping)]
        return {
            "preferences": [
                {
                    "anchor_id": str(row.get("anchor_id") or "").strip(),
                    "anchor_type": str(row.get("anchor_type") or "topic").strip(),
                    "action": str(row.get("action") or "").strip(),
                    "weight": float(row.get("weight") or 0.0),
                    "updated_at": str(row.get("updated_at") or "").strip(),
                }
                for row in rows
            ],
            "count": int(payload.get("count") or len(rows)),
        }

    def _tool_explore_whats_new(self, args: dict[str, Any]) -> dict[str, Any]:
        assistant_id = str(args.get("assistant_id") or "").strip() or None
        session_id = str(args.get("session_id") or "").strip() or None
        peek_only = bool(args.get("peek_only")) if "peek_only" in args else None
        limit = _coerce_int(args.get("limit"), default=8, minimum=1, maximum=40)
        payload = self.api_client.get_json(
            "/api/explore/whats-new",
            query={
                "assistant_id": assistant_id,
                "session_id": session_id,
                "peek_only": peek_only,
                "limit": limit,
            },
        )
        cursor = payload.get("cursor")
        changes = payload.get("changes")
        if not isinstance(cursor, Mapping) or not isinstance(changes, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid whats_new payload")
        return {
            "assistant_id": str(payload.get("assistant_id") or ""),
            "peek_only": bool(payload.get("peek_only")),
            "cursor": dict(cursor),
            "changes": dict(changes),
        }

    def _tool_system_usage_guide(self, _args: dict[str, Any]) -> dict[str, Any]:
        payload = self.api_client.get_json("/api/system/usage-guide")
        guide = payload.get("guide")
        if not isinstance(guide, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid usage guide payload")
        return {
            "guide": dict(guide),
        }

    def _tool_methodology_list(self, args: dict[str, Any]) -> dict[str, Any]:
        status = str(args.get("status") or "all").strip().lower() or "all"
        mode = _coerce_mode(args.get("mode"), default="full")
        include_retired = _coerce_bool(args.get("include_retired"), default=True)
        limit = _coerce_int(args.get("limit"), default=40, minimum=1, maximum=self.config.max_list_limit)
        offset = _coerce_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000)
        payload = self.api_client.get_json(
            "/api/methodology/records",
            query={
                "status": status,
                "include_retired": include_retired,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = [row for row in list(payload.get("records") or []) if isinstance(row, Mapping)]
        rows_payload = (
            [self._methodology_record_compact(row) for row in rows]
            if mode == "compact"
            else [dict(row) for row in rows]
        )
        return {
            "mode": mode,
            "status_filter": str(payload.get("status_filter") or status),
            "include_retired": bool(payload.get("include_retired") if payload.get("include_retired") is not None else include_retired),
            "records": rows_payload,
            "offset": int(payload.get("offset") or offset),
            "limit": int(payload.get("limit") or limit),
            "total": int(payload.get("total") or len(rows)),
            "has_more": bool(payload.get("has_more")),
            "active_methodology_id": str(payload.get("active_methodology_id") or ""),
        }

    @staticmethod
    def _methodology_record_compact(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "methodology_id": str(row.get("methodology_id") or ""),
            "status": str(row.get("status") or ""),
            "approval_state": str(row.get("approval_state") or ""),
            "trigger_condition": str(row.get("trigger_condition") or ""),
            "action": str(row.get("action") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        }

    def _tool_methodology_get(self, args: dict[str, Any]) -> dict[str, Any]:
        methodology_id = str(args.get("methodology_id") or "").strip()
        if not methodology_id:
            raise MCPRequestError(-32602, "methodology_id is required")
        payload = self.api_client.get_json(f"/api/methodology/records/{quote(methodology_id, safe='')}")
        record = payload.get("record")
        if not isinstance(record, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid methodology record payload")
        return {
            "record": dict(record),
            "active_methodology_id": str(payload.get("active_methodology_id") or ""),
        }

    def _tool_methodology_readout(self, _args: dict[str, Any]) -> dict[str, Any]:
        payload = self.api_client.get_json("/api/methodology/readout")
        readout = payload.get("readout")
        if not isinstance(readout, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid methodology readout payload")
        return {
            "readout": dict(readout),
        }

    def _tool_methodology_list_correction_clusters(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _coerce_int(args.get("limit"), default=20, minimum=1, maximum=self.config.max_list_limit)
        payload = self.api_client.get_json(
            "/api/methodology/corrections/clusters",
            query={"limit": limit},
        )
        rows = [row for row in list(payload.get("clusters") or []) if isinstance(row, Mapping)]
        return {
            "clusters": [dict(row) for row in rows],
            "count": int(payload.get("count") or len(rows)),
        }

    def _tool_methodology_create_draft(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        trigger_condition = str(args.get("trigger_condition") or "").strip()
        action = str(args.get("action") or "").strip()
        rationale = str(args.get("rationale") or "").strip()
        if not trigger_condition:
            raise MCPRequestError(-32602, "trigger_condition is required")
        if not action:
            raise MCPRequestError(-32602, "action is required")
        if not rationale:
            raise MCPRequestError(-32602, "rationale is required")
        payload: dict[str, Any] = {
            "trigger_condition": trigger_condition,
            "action": action,
            "rationale": rationale,
            "actor": str(args.get("actor") or "operator").strip() or "operator",
        }
        provenance_refs = _normalize_string_list(args.get("provenance_refs"), max_items=16, max_chars=220)
        if provenance_refs:
            payload["provenance_refs"] = provenance_refs
        supersedes_id = str(args.get("supersedes_id") or "").strip()
        if supersedes_id:
            payload["supersedes_id"] = supersedes_id
        metadata = args.get("metadata")
        if isinstance(metadata, Mapping):
            payload["metadata"] = dict(metadata)
        response = self.api_client.post_json("/api/methodology/create", payload)
        return dict(response)

    def _tool_methodology_review(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        methodology_id = str(args.get("methodology_id") or "").strip()
        decision = str(args.get("decision") or "").strip().lower()
        reviewer = str(args.get("reviewer") or "").strip()
        if not methodology_id:
            raise MCPRequestError(-32602, "methodology_id is required")
        if decision not in {"approve", "reject"}:
            raise MCPRequestError(-32602, "decision must be approve or reject")
        if not reviewer:
            raise MCPRequestError(-32602, "reviewer is required")
        response = self.api_client.post_json(
            "/api/methodology/review",
            {
                "methodology_id": methodology_id,
                "decision": decision,
                "reviewer": reviewer,
                "note": str(args.get("note") or "").strip(),
            },
        )
        return dict(response)

    def _tool_methodology_start_canary(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        methodology_id = str(args.get("methodology_id") or "").strip()
        if not methodology_id:
            raise MCPRequestError(-32602, "methodology_id is required")
        response = self.api_client.post_json(
            "/api/methodology/canary/start",
            {
                "methodology_id": methodology_id,
                "auto_rollback": bool(args.get("auto_rollback", True)),
                "actor": str(args.get("actor") or "operator").strip() or "operator",
            },
        )
        return dict(response)

    def _tool_methodology_evaluate_canary(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        methodology_id = str(args.get("methodology_id") or "").strip()
        if not methodology_id:
            raise MCPRequestError(-32602, "methodology_id is required")
        response = self.api_client.post_json(
            "/api/methodology/canary/evaluate",
            {
                "methodology_id": methodology_id,
                "actor": str(args.get("actor") or "operator").strip() or "operator",
            },
        )
        return dict(response)

    def _tool_methodology_activate(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        methodology_id = str(args.get("methodology_id") or "").strip()
        if not methodology_id:
            raise MCPRequestError(-32602, "methodology_id is required")
        response = self.api_client.post_json(
            "/api/methodology/activate",
            {
                "methodology_id": methodology_id,
                "actor": str(args.get("actor") or "operator").strip() or "operator",
            },
        )
        return dict(response)

    def _tool_methodology_rollback(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        methodology_id = str(args.get("methodology_id") or "").strip()
        if not methodology_id:
            raise MCPRequestError(-32602, "methodology_id is required")
        response = self.api_client.post_json(
            "/api/methodology/rollback",
            {
                "methodology_id": methodology_id,
                "reason": str(args.get("reason") or "manual_rollback").strip() or "manual_rollback",
                "actor": str(args.get("actor") or "operator").strip() or "operator",
            },
        )
        return dict(response)

    def _tool_methodology_record_correction(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        text = str(args.get("text") or "").strip()
        if not text:
            raise MCPRequestError(-32602, "text is required")
        response = self.api_client.post_json(
            "/api/methodology/corrections/record",
            {
                "text": text,
                "assistant_id": str(args.get("assistant_id") or "").strip(),
                "session_id": str(args.get("session_id") or "").strip(),
                "actor": str(args.get("actor") or "operator").strip() or "operator",
            },
        )
        return dict(response)

    def _tool_methodology_evaluate_maintenance(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        response = self.api_client.post_json(
            "/api/methodology/maintenance/evaluate",
            {
                "force": bool(args.get("force", False)),
                "actor": str(args.get("actor") or "operator").strip() or "operator",
            },
        )
        return dict(response)

    def _tool_explore_set_preference(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        anchor_id = str(args.get("anchor_id") or "").strip()
        if not anchor_id:
            raise MCPRequestError(-32602, "anchor_id is required")
        anchor_type = str(args.get("anchor_type") or "topic").strip().lower() or "topic"
        if anchor_type not in {"person", "project", "topic", "event", "unknown"}:
            anchor_type = "topic"
        action = str(args.get("action") or "").strip().lower()
        if action not in {"pin", "more", "less", "ignore", "clear"}:
            raise MCPRequestError(-32602, "action must be one of: pin, more, less, ignore, clear")
        payload = self.api_client.post_json(
            "/api/explore/preferences",
            {
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "action": action,
            },
        )
        return {
            "ok": bool(payload.get("ok", True)),
            "applied": bool(payload.get("applied", True)),
            "removed": bool(payload.get("removed", False)),
            "preference": dict(payload.get("preference") or {}),
            "count": int(payload.get("count") or 0),
        }

    def _sanitize_turn(self, turn: Mapping[str, Any]) -> dict[str, Any]:
        citations = _normalize_string_list(turn.get("citations"), max_items=24, max_chars=120)
        answer_text = str(turn.get("response_text") or "").strip()
        if not answer_text:
            for key in ("answer", "assistant_text", "output_text", "response"):
                candidate = str(turn.get(key) or "").strip()
                if candidate:
                    answer_text = candidate
                    break
        return {
            "turn_id": str(turn.get("turn_id") or "").strip(),
            "session_id": str(turn.get("session_id") or "").strip(),
            "timestamp": str(turn.get("timestamp") or "").strip(),
            "decision": str(turn.get("decision") or "").strip() or "FAIL",
            "answer": self._clip_text(answer_text, max_chars=max(160, self.config.max_text_chars)),
            "citations": citations,
            "memory_route": str(turn.get("memory_route") or "").strip(),
            "route_reason": str(turn.get("route_reason") or "").strip(),
            "retrieval_stop_reason": str(turn.get("retrieval_stop_reason") or "").strip(),
            "retrieval_passes": int(turn.get("retrieval_passes") or 0),
        }

    def _build_peek_payload(self, turn: Mapping[str, Any]) -> dict[str, Any]:
        cards = [row for row in list(turn.get("memory_cards") or []) if isinstance(row, Mapping)]
        snippets: list[dict[str, Any]] = []
        for row in cards[:5]:
            citations = _normalize_string_list(row.get("citations"), max_items=4, max_chars=120)
            first = citations[0] if citations else ""
            source_id = str(first).split("#", 1)[0] if first else ""
            summary = str(row.get("summary_abstractive") or row.get("summary") or "").strip()
            raw_excerpt = str(row.get("raw_excerpt") or row.get("summary") or "").strip()
            snippets.append(
                {
                    "snippet": self._clip_text(summary, max_chars=220),
                    "raw_excerpt": self._clip_text(raw_excerpt, max_chars=320),
                    "confidence": float(row.get("confidence") or 0.0),
                    "source_id": source_id,
                    "source_ref": first,
                    "card_id": str(row.get("card_id") or "").strip(),
                }
            )
        return {
            "snippets": snippets,
            "count": len(snippets),
            "mode": "lightweight",
        }

    def _tool_chat_start_session(self, args: dict[str, Any]) -> dict[str, Any]:
        label = str(args.get("label") or "").strip() or None
        payload = self.api_client.post_json("/api/chat/session/start", {"label": label} if label else {})
        session = payload.get("session")
        if not isinstance(session, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid session payload")
        return {
            "session_id": str(session.get("session_id") or "").strip(),
            "label": str(session.get("label") or "").strip(),
            "created_at": str(session.get("created_at") or "").strip(),
            "updated_at": str(session.get("updated_at") or "").strip(),
            "turn_count": int(session.get("turn_count") or 0),
        }

    def _tool_chat_rename_session(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = str(args.get("session_id") or "").strip()
        label = str(args.get("label") or "").strip()
        if not session_id:
            raise MCPRequestError(-32602, "session_id is required")
        if not label:
            raise MCPRequestError(-32602, "label is required")
        payload = self.api_client.post_json(
            f"/api/chat/session/{quote(session_id, safe='')}/label",
            {"label": label},
        )
        session = payload.get("session")
        if not isinstance(session, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid session payload")
        return {
            "session_id": str(session.get("session_id") or "").strip(),
            "label": str(session.get("label") or "").strip(),
            "created_at": str(session.get("created_at") or "").strip(),
            "updated_at": str(session.get("updated_at") or "").strip(),
            "turn_count": int(session.get("turn_count") or 0),
        }

    def _tool_chat_list_sessions(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _coerce_int(args.get("limit"), default=40, minimum=1, maximum=self.config.max_list_limit)
        offset = _coerce_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000)
        payload = self.api_client.get_json("/api/chat/sessions")
        rows = [row for row in list(payload.get("sessions") or []) if isinstance(row, Mapping)]
        total = len(rows)
        page = rows[offset : offset + limit]
        sessions = [
            {
                "session_id": str(row.get("session_id") or "").strip(),
                "label": self._clip_text(row.get("label"), max_chars=120),
                "created_at": str(row.get("created_at") or "").strip(),
                "updated_at": str(row.get("updated_at") or "").strip(),
                "turn_count": int(row.get("turn_count") or 0),
            }
            for row in page
        ]
        return {
            "sessions": sessions,
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(sessions) < total,
        }

    def _tool_chat_session_history(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = str(args.get("session_id") or "").strip()
        if not session_id:
            raise MCPRequestError(-32602, "session_id is required")
        limit = _coerce_int(args.get("limit"), default=30, minimum=1, maximum=self.config.max_list_limit)
        offset = _coerce_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000)
        payload = self.api_client.get_json(f"/api/chat/session/{quote(session_id, safe='')}/history")
        rows = [row for row in list(payload.get("history") or []) if isinstance(row, Mapping)]
        total = len(rows)
        page = rows[offset : offset + limit]
        return {
            "session_id": session_id,
            "history": [self._sanitize_turn(row) for row in page],
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(page) < total,
        }

    def _tool_chat_turn(self, args: dict[str, Any]) -> dict[str, Any]:
        message = str(args.get("message") or "").strip()
        if not message:
            raise MCPRequestError(-32602, "message is required")
        session_id = str(args.get("session_id") or "").strip() or None
        retrieval_query = str(args.get("retrieval_query") or "").strip() or None
        if retrieval_query and not _role_allows(self._session_role, "operator"):
            raise MCPRequestError(-32002, "retrieval_query override requires operator role")
        payload: dict[str, Any] = {
            "message": message,
            "high_risk": bool(args.get("high_risk")),
        }
        memory_preference = str(args.get("memory_preference") or "").strip() or None
        if memory_preference:
            payload["memory_preference"] = memory_preference
        if retrieval_query:
            payload["retrieval_override"] = {
                "query": retrieval_query,
                "invoker": "engine.mcp.server.chat.turn",
                "reason": "operator_requested_override",
                "scope": "mcp_chat_turn",
            }
        path = "/api/chat"
        if session_id:
            path = f"/api/chat/session/{quote(session_id, safe='')}/turn"
        response = self.api_client.post_json(path, payload)
        turn_raw = response.get("turn")
        if not isinstance(turn_raw, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid turn payload")
        turn = self._sanitize_turn(turn_raw)
        out: dict[str, Any] = {
            "answer": turn["answer"],
            "decision": turn["decision"],
            "citations": list(turn["citations"]),
            "turn_id": turn["turn_id"],
            "session_id": turn["session_id"],
            "memory_route": turn["memory_route"],
            "route_reason": turn["route_reason"],
            "retrieval_stop_reason": turn["retrieval_stop_reason"],
        }
        if bool(args.get("peek")):
            out["peek"] = self._build_peek_payload(turn_raw)
        include_why = bool(args.get("include_why"))
        if include_why and turn["turn_id"]:
            why_payload = self.api_client.get_json(f"/api/turns/{quote(turn['turn_id'], safe='')}/why", query={"citations": "false"})
            why = why_payload.get("why")
            if isinstance(why, Mapping):
                out["why"] = dict(why)
        return out

    def _tool_chat_route_preview(self, args: dict[str, Any]) -> dict[str, Any]:
        message = str(args.get("message") or "").strip()
        if not message:
            raise MCPRequestError(-32602, "message is required")
        payload: dict[str, Any] = {
            "message": message,
            "high_risk": bool(args.get("high_risk")),
        }
        session_id = str(args.get("session_id") or "").strip() or None
        if session_id:
            payload["session_id"] = session_id
        memory_preference = str(args.get("memory_preference") or "").strip() or None
        if memory_preference:
            payload["memory_preference"] = memory_preference
        response = self.api_client.post_json("/api/chat/route-preview", payload)
        preview = response.get("preview")
        if not isinstance(preview, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid route preview payload")
        out = dict(preview)
        route = str(out.get("route") or "").strip().lower()
        predicted_mode = str(out.get("predicted_memory_mode") or "").strip().lower()
        if predicted_mode in {"none", "stm_only", "ltm_light", "ltm_deep"}:
            expected_touch = predicted_mode
        elif route in {"none", "stm_only", "ltm_light", "ltm_deep"}:
            expected_touch = route
        else:
            expected_touch = "ltm_light"
        if expected_touch in {"none", "stm_only"}:
            cost_class = "low"
        elif expected_touch == "ltm_light":
            cost_class = "medium"
        else:
            cost_class = "high"
        msg_len = len(message)
        if msg_len <= 80:
            request_band = "low"
        elif msg_len <= 240:
            request_band = "medium"
        else:
            request_band = "high"
        response_band = {
            "low": "compact",
            "medium": "standard",
            "high": "heavy",
        }.get(cost_class, "standard")
        out["expected_memory_touch"] = expected_touch
        out["estimated_route_cost_class"] = cost_class
        out["estimated_token_band"] = {
            "request": request_band,
            "response": response_band,
        }
        return out

    def _tool_chat_build_context_package(self, args: dict[str, Any]) -> dict[str, Any]:
        message = str(args.get("message") or "").strip()
        if not message:
            raise MCPRequestError(-32602, "message is required")
        retrieval_query = str(args.get("retrieval_query") or "").strip() or None
        if retrieval_query and not _role_allows(self._session_role, "operator"):
            raise MCPRequestError(-32002, "retrieval_query override requires operator role")
        payload: dict[str, Any] = {
            "message": message,
            "high_risk": bool(args.get("high_risk")),
            "package_version": str(args.get("package_version") or "v2"),
        }
        session_id = str(args.get("session_id") or "").strip() or None
        if session_id:
            payload["session_id"] = session_id
        memory_preference = str(args.get("memory_preference") or "").strip() or None
        if memory_preference:
            payload["memory_preference"] = memory_preference
        if retrieval_query:
            payload["retrieval_override"] = {
                "query": retrieval_query,
                "invoker": "engine.mcp.server.chat.build_context_package",
                "reason": "operator_requested_override",
                "scope": "mcp_context_package",
            }
        render_citations = args.get("render_citations")
        if isinstance(render_citations, bool):
            payload["render_citations"] = render_citations
        response = self.api_client.post_json("/api/chat/context-package", payload)
        package = response.get("package")
        if not isinstance(package, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid context package")
        retrieval_stats = dict(package.get("retrieval_stats") or {}) if isinstance(package.get("retrieval_stats"), Mapping) else {}
        retrieved_atom_ids_raw = retrieval_stats.get("retrieved_atom_ids")
        if isinstance(retrieved_atom_ids_raw, list):
            retrieved_atom_ids = [str(item).strip() for item in retrieved_atom_ids_raw if str(item).strip()]
        elif isinstance(retrieved_atom_ids_raw, str):
            cleaned = retrieved_atom_ids_raw.strip()
            retrieved_atom_ids = [cleaned] if cleaned else []
        else:
            retrieved_atom_ids = []
        return {
            "package": dict(package),
            "stats": {
                "retrieved_count": len(retrieved_atom_ids),
                "route": str(retrieval_stats.get("memory_route") or ""),
                "stop_reason": str(retrieval_stats.get("retrieval_stop_reason") or ""),
            },
        }

    def _tool_why_explain_turn(self, args: dict[str, Any]) -> dict[str, Any]:
        turn_id = str(args.get("turn_id") or "").strip()
        if not turn_id:
            raise MCPRequestError(-32602, "turn_id is required")
        include_citations = bool(args.get("include_citations"))
        payload = self.api_client.get_json(
            f"/api/turns/{quote(turn_id, safe='')}/why",
            query={"citations": "true" if include_citations else "false"},
        )
        why_raw = payload.get("why")
        if not isinstance(why_raw, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid why payload")
        top_evidence_raw = [row for row in list(why_raw.get("top_evidence") or []) if isinstance(row, Mapping)]
        top_evidence = top_evidence_raw[: self.config.max_why_evidence_items]
        citations = _normalize_string_list(
            why_raw.get("citations"),
            max_items=self.config.max_citation_matches,
            max_chars=120,
        )
        decision_reason = str(why_raw.get("decision_reason") or "").strip()
        return {
            "turn_id": str(why_raw.get("turn_id") or turn_id).strip(),
            "decision": str(why_raw.get("decision") or "").strip(),
            "reason": str(why_raw.get("reason") or decision_reason).strip(),
            "decision_reason": decision_reason,
            "summary": self._clip_text(why_raw.get("plain_summary"), max_chars=180),
            "evidence_time_window": dict(why_raw.get("evidence_time_window") or {}),
            "evidence": top_evidence,
            "citations": citations if include_citations else [],
            "citations_hidden": bool(why_raw.get("citations_hidden", not include_citations)),
            "package_version": str(why_raw.get("package_version") or "").strip(),
        }

    def _tool_evidence_resolve_citation(self, args: dict[str, Any]) -> dict[str, Any]:
        citation_token = str(args.get("citation_token") or "").strip()
        if not citation_token:
            raise MCPRequestError(-32602, "citation_token is required")
        if len(citation_token) > 128:
            raise MCPRequestError(-32602, "citation_token is too long")
        max_matches = _coerce_int(
            args.get("max_matches"),
            default=self.config.max_citation_matches,
            minimum=1,
            maximum=self.config.max_citation_matches,
        )
        context_window = _coerce_int(
            args.get("context_window"),
            default=3,
            minimum=0,
            maximum=5,
        )
        payload = self.api_client.get_json(
            f"/api/archive/citation/{quote(citation_token, safe='')}",
            query={"context_window": context_window},
        )
        matches_raw = [row for row in list(payload.get("matches") or []) if isinstance(row, Mapping)]
        trimmed = matches_raw[:max_matches]
        matches: list[dict[str, Any]] = []
        for row in trimmed:
            source_id = str(row.get("source_id") or payload.get("source_id") or "").strip()
            message_id = str(row.get("message_id") or "").strip()
            source_ref = source_id if not message_id else f"{source_id}#{message_id}"
            matches.append(
                {
                    "source_ref": source_ref,
                    "timestamp": str(row.get("timestamp") or "").strip(),
                    "excerpt": self._clip_text(row.get("excerpt"), max_chars=self.config.max_text_chars),
                    "is_target": bool(row.get("is_target")),
                    "distance": int(row.get("distance") or 0),
                }
            )
        resolved_token = unquote(str(payload.get("citation") or citation_token).strip())
        return {
            "citation_token": resolved_token,
            "source_id": str(payload.get("source_id") or "").strip(),
            "message_id": str(payload.get("message_id") or "").strip(),
            "context_window": int(payload.get("context_window") or context_window),
            "matches": matches,
            "truncated": len(matches_raw) > len(trimmed),
            "match_limit": max_matches,
        }

    def _tool_memory_disable_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        episode_id = str(args.get("episode_id") or "").strip()
        if not episode_id:
            raise MCPRequestError(-32602, "episode_id is required")
        reason = str(args.get("reason") or "").strip() or "disabled_from_mcp"
        payload = self.api_client.post_json(
            f"/api/memory/episodes/{quote(episode_id, safe='')}/disable",
            {"reason": reason},
        )
        episode = payload.get("episode")
        status = "disabled"
        if isinstance(episode, Mapping):
            status = str(episode.get("promotion_status") or status).strip().lower() or status
        return {"ok": True, "episode_id": episode_id, "status": status}

    def _tool_memory_enable_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        episode_id = str(args.get("episode_id") or "").strip()
        if not episode_id:
            raise MCPRequestError(-32602, "episode_id is required")
        payload = self.api_client.post_json(
            f"/api/memory/episodes/{quote(episode_id, safe='')}/enable",
            {},
        )
        episode = payload.get("episode")
        status = "approved"
        if isinstance(episode, Mapping):
            status = str(episode.get("promotion_status") or status).strip().lower() or status
        return {"ok": True, "episode_id": episode_id, "status": status}

    def _tool_memory_edit_episode(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        episode_id = str(args.get("episode_id") or "").strip()
        if not episode_id:
            raise MCPRequestError(-32602, "episode_id is required")
        patch = dict(args.get("patch") or {}) if isinstance(args.get("patch"), Mapping) else {}
        if not patch:
            raise MCPRequestError(-32602, "patch must include at least one editable field")
        title = str(patch.get("title") or "").strip()
        summary = str(patch.get("summary") or "").strip()
        tags = _normalize_string_list(patch.get("tags"), max_items=24, max_chars=80)
        actors = _normalize_string_list(patch.get("actors"), max_items=24, max_chars=80)
        cue_terms = _normalize_string_list(patch.get("cue_terms"), max_items=48, max_chars=72)
        diff_summary = {
            "title": bool(title),
            "summary": bool(summary),
            "tags": len(tags),
            "actors": len(actors),
            "cue_terms": len(cue_terms),
        }
        dry_run = bool(args.get("dry_run"))
        if dry_run:
            return {"ok": True, "episode_id": episode_id, "applied": False, "diff_summary": diff_summary}
        payload: dict[str, Any] = {}
        if title:
            payload["title"] = title
        if summary:
            payload["summary"] = summary
        if tags:
            payload["topic_tags"] = tags
        if actors:
            payload["actors"] = actors
        if cue_terms:
            payload["cue_terms"] = cue_terms
        if not payload:
            raise MCPRequestError(-32602, "patch did not contain any non-empty editable values")
        self.api_client.post_json(
            f"/api/memory/episodes/{quote(episode_id, safe='')}/edit",
            payload,
        )
        return {"ok": True, "episode_id": episode_id, "applied": True, "diff_summary": diff_summary}

    def _tool_memory_undo_last_change(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        scope = str(args.get("scope") or "episode_edits").strip().lower() or "episode_edits"
        if scope == "proposals":
            raise MCPRequestError(-32602, "scope=proposals is not supported by runtime undo endpoint")
        payload = self.api_client.post_json("/api/memory/episodes/undo-last", {})
        undo = dict(payload.get("undo") or {}) if isinstance(payload.get("undo"), Mapping) else {}
        reload_state = dict(payload.get("reload") or {}) if isinstance(payload.get("reload"), Mapping) else {}
        return {
            "ok": True,
            "undone": {
                "kind": str(undo.get("action") or "episode_edit"),
                "id": str(undo.get("restored_path") or undo.get("backup_path") or "").strip(),
            },
            "state": reload_state,
        }

    @staticmethod
    def _proposal_summary(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "proposal_id": str(row.get("proposal_id") or "").strip(),
            "kind": str(row.get("kind") or "").strip(),
            "status": str(row.get("status") or "").strip(),
            "created_at": str(row.get("created_at") or "").strip(),
            "summary": str(row.get("reason_code") or row.get("status_reason") or "").strip(),
        }

    def _tool_proposals_list(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        status = str(args.get("status") or "all").strip().lower() or "all"
        limit = _coerce_int(args.get("limit"), default=40, minimum=1, maximum=self.config.max_list_limit)
        offset = _coerce_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000)
        runtime_status = "all" if status in {"all", "open"} else status
        payload = self.api_client.get_json("/api/memory/proposals", query={"status": runtime_status})
        rows = [row for row in list(payload.get("proposals") or []) if isinstance(row, Mapping)]
        if status == "open":
            rows = [row for row in rows if str(row.get("status") or "").strip().lower() == "pending"]
        total = len(rows)
        page = rows[offset : offset + limit]
        return {
            "proposals": [self._proposal_summary(row) for row in page],
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(page) < total,
        }

    def _tool_proposals_create_edit(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        target_id = str(args.get("target_id") or "").strip()
        reason = str(args.get("reason") or "").strip()
        patch = dict(args.get("patch") or {}) if isinstance(args.get("patch"), Mapping) else {}
        if not target_id or not reason:
            raise MCPRequestError(-32602, "target_id and reason are required")
        canonical_text = str(patch.get("canonical_text") or patch.get("text") or patch.get("summary") or "").strip()
        if not canonical_text:
            raise MCPRequestError(-32602, "patch must include canonical_text/text/summary")
        if bool(args.get("dry_run")):
            return {"proposal_id": "", "status": "open", "applied": False}
        payload = {
            "target_atom_id": target_id,
            "canonical_text": canonical_text,
            "reason_code": reason,
        }
        if isinstance(patch.get("entities"), list):
            payload["entities"] = patch.get("entities")
        if isinstance(patch.get("topics"), list):
            payload["topics"] = patch.get("topics")
        response = self.api_client.post_json("/api/memory/proposals/create-edit", payload)
        proposal = response.get("proposal")
        if not isinstance(proposal, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid proposal payload")
        return {"proposal_id": str(proposal.get("proposal_id") or "").strip(), "status": "open"}

    def _tool_proposals_create_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        target_id = str(args.get("target_id") or "").strip()
        reason = str(args.get("reason") or "").strip()
        if not target_id or not reason:
            raise MCPRequestError(-32602, "target_id and reason are required")
        if bool(args.get("dry_run")):
            return {"proposal_id": "", "status": "open", "applied": False}
        response = self.api_client.post_json(
            "/api/memory/proposals/create-delete",
            {"target_atom_id": target_id, "reason_code": reason},
        )
        proposal = response.get("proposal")
        if not isinstance(proposal, Mapping):
            raise MCPRequestError(-32003, "runtime returned invalid proposal payload")
        return {"proposal_id": str(proposal.get("proposal_id") or "").strip(), "status": "open"}

    def _tool_proposals_approve(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        proposal_id = str(args.get("proposal_id") or "").strip()
        if not proposal_id:
            raise MCPRequestError(-32602, "proposal_id is required")
        note = str(args.get("note") or "").strip() or "approved_from_mcp"
        apply_now = bool(args.get("apply"))
        response = self.api_client.post_json(
            f"/api/memory/proposals/{quote(proposal_id, safe='')}/approve",
            {"reviewer": "mcp_operator", "apply": apply_now, "note": note},
        )
        proposal = response.get("proposal")
        status = "approved"
        if isinstance(proposal, Mapping):
            status = str(proposal.get("status") or status).strip().lower() or status
        return {"ok": True, "proposal_id": proposal_id, "status": status}

    def _tool_proposals_reject(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        proposal_id = str(args.get("proposal_id") or "").strip()
        note = str(args.get("note") or "").strip()
        if not proposal_id or not note:
            raise MCPRequestError(-32602, "proposal_id and note are required")
        response = self.api_client.post_json(
            f"/api/memory/proposals/{quote(proposal_id, safe='')}/reject",
            {"reviewer": "mcp_operator", "reason": note},
        )
        proposal = response.get("proposal")
        status = "rejected"
        if isinstance(proposal, Mapping):
            status = str(proposal.get("status") or status).strip().lower() or status
        return {"ok": True, "proposal_id": proposal_id, "status": status}

    @staticmethod
    def _wizard_status(raw: Any) -> str:
        text = str(raw or "").strip().lower()
        if not text:
            return "watch"
        normalized = text.replace(" ", "_")
        if any(token in normalized for token in ("unsafe", "fail", "error", "needs_attention", "needsattention")):
            return "needs_attention"
        if normalized in {"safe", "ok", "pass"}:
            return "safe"
        if "safe" in normalized:
            return "safe"
        return "watch"

    @staticmethod
    def _archive_descriptor_payload(value: Any) -> dict[str, Any]:
        descriptor = dict(value or {}) if isinstance(value, Mapping) else {}
        archive_path = str(
            descriptor.get("archive_path") or descriptor.get("path") or descriptor.get("archive") or ""
        ).strip()
        store_path = str(descriptor.get("store_path") or "").strip()
        out_dir = str(descriptor.get("out_dir") or descriptor.get("output_dir") or "").strip()
        return {
            "archive_path": archive_path,
            "store_path": store_path,
            "out_dir": out_dir,
        }

    def _tool_wizard_start_or_resume(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        mode = str(args.get("mode") or "").strip().lower()
        if mode not in {"new", "resume"}:
            raise MCPRequestError(-32602, "mode must be one of: new, resume")
        payload = {"mode": mode}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/start", payload)
        state = dict(response.get("state") or {}) if isinstance(response.get("state"), Mapping) else {}
        return {
            "run_id": str(response.get("run_id") or state.get("run_id") or "").strip(),
            "stage": str(state.get("current_stage") or "").strip(),
            "resume_supported": True,
        }

    def _tool_wizard_validate_archive(self, args: dict[str, Any]) -> dict[str, Any]:
        descriptor = self._archive_descriptor_payload(args.get("archive_descriptor"))
        archive_path = descriptor.get("archive_path") or ""
        if not archive_path:
            raise MCPRequestError(-32602, "archive_descriptor.archive_path is required")
        payload = {"archive_path": archive_path}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/import/validate", payload)
        issues = [str(item) for item in list(response.get("issues") or []) if str(item).strip()]
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "counts": {
                "conversation_count": int(response.get("conversation_count") or 0),
                "message_count": int(response.get("message_count") or 0),
            },
            "warnings": issues,
            "blockers": issues if str(response.get("status") or "").strip().lower() != "safe" else [],
        }

    def _tool_wizard_import_run(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        descriptor = self._archive_descriptor_payload(args.get("archive_descriptor"))
        archive_path = descriptor.get("archive_path") or ""
        if not archive_path:
            raise MCPRequestError(-32602, "archive_descriptor.archive_path is required")
        dry_run = bool(args.get("dry_run"))
        if dry_run:
            return {
                "ok": True,
                "applied": False,
                "import_report": {"status": "dry_run"},
                "store_descriptor": {"store_path": str(descriptor.get("store_path") or "").strip()},
            }
        payload = {"archive_path": archive_path}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        store_path = str(descriptor.get("store_path") or "").strip()
        out_dir = str(descriptor.get("out_dir") or "").strip()
        if store_path:
            payload["store_path"] = store_path
        if out_dir:
            payload["out_dir"] = out_dir
        response = self.api_client.post_json("/api/wizard/import/run", payload)
        reports = dict(response.get("reports") or {}) if isinstance(response.get("reports"), Mapping) else {}
        return {
            "ok": bool(response.get("ok", True)),
            "applied": True,
            "run_id": str(response.get("run_id") or "").strip(),
            "import_report": {
                "json": str(reports.get("json") or "").strip(),
                "md": str(reports.get("md") or "").strip(),
            },
            "store_descriptor": {"store_path": str(response.get("store_path") or "").strip()},
        }

    def _tool_wizard_build_episodes(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        dry_run = bool(args.get("dry_run"))
        policy_preset = str(args.get("policy_preset") or "").strip() or "strict"
        store_descriptor = dict(args.get("store_descriptor") or {}) if isinstance(args.get("store_descriptor"), Mapping) else {}
        if dry_run:
            return {
                "ok": True,
                "applied": False,
                "episode_build_report": {"policy_preset": policy_preset, "status": "dry_run"},
                "draft_descriptor": {"draft_path": "", "rejects_path": "", "readout_path": ""},
            }
        payload: dict[str, Any] = {"policy_preset": policy_preset}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        store_path = str(store_descriptor.get("store_path") or "").strip()
        if store_path:
            payload["store_path"] = store_path
        response = self.api_client.post_json("/api/wizard/build/run", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "applied": True,
            "run_id": str(response.get("run_id") or "").strip(),
            "episode_build_report": {
                "policy_preset": str(response.get("policy_preset") or policy_preset).strip(),
                "counts": dict(response.get("counts") or {}),
            },
            "draft_descriptor": {
                "draft_path": str(response.get("draft_path") or "").strip(),
                "rejects_path": str(response.get("rejects_path") or "").strip(),
                "readout_path": str(response.get("readout_path") or "").strip(),
            },
        }

    def _tool_wizard_draft_curation_status(self, args: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            query["run_id"] = run_id
        response = self.api_client.get_json("/api/wizard/draft-curation/status", query=query)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "draft_ready": bool(response.get("draft_ready")),
            "build_id": str(response.get("build_id") or "").strip(),
            "source_cards_path": str(response.get("source_cards_path") or "").strip(),
            "draft_curation": dict(response.get("draft_curation") or {}),
            "audit_count": int(response.get("audit_count") or 0),
            "context_policy": dict(response.get("context_policy") or {}),
        }

    def _tool_wizard_draft_curation_cards(self, args: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            query["run_id"] = run_id
        mode = str(args.get("mode") or "compact").strip().lower() or "compact"
        if mode not in {"compact", "full"}:
            mode = "compact"
        query["mode"] = mode
        q = str(args.get("q") or "").strip()
        if q:
            query["q"] = q
        proposal_status = str(args.get("proposal_status") or "all").strip().lower() or "all"
        query["proposal_status"] = proposal_status
        query["page"] = _coerce_int(args.get("page"), default=1, minimum=1, maximum=10_000)
        query["page_size"] = _coerce_int(args.get("page_size"), default=24, minimum=1, maximum=self.config.max_list_limit)
        response = self.api_client.get_json("/api/wizard/draft-curation/cards", query=query)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "build_id": str(response.get("build_id") or "").strip(),
            "mode": str(response.get("mode") or mode).strip().lower() or mode,
            "cards": [dict(row) for row in list(response.get("cards") or []) if isinstance(row, Mapping)],
            "total": int(response.get("total") or 0),
            "page": int(response.get("page") or 1),
            "page_size": int(response.get("page_size") or query["page_size"]),
            "total_pages": int(response.get("total_pages") or 1),
            "has_prev": bool(response.get("has_prev")),
            "has_next": bool(response.get("has_next")),
            "proposal_status": str(response.get("proposal_status") or proposal_status),
        }

    def _tool_wizard_draft_curation_get_card(self, args: dict[str, Any]) -> dict[str, Any]:
        episode_id = str(args.get("episode_id") or "").strip()
        if not episode_id:
            raise MCPRequestError(-32602, "episode_id is required")
        query: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            query["run_id"] = run_id
        include_context = bool(args.get("include_context", True))
        query["include_context"] = include_context
        if args.get("context_window") is not None:
            query["context_window"] = _coerce_int(args.get("context_window"), default=2, minimum=0, maximum=8)
        response = self.api_client.get_json(f"/api/wizard/draft-curation/cards/{quote(episode_id)}", query=query)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "build_id": str(response.get("build_id") or "").strip(),
            "source_cards_path": str(response.get("source_cards_path") or "").strip(),
            "card": dict(response.get("card") or {}),
            "proposal": dict(response.get("proposal") or {}),
            "review_payload": dict(response.get("review_payload") or {}),
            "context_policy": dict(response.get("context_policy") or {}),
            "context": dict(response.get("context") or {}),
        }

    def _tool_wizard_draft_curation_proposals(self, args: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            query["run_id"] = run_id
        status = str(args.get("status") or "all").strip().lower() or "all"
        query["status"] = status
        response = self.api_client.get_json("/api/wizard/draft-curation/proposals", query=query)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "build_id": str(response.get("build_id") or "").strip(),
            "status": str(response.get("status") or status),
            "proposals": [dict(row) for row in list(response.get("proposals") or []) if isinstance(row, Mapping)],
            "total": int(response.get("total") or 0),
            "context_policy": dict(response.get("context_policy") or {}),
        }

    def _tool_wizard_draft_curation_session_start(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload = {
            "owner_id": str(args.get("owner_id") or "").strip(),
            "session_id": str(args.get("session_id") or "").strip(),
            "model_identity": str(args.get("model_identity") or "").strip(),
            "force_release": bool(args.get("force_release")),
        }
        if not payload["owner_id"] or not payload["session_id"]:
            raise MCPRequestError(-32602, "owner_id and session_id are required")
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            payload["run_id"] = run_id
        if args.get("ttl_seconds") is not None:
            payload["ttl_seconds"] = _coerce_int(args.get("ttl_seconds"), default=1800, minimum=60, maximum=86_400)
        response = self.api_client.post_json("/api/wizard/draft-curation/session/start", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "draft_curation": dict(response.get("draft_curation") or {}),
        }

    def _tool_wizard_draft_curation_session_heartbeat(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload = {
            "owner_id": str(args.get("owner_id") or "").strip(),
            "session_id": str(args.get("session_id") or "").strip(),
        }
        if not payload["owner_id"] or not payload["session_id"]:
            raise MCPRequestError(-32602, "owner_id and session_id are required")
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/draft-curation/session/heartbeat", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "lease": dict(response.get("lease") or {}),
        }

    def _tool_wizard_draft_curation_session_release(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload = {
            "owner_id": str(args.get("owner_id") or "").strip(),
            "session_id": str(args.get("session_id") or "").strip(),
            "force_release": bool(args.get("force_release")),
            "note": str(args.get("note") or "").strip(),
        }
        if not payload["owner_id"] or not payload["session_id"]:
            raise MCPRequestError(-32602, "owner_id and session_id are required")
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/draft-curation/session/release", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "draft_curation": dict(response.get("draft_curation") or {}),
        }

    def _tool_wizard_draft_curation_proposal_upsert(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload: dict[str, Any] = {
            "episode_id": str(args.get("episode_id") or "").strip(),
            "owner_id": str(args.get("owner_id") or "").strip(),
            "session_id": str(args.get("session_id") or "").strip(),
            "model_identity": str(args.get("model_identity") or "").strip(),
            "title": str(args.get("title") or "").strip(),
            "summary": str(args.get("summary") or "").strip(),
            "actors": _normalize_string_list(args.get("actors") or [], max_items=32, max_chars=64),
            "topic_tags": _normalize_string_list(args.get("topic_tags") or [], max_items=32, max_chars=64),
            "cue_terms": _normalize_string_list(args.get("cue_terms") or [], max_items=48, max_chars=72),
            "decision_suggestion": str(args.get("decision_suggestion") or "").strip().lower(),
            "ranking_hint": dict(args.get("ranking_hint") or {}),
            "retrieval_cues": _normalize_string_list(args.get("retrieval_cues") or [], max_items=48, max_chars=72),
            "rationale": str(args.get("rationale") or "").strip(),
        }
        if not payload["episode_id"] or not payload["owner_id"] or not payload["session_id"]:
            raise MCPRequestError(-32602, "episode_id, owner_id, and session_id are required")
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/draft-curation/proposals/upsert", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or run_id).strip(),
            "proposal": dict(response.get("proposal") or {}),
        }

    def _tool_wizard_review_list(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _coerce_int(args.get("limit"), default=40, minimum=1, maximum=self.config.max_list_limit)
        offset = _coerce_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000)
        query: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip()
        if run_id:
            query["run_id"] = run_id
        q = str(args.get("q") or "").strip()
        if q:
            query["q"] = q
        status = str(args.get("status") or "all").strip().lower() or "all"
        if status != "all":
            query["status"] = status
        response = self.api_client.get_json("/api/wizard/review/cards", query=query)
        cards = [row for row in list(response.get("cards") or []) if isinstance(row, Mapping)]
        total = len(cards)
        page = cards[offset : offset + limit]
        return {
            "run_id": str(response.get("run_id") or run_id).strip(),
            "cards": page,
            "counts": {"total": total, "returned": len(page)},
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
        }

    def _tool_wizard_review_update(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        updates = list(args.get("updates") or []) if isinstance(args.get("updates"), list) else []
        if not updates:
            raise MCPRequestError(-32602, "updates must contain at least one row")
        dry_run = bool(args.get("dry_run"))
        run_id = str(args.get("run_id") or "").strip() or None
        if dry_run:
            return {"ok": True, "applied": False, "updated": len(updates)}
        updated = 0
        for row in updates:
            if not isinstance(row, Mapping):
                continue
            episode_id = str(row.get("episode_id") or "").strip()
            if not episode_id:
                raise MCPRequestError(-32602, "each update must include episode_id")
            decision = str(row.get("decision") or "").strip().lower() or "pending"
            if decision not in {"pending", "approved", "edited", "rejected"}:
                raise MCPRequestError(-32602, "decision must be one of: pending, approved, edited, rejected")
            edits = dict(row.get("edits") or {}) if isinstance(row.get("edits"), Mapping) else {}
            payload: dict[str, Any] = {"episode_id": episode_id, "decision": decision}
            if run_id:
                payload["run_id"] = run_id
            title = str(edits.get("title") or row.get("title") or "").strip()
            summary = str(edits.get("summary") or row.get("summary") or "").strip()
            actors = _normalize_string_list(edits.get("actors") or row.get("actors"), max_items=24, max_chars=80)
            tags = _normalize_string_list(edits.get("tags") or edits.get("topic_tags") or row.get("topic_tags"), max_items=24, max_chars=80)
            if title:
                payload["title"] = title
            if summary:
                payload["summary"] = summary
            if actors:
                payload["actors"] = actors
            if tags:
                payload["topic_tags"] = tags
            self.api_client.post_json("/api/wizard/review/update", payload)
            updated += 1
        return {"ok": True, "applied": True, "updated": updated}

    def _tool_wizard_compile_reviewed(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        dry_run = bool(args.get("dry_run"))
        if dry_run:
            return {"ok": True, "applied": False, "episode_count": 0, "published_descriptor": {}}
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        reviewer = str(args.get("reviewer") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        if reviewer:
            payload["reviewer"] = reviewer
        response = self.api_client.post_json("/api/wizard/review/compile", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "applied": True,
            "episode_count": int(response.get("episode_count") or 0),
            "published_descriptor": {
                "reviewed_path": str(response.get("reviewed_path") or "").strip(),
                "snapshot_path": str(response.get("reviewed_snapshot_path") or "").strip(),
            },
        }

    def _tool_wizard_verify(self, args: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/verify/run", payload)
        checks = [row for row in list(response.get("checks") or []) if isinstance(row, Mapping)]
        actionable = [row for row in list(response.get("actionable_links") or []) if isinstance(row, Mapping)]
        return {
            "status": self._wizard_status(response.get("status")),
            "checks": checks,
            "actionable": actionable,
        }

    def _tool_wizard_go_live(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        if bool(args.get("dry_run")):
            return {"ok": True, "applied": False, "runtime_descriptor": {}, "provider_snapshot": {}}
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/go-live", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "applied": True,
            "runtime_descriptor": {
                "runtime_url": str(response.get("runtime_url") or "").strip(),
                "published_pointers": dict(response.get("published_pointers") or {}),
            },
            "provider_snapshot": dict(response.get("provider_config") or {}),
        }

    def _tool_wizard_restore_last_published(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        if bool(args.get("dry_run")):
            return {"ok": True, "applied": False, "restored": False, "pointers": {}}
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/restore-last-published", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "applied": True,
            "restored": bool(response.get("ok", True)),
            "pointers": dict(response.get("published_pointers") or {}),
        }

    def _tool_wizard_organizer_inventory(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        if args.get("limit") is not None:
            payload["limit"] = _coerce_int(args.get("limit"), default=24, minimum=1, maximum=80)
        response = self.api_client.post_json("/api/wizard/organizer/inventory", payload)
        inventory = dict(response.get("inventory") or {}) if isinstance(response.get("inventory"), Mapping) else {}
        typed = [row for row in list(inventory.get("typed_candidates") or []) if isinstance(row, Mapping)]
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "status": str(inventory.get("status") or "").strip().lower() or "unknown",
            "counts": dict(inventory.get("counts") or {}),
            "typed_candidates": typed[: self.config.max_list_limit],
            "truncated": len(typed) > min(len(typed), self.config.max_list_limit),
        }

    def _tool_wizard_organizer_dedupe(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/organizer/dedupe", payload)
        dedupe = dict(response.get("dedupe") or {}) if isinstance(response.get("dedupe"), Mapping) else {}
        proposals = [row for row in list(dedupe.get("proposals") or []) if isinstance(row, Mapping)]
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "counts": dict(dedupe.get("counts") or {}),
            "proposals": proposals[: self.config.max_list_limit],
            "truncated": len(proposals) > min(len(proposals), self.config.max_list_limit),
        }

    def _tool_wizard_organizer_conflicts(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/organizer/conflicts", payload)
        conflicts = dict(response.get("conflicts") or {}) if isinstance(response.get("conflicts"), Mapping) else {}
        conflict_queue = [row for row in list(conflicts.get("conflict_queue") or []) if isinstance(row, Mapping)]
        ambiguity_queue = [row for row in list(conflicts.get("ambiguity_queue") or []) if isinstance(row, Mapping)]
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "counts": dict(conflicts.get("counts") or {}),
            "conflict_queue": conflict_queue[: self.config.max_list_limit],
            "ambiguity_queue": ambiguity_queue[: self.config.max_list_limit],
            "truncated": len(conflict_queue) > self.config.max_list_limit or len(ambiguity_queue) > self.config.max_list_limit,
        }

    def _tool_wizard_organizer_package(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/organizer/package", payload)
        package = dict(response.get("package") or {}) if isinstance(response.get("package"), Mapping) else {}
        safe_ops = [row for row in list(package.get("safe_operations") or []) if isinstance(row, Mapping)]
        review_ops = [row for row in list(package.get("review_operations") or []) if isinstance(row, Mapping)]
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "package_id": str(package.get("package_id") or "").strip(),
            "counts": dict(package.get("counts") or {}),
            "safe_operations": safe_ops[: self.config.max_list_limit],
            "review_operations": review_ops[: self.config.max_list_limit],
            "truncated": len(safe_ops) > self.config.max_list_limit or len(review_ops) > self.config.max_list_limit,
        }

    def _tool_wizard_organizer_apply(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        dry_run = bool(args.get("dry_run"))
        payload: dict[str, Any] = {"dry_run": dry_run}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/organizer/apply", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "applied": bool(response.get("applied", False)),
            "dry_run": bool(response.get("dry_run", dry_run)),
            "rollback_id": str(response.get("rollback_id") or "").strip(),
            "safe_operation_count": int(response.get("safe_operation_count") or 0),
            "profile": dict(response.get("profile") or response.get("profile_preview") or {}),
        }

    def _tool_wizard_organizer_verify(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/organizer/verify", payload)
        verify = dict(response.get("verify") or {}) if isinstance(response.get("verify"), Mapping) else {}
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "status": str(verify.get("status") or "").strip().lower(),
            "metrics": dict(verify.get("metrics") or {}),
            "recommendation": str(verify.get("recommendation") or "").strip(),
        }

    def _tool_wizard_organizer_restore_last(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        if bool(args.get("dry_run")):
            return {"ok": True, "applied": False, "restored": False, "remaining_snapshots": 0}
        payload: dict[str, Any] = {}
        run_id = str(args.get("run_id") or "").strip() or None
        if run_id:
            payload["run_id"] = run_id
        response = self.api_client.post_json("/api/wizard/organizer/restore-last", payload)
        return {
            "ok": bool(response.get("ok", True)),
            "run_id": str(response.get("run_id") or "").strip(),
            "restored": bool(response.get("restored", False)),
            "snapshot": dict(response.get("snapshot") or {}),
            "remaining_snapshots": int(response.get("remaining_snapshots") or 0),
            "applied_profile": dict(response.get("applied_profile") or {}),
        }

    def _tool_wizard_organizer_run(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_mutations_enabled()
        run_id = str(args.get("run_id") or "").strip() or None
        include_stage_payloads = bool(args.get("include_stage_payloads"))
        apply_changes = bool(args.get("apply_changes"))
        dry_run = bool(args.get("dry_run"))
        base_args: dict[str, Any] = {}
        if run_id:
            base_args["run_id"] = run_id

        inventory = self._tool_wizard_organizer_inventory(dict(base_args))
        dedupe = self._tool_wizard_organizer_dedupe(dict(base_args))
        conflicts = self._tool_wizard_organizer_conflicts(dict(base_args))
        package = self._tool_wizard_organizer_package(dict(base_args))

        apply_result: dict[str, Any] = {
            "ok": True,
            "applied": False,
            "dry_run": False,
            "safe_operation_count": int(dict(package.get("counts") or {}).get("safe_operations") or 0),
            "profile": {},
        }
        if apply_changes or dry_run:
            apply_args = dict(base_args)
            apply_args["dry_run"] = dry_run or not apply_changes
            apply_result = self._tool_wizard_organizer_apply(apply_args)

        verify = self._tool_wizard_organizer_verify(dict(base_args))
        effective_run_id = (
            str(run_id or "")
            or str(inventory.get("run_id") or "")
            or str(dedupe.get("run_id") or "")
            or str(conflicts.get("run_id") or "")
            or str(package.get("run_id") or "")
            or str(verify.get("run_id") or "")
        )
        counts = {
            "typed_candidates": int(dict(inventory.get("counts") or {}).get("typed_candidates") or 0),
            "dedupe_proposals": int(dict(dedupe.get("counts") or {}).get("proposal_count") or 0),
            "conflicts": int(dict(conflicts.get("counts") or {}).get("conflicts") or 0),
            "ambiguities": int(dict(conflicts.get("counts") or {}).get("ambiguities") or 0),
            "safe_operations": int(dict(package.get("counts") or {}).get("safe_operations") or 0),
            "review_operations": int(dict(package.get("counts") or {}).get("review_operations") or 0),
            "applied_safe_operations": int(apply_result.get("safe_operation_count") or 0),
        }
        summary: dict[str, Any] = {
            "ok": bool(
                inventory.get("ok", False)
                and dedupe.get("ok", False)
                and conflicts.get("ok", False)
                and package.get("ok", False)
                and verify.get("ok", False)
                and apply_result.get("ok", False)
            ),
            "run_id": effective_run_id,
            "status": str(verify.get("status") or "").strip().lower() or "unknown",
            "counts": counts,
            "applied": bool(apply_result.get("applied", False)),
            "dry_run": bool(apply_result.get("dry_run", False)),
            "recommendation": str(verify.get("recommendation") or "").strip(),
        }
        if include_stage_payloads:
            summary["stages"] = {
                "inventory": inventory,
                "dedupe": dedupe,
                "conflicts": conflicts,
                "package": package,
                "apply": apply_result,
                "verify": verify,
            }
        return summary

    def _handle_initialize(self, params: dict[str, Any], *, client_key: str | None = None) -> dict[str, Any]:
        auth_token = params.get("auth_token")
        if auth_token is not None and not isinstance(auth_token, str):
            raise MCPRequestError(-32602, "initialize.auth_token must be a string when provided")
        self._session_role = self.config.auth.resolve_role(auth_token if isinstance(auth_token, str) else None)
        self._client_info = dict(params.get("clientInfo") or {}) if isinstance(params.get("clientInfo"), Mapping) else {}
        if client_key:
            self._initialized_clients.add(client_key)
        else:
            self._initialized = True
        return {
            "protocolVersion": self.config.protocol_version,
            "serverInfo": {"name": "numquamoblita-mcp", "version": self.config.server_version},
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
        }

    def _ensure_initialized(self, *, client_key: str | None = None) -> None:
        if client_key:
            if self.config.transport == "http" and not self.config.auth.require_auth:
                # Native Claude HTTP clients can treat loopback MCP servers as stateless
                # and skip an explicit initialize round-trip after reconnects. In no-auth
                # mode there is no role or token state to negotiate, so the local managed
                # HTTP sidecar can safely auto-initialize per client key.
                self._initialized_clients.add(client_key)
                return
            if client_key not in self._initialized_clients:
                raise MCPRequestError(-32002, "server is not initialized")
            return
        if not self._initialized:
            raise MCPRequestError(-32002, "server is not initialized")

    def _handle_tools_list(self, *, client_key: str | None = None) -> dict[str, Any]:
        self._ensure_initialized(client_key=client_key)
        tools: list[dict[str, Any]] = []
        for name in sorted(self._tools.keys()):
            spec = self._tools[name]
            if not _role_allows(self._session_role, spec.permission):
                continue
            item = {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.input_schema,
            }
            if self._compat_mode_enabled():
                item["input_schema"] = spec.input_schema
            tools.append(item)
        return {"tools": tools}

    def _handle_tools_call(self, params: dict[str, Any], *, client_key: str | None = None) -> dict[str, Any]:
        self._ensure_initialized(client_key=client_key)
        name = str(params.get("name") or "").strip()
        if not name:
            raise MCPRequestError(-32602, "tools/call requires name")
        spec = self._tools.get(name)
        if spec is None:
            raise MCPRequestError(-32602, f"unknown tool: {name}")
        if not _role_allows(self._session_role, spec.permission):
            raise MCPRequestError(-32002, f"role '{self._session_role}' cannot call '{name}'")

        raw_args = params.get("arguments", None)
        if raw_args is None and self._compat_mode_enabled():
            raw_args = params.get("args", None)
        if raw_args is None:
            args: dict[str, Any] = {}
        elif isinstance(raw_args, Mapping):
            args = dict(raw_args)
        else:
            raise MCPRequestError(-32602, "tools/call requires 'arguments' to be an object")
        _validate_args(args, spec.input_schema)
        try:
            output = spec.handler(args)
        except RuntimeApiError as exc:
            raise MCPRequestError(
                -32003,
                "runtime upstream request failed",
                data={"status_code": exc.status_code, "detail": exc.detail},
            ) from exc

        text = json.dumps(output, ensure_ascii=True, separators=(",", ":"))
        result = {
            "structuredContent": output,
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
        if self._compat_mode_enabled():
            result["structured_content"] = output
            result["is_error"] = False
        return result

    def _handle_resources_list(self, *, client_key: str | None = None) -> dict[str, Any]:
        self._ensure_initialized(client_key=client_key)
        return {
            "resources": [
                {
                    "uri": "resource://capabilities",
                    "name": "Capabilities",
                    "description": "Current MCP capabilities, roles, limits, and enabled tools.",
                    "mimeType": "application/json",
                },
                {
                    "uri": "resource://audit/summary",
                    "name": "Audit Summary",
                    "description": "Recent MCP request audit summary and error counts.",
                    "mimeType": "application/json",
                },
            ]
        }

    def _handle_resources_read(self, params: dict[str, Any], *, client_key: str | None = None) -> dict[str, Any]:
        self._ensure_initialized(client_key=client_key)
        uri = str(params.get("uri") or "").strip()
        if not uri:
            raise MCPRequestError(-32602, "resources/read requires uri")
        payload = self._resource_payload(uri)
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                }
            ]
        }

    def _handle_prompts_list(self, *, client_key: str | None = None) -> dict[str, Any]:
        self._ensure_initialized(client_key=client_key)
        rows: list[dict[str, Any]] = []
        for item in self._prompts.values():
            rows.append(
                {
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                }
            )
        return {"prompts": rows}

    def _handle_prompts_get(self, params: dict[str, Any], *, client_key: str | None = None) -> dict[str, Any]:
        self._ensure_initialized(client_key=client_key)
        name = str(params.get("name") or "").strip()
        if not name:
            raise MCPRequestError(-32602, "prompts/get requires name")
        prompt = self._prompts.get(name)
        if prompt is None:
            raise MCPRequestError(-32602, f"unknown prompt: {name}")
        return {
            "description": str(prompt.get("description") or ""),
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": str(prompt.get("template") or ""),
                    },
                }
            ],
        }

    def handle_request(self, payload: dict[str, Any], *, client_key: str | None = None) -> dict[str, Any] | None:
        if not isinstance(payload, Mapping):
            return self._error_response(None, -32600, "invalid request payload")

        request_id = payload.get("id")
        method = str(payload.get("method") or "").strip()
        method = self._normalize_method(method)
        params = payload.get("params")
        if params is None:
            params_obj: dict[str, Any] = {}
        elif isinstance(params, Mapping):
            params_obj = dict(params)
        else:
            return self._error_response(request_id, -32602, "params must be an object")
        if not method:
            return self._error_response(request_id, -32600, "method is required")

        if method.startswith("notifications/"):
            started = time.perf_counter()
            if method == "notifications/initialized":
                self._record_audit(method=method, status="ok", request_id=request_id, started=started)
                return None
            self._record_audit(method=method, status="ok", request_id=request_id, started=started)
            return None

        started = time.perf_counter()
        try:
            if method == "initialize":
                result = self._handle_initialize(params_obj, client_key=client_key)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self._handle_tools_list(client_key=client_key)
            elif method == "tools/call":
                result = self._handle_tools_call(params_obj, client_key=client_key)
            elif method == "resources/list":
                result = self._handle_resources_list(client_key=client_key)
            elif method == "resources/read":
                result = self._handle_resources_read(params_obj, client_key=client_key)
            elif method == "prompts/list":
                result = self._handle_prompts_list(client_key=client_key)
            elif method == "prompts/get":
                result = self._handle_prompts_get(params_obj, client_key=client_key)
            else:
                raise MCPRequestError(-32601, f"method not found: {method}")
            self._record_audit(method=method, status="ok", request_id=request_id, started=started)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except MCPRequestError as exc:
            self._record_audit(
                method=method,
                status="error",
                request_id=request_id,
                started=started,
                error_code=exc.code,
            )
            return self._error_response(request_id, exc.code, exc.message, data=exc.data)
        except Exception as exc:
            self._record_audit(
                method=method,
                status="error",
                request_id=request_id,
                started=started,
                error_code=-32000,
            )
            return self._error_response(
                request_id,
                -32000,
                "internal error",
                data={"detail": str(exc)},
            )

    @staticmethod
    def _error_response(request_id: Any, code: int, message: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": int(code),
                "message": str(message),
            },
        }
        if isinstance(data, dict):
            payload["error"]["data"] = data
        return payload


def _read_message(stdin_buffer: Any) -> dict[str, Any] | None:
    content_length: int | None = None
    while True:
        line = stdin_buffer.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        key, sep, value = text.partition(":")
        if not sep:
            continue
        if key.strip().lower() == "content-length":
            try:
                content_length = int(value.strip())
            except ValueError as exc:
                raise RuntimeError("invalid Content-Length header") from exc

    if content_length is None or content_length < 0:
        raise RuntimeError("missing Content-Length header")

    body = stdin_buffer.read(content_length)
    if body is None:
        return None
    if len(body) != content_length:
        raise RuntimeError("incomplete message body")
    try:
        decoded = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid JSON body") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("JSON body must be an object")
    return decoded


def _write_message(stdout_buffer: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8")
    stdout_buffer.write(header)
    stdout_buffer.write(body)
    stdout_buffer.flush()


def run_stdio_server(server: MCPServer, *, stdin_buffer: Any, stdout_buffer: Any) -> int:
    while True:
        try:
            request_payload = _read_message(stdin_buffer)
        except RuntimeError:
            _stdio_trace_log({"ts": _utc_iso(), "event": "parse_error"})
            _write_message(
                stdout_buffer,
                MCPServer._error_response(None, -32700, "Parse error"),
            )
            continue
        if request_payload is None:
            _stdio_trace_log({"ts": _utc_iso(), "event": "stdin_closed"})
            return 0
        method = str(request_payload.get("method") or "")
        params = dict(request_payload.get("params") or {}) if isinstance(request_payload.get("params"), Mapping) else {}
        _stdio_trace_log(
            {
                "ts": _utc_iso(),
                "event": "request",
                "id": request_payload.get("id"),
                "method": method,
                "params_keys": sorted(list(params.keys())),
                "params": params if method == "initialize" else None,
            }
        )
        response_payload = server.handle_request(request_payload)
        if response_payload is not None:
            _stdio_trace_log(
                {
                    "ts": _utc_iso(),
                    "event": "response",
                    "id": response_payload.get("id"),
                    "has_error": "error" in response_payload,
                    "result_keys": sorted(list(dict(response_payload.get("result") or {}).keys())) if isinstance(response_payload.get("result"), Mapping) else [],
                    "result": dict(response_payload.get("result") or {}) if method == "initialize" and isinstance(response_payload.get("result"), Mapping) else None,
                    "error": dict(response_payload.get("error") or {}) if isinstance(response_payload.get("error"), Mapping) else None,
                }
            )
            _write_message(stdout_buffer, response_payload)


def _extract_bearer_token(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    prefix = "bearer "
    if raw.lower().startswith(prefix):
        token = raw[len(prefix) :].strip()
        return token or None
    return raw


class _MCPHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, server_address: tuple[str, int], mcp_server: MCPServer):
        super().__init__(server_address, _MCPHTTPHandler)
        self.mcp_server = mcp_server


class _MCPHTTPHandler(BaseHTTPRequestHandler):
    server: _MCPHTTPServer

    def do_POST(self) -> None:  # noqa: N802
        mcp_server = self.server.mcp_server
        observed_proto = "http"
        if mcp_server.config.trust_proxy_headers:
            observed_proto = str(self.headers.get("X-Forwarded-Proto") or "http").strip().lower() or "http"
        auth_token = _extract_bearer_token(self.headers.get("Authorization"))
        client_ip = str(self.client_address[0] if self.client_address else "")
        path = str(self.path or "")
        client_key: str | None = None
        content_length = 0
        nonce_header = str(self.headers.get("X-MCP-Nonce") or "").strip()

        if path.rstrip("/") != "/mcp":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.NOT_FOUND.value,
                outcome="rejected",
                reason="route_not_found",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=0,
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        if mcp_server.config.enforce_https and observed_proto != "https":
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "https is required by server policy"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.FORBIDDEN.value,
                outcome="rejected",
                reason="https_required",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=0,
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length header"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.BAD_REQUEST.value,
                outcome="rejected",
                reason="invalid_content_length",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=0,
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        if content_length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "request body is required"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.BAD_REQUEST.value,
                outcome="rejected",
                reason="missing_body",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        if content_length > mcp_server.config.http_max_request_bytes:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request body exceeds limit"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE.value,
                outcome="rejected",
                reason="request_body_exceeds_limit",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.BAD_REQUEST.value,
                outcome="rejected",
                reason="invalid_json",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "json body must be an object"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.BAD_REQUEST.value,
                outcome="rejected",
                reason="invalid_payload_shape",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return

        try:
            role = mcp_server.config.auth.resolve_role(auth_token)
        except MCPRequestError as exc:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": exc.message, "code": exc.code})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.UNAUTHORIZED.value,
                outcome="rejected",
                reason="auth_failed",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=None,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return

        key_token: str | None = auth_token
        if key_token is None:
            params = payload.get("params")
            if isinstance(params, Mapping):
                param_token = params.get("auth_token")
                if isinstance(param_token, str):
                    token_text = param_token.strip()
                    key_token = token_text or None
        if key_token is None:
            key_token = "anon"
        client_key = f"{self.client_address[0]}:{key_token}"
        if nonce_header and len(nonce_header) > 256:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid nonce"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.BAD_REQUEST.value,
                outcome="rejected",
                reason="invalid_nonce",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=client_key,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        if nonce_header and not mcp_server.allow_http_nonce(client_key=client_key, nonce=nonce_header):
            self._send_json(HTTPStatus.CONFLICT, {"error": "replay nonce already used"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.CONFLICT.value,
                outcome="rejected",
                reason="replay_nonce_detected",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=client_key,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        if not mcp_server.allow_http_request(client_key=client_key):
            self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "rate limit exceeded"})
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.TOO_MANY_REQUESTS.value,
                outcome="rejected",
                reason="rate_limited",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=client_key,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return

        with mcp_server._state_lock:
            mcp_server._session_role = role
            if str(payload.get("method") or "").strip() == "initialize":
                params = payload.get("params")
                if isinstance(params, dict) and "auth_token" not in params and auth_token:
                    params = dict(params)
                    params["auth_token"] = auth_token
                    payload = dict(payload)
                    payload["params"] = params
            response = mcp_server.handle_request(payload, client_key=client_key)
        if response is None:
            self.send_response(HTTPStatus.NO_CONTENT.value)
            self.end_headers()
            mcp_server._record_http_security_event(
                path=path,
                status_code=HTTPStatus.NO_CONTENT.value,
                outcome="ok",
                reason="notification_no_content",
                client_ip=client_ip,
                auth_token=auth_token,
                client_key=client_key,
                request_bytes=max(0, int(content_length)),
                observed_proto=observed_proto,
                nonce=nonce_header,
            )
            return
        self._send_json(HTTPStatus.OK, response)
        mcp_server._record_http_security_event(
            path=path,
            status_code=HTTPStatus.OK.value,
            outcome="ok",
            reason="request_completed",
            client_ip=client_ip,
            auth_token=auth_token,
            client_key=client_key,
            request_bytes=max(0, int(content_length)),
            observed_proto=observed_proto,
            nonce=nonce_header,
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in {"", "/"}:
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "numquamoblita-mcp-http",
                    "path": "/mcp",
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_http_server(mcp_server: MCPServer, *, host: str, port: int) -> tuple[_MCPHTTPServer, threading.Thread]:
    http_server = _MCPHTTPServer((host, int(port)), mcp_server)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    return http_server, thread


def stop_http_server(http_server: _MCPHTTPServer, thread: threading.Thread) -> None:
    http_server.shutdown()
    http_server.server_close()
    thread.join(timeout=5)


def run_http_server(mcp_server: MCPServer, *, host: str, port: int) -> int:
    http_server = _MCPHTTPServer((host, int(port)), mcp_server)
    try:
        http_server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        http_server.server_close()
