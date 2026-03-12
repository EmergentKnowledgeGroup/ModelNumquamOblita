from __future__ import annotations

from collections import deque
import base64
import json
import logging
import os
import re
import shutil
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import uuid4

from ..config import default_config
from ..continuity import Consolidator, ContinuityBuilder, SharedLanguageRegistry
from ..contracts import AtomType, CandidateAtom, RetrievalOverrideRequestContract, SourceRef
from ..memory import AtomStatus, MutationReviewQueue, ProposalStatus, SqliteAtomStore
from .adapters import AdapterRegistry, build_default_registry
from .methodology import (
    build_operator_readout,
    create_methodology_record,
    evaluate_maintenance_triggers,
    evaluate_methodology_canary,
    list_correction_clusters,
    list_methodology_records,
    load_methodology_state,
    persist_methodology_state,
    promote_methodology_to_canary,
    record_correction_event,
    review_methodology_record,
    rollback_methodology_record,
    activate_methodology_record,
)
from .session import RuntimeSession
from .live_eval import load_inmemory_store_from_json

UI_ROOT = Path(__file__).resolve().parent / "ui"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "runtime"
WIZARD_RUNS_ROOT = RUNTIME_ROOT / "wizard_runs"
WIZARD_LATEST_PATH = WIZARD_RUNS_ROOT / "LATEST.json"
BUILDER_PROFILES_ROOT = RUNTIME_ROOT / "builder_profiles"
EPISODES_ROOT = RUNTIME_ROOT / "episodes"
BACKUPS_ROOT = RUNTIME_ROOT / "backups"
DIAGNOSTICS_ROOT = RUNTIME_ROOT / "diagnostics"
PACKAGING_ROOT = RUNTIME_ROOT / "packaging"
LIVE_RUNTIME_LOCK_PATH = RUNTIME_ROOT / "live_runtime.lock.json"
PACKAGING_GUIDE_PATH = REPO_ROOT / "docs" / "OPERATOR_SETUP_AND_DIAGNOSTICS.md"
WINDOWS_PACKAGING_SCRIPT_PY = REPO_ROOT / "tools" / "build_windows_single_exe.py"
WINDOWS_PACKAGING_SCRIPT_PS1 = REPO_ROOT / "tools" / "build_windows_single_exe.ps1"
WINDOWS_PACKAGING_SCRIPT_BAT = REPO_ROOT / "tools" / "build_windows_single_exe.bat"
LOGGER = logging.getLogger(__name__)
WIZARD_RUN_ID_PATTERN = re.compile(r"^wizard_[A-Za-z0-9_-]+$")
GRAPH_NEIGHBOR_DEFAULT_DEPTH = 1
GRAPH_NEIGHBOR_MAX_DEPTH = 2
GRAPH_NEIGHBOR_DEFAULT_NODE_LIMIT = 60
GRAPH_NEIGHBOR_MAX_NODE_LIMIT = 120
GRAPH_NEIGHBOR_DEFAULT_LINK_LIMIT = 120
GRAPH_NEIGHBOR_MAX_LINK_LIMIT = 240
GRAPH_NEIGHBOR_REQUEST_BUDGET = 12
GRAPH_NEIGHBOR_EXPANDABLE_EDGE_ORDER = ("conflict", "constellation", "narrative_arc")
GRAPH_NEIGHBOR_RECORD_ONLY_EDGE_ORDER = ("shared_language",)


def _canonical_graph_link_key(source: str, target: str, kind: str) -> tuple[str, str, str]:
    left, right = sorted((str(source), str(target)))
    return left, right, str(kind)


ROUTE_REASON_DESCRIPTIONS: dict[str, str] = {
    "smalltalk_routine": "Routine small talk, memory lookup skipped.",
    "casual_prompt_no_recall": "Casual prompt with no memory signal, memory lookup skipped.",
    "ambiguous_low_signal_skip": "Ambiguous low-signal prompt, memory lookup skipped.",
    "thread_local_reference": "Prompt references recent thread context, STM route selected.",
    "explicit_memory_request": "Prompt asks for remembered details, deep route selected.",
    "memory_signal_probe": "Prompt includes memory signal terms, light retrieval selected.",
    "default_memory_probe": "Default route for non-routine prompts.",
    "retrieval_query_override": "Caller provided retrieval query override, light retrieval selected.",
    "high_risk_escalation": "High-risk flag escalates retrieval to deep route.",
    "memory_preference_chat_first": "Chat-first preference reduced memory retrieval.",
    "memory_preference_memory_assist": "Memory-assist preference expanded retrieval.",
    "identity_relationship_probe": "Identity or relationship query forces memory lookup.",
    "name_frequency_trigger": "Known recurring person/entity name forces memory lookup.",
}


def _retrieval_override_from_payload(
    payload: Mapping[str, Any],
    *,
    default_invoker: str,
    default_scope: str,
    default_reason: str,
    default_auth_context: str,
) -> RetrievalOverrideRequestContract | None:
    override_raw = payload.get("retrieval_override")
    if not isinstance(override_raw, Mapping):
        return None
    query = str(override_raw.get("query") or "").strip()
    if not query:
        return None
    invoker = str(override_raw.get("invoker") or default_invoker).strip() or default_invoker
    reason = str(override_raw.get("reason") or default_reason).strip() or default_reason
    scope = str(override_raw.get("scope") or default_scope).strip() or default_scope
    auth_context = str(default_auth_context or "internal").strip() or "internal"
    return RetrievalOverrideRequestContract(
        query=query,
        invoker=invoker,
        reason=reason,
        scope=scope,
        auth_context=auth_context,
    )

EXPLORATION_ALLOWED_ACTIONS = {"pin", "more", "less", "ignore", "clear"}
EXPLORATION_ALLOWED_TYPES = {"person", "project", "topic", "event", "unknown"}
EXPLORATION_PREFERENCE_WEIGHTS: dict[str, float] = {
    "pin": 2.0,
    "more": 1.0,
    "less": -0.8,
    "ignore": -2.5,
}
QUICKNOTE_STATE_SCHEMA = "numquamoblita.runtime.quicknote_state.v1"
QUICKNOTE_STATE_PATH = DIAGNOSTICS_ROOT / "quicknote_state.json"
METHODOLOGY_STATE_PATH = DIAGNOSTICS_ROOT / "methodology_state.json"
QUICKNOTE_ALLOWED_IMPORTANCE = {"low", "normal", "high", "critical"}
QUICKNOTE_ALLOWED_CONTEXT_PRESSURE = {"low", "medium", "high"}
QUICKNOTE_ALLOWED_FLUSH_REASONS = {
    "manual",
    "inactivity_timeout",
    "session_rollover",
    "cap_reached",
    "context_pressure_high",
    "operator_reset",
}

BUILD_POLICY_PRESETS: dict[str, dict[str, Any]] = {
    "strict": {
        "label": "Strict event grade",
        "min_atoms": 3,
        "min_meaningful_tokens": 30,
        "min_evidence_strength": 0.35,
        "allow_single_strong": False,
    },
    "balanced": {
        "label": "Balanced",
        "min_atoms": 3,
        "min_meaningful_tokens": 24,
        "min_evidence_strength": 0.30,
        "allow_single_strong": False,
    },
    "assist": {
        "label": "Memory assist",
        "min_atoms": 2,
        "min_meaningful_tokens": 16,
        "min_evidence_strength": 0.22,
        "allow_single_strong": True,
    },
}

WIZARD_STAGES = [
    "import",
    "build_episodes",
    "review",
    "publish",
    "verify",
    "activate",
    "operate",
]
WIZARD_STAGE_SEQUENCE = tuple(WIZARD_STAGES)
WIZARD_STAGE_INDEX = {stage: index for index, stage in enumerate(WIZARD_STAGE_SEQUENCE)}
WIZARD_VALID_INPUT_KINDS = {"ia_archive", "mno_store_sqlite", "mno_store_json"}
WIZARD_VALID_STORE_KINDS = {"mno_store_sqlite", "mno_store_json"}
WIZARD_VERIFY_STATUSES = {"Unknown", "Safe", "Needs attention", "Blocked"}
WIZARD_PRIMARY_CHECK_IDS_BLOCK = {
    "selected_input",
    "store_validation",
    "draft_cards",
    "published_set",
    "published_store_match",
    "published_schema_match",
    "published_build_match",
}
WIZARD_STAGE_BYPASS_ACTIONS = {"start", "import_validate", "import_run"}

INTEGRATION_SCHEMA_VERSION = "integration.v1"
INTEGRATION_REQUEST_ID_RE = re.compile(r"^req_[A-Za-z0-9_-]{16,64}$")
INTEGRATION_ALLOWED_ROLES = {"viewer", "operator", "admin"}
INTEGRATION_MAX_GENERIC_STRING = 4096
INTEGRATION_MAX_CONTEXT_TEXT = 120000
INTEGRATION_MAX_ARRAY_ITEMS = 100
INTEGRATION_MAX_WARNINGS = 16
INTEGRATION_MAX_EVIDENCE = 30
INTEGRATION_MAX_NESTING_DEPTH = 6
INTEGRATION_IDEMPOTENCY_WINDOW_S = 24 * 60 * 60
INTEGRATION_TOKEN_OVERLAP_S = 15 * 60
INTEGRATION_AUTH_CACHE_TTL_S = 60.0
INTEGRATION_ERROR_HTTP_STATUS: dict[str, HTTPStatus] = {
    "INVALID_INPUT": HTTPStatus.BAD_REQUEST,
    "AUTH_REQUIRED": HTTPStatus.UNAUTHORIZED,
    "AUTH_FORBIDDEN": HTTPStatus.FORBIDDEN,
    "RATE_LIMITED": HTTPStatus.TOO_MANY_REQUESTS,
    "DEPENDENCY_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
    "TIMEOUT": HTTPStatus.GATEWAY_TIMEOUT,
    "CONTRACT_VERSION_UNSUPPORTED": HTTPStatus.UPGRADE_REQUIRED,
    "INTERNAL_ERROR": HTTPStatus.INTERNAL_SERVER_ERROR,
}
INTEGRATION_OPERATION_SLA_MS: dict[str, int] = {
    "health.get": 150,
    "capabilities.get": 150,
    "context.build": 2000,
    "writeback.propose": 1500,
    "writeback.resolve": 2500,
    "context.why": 2000,
}
INTEGRATION_OPERATION_TIMEOUT_MS: dict[str, int] = {
    "context.build": 4000,
    "context.why": 4000,
    "writeback.propose": 3000,
    "writeback.resolve": 2500,
}
INTEGRATION_REQUIRED_ROLES: dict[str, set[str]] = {
    "context.build": {"viewer", "operator", "admin"},
    "context.why": {"viewer", "operator", "admin"},
    "writeback.propose": {"operator", "admin"},
    "writeback.resolve": {"operator", "admin"},
    "health.get": {"viewer", "operator", "admin"},
    "capabilities.get": {"viewer", "operator", "admin"},
}
INTEGRATION_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
INTEGRATION_PHONE_RE = re.compile(r"\b(?:\+?1[\s\-]?)?(?:\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4})\b")
INTEGRATION_SECRET_KEY_RE = re.compile(r"(token|secret|authorization|password|api[_-]?key)", re.IGNORECASE)


class IntegrationContractError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        operator_action: str,
        status: HTTPStatus | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.retryable = bool(retryable)
        self.operator_action = str(operator_action)
        self.status = status or INTEGRATION_ERROR_HTTP_STATUS.get(self.code, HTTPStatus.BAD_REQUEST)


class IntegrationAuthManager:
    def __init__(
        self,
        *,
        token_file: Path | None,
        jwt_secret: str,
        default_tokens: dict[str, dict[str, Any]],
        auth_cache_ttl_s: float = INTEGRATION_AUTH_CACHE_TTL_S,
        overlap_window_s: float = INTEGRATION_TOKEN_OVERLAP_S,
        secret_manager_provider: str = "none",
        secret_manager_env_var: str = "NO_INTEGRATION_SECRET_MANAGER_JSON",
        secret_manager_command: str = "",
        secret_manager_timeout_s: float = 5.0,
        secret_manager_refresh_interval_s: float = 10.0,
    ) -> None:
        self._token_file = token_file
        self._jwt_secret = str(jwt_secret or "")
        self._default_tokens = dict(default_tokens)
        self._auth_cache_ttl_s = max(1.0, float(auth_cache_ttl_s))
        self._overlap_window_s = max(0.0, float(overlap_window_s))
        self._secret_manager_provider = str(secret_manager_provider or "none").strip().lower() or "none"
        self._secret_manager_env_var = str(secret_manager_env_var or "NO_INTEGRATION_SECRET_MANAGER_JSON").strip() or "NO_INTEGRATION_SECRET_MANAGER_JSON"
        self._secret_manager_command = str(secret_manager_command or "").strip()
        self._secret_manager_timeout_s = max(1.0, float(secret_manager_timeout_s))
        self._secret_manager_refresh_interval_s = max(1.0, float(secret_manager_refresh_interval_s))
        self._active_tokens: dict[str, dict[str, Any]] = {}
        self._grace_tokens: dict[str, tuple[dict[str, Any], float]] = {}
        self._auth_cache: dict[str, tuple[dict[str, Any], float]] = {}
        self._cached_file_payload: dict[str, Any] = {}
        self._cached_secret_payload: dict[str, Any] = {}
        self._last_file_mtime_ns: int | None = None
        self._last_reload_monotonic: float = 0.0
        self._last_secret_reload_monotonic: float = 0.0
        self._lock = threading.Lock()
        self.refresh(force=True)

    @classmethod
    def from_env(cls) -> "IntegrationAuthManager":
        runtime_mode = str(os.getenv("NO_INTEGRATION_RUNTIME_MODE", "development") or "").strip().lower()
        production_mode = runtime_mode in {"production", "prod"}
        token_file_raw = str(os.getenv("NO_INTEGRATION_TOKENS_FILE", "") or "").strip()
        token_file = Path(token_file_raw).expanduser().resolve() if token_file_raw else None
        secret_manager_provider = str(os.getenv("NO_INTEGRATION_SECRET_MANAGER_PROVIDER", "none") or "").strip().lower() or "none"
        secret_manager_env_var = str(os.getenv("NO_INTEGRATION_SECRET_MANAGER_ENV", "NO_INTEGRATION_SECRET_MANAGER_JSON") or "").strip() or "NO_INTEGRATION_SECRET_MANAGER_JSON"
        secret_manager_command = str(os.getenv("NO_INTEGRATION_SECRET_MANAGER_COMMAND", "") or "").strip()
        if secret_manager_provider not in {"none", "env_json", "command"}:
            raise ValueError("NO_INTEGRATION_SECRET_MANAGER_PROVIDER must be one of: none, env_json, command")
        timeout_raw = str(os.getenv("NO_INTEGRATION_SECRET_MANAGER_TIMEOUT_S", "5") or "5")
        try:
            secret_manager_timeout_s = float(timeout_raw)
        except Exception:
            secret_manager_timeout_s = 5.0
        default_tokens: dict[str, dict[str, Any]] = {}
        disabled_defaults = str(os.getenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "")).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        enabled_defaults = str(os.getenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", "")).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if production_mode and enabled_defaults and not disabled_defaults:
            raise ValueError("default integration tokens are forbidden in production mode")
        if production_mode and secret_manager_provider == "none" and token_file is None:
            raise ValueError(
                "production mode requires NO_INTEGRATION_TOKENS_FILE or NO_INTEGRATION_SECRET_MANAGER_PROVIDER"
            )
        if production_mode and token_file is None and secret_manager_provider == "command" and not secret_manager_command:
            raise ValueError(
                "production mode with command secret manager requires NO_INTEGRATION_SECRET_MANAGER_COMMAND"
            )
        if enabled_defaults and not disabled_defaults:
            viewer_token = str(os.getenv("NO_INTEGRATION_VIEWER_TOKEN", "local-integration-viewer-token") or "").strip()
            operator_token = str(os.getenv("NO_INTEGRATION_OPERATOR_TOKEN", "local-integration-operator-token") or "").strip()
            admin_token = str(os.getenv("NO_INTEGRATION_ADMIN_TOKEN", "local-integration-admin-token") or "").strip()
            if viewer_token:
                default_tokens[viewer_token] = {
                    "principal_id": "integration_viewer",
                    "roles": ["viewer"],
                }
            if operator_token:
                default_tokens[operator_token] = {
                    "principal_id": "integration_operator",
                    "roles": ["operator"],
                }
            if admin_token:
                default_tokens[admin_token] = {
                    "principal_id": "integration_admin",
                    "roles": ["admin"],
                }
        jwt_secret = str(os.getenv("NO_INTEGRATION_JWT_HS256_SECRET", "") or "").strip()
        return cls(
            token_file=token_file,
            jwt_secret=jwt_secret,
            default_tokens=default_tokens,
            secret_manager_provider=secret_manager_provider,
            secret_manager_env_var=secret_manager_env_var,
            secret_manager_command=secret_manager_command,
            secret_manager_timeout_s=secret_manager_timeout_s,
        )

    @property
    def secret_manager_enabled(self) -> bool:
        return self._secret_manager_provider != "none"

    def _load_secret_manager_payload(self) -> dict[str, Any]:
        provider = self._secret_manager_provider
        if provider == "none":
            return {}
        if provider == "env_json":
            raw_payload = str(os.getenv(self._secret_manager_env_var, "") or "").strip()
            if not raw_payload:
                return {}
            parsed = json.loads(raw_payload)
            return parsed if isinstance(parsed, dict) else {}
        if provider == "command":
            if not self._secret_manager_command:
                return {}
            try:
                command_parts = shlex.split(self._secret_manager_command)
            except ValueError:
                return {}
            if not command_parts:
                return {}
            completed = subprocess.run(
                command_parts,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._secret_manager_timeout_s,
            )
            if int(completed.returncode or 0) != 0:
                return {}
            parsed = json.loads(str(completed.stdout or "").strip() or "{}")
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _decode_jwt_payload(self, token: str) -> dict[str, Any] | None:
        parts = str(token or "").split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts
        if not self._jwt_secret:
            return None
        try:
            header_raw = base64.urlsafe_b64decode(self._pad_b64(header_b64))
            payload_raw = base64.urlsafe_b64decode(self._pad_b64(payload_b64))
            signature_raw = base64.urlsafe_b64decode(self._pad_b64(signature_b64))
            header_obj = json.loads(header_raw.decode("utf-8"))
            payload_obj = json.loads(payload_raw.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(header_obj, dict) or not isinstance(payload_obj, dict):
            return None
        if str(header_obj.get("alg") or "").strip().upper() != "HS256":
            return None
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected = hmac.new(self._jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature_raw):
            return None
        exp = payload_obj.get("exp")
        if isinstance(exp, (int, float)):
            if float(exp) <= float(time.time()):
                return None
        return payload_obj

    @staticmethod
    def _pad_b64(value: str) -> bytes:
        raw = str(value or "")
        padded = raw + "=" * ((4 - (len(raw) % 4)) % 4)
        return padded.encode("utf-8")

    def _load_token_file(self) -> dict[str, Any]:
        if self._token_file is None:
            return {}
        if not self._token_file.exists():
            return {}
        payload = json.loads(self._token_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        return payload

    def _maybe_refresh_secret_payload(self, *, now: float, force: bool = False) -> bool:
        with self._lock:
            should_refresh = force or (
                (now - self._last_secret_reload_monotonic) >= self._secret_manager_refresh_interval_s
            )
        if not should_refresh:
            return False
        payload: dict[str, Any] = {}
        try:
            payload = self._load_secret_manager_payload()
        except (json.JSONDecodeError, OSError, subprocess.SubprocessError, ValueError):
            payload = {}
        with self._lock:
            still_due = force or (
                (now - self._last_secret_reload_monotonic) >= self._secret_manager_refresh_interval_s
            )
            if not still_due:
                return False
            self._cached_secret_payload = payload if isinstance(payload, dict) else {}
            self._last_secret_reload_monotonic = now
            return True

    def _reload_locked(self, *, now: float, force: bool = False) -> None:
        if not force and (now - self._last_reload_monotonic) < 1.0:
            return
        file_payload: dict[str, Any] = dict(self._cached_file_payload)
        file_mtime_ns: int | None = None
        if self._token_file is not None and self._token_file.exists():
            try:
                file_mtime_ns = self._token_file.stat().st_mtime_ns
            except Exception:
                file_mtime_ns = None
        should_reload_file = force or file_mtime_ns != self._last_file_mtime_ns
        if should_reload_file:
            try:
                file_payload = self._load_token_file()
            except Exception:
                file_payload = {}
            self._cached_file_payload = file_payload if isinstance(file_payload, dict) else {}
            file_payload = dict(self._cached_file_payload)
            self._last_file_mtime_ns = file_mtime_ns
            if isinstance(file_payload.get("jwt_hs256_secret"), str):
                candidate = str(file_payload.get("jwt_hs256_secret") or "").strip()
                if candidate:
                    self._jwt_secret = candidate
        secret_payload = dict(self._cached_secret_payload)
        if isinstance(secret_payload.get("jwt_hs256_secret"), str):
            candidate = str(secret_payload.get("jwt_hs256_secret") or "").strip()
            if candidate:
                self._jwt_secret = candidate
        new_tokens: dict[str, dict[str, Any]] = {}
        for token, row in self._default_tokens.items():
            if not token:
                continue
            normalized = self._normalize_principal(row)
            if normalized is not None:
                new_tokens[token] = normalized
        for token_payload in [file_payload, secret_payload]:
            raw_tokens = token_payload.get("opaque_tokens")
            if not isinstance(raw_tokens, list):
                continue
            for row in raw_tokens:
                if not isinstance(row, dict):
                    continue
                token = str(row.get("token") or "").strip()
                if not token:
                    continue
                normalized = self._normalize_principal(row)
                if normalized is not None:
                    new_tokens[token] = normalized
        removed_tokens = set(self._active_tokens.keys()) - set(new_tokens.keys())
        for token in removed_tokens:
            previous = self._active_tokens.get(token)
            if previous is not None:
                self._grace_tokens[token] = (previous, now + self._overlap_window_s)
        self._active_tokens = new_tokens
        stale_grace = [token for token, (_principal, expiry) in self._grace_tokens.items() if expiry <= now]
        for token in stale_grace:
            self._grace_tokens.pop(token, None)
        stale_cache = [token for token, (_principal, expiry) in self._auth_cache.items() if expiry <= now]
        for token in stale_cache:
            self._auth_cache.pop(token, None)
        self._last_reload_monotonic = now

    @staticmethod
    def _normalize_principal(row: dict[str, Any]) -> dict[str, Any] | None:
        principal_id = str(row.get("principal_id") or row.get("sub") or "").strip() or f"principal_{uuid4().hex[:12]}"
        roles_raw = row.get("roles")
        roles: list[str] = []
        if isinstance(roles_raw, list):
            for item in roles_raw:
                role = str(item or "").strip().lower()
                if role in INTEGRATION_ALLOWED_ROLES and role not in roles:
                    roles.append(role)
        elif isinstance(row.get("role"), str):
            role = str(row.get("role") or "").strip().lower()
            if role in INTEGRATION_ALLOWED_ROLES:
                roles.append(role)
        if not roles:
            return None
        allowed_ops_raw = row.get("allowed_operations")
        if allowed_ops_raw is None:
            allowed_ops_raw = row.get("operations")
        if allowed_ops_raw is None:
            allowed_ops_raw = row.get("scopes")
        allowed_operations: list[str] = []
        if isinstance(allowed_ops_raw, list):
            for item in allowed_ops_raw:
                operation = str(item or "").strip().lower()
                if operation and operation not in allowed_operations:
                    allowed_operations.append(operation)
        elif isinstance(allowed_ops_raw, str):
            for item in allowed_ops_raw.replace(";", ",").split(","):
                operation = str(item or "").strip().lower()
                if operation and operation not in allowed_operations:
                    allowed_operations.append(operation)
        principal: dict[str, Any] = {"principal_id": principal_id, "roles": roles}
        if allowed_operations:
            principal["allowed_operations"] = allowed_operations
        return principal

    def refresh(self, *, force: bool = False) -> None:
        now = time.monotonic()
        secret_refreshed = self._maybe_refresh_secret_payload(now=now, force=force)
        with self._lock:
            self._reload_locked(now=now, force=force or secret_refreshed)

    def resolve_authorization(
        self,
        authorization_header: str | None,
        *,
        force_reload: bool = False,
    ) -> tuple[dict[str, Any] | None, IntegrationContractError | None]:
        token = _extract_bearer_token(authorization_header)
        if token is None:
            return None, IntegrationContractError(
                code="AUTH_REQUIRED",
                message="missing bearer token",
                retryable=False,
                operator_action="provide_valid_bearer_token",
            )
        now = time.monotonic()
        secret_refreshed = self._maybe_refresh_secret_payload(now=now, force=force_reload)
        with self._lock:
            self._reload_locked(now=now, force=force_reload or secret_refreshed)
            cached = self._auth_cache.get(token)
            if cached is not None and cached[1] > now:
                return dict(cached[0]), None
            principal = self._active_tokens.get(token)
            if principal is None:
                grace = self._grace_tokens.get(token)
                if grace is not None and grace[1] > now:
                    principal = grace[0]
            if principal is None:
                payload = self._decode_jwt_payload(token)
                if payload is not None:
                    principal = self._normalize_principal(payload)
            if principal is None:
                return None, IntegrationContractError(
                    code="AUTH_REQUIRED",
                    message="invalid bearer token",
                    retryable=False,
                    operator_action="rotate_or_refresh_auth_token",
                )
            cached_principal = dict(principal)
            self._auth_cache[token] = (cached_principal, now + self._auth_cache_ttl_s)
            return dict(cached_principal), None


class IntegrationDegradeTracker:
    def __init__(self, *, manual_override: bool = False) -> None:
        self._lock = threading.Lock()
        self._manual_override = bool(manual_override)
        self._request_events: list[tuple[float, bool]] = []
        self._latency_events: dict[str, list[tuple[float, float]]] = {}
        self._p95_breach_streak: dict[str, int] = {}
        self._dependency_unhealthy_since: float | None = None
        self._warning_started_at_epoch: dict[str, float] = {}
        self._degrade_mode = False
        self._healthy_since: float | None = None

    def _prune_locked(self, *, now: float) -> None:
        cutoff = now - 60.0
        self._request_events = [item for item in self._request_events if item[0] >= cutoff]
        stale_ops: list[str] = []
        for operation, rows in self._latency_events.items():
            kept = [item for item in rows if item[0] >= cutoff]
            if kept:
                self._latency_events[operation] = kept
            else:
                stale_ops.append(operation)
        for operation in stale_ops:
            self._latency_events.pop(operation, None)
            self._p95_breach_streak.pop(operation, None)

    def evaluate(
        self,
        *,
        operation: str,
        latency_ms: float,
        dependency_healthy: bool,
        error_code: str | None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        now_monotonic = time.monotonic()
        now_epoch = time.time()
        with self._lock:
            self._prune_locked(now=now_monotonic)
            timeout_hit = str(error_code or "").strip().upper() == "TIMEOUT"
            self._request_events.append((now_monotonic, timeout_hit))
            op_rows = self._latency_events.setdefault(operation, [])
            op_rows.append((now_monotonic, max(0.0, float(latency_ms))))

            if dependency_healthy:
                self._dependency_unhealthy_since = None
            elif self._dependency_unhealthy_since is None:
                self._dependency_unhealthy_since = now_monotonic

            latencies = [value for _stamp, value in op_rows]
            p95 = 0.0
            if latencies:
                ranked = sorted(latencies)
                idx = int(max(0, min(len(ranked) - 1, round((len(ranked) - 1) * 0.95))))
                p95 = float(ranked[idx])
            sla = float(INTEGRATION_OPERATION_SLA_MS.get(operation, 2000))
            if sla > 0 and p95 > (2.0 * sla):
                self._p95_breach_streak[operation] = int(self._p95_breach_streak.get(operation, 0)) + 1
            else:
                self._p95_breach_streak[operation] = 0

            timeout_total = len(self._request_events)
            timeout_count = len([item for item in self._request_events if item[1]])
            timeout_ratio = (float(timeout_count) / float(timeout_total)) if timeout_total > 0 else 0.0

            conditions: list[dict[str, Any]] = []
            if self._manual_override:
                conditions.append(
                    {
                        "warning_code": "MANUAL_DEGRADE_OVERRIDE",
                        "message": "manual degrade override is enabled",
                        "scope": "global",
                    }
                )
            if self._dependency_unhealthy_since is not None and (now_monotonic - self._dependency_unhealthy_since) > 30.0:
                conditions.append(
                    {
                        "warning_code": "DEPENDENCY_UNAVAILABLE",
                        "message": "dependency unavailable for more than 30 seconds",
                        "scope": "global",
                    }
                )
            if timeout_total >= 5 and timeout_ratio > 0.2:
                conditions.append(
                    {
                        "warning_code": "TIMEOUT_RATE_HIGH",
                        "message": "timeout rate exceeded 20% over rolling 1-minute window",
                        "scope": "context",
                    }
                )
            if any(value >= 3 for value in self._p95_breach_streak.values()):
                conditions.append(
                    {
                        "warning_code": "LATENCY_P95_BREACH",
                        "message": "operation p95 exceeded 2x SLA for 3 consecutive windows",
                        "scope": "global",
                    }
                )

            if conditions:
                self._degrade_mode = True
                self._healthy_since = None
            elif self._degrade_mode:
                if self._healthy_since is None:
                    self._healthy_since = now_monotonic
                elif (now_monotonic - self._healthy_since) >= 300.0:
                    self._degrade_mode = False
            else:
                self._healthy_since = now_monotonic

            warnings: list[dict[str, Any]] = []
            for item in conditions[:INTEGRATION_MAX_WARNINGS]:
                warning_code = str(item.get("warning_code") or "UNKNOWN")
                started_at_epoch = self._warning_started_at_epoch.get(warning_code)
                if started_at_epoch is None:
                    started_at_epoch = now_epoch
                    self._warning_started_at_epoch[warning_code] = started_at_epoch
                started_at_utc = datetime.fromtimestamp(started_at_epoch, tz=timezone.utc).isoformat()
                warnings.append(
                    {
                        "warning_code": warning_code,
                        "message": str(item.get("message") or ""),
                        "started_at_utc": started_at_utc,
                        "scope": str(item.get("scope") or "global"),
                    }
                )
            active_warning_codes = {str(item.get("warning_code") or "UNKNOWN") for item in conditions}
            stale_codes = [code for code in self._warning_started_at_epoch.keys() if code not in active_warning_codes]
            for code in stale_codes:
                self._warning_started_at_epoch.pop(code, None)
            return bool(self._degrade_mode), warnings


def _extract_bearer_token(header_value: str | None) -> str | None:
    raw = str(header_value or "").strip()
    if not raw:
        return None
    prefix = "bearer "
    if raw.lower().startswith(prefix):
        token = raw[len(prefix) :].strip()
        return token or None
    return None


def _integration_hash_identifier(value: str) -> str:
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
    return f"sha256:{digest[:20]}"


def _integration_redact_value(value: Any, *, key_name: str | None = None, depth: int = 0) -> Any:
    if depth > INTEGRATION_MAX_NESTING_DEPTH:
        return "<redacted_depth_limit>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, row in value.items():
            key_text = str(key or "")
            if INTEGRATION_SECRET_KEY_RE.search(key_text):
                out[key_text] = "<redacted_secret>"
                continue
            out[key_text] = _integration_redact_value(row, key_name=key_text, depth=depth + 1)
        return out
    if isinstance(value, list):
        clipped = value[:INTEGRATION_MAX_ARRAY_ITEMS]
        return [_integration_redact_value(item, key_name=key_name, depth=depth + 1) for item in clipped]
    if isinstance(value, str):
        text = str(value)
        text = INTEGRATION_EMAIL_RE.sub(lambda match: _integration_hash_identifier(match.group(0)), text)
        text = INTEGRATION_PHONE_RE.sub(lambda match: _integration_hash_identifier(match.group(0)), text)
        max_chars = 300 if str(key_name or "").lower().endswith("excerpt") else INTEGRATION_MAX_GENERIC_STRING
        if len(text) > max_chars:
            return text[:max_chars]
        return text
    return value


def _integration_new_request_id() -> str:
    timestamp_ms = int(time.time() * 1000.0)
    random_bytes = os.urandom(10)
    value = (timestamp_ms << 80) | int.from_bytes(random_bytes, byteorder="big", signed=False)
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    chars = []
    for _ in range(26):
        chars.append(alphabet[value & 0x1F])
        value >>= 5
    return f"req_{''.join(reversed(chars))}"


def _integration_validate_request_id(value: Any) -> tuple[str, str]:
    raw = str(value or "").strip()
    if raw and INTEGRATION_REQUEST_ID_RE.match(raw):
        return raw, "client"
    return _integration_new_request_id(), "server_generated"


def _integration_validate_depth(value: Any, *, depth: int = 0) -> None:
    if depth > INTEGRATION_MAX_NESTING_DEPTH:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="payload nesting depth exceeded",
            retryable=False,
            operator_action="reduce_payload_depth",
        )
    if isinstance(value, dict):
        for row in value.values():
            _integration_validate_depth(row, depth=depth + 1)
    elif isinstance(value, list):
        for row in value:
            _integration_validate_depth(row, depth=depth + 1)


def _integration_make_envelope(
    *,
    request_id: str,
    request_id_source: str,
    operation: str,
    ok: bool,
    degrade_mode: bool,
    warnings: list[dict[str, Any]],
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": INTEGRATION_SCHEMA_VERSION,
        "request_id": str(request_id),
        "request_id_source": str(request_id_source),
        "operation": str(operation),
        "ok": bool(ok),
        "degrade_mode": bool(degrade_mode),
        "warnings": list(warnings)[:INTEGRATION_MAX_WARNINGS],
    }
    if ok:
        payload["data"] = dict(data or {})
        if bool(degrade_mode):
            payload["fallback_recommendation"] = "stateless_chat"
    else:
        payload["error"] = dict(error or {})
        payload["fallback_recommendation"] = "stateless_chat"
    return payload


def _integration_error_payload(*, code: str, message: str, retryable: bool, operator_action: str) -> dict[str, Any]:
    return {
        "code": str(code),
        "message": str(message),
        "retryable": bool(retryable),
        "operator_action": str(operator_action),
    }


def _integration_payload_fingerprint(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _integration_list_roles(principal: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    for item in list(principal.get("roles") or []):
        role = str(item or "").strip().lower()
        if role in INTEGRATION_ALLOWED_ROLES and role not in roles:
            roles.append(role)
    return roles


def _integration_role_allowed(*, principal: dict[str, Any], required_roles: set[str]) -> bool:
    roles = _integration_list_roles(principal)
    if not roles:
        return False
    return bool(set(roles).intersection(set(required_roles)))


def _json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length).decode("utf-8") if length else "{}"
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


def _as_int(value: str | None, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(str(value or default))
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _to_bool(value: Any, *, default: bool = False) -> bool:
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


def _normalize_string_list(value: Any, *, max_items: int = 128, max_chars: int = 120) -> list[str]:
    if isinstance(value, str):
        rows = [item.strip() for item in value.replace("\n", ",").split(",")]
    elif isinstance(value, list):
        rows = [str(item).strip() for item in value]
    else:
        rows = []
    out: list[str] = []
    seen: set[str] = set()
    for item in rows:
        if not item:
            continue
        cleaned = item[:max_chars].strip()
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
        if len(out) >= max_items:
            break
    return out


def _normalize_aliases(value: Any, *, max_items: int = 200) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in value:
        if not isinstance(row, dict):
            continue
        alias = str(row.get("alias") or row.get("name") or "").strip()
        canonical = str(row.get("canonical") or row.get("alias_of") or row.get("entity") or "").strip()
        if not alias or not canonical:
            continue
        key = (alias.lower(), canonical.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"alias": alias[:120], "canonical": canonical[:120]})
        if len(out) >= max_items:
            break
    return out


def _normalize_profile_status(value: Any, *, default: str = "include") -> str:
    allowed = {"include", "exclude", "alias_of", "candidate", "active", "disabled"}
    cleaned = str(value or default).strip().lower() or str(default).strip().lower() or "include"
    if cleaned in allowed:
        return cleaned
    return str(default).strip().lower() or "include"


def _normalize_builder_profile_entries(
    value: Any,
    *,
    default_kind: str,
    allow_aliases: bool = False,
    max_items: int = 128,
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    alias_map: dict[str, list[str]] = {}
    if isinstance(value, dict):
        include_values = _normalize_string_list(value.get("include"), max_items=max_items, max_chars=120)
        exclude_values = _normalize_string_list(value.get("exclude"), max_items=max_items, max_chars=120)
        for item in include_values:
            normalized_rows.append({"value": item, "status": "include"})
        for item in exclude_values:
            normalized_rows.append({"value": item, "status": "exclude"})
        if allow_aliases:
            for pair in _normalize_aliases(value.get("aliases")):
                canonical = str(pair.get("canonical") or "").strip()
                alias = str(pair.get("alias") or "").strip()
                if not canonical or not alias:
                    continue
                key = canonical.lower()
                alias_map.setdefault(key, [])
                if alias not in alias_map[key]:
                    alias_map[key].append(alias)
        if isinstance(value.get("entries"), list):
            for row in list(value.get("entries") or []):
                if isinstance(row, dict):
                    normalized_rows.append(dict(row))
    elif isinstance(value, list):
        for row in value:
            if isinstance(row, dict):
                normalized_rows.append(dict(row))
            else:
                normalized_rows.append({"value": str(row).strip(), "status": "include"})
    elif value is not None:
        for item in _normalize_string_list(value, max_items=max_items, max_chars=120):
            normalized_rows.append({"value": item, "status": "include"})

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in normalized_rows:
        value_text = str(
            row.get("value")
            or row.get("term")
            or row.get("name")
            or row.get("canonical")
            or ""
        ).strip()
        if not value_text:
            continue
        status = _normalize_profile_status(row.get("status"), default="include")
        if status == "disabled":
            continue
        kind = str(row.get("kind") or default_kind).strip()[:64] or default_kind
        notes = str(row.get("notes") or "").strip()[:280]
        aliases: list[str] = []
        if allow_aliases:
            aliases = _normalize_string_list(row.get("aliases"), max_items=24, max_chars=80)
            if not aliases:
                aliases = list(alias_map.get(value_text.lower()) or [])
        key = (value_text.lower(), kind.lower(), status)
        if key in seen:
            continue
        seen.add(key)
        entry: dict[str, Any] = {
            "value": value_text[:120],
            "kind": kind,
            "status": status,
        }
        if aliases:
            entry["aliases"] = aliases
        if notes:
            entry["notes"] = notes
        deduped.append(entry)
        if len(deduped) >= max_items:
            break
    return deduped


def _profile_entries_to_legacy(entries: list[dict[str, Any]], *, include_aliases: bool = False) -> dict[str, Any]:
    include_values: list[str] = []
    exclude_values: list[str] = []
    aliases: list[dict[str, str]] = []
    for row in list(entries or []):
        if not isinstance(row, dict):
            continue
        value_text = str(row.get("value") or row.get("pattern") or "").strip()
        if not value_text:
            continue
        status = _normalize_profile_status(row.get("status"), default="include")
        if status == "disabled":
            continue
        if status == "exclude":
            exclude_values.append(value_text)
        else:
            include_values.append(value_text)
        if include_aliases:
            for alias in _normalize_string_list(row.get("aliases"), max_items=24, max_chars=80):
                if alias.lower() == value_text.lower():
                    continue
                aliases.append({"alias": alias, "canonical": value_text})
    out: dict[str, Any] = {
        "include": _normalize_string_list(include_values, max_items=200, max_chars=120),
        "exclude": _normalize_string_list(exclude_values, max_items=200, max_chars=120),
    }
    if include_aliases:
        out["aliases"] = _normalize_aliases(aliases, max_items=400)
    return out


def _normalize_builder_domain_rules(value: Any, *, max_items: int = 128) -> list[dict[str, str]]:
    normalized_rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        include_values = _normalize_string_list(value.get("include"), max_items=max_items, max_chars=160)
        exclude_values = _normalize_string_list(value.get("exclude"), max_items=max_items, max_chars=160)
        for item in include_values:
            normalized_rows.append({"pattern": item, "domain": "general", "status": "include"})
        for item in exclude_values:
            normalized_rows.append({"pattern": item, "domain": "general", "status": "exclude"})
        if isinstance(value.get("entries"), list):
            for row in list(value.get("entries") or []):
                if isinstance(row, dict):
                    normalized_rows.append(dict(row))
    elif isinstance(value, list):
        for row in value:
            if isinstance(row, dict):
                normalized_rows.append(dict(row))
            else:
                normalized_rows.append({"pattern": str(row).strip(), "domain": "general", "status": "include"})
    elif value is not None:
        for item in _normalize_string_list(value, max_items=max_items, max_chars=160):
            normalized_rows.append({"pattern": item, "domain": "general", "status": "include"})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in normalized_rows:
        pattern = str(
            row.get("pattern")
            or row.get("value")
            or row.get("term")
            or row.get("match")
            or ""
        ).strip()[:160]
        if not pattern:
            continue
        domain = str(row.get("domain") or row.get("label") or "general").strip()[:80] or "general"
        status = _normalize_profile_status(row.get("status"), default="include")
        if status == "disabled":
            continue
        key = (pattern.lower(), domain.lower(), status)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "pattern": pattern,
                "domain": domain,
                "status": status,
            }
        )
        if len(deduped) >= max_items:
            break
    return deduped


def _parse_tool_kv(stdout_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in str(stdout_text or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned_key = str(key).strip()
        if not cleaned_key:
            continue
        out[cleaned_key] = str(value).strip()
    return out


def _run_repo_tool(args: list[str], *, timeout_s: float = 180.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": 124,
            "stdout": str(getattr(exc, "stdout", "") or ""),
            "stderr": str(getattr(exc, "stderr", "") or ""),
            "kv": {},
            "error": "tool command timed out",
            "command": args,
        }
    except Exception as exc:
        return {
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": str(exc),
            "kv": {},
            "error": f"tool command failed to start: {exc}",
            "command": args,
        }
    stdout_text = str(completed.stdout or "")
    stderr_text = str(completed.stderr or "")
    return {
        "ok": completed.returncode == 0,
        "exit_code": int(completed.returncode),
        "stdout": stdout_text,
        "stderr": stderr_text,
        "kv": _parse_tool_kv(stdout_text),
        "command": args,
    }


def _wizard_state_defaults(run_id: str) -> dict[str, Any]:
    now = _utc_iso()
    return {
        "schema": "numquamoblita.runtime.wizard_state.v1",
        "run_id": str(run_id),
        "created_at": now,
        "updated_at": now,
        "current_stage": "import",
        "completed_stages": [],
        "selected_input_archive_path": "",
        "store_path": str((REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3").resolve()),
        "last_built_episode_draft_path": "",
        "last_built_episode_rejects_path": "",
        "last_built_episode_readout_path": "",
        "last_compiled_reviewed_path": "",
        "builder_profile_id": "",
        "published_pointers": {"store_path": "", "episodes_path": ""},
        "published_history": [],
        "review_decisions": {},
        "verify": {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False},
        "history": [],
        "artifacts": {},
        "selected_input": _wizard_empty_input_selection(),
        "store_validation": _wizard_empty_store_validation(),
        "build_info": _wizard_empty_build_info(),
        "review_state": _wizard_empty_review_state(),
        "published_set": _wizard_empty_published_set(),
        "activation": _wizard_empty_activation_state(),
    }


def _wizard_state_path(run_id: str) -> Path:
    cleaned = str(run_id or "").strip()
    if not cleaned:
        raise ValueError("run_id is required")
    if not WIZARD_RUN_ID_PATTERN.fullmatch(cleaned):
        raise FileNotFoundError(f"wizard run not found: {cleaned}")
    return WIZARD_RUNS_ROOT / cleaned / "wizard_state.json"


def _load_json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _wizard_empty_input_selection() -> dict[str, Any]:
    return {
        "path": "",
        "kind": "unselected",
        "label": "Nothing selected yet",
        "is_valid": False,
        "status": "unknown",
        "issues": [],
        "conversation_count": 0,
        "message_count": 0,
        "roles": {},
        "store_fingerprint": "",
        "schema_version": None,
        "atom_count": 0,
        "source": "none",
    }


def _wizard_empty_store_validation() -> dict[str, Any]:
    return {
        "path": "",
        "kind": "unvalidated",
        "is_valid": False,
        "issues": [],
        "store_fingerprint": "",
        "schema_version": None,
        "atom_count": 0,
        "source": "none",
    }


def _wizard_empty_build_info() -> dict[str, Any]:
    return {
        "build_id": "",
        "store_fingerprint": "",
        "schema_version": None,
        "draft_path": "",
        "rejects_path": "",
        "readout_path": "",
        "counts": {},
    }


def _wizard_empty_review_state() -> dict[str, Any]:
    return {
        "build_id": "",
        "store_fingerprint": "",
        "reviewable_count": 0,
        "pending_count": 0,
        "complete": False,
        "decision_count": 0,
        "source_cards_path": "",
    }


def _wizard_empty_published_set() -> dict[str, Any]:
    return {
        "version_id": "",
        "episodes_path": "",
        "snapshot_path": "",
        "store_fingerprint": "",
        "schema_version": None,
        "build_id": "",
        "episode_count": 0,
        "review_counts": {},
        "status": "unpublished",
        "published_at": "",
    }


def _wizard_empty_activation_state() -> dict[str, Any]:
    return {
        "direct": {
            "status": "not_active",
            "checked_at": "",
            "store_fingerprint": "",
            "episodes_path": "",
            "runtime_url": "",
            "issues": [],
        },
        "mcp": {
            "status": "not_installed",
            "checked_at": "",
            "issues": [],
            "owned_targets": {},
        },
        "developer_mode": False,
        "draft_override": {},
    }


def _wizard_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _wizard_store_fingerprint_from_atom_ids(
    atom_ids: list[str],
    *,
    prefix: str,
    schema_version: int | None,
    total_count: int | None = None,
) -> str:
    clean_ids = [str(item).strip() for item in atom_ids if str(item).strip()]
    clean_ids.sort()
    sample = clean_ids[:64]
    digest = hashlib.sha256("|".join(sample).encode("utf-8")).hexdigest()[:16] if sample else "none"
    schema_part = str(schema_version) if schema_version is not None else "na"
    count = int(total_count) if total_count is not None else len(clean_ids)
    return f"{prefix}:v{schema_part}:atoms:{count}:sample:{digest}"


def _wizard_validate_sqlite_store(path: Path) -> dict[str, Any]:
    issues: list[str] = []
    if not path.exists():
        return {"path": str(path), "kind": "invalid_corrupted", "is_valid": False, "issues": ["file not found"]}
    required_tables = {"atoms", "provenance_events", "conflicts", "recognition_events", "shared_language_keys", "shared_language_links"}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()
        if not quick_check or str(quick_check[0]).strip().lower() != "ok":
            issues.append("sqlite quick_check failed")
        version_row = conn.execute("PRAGMA user_version").fetchone()
        schema_version = int(version_row[0]) if version_row else 0
        table_rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {str(row[0]).strip() for row in table_rows}
        missing = sorted(required_tables - tables)
        if missing:
            return {
                "path": str(path),
                "kind": "unsupported_sqlite",
                "is_valid": False,
                "issues": [f"missing MNO tables: {', '.join(missing)}"],
                "schema_version": schema_version,
            }
        atom_rows = conn.execute("SELECT atom_id FROM atoms ORDER BY atom_id LIMIT 64").fetchall()
        count_row = conn.execute("SELECT COUNT(*) FROM atoms").fetchone()
        atom_count = int(count_row[0]) if count_row else 0
        atom_ids = [str(row[0]).strip() for row in atom_rows if str(row[0]).strip()]
        fingerprint = _wizard_store_fingerprint_from_atom_ids(atom_ids, prefix="sqlite_store", schema_version=schema_version, total_count=atom_count)
        return {
            "path": str(path),
            "kind": "mno_store_sqlite",
            "is_valid": not issues and schema_version >= 2,
            "issues": issues if issues else ([] if schema_version >= 2 else [f"unsupported schema version: {schema_version}"]),
            "schema_version": schema_version,
            "atom_count": atom_count,
            "store_fingerprint": fingerprint,
            "source": "existing_store",
        }
    finally:
        conn.close()


def _wizard_validate_memory_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    atoms_raw = payload.get("atoms")
    if not isinstance(atoms_raw, list):
        atoms_raw = payload.get("memory_atoms")
    if not isinstance(atoms_raw, list):
        atoms_raw = payload.get("items")
    if not isinstance(atoms_raw, list):
        return {
            "path": str(path),
            "kind": "unsupported_json",
            "is_valid": False,
            "issues": ["json is not an MNO memory payload"],
        }
    atom_ids: list[str] = []
    for row in atoms_raw:
        if not isinstance(row, dict):
            continue
        atom_id = str(row.get("atom_id") or row.get("id") or "").strip()
        if atom_id:
            atom_ids.append(atom_id)
    fingerprint = _wizard_store_fingerprint_from_atom_ids(atom_ids, prefix="json_store", schema_version=1)
    return {
        "path": str(path),
        "kind": "mno_store_json",
        "is_valid": True,
        "issues": [],
        "schema_version": 1,
        "atom_count": len(atom_ids) if atom_ids else len(atoms_raw),
        "store_fingerprint": fingerprint,
        "source": "existing_store",
    }


def _wizard_validate_archive_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return {
            "path": str(path),
            "kind": "unsupported_json",
            "is_valid": False,
            "issues": ["db.json missing conversations[] list"],
        }
    conversation_count = len(conversations)
    message_count = 0
    roles: dict[str, int] = {}
    invalid_messages = 0
    for convo in conversations:
        messages = convo.get("messages") if isinstance(convo, dict) else []
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                invalid_messages += 1
                continue
            role = str(message.get("role") or "").strip().lower()
            text = str(message.get("text") or message.get("content") or "").strip()
            if role:
                roles[role] = int(roles.get(role) or 0) + 1
            if not role or not text:
                invalid_messages += 1
            message_count += 1
    issues: list[str] = []
    if conversation_count == 0:
        issues.append("no conversations found")
    if message_count == 0:
        issues.append("no messages found")
    if invalid_messages > 0:
        issues.append(f"{invalid_messages} messages are missing role/text")
    return {
        "path": str(path),
        "kind": "ia_archive",
        "is_valid": True,
        "status": "safe" if not issues else "needs_attention",
        "issues": issues,
        "conversation_count": conversation_count,
        "message_count": message_count,
        "roles": roles,
        "source": "archive",
    }


def _wizard_classify_input_path(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return {"path": str(resolved), "kind": "invalid_corrupted", "is_valid": False, "issues": ["path not found"]}
    if not resolved.is_file():
        return {"path": str(resolved), "kind": "invalid_corrupted", "is_valid": False, "issues": ["path is not a file"]}
    suffix = resolved.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return _wizard_validate_sqlite_store(resolved)
    if suffix != ".json":
        return {"path": str(resolved), "kind": "invalid_corrupted", "is_valid": False, "issues": [f"unsupported file suffix: {suffix or '(none)'}"]}
    try:
        payload = _load_json_file(resolved)
    except Exception as exc:
        return {"path": str(resolved), "kind": "invalid_corrupted", "is_valid": False, "issues": [f"invalid json: {exc}"]}
    if any(isinstance(payload.get(key), list) for key in ("atoms", "memory_atoms", "items")):
        return _wizard_validate_memory_json(resolved, payload)
    if isinstance(payload.get("conversations"), list):
        return _wizard_validate_archive_json(resolved, payload)
    return {"path": str(resolved), "kind": "unsupported_json", "is_valid": False, "issues": ["json is neither IA archive nor MNO memory store"]}


def _wizard_bind_input_to_state(state: dict[str, Any], classification: Mapping[str, Any]) -> None:
    selected = _wizard_empty_input_selection()
    selected.update(dict(classification))
    state["selected_input"] = selected
    if str(selected.get("kind") or "") in WIZARD_VALID_STORE_KINDS and bool(selected.get("is_valid")):
        store_validation = _wizard_empty_store_validation()
        store_validation.update(dict(classification))
        state["store_validation"] = store_validation
        state["store_path"] = str(selected.get("path") or state.get("store_path") or "")
    elif str(selected.get("kind") or "") == "ia_archive":
        state["selected_input_archive_path"] = str(selected.get("path") or "")


def _wizard_review_counts(source_payload: dict[str, Any], review_decisions: Mapping[str, Any]) -> dict[str, int]:
    total = 0
    explicit = 0
    pending = 0
    for row in list(source_payload.get("cards") or []):
        if not isinstance(row, dict):
            continue
        episode_id = str(row.get("episode_id") or "").strip()
        if not episode_id:
            continue
        total += 1
        decision_payload = review_decisions.get(episode_id)
        decision = str((decision_payload or {}).get("decision") or "pending").strip().lower()
        if decision in {"approved", "edited", "rejected"}:
            explicit += 1
        else:
            pending += 1
    return {"reviewable_count": total, "decision_count": explicit, "pending_count": pending}


def _wizard_stage_state_payload(state: dict[str, Any]) -> dict[str, Any]:
    current = str(state.get("current_stage") or "import").strip() or "import"
    completed = {str(item).strip() for item in list(state.get("completed_stages") or []) if str(item).strip()}
    rows = []
    for stage in WIZARD_STAGE_SEQUENCE:
        if stage == current:
            status = "current"
        elif stage in completed:
            status = "done"
        else:
            status = "pending"
        rows.append({"stage": stage, "status": status})
    return {
        "current_stage": current,
        "completed_stages": sorted(completed, key=lambda item: WIZARD_STAGE_INDEX.get(item, 10**6)),
        "sequence": list(WIZARD_STAGE_SEQUENCE),
        "items": rows,
    }


def _wizard_transition(state: dict[str, Any], stage: str, note: str, *, completed: bool = False) -> None:
    clean_stage = str(stage or "").strip()
    if clean_stage not in WIZARD_STAGE_SEQUENCE:
        raise ValueError(f"unsupported wizard stage: {clean_stage}")
    state["current_stage"] = clean_stage
    completed_stages = [str(item).strip() for item in list(state.get("completed_stages") or []) if str(item).strip() in WIZARD_STAGE_SEQUENCE]
    if completed and clean_stage not in completed_stages:
        completed_stages.append(clean_stage)
    completed_stages.sort(key=lambda item: WIZARD_STAGE_INDEX.get(item, 10**6))
    state["completed_stages"] = completed_stages
    _wizard_history(state, stage=clean_stage, note=note, status="ok")


def _wizard_reset_downstream_state(state: dict[str, Any], *, from_stage: str) -> None:
    stage = str(from_stage or "").strip()
    if stage == "import":
        state["last_built_episode_draft_path"] = ""
        state["last_built_episode_rejects_path"] = ""
        state["last_built_episode_readout_path"] = ""
        state["last_compiled_reviewed_path"] = ""
        state["review_decisions"] = {}
        state["build_info"] = _wizard_empty_build_info()
        state["review_state"] = _wizard_empty_review_state()
        state["published_set"] = _wizard_empty_published_set()
        state["verify"] = {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False}
        state["activation"] = _wizard_empty_activation_state()
        state["published_pointers"] = {"store_path": "", "episodes_path": ""}
    elif stage == "build_episodes":
        state["last_compiled_reviewed_path"] = ""
        state["review_decisions"] = {}
        state["review_state"] = _wizard_empty_review_state()
        state["published_set"] = _wizard_empty_published_set()
        state["verify"] = {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False}
        state["activation"] = _wizard_empty_activation_state()
        published = dict(state.get("published_pointers") or {})
        published["episodes_path"] = ""
        state["published_pointers"] = published
    elif stage == "review":
        state["published_set"] = _wizard_empty_published_set()
        state["verify"] = {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False}
        state["activation"] = _wizard_empty_activation_state()
        published = dict(state.get("published_pointers") or {})
        published["episodes_path"] = ""
        state["published_pointers"] = published
    elif stage in {"publish", "verify"}:
        state["activation"] = _wizard_empty_activation_state()


def _wizard_clear_completed_from(state: dict[str, Any], *, from_stage: str) -> None:
    clean_stage = str(from_stage or "").strip()
    from_index = WIZARD_STAGE_INDEX.get(clean_stage, 0)
    completed = [
        str(item).strip()
        for item in list(state.get("completed_stages") or [])
        if str(item).strip() in WIZARD_STAGE_SEQUENCE and WIZARD_STAGE_INDEX[str(item).strip()] < from_index
    ]
    completed.sort(key=lambda item: WIZARD_STAGE_INDEX.get(item, 10**6))
    state["completed_stages"] = completed
    current_stage = str(state.get("current_stage") or "import").strip() or "import"
    if WIZARD_STAGE_INDEX.get(current_stage, 10**6) >= from_index:
        state["current_stage"] = clean_stage if clean_stage in WIZARD_STAGE_SEQUENCE else "import"


def _wizard_reset_to_stage(state: dict[str, Any], *, stage: str, note: str, history_status: str = "warn") -> None:
    clean_stage = str(stage or "").strip()
    if clean_stage not in WIZARD_STAGE_SEQUENCE:
        raise ValueError(f"unsupported wizard stage: {clean_stage}")
    _wizard_clear_completed_from(state, from_stage=clean_stage)
    state["current_stage"] = clean_stage
    _wizard_history(state, stage=clean_stage, note=note, status=history_status)


def _wizard_is_stage_complete(state: Mapping[str, Any], stage: str) -> bool:
    return str(stage or "").strip() in {str(item).strip() for item in list(state.get("completed_stages") or [])}


def _wizard_require(state: Mapping[str, Any], *, action: str) -> None:
    if action in WIZARD_STAGE_BYPASS_ACTIONS:
        return
    store_validation = dict(state.get("store_validation") or {})
    build_info = dict(state.get("build_info") or {})
    review_state = dict(state.get("review_state") or {})
    published_set = dict(state.get("published_set") or {})
    verify = dict(state.get("verify") or {})
    if action == "build_run":
        if not bool(store_validation.get("is_valid")):
            raise ValueError("Select or import a valid MNO memory store before building episodes.")
        return
    if action in {"review_cards", "review_update"}:
        if not str(build_info.get("draft_path") or "").strip():
            raise ValueError("Build episode draft cards before review.")
        return
    if action in {"publish_run", "review_compile"}:
        if not str(build_info.get("draft_path") or "").strip():
            raise ValueError("Build episode draft cards before publishing.")
        if int(review_state.get("reviewable_count") or 0) <= 0:
            raise ValueError("Review draft cards before publishing.")
        if int(review_state.get("pending_count") or 0) > 0:
            raise ValueError("Every review card must be approved, edited, or rejected before publish.")
        return
    if action == "verify_run":
        if not str(published_set.get("episodes_path") or "").strip():
            raise ValueError("Publish a reviewed episode set before verification.")
        return
    if action in {"activate_status", "activate_direct", "activate_mcp", "mcp_export"}:
        if str(verify.get("status") or "Unknown") != "Safe":
            raise ValueError("Verification must be Safe before normal activation.")
        if not str(published_set.get("episodes_path") or "").strip():
            raise ValueError("A published reviewed set is required for activation.")
        if not bool(store_validation.get("is_valid")):
            raise ValueError("A valid MNO memory store is required for activation.")


def _wizard_publish_version_id(*, build_id: str, store_fingerprint: str, published_path: Path) -> str:
    token = f"{build_id}|{store_fingerprint}|{published_path.name}|{int(published_path.stat().st_mtime_ns)}"
    return f"published_{hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]}"


def _wizard_sync_review_state(
    state: dict[str, Any],
    *,
    source_payload: dict[str, Any] | None = None,
    source_cards_path: Path | None = None,
) -> dict[str, Any]:
    payload = source_payload
    resolved_path = source_cards_path
    if payload is None:
        draft_path_raw = str((state.get("build_info") or {}).get("draft_path") or "").strip()
        if draft_path_raw:
            resolved_path = Path(draft_path_raw).expanduser().resolve()
            if resolved_path.exists():
                payload = _load_episode_cards_payload(resolved_path)
    review_decisions = state.get("review_decisions")
    if not isinstance(review_decisions, dict):
        review_decisions = {}
        state["review_decisions"] = review_decisions
    review_state = _wizard_empty_review_state()
    build_info = dict(state.get("build_info") or {})
    review_state["build_id"] = str(build_info.get("build_id") or "")
    review_state["store_fingerprint"] = str(build_info.get("store_fingerprint") or "")
    if payload is not None:
        counts = _wizard_review_counts(payload, review_decisions)
        review_state.update(counts)
        review_state["complete"] = counts["reviewable_count"] > 0 and counts["pending_count"] == 0
    if resolved_path is not None:
        review_state["source_cards_path"] = str(resolved_path)
    state["review_state"] = review_state
    return review_state


def _wizard_verify_payload(server: "RuntimeHTTPServer", state: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    actionable_links: list[dict[str, Any]] = []
    run_id_value = str(state.get("run_id") or "").strip()
    selected_input = dict(state.get("selected_input") or {})
    store_validation = dict(state.get("store_validation") or {})
    build_info = dict(state.get("build_info") or {})
    published_set = dict(state.get("published_set") or {})

    def _append_check(
        check_id: str,
        status: str,
        detail: str,
        *,
        path: str = "",
        api_path: str = "",
        link_label: str = "",
    ) -> None:
        payload: dict[str, Any] = {"id": check_id, "status": status, "detail": detail}
        if path:
            payload["path"] = path
        if api_path:
            payload["api_path"] = api_path
        checks.append(payload)
        if api_path:
            actionable_links.append(
                {
                    "id": check_id,
                    "label": link_label or detail,
                    "api_path": api_path,
                    "path": path,
                }
            )

    input_kind = str(selected_input.get("kind") or "").strip()
    selected_path = str(selected_input.get("path") or "").strip()
    if input_kind in WIZARD_VALID_INPUT_KINDS and bool(selected_input.get("is_valid")):
        _append_check("selected_input", "ok", f"Selected input: {input_kind}", path=selected_path)
    else:
        detail = ", ".join(str(item) for item in list(selected_input.get("issues") or []) if str(item).strip()) or "Select a valid archive or MNO store."
        _append_check("selected_input", "fail", detail, path=selected_path)

    store_path = str(store_validation.get("path") or state.get("store_path") or "").strip()
    store_kind = str(store_validation.get("kind") or "").strip()
    if store_kind in WIZARD_VALID_STORE_KINDS and bool(store_validation.get("is_valid")):
        _append_check("store_validation", "ok", f"Runtime store ready: {store_kind}", path=store_path)
    else:
        detail = ", ".join(str(item) for item in list(store_validation.get("issues") or []) if str(item).strip()) or "Import or select a valid MNO store."
        _append_check("store_validation", "fail", detail, path=store_path)

    draft_path = str(build_info.get("draft_path") or state.get("last_built_episode_draft_path") or "").strip()
    if draft_path and Path(draft_path).expanduser().resolve().exists():
        _append_check(
            "draft_cards",
            "ok",
            "Draft episode cards are available.",
            path=draft_path,
            api_path=f"/api/wizard/review/cards?run_id={quote(run_id_value)}",
            link_label="Open draft review list",
        )
    else:
        _append_check("draft_cards", "fail", "Build episode draft cards before publish.", path=draft_path)

    published_path = str(published_set.get("episodes_path") or state.get("last_compiled_reviewed_path") or "").strip()
    published_exists = bool(published_path) and Path(published_path).expanduser().resolve().exists()
    if published_exists:
        _append_check(
            "published_set",
            "ok",
            "Published reviewed set is available.",
            path=published_path,
            api_path=f"/api/memory/episodes?run_id={quote(run_id_value)}&status=approved",
            link_label="Open published reviewed episodes",
        )
    else:
        _append_check("published_set", "fail", "Publish a reviewed set before verification.", path=published_path)

    published_store_match = (
        published_exists
        and str(published_set.get("store_fingerprint") or "").strip()
        and str(published_set.get("store_fingerprint") or "").strip() == str(store_validation.get("store_fingerprint") or "").strip()
    )
    _append_check(
        "published_store_match",
        "ok" if published_store_match else "fail",
        "Published set matches the selected store." if published_store_match else "Published set does not match the selected store.",
    )

    published_schema_match = (
        published_exists
        and published_set.get("schema_version") is not None
        and store_validation.get("schema_version") is not None
        and int(published_set.get("schema_version")) == int(store_validation.get("schema_version"))
    )
    _append_check(
        "published_schema_match",
        "ok" if published_schema_match else "fail",
        "Published set matches the current schema." if published_schema_match else "Published set schema does not match the selected store.",
    )

    published_build_match = (
        published_exists
        and str(published_set.get("build_id") or "").strip()
        and str(published_set.get("build_id") or "").strip() == str(build_info.get("build_id") or "").strip()
    )
    _append_check(
        "published_build_match",
        "ok" if published_build_match else "fail",
        "Published set matches the latest reviewed build." if published_build_match else "Published set is stale for the latest build.",
    )

    review_state = dict(state.get("review_state") or {})
    if int(review_state.get("pending_count") or 0) > 0:
        _append_check(
            "review_pending",
            "warn",
            f"{int(review_state.get('pending_count') or 0)} draft review decisions are still pending.",
            api_path=f"/api/wizard/review/cards?run_id={quote(run_id_value)}&status=pending",
            link_label="Open pending review decisions",
        )

    if bool(selected_input.get("issues")):
        _append_check(
            "selected_input_issues",
            "warn",
            "; ".join(str(item) for item in list(selected_input.get("issues") or []) if str(item).strip()),
            path=selected_path,
        )

    remap_required = False
    for check in checks:
        if str(check.get("id") or "") in {"selected_input", "store_validation", "draft_cards", "published_set"}:
            path = str(check.get("path") or "").strip()
            if path and not Path(path).expanduser().resolve().exists():
                remap_required = True
                break

    blocked = any(
        str(item.get("status") or "") == "fail" and str(item.get("id") or "") in WIZARD_PRIMARY_CHECK_IDS_BLOCK
        for item in checks
    )
    needs_attention = any(str(item.get("status") or "") == "warn" for item in checks)
    status = "Blocked" if blocked else ("Needs attention" if needs_attention else "Safe")
    if remap_required and status == "Needs attention":
        status = "Blocked"
    checked_at = _utc_iso()

    if published_exists:
        try:
            payload = _load_json_file(Path(published_path))
            cards = [row for row in list(payload.get("cards") or []) if isinstance(row, dict)]
            count = len(cards)
            _append_check(
                "published_count",
                "ok" if count > 0 else "warn",
                f"{count} published reviewed episode cards.",
                path=published_path,
            )
        except Exception as exc:
            _append_check("published_parse", "fail", f"Published set could not be read: {exc}", path=published_path)
            status = "Blocked"

    return {
        "status": status,
        "checks": checks,
        "actionable_links": actionable_links,
        "checked_at": checked_at,
        "remap_required": remap_required,
    }


def _wizard_current_runtime_binding(server: "RuntimeHTTPServer") -> dict[str, Any]:
    binding = dict(getattr(server, "active_runtime_binding", {}) or {})
    return {
        "store_path": str(binding.get("store_path") or ""),
        "store_fingerprint": str(binding.get("store_fingerprint") or ""),
        "episodes_path": str(binding.get("episodes_path") or ""),
        "checked_at": str(binding.get("checked_at") or ""),
        "backend": str(binding.get("backend") or ""),
        "artifact_mode": str(binding.get("artifact_mode") or ""),
        "build_id": str(binding.get("build_id") or ""),
    }


def _wizard_open_store(path: Path) -> tuple[Any, str, bool]:
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), "sqlite", True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), "json", False
    raise ValueError(f"unsupported store path: {path}")


def _wizard_runtime_store_fingerprint(runtime: RuntimeSession) -> str:
    store = runtime.retriever.store
    try:
        atoms = list(store.list_atoms())
    except Exception:
        return ""
    atom_ids = [str(getattr(atom, "atom_id", "") or "").strip() for atom in atoms if str(getattr(atom, "atom_id", "") or "").strip()]
    return _wizard_store_fingerprint_from_atom_ids(atom_ids, prefix="runtime_store", schema_version=1, total_count=len(atom_ids))


def _wizard_activate_direct(
    server: "RuntimeHTTPServer",
    *,
    store_path: Path,
    episodes_path: Path,
    store_validation: Mapping[str, Any],
    artifact_mode: str,
    build_id: str = "",
) -> dict[str, Any]:
    existing_lock = _wizard_read_runtime_lock()
    if existing_lock and not _wizard_runtime_lock_matches_server(server, existing_lock):
        owner_pid = int(existing_lock.get("pid") or 0)
        owner_host = str(existing_lock.get("host") or "").strip()
        owner_port = int(existing_lock.get("port") or 0)
        if _wizard_pid_alive(owner_pid):
            raise RuntimeError(
                f"Direct runtime is already owned by pid {owner_pid} at {owner_host or 'unknown-host'}:{owner_port or 0}. "
                "Stop the other runtime or use stale-lock cleanup if that owner is gone."
            )
        _wizard_clear_runtime_lock(only_if_stale=True)
    runtime = server.runtime
    existing_store = runtime.retriever.store
    new_store, backend_name, close_store = _wizard_open_store(store_path)
    try:
        runtime.retriever.store = new_store
        if server.review_queue is not None:
            server.review_queue.store = new_store
        _reload_runtime_episode_index(runtime, episodes_path)
        snapshot_info = _rebuild_snapshot(runtime)
        binding = {
            "store_path": str(store_path.resolve()),
            "store_fingerprint": str(store_validation.get("store_fingerprint") or ""),
            "episodes_path": str(episodes_path.resolve()),
            "checked_at": _utc_iso(),
            "backend": backend_name,
            "artifact_mode": str(artifact_mode or ""),
            "build_id": str(build_id or ""),
        }
        lock_payload = _wizard_write_runtime_lock(server, binding=binding)
        server.active_runtime_binding = binding
        server.active_runtime_lock = dict(lock_payload)
        host, port = server.server_address
        return {
            "status": "running",
            "runtime_url": f"http://{host}:{port}/",
            "binding": binding,
            "lock": {
                "status": "owned",
                "checked_at": str(lock_payload.get("checked_at") or ""),
                "cleanup_allowed": False,
                "owner_pid": int(lock_payload.get("pid") or 0),
                "owner_host": str(lock_payload.get("host") or ""),
                "owner_port": int(lock_payload.get("port") or 0),
            },
            "snapshot": snapshot_info,
        }
    except Exception:
        if close_store:
            closer = getattr(new_store, "close", None)
            if callable(closer):
                closer()
        runtime.retriever.store = existing_store
        if server.review_queue is not None:
            server.review_queue.store = existing_store
        raise
    else:
        if close_store:
            old_closer = getattr(existing_store, "close", None)
            if callable(old_closer) and existing_store is not new_store:
                try:
                    old_closer()
                except Exception:
                    pass


def _wizard_connector_panel():
    from tools.run_mcp_connector_gui import ConnectorControlPanel

    return ConnectorControlPanel(repo_root=REPO_ROOT)


def _wizard_mcp_payload(state: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    from tools.mcp_connector_common import DEFAULT_SERVER_NAME

    store_path = str((state.get("store_validation") or {}).get("path") or state.get("store_path") or "").strip()
    episodes_path = str((state.get("published_set") or {}).get("episodes_path") or state.get("last_compiled_reviewed_path") or "").strip()
    return {
        "server_name": str(payload.get("server_name") or DEFAULT_SERVER_NAME).strip() or DEFAULT_SERVER_NAME,
        "default_role": str(payload.get("default_role") or "viewer").strip() or "viewer",
        "compat_mode": str(payload.get("compat_mode") or "strict").strip() or "strict",
        "claude_code_scope": str(payload.get("claude_code_scope") or "local").strip() or "local",
        "memories_path": store_path,
        "episodes_path": episodes_path,
        "mutations_enabled": bool(payload.get("mutations_enabled")),
        "wsl_distro": str(payload.get("wsl_distro") or "").strip(),
    }


def _wizard_mcp_targets_payload(panel: Any, payload: dict[str, Any]) -> dict[str, Any]:
    preview = panel.build_preview(payload)
    return {
        "claude_code": {
            "entry": dict(preview.get("claude_code_entry") or {}),
            "config_path": str(preview.get("windows_claude_code_config") or ""),
            "install_context": str(preview.get("claude_code_install_context") or ""),
            "display": str(preview.get("claude_code_display") or ""),
        },
        "claude_desktop": {
            "entry": dict(preview.get("windows_entry") or {}),
            "config_path": str(preview.get("windows_claude_desktop_config") or ""),
            "install_context": "desktop_config",
            "display": "Claude Desktop",
        },
    }


def _wizard_mcp_entry_looks_app_owned(entry: Mapping[str, Any]) -> bool:
    command = str(entry.get("command") or "").strip().lower()
    args = [str(item).strip().lower() for item in list(entry.get("args") or []) if str(item).strip()]
    if "run_claude_live_mcp.py" in command:
        return True
    return any("run_claude_live_mcp.py" in item for item in args)


def _wizard_mcp_existing_entry(target: str, payload: dict[str, Any], expected_entry: Mapping[str, Any]) -> dict[str, Any]:
    from tools.mcp_connector_common import DEFAULT_SERVER_NAME, load_json_object

    config_path_raw = str(payload.get("config_path") or "").strip()
    config_path = Path(config_path_raw).expanduser().resolve() if config_path_raw else None
    existing_entry: dict[str, Any] | None = None
    if config_path is not None and config_path.exists():
        try:
            config_payload = load_json_object(config_path)
            servers = dict(config_payload.get("mcpServers") or {}) if isinstance(config_payload.get("mcpServers"), Mapping) else {}
            raw_entry = servers.get(str(payload.get("server_name") or DEFAULT_SERVER_NAME))
            if isinstance(raw_entry, Mapping):
                existing_entry = dict(raw_entry)
        except Exception:
            existing_entry = None
    return {
        "target": target,
        "config_path": str(config_path) if config_path is not None else "",
        "existing_entry": existing_entry or {},
        "expected_entry": dict(expected_entry),
    }


def _wizard_mcp_status_for_target(state: Mapping[str, Any], *, target: str, existing: Mapping[str, Any], expected_entry: Mapping[str, Any]) -> dict[str, Any]:
    existing_entry = dict(existing.get("existing_entry") or {})
    config_path = str(existing.get("config_path") or "")
    activation = dict(state.get("activation") or {})
    mcp_state = dict(activation.get("mcp") or {})
    owned_targets = dict(mcp_state.get("owned_targets") or {})
    adopted = bool(owned_targets.get(target))
    if not existing_entry:
        return {
            "target": target,
            "config_path": config_path,
            "ownership": "absent",
            "status": "not_installed",
            "issues": [],
        }
    if existing_entry == dict(expected_entry):
        return {
            "target": target,
            "config_path": config_path,
            "ownership": "app_owned",
            "status": "installed",
            "issues": [],
        }
    if adopted:
        return {
            "target": target,
            "config_path": config_path,
            "ownership": "adopted",
            "status": "installed",
            "issues": ["Using an adopted MCP entry."],
        }
    if _wizard_mcp_entry_looks_app_owned(existing_entry):
        return {
            "target": target,
            "config_path": config_path,
            "ownership": "app_owned",
            "status": "stale_config",
            "issues": ["Existing app-owned MCP entry does not match the selected store or reviewed set."],
        }
    return {
        "target": target,
        "config_path": config_path,
        "ownership": "unknown",
        "status": "installed",
        "issues": ["Existing MCP entry was not created by this app."],
    }


def _wizard_mcp_handshake(entry: Mapping[str, Any]) -> dict[str, Any]:
    command = str(entry.get("command") or "").strip()
    args = [str(item) for item in list(entry.get("args") or [])]
    if not command:
        raise ValueError("MCP entry is missing command")
    from engine.mcp.server import _read_message as _mcp_read_message
    from engine.mcp.server import _write_message as _mcp_write_message

    process = subprocess.Popen(
        [command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("MCP process stdio pipes are unavailable")
        _mcp_write_message(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "mno-caveman-ui", "version": "1"}},
            },
        )
        initialize_response = _mcp_read_message(process.stdout)
        if not isinstance(initialize_response, dict) or initialize_response.get("error"):
            raise RuntimeError(f"initialize failed: {initialize_response}")
        _mcp_write_message(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "ops.health", "arguments": {}},
            },
        )
        health_response = _mcp_read_message(process.stdout)
        if not isinstance(health_response, dict) or health_response.get("error"):
            raise RuntimeError(f"ops.health failed: {health_response}")
        result = dict(health_response.get("result") or {})
        return {
            "ok": True,
            "initialize": initialize_response.get("result"),
            "health": dict(result.get("structuredContent") or {}),
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()


def _wizard_activation_status(server: "RuntimeHTTPServer", state: dict[str, Any]) -> dict[str, Any]:
    binding = _wizard_current_runtime_binding(server)
    verify = dict(state.get("verify") or {})
    published_set = dict(state.get("published_set") or {})
    store_validation = dict(state.get("store_validation") or {})
    build_info = dict(state.get("build_info") or {})
    current_activation = dict(state.get("activation") or _wizard_empty_activation_state())
    draft_override = dict(current_activation.get("draft_override") or {})
    direct_issues: list[str] = []
    direct_status = "not_active"
    lock_summary = _wizard_runtime_lock_summary(server)
    if bool(draft_override.get("active")):
        if str(binding.get("artifact_mode") or "") != "draft":
            direct_status = "stale_config"
            direct_issues.append("Draft override audit exists, but the runtime is not serving the draft artifact anymore.")
        elif binding.get("store_fingerprint") != str(store_validation.get("store_fingerprint") or ""):
            direct_status = "stale_config"
            direct_issues.append("Draft runtime store does not match the selected store.")
        elif binding.get("episodes_path") != str(build_info.get("draft_path") or ""):
            direct_status = "stale_config"
            direct_issues.append("Draft runtime artifact does not match the current draft build.")
        else:
            lock_status = str(lock_summary.get("status") or "")
            if lock_status == "missing":
                direct_status = "needs_attention"
                direct_issues.append("Draft runtime lock is missing. Repair the runtime claim before treating it as active.")
            elif lock_status == "stale":
                direct_status = "needs_attention"
                direct_issues.append("Draft runtime lock is stale. Run cleanup to repair ownership.")
            elif lock_status == "foreign_live":
                direct_status = "needs_attention"
                direct_issues.append("Another live runtime currently owns the direct-runtime lock.")
            elif lock_status != "owned":
                direct_status = "needs_attention"
                direct_issues.append("Draft runtime ownership could not be verified.")
            else:
                health = _runtime_health(server)
                if str(health.get("status") or "") == "needs_attention":
                    direct_status = "needs_attention"
                    direct_issues.append("Runtime health is degraded.")
                else:
                    direct_status = "draft_active"
                    direct_issues.append("Unreviewed draft is active. This is unsafe local developer mode, not the normal caveman path.")
    elif str(verify.get("status") or "") != "Safe":
        direct_issues.append("Verification must be Safe before normal activation.")
    elif binding.get("store_fingerprint") != str(store_validation.get("store_fingerprint") or ""):
        direct_status = "stale_config"
        direct_issues.append("Runtime store does not match the selected store.")
    elif binding.get("episodes_path") != str(published_set.get("episodes_path") or ""):
        direct_status = "stale_config"
        direct_issues.append("Runtime reviewed set does not match the published set.")
    else:
        lock_status = str(lock_summary.get("status") or "")
        if lock_status == "missing":
            direct_status = "needs_attention"
            direct_issues.append("Direct runtime lock is missing. Repair the runtime claim before treating it as active.")
        elif lock_status == "stale":
            direct_status = "needs_attention"
            direct_issues.append("Direct runtime lock is stale. Run cleanup to repair ownership.")
        elif lock_status == "foreign_live":
            direct_status = "needs_attention"
            direct_issues.append("Another live runtime currently owns the direct-runtime lock.")
        elif lock_status != "owned":
            direct_status = "needs_attention"
            direct_issues.append("Direct runtime ownership could not be verified.")
        else:
            health = _runtime_health(server)
            if str(health.get("status") or "") == "needs_attention":
                direct_status = "needs_attention"
                direct_issues.append("Runtime health is degraded.")
            elif binding.get("episodes_path"):
                direct_status = "running"
    activation = dict(state.get("activation") or _wizard_empty_activation_state())
    activation["direct"] = {
        "status": direct_status,
        "checked_at": _utc_iso(),
        "store_fingerprint": str(binding.get("store_fingerprint") or ""),
        "episodes_path": str(binding.get("episodes_path") or ""),
        "runtime_url": f"http://{server.server_address[0]}:{server.server_address[1]}/" if binding.get("episodes_path") else "",
        "issues": direct_issues,
        "lock": lock_summary,
        "artifact_mode": str(binding.get("artifact_mode") or ""),
        "build_id": str(binding.get("build_id") or ""),
    }
    activation["draft_override"] = draft_override
    return activation


def _wizard_restore_json_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _wizard_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wizard_read_runtime_lock() -> dict[str, Any]:
    if not LIVE_RUNTIME_LOCK_PATH.exists():
        return {}
    try:
        payload = _load_json_file(LIVE_RUNTIME_LOCK_PATH)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _wizard_write_runtime_lock(server: "RuntimeHTTPServer", *, binding: Mapping[str, Any]) -> dict[str, Any]:
    token = str(uuid4().hex)
    host, port = server.server_address
    payload = {
        "pid": os.getpid(),
        "host": str(host),
        "port": int(port),
        "token": token,
        "store_path": str(binding.get("store_path") or ""),
        "store_fingerprint": str(binding.get("store_fingerprint") or ""),
        "episodes_path": str(binding.get("episodes_path") or ""),
        "checked_at": _utc_iso(),
    }
    LIVE_RUNTIME_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(LIVE_RUNTIME_LOCK_PATH, payload)
    return payload


def _wizard_clear_runtime_lock(*, only_if_stale: bool = False) -> bool:
    payload = _wizard_read_runtime_lock()
    if not payload:
        return False
    if only_if_stale and _wizard_pid_alive(int(payload.get("pid") or 0)):
        return False
    LIVE_RUNTIME_LOCK_PATH.unlink(missing_ok=True)
    return True


def _wizard_runtime_lock_matches_server(server: "RuntimeHTTPServer", payload: Mapping[str, Any]) -> bool:
    expected = dict(getattr(server, "active_runtime_lock", {}) or {})
    if not expected:
        return False
    token = str(payload.get("token") or "")
    if token != str(expected.get("token") or ""):
        return False
    host, port = server.server_address
    return str(payload.get("host") or "") == str(host) and int(payload.get("port") or 0) == int(port)


def _wizard_runtime_lock_summary(server: "RuntimeHTTPServer") -> dict[str, Any]:
    payload = _wizard_read_runtime_lock()
    if not payload:
        return {
            "status": "missing",
            "checked_at": _utc_iso(),
            "cleanup_allowed": bool(getattr(server, "active_runtime_binding", {}).get("episodes_path")),
            "owner_pid": 0,
            "owner_host": "",
            "owner_port": 0,
        }
    owner_pid = int(payload.get("pid") or 0)
    owner_host = str(payload.get("host") or "")
    owner_port = int(payload.get("port") or 0)
    alive = _wizard_pid_alive(owner_pid)
    if _wizard_runtime_lock_matches_server(server, payload):
        status = "owned"
    elif alive:
        status = "foreign_live"
    else:
        status = "stale"
    return {
        "status": status,
        "checked_at": str(payload.get("checked_at") or _utc_iso()),
        "cleanup_allowed": status in {"missing", "stale"},
        "owner_pid": owner_pid,
        "owner_host": owner_host,
        "owner_port": owner_port,
    }


def _wizard_repair_or_clear_runtime_lock(server: "RuntimeHTTPServer", state: Mapping[str, Any]) -> dict[str, Any]:
    lock_payload = _wizard_read_runtime_lock()
    if lock_payload and not _wizard_runtime_lock_matches_server(server, lock_payload) and _wizard_pid_alive(int(lock_payload.get("pid") or 0)):
        raise RuntimeError("A different live runtime still owns the direct-runtime lock. Cleanup is blocked.")
    binding = _wizard_current_runtime_binding(server)
    verify = dict(state.get("verify") or {})
    store_validation = dict(state.get("store_validation") or {})
    published_set = dict(state.get("published_set") or {})
    binding_matches_selected = (
        str(verify.get("status") or "") == "Safe"
        and str(binding.get("store_fingerprint") or "") == str(store_validation.get("store_fingerprint") or "")
        and str(binding.get("episodes_path") or "") == str(published_set.get("episodes_path") or "")
        and bool(binding.get("episodes_path"))
    )
    if binding_matches_selected:
        repaired = _wizard_write_runtime_lock(server, binding=binding)
        server.active_runtime_lock = dict(repaired)
        return {"action": "repaired", "lock": _wizard_runtime_lock_summary(server)}
    cleared = _wizard_clear_runtime_lock(only_if_stale=False)
    if cleared:
        server.active_runtime_lock = {}
    return {"action": "cleared" if cleared else "noop", "lock": _wizard_runtime_lock_summary(server)}


def _wizard_release_runtime_lock(server: "RuntimeHTTPServer") -> bool:
    payload = _wizard_read_runtime_lock()
    if not payload or not _wizard_runtime_lock_matches_server(server, payload):
        return False
    LIVE_RUNTIME_LOCK_PATH.unlink(missing_ok=True)
    server.active_runtime_lock = {}
    return True


def _wizard_validate_episode_artifact(
    path: Path,
    *,
    mode: str,
    expected_store_fingerprint: str = "",
    expected_build_id: str = "",
) -> dict[str, Any]:
    payload = _load_episode_cards_payload(path)
    schema = str(payload.get("schema") or "").strip()
    cards = [row for row in list(payload.get("cards") or []) if isinstance(row, dict)]
    if mode == "draft":
        if schema != "numquamoblita.episode_cards.v1":
            raise ValueError("replacement draft must be an episode_cards draft artifact")
        return {
            "path": str(path),
            "schema": schema,
            "episode_count": len(cards),
        }
    if mode != "published":
        raise ValueError("unsupported episode artifact mode")
    if schema != "numquamoblita.episode_cards.reviewed.v1":
        raise ValueError("replacement published set must be an episode_cards.reviewed artifact")
    payload_store = str(payload.get("store_fingerprint") or "").strip()
    payload_build = str(payload.get("build_id") or "").strip()
    if expected_store_fingerprint and payload_store and payload_store != expected_store_fingerprint:
        raise ValueError("replacement published set does not match the selected store fingerprint")
    if expected_build_id and payload_build and payload_build != expected_build_id:
        raise ValueError("replacement published set does not match the latest build identifier")
    return {
        "path": str(path),
        "schema": schema,
        "episode_count": len(cards),
        "store_fingerprint": payload_store,
        "build_id": payload_build,
    }


def _wizard_missing_artifact_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected_input = dict(state.get("selected_input") or {})
    store_validation = dict(state.get("store_validation") or {})
    build_info = dict(state.get("build_info") or {})
    published_set = dict(state.get("published_set") or {})
    rows: list[dict[str, Any]] = []

    def _append(target: str, label: str, path: str, recommendation: str, reset_stage: str) -> None:
        clean_path = str(path or "").strip()
        if not clean_path:
            return
        resolved = Path(clean_path).expanduser().resolve()
        if resolved.exists():
            return
        rows.append(
            {
                "target": target,
                "label": label,
                "missing_path": clean_path,
                "recommendation": recommendation,
                "reset_stage": reset_stage,
            }
        )

    selected_kind = str(selected_input.get("kind") or "").strip()
    if selected_kind == "ia_archive":
        _append("selected_input", "Original IA archive", str(selected_input.get("path") or ""), "Pick the archive again or reset to Import.", "import")
    elif selected_kind in WIZARD_VALID_STORE_KINDS:
        _append("selected_input", "Selected MNO store", str(selected_input.get("path") or ""), "Pick the store again or reset to Import.", "import")
    _append("store_validation", "Active runtime store", str(store_validation.get("path") or state.get("store_path") or ""), "Pick a valid MNO store or reset to Import.", "import")
    _append("draft_cards", "Draft episode cards", str(build_info.get("draft_path") or state.get("last_built_episode_draft_path") or ""), "Pick the draft cards again or reset to Build Episodes.", "build_episodes")
    _append("published_set", "Published reviewed set", str(published_set.get("episodes_path") or state.get("last_compiled_reviewed_path") or ""), "Pick the reviewed set again or reset to Review.", "review")
    return rows


def _wizard_remap_status_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    verify = dict(state.get("verify") or {})
    return {
        "required": bool(verify.get("remap_required")),
        "missing_artifacts": _wizard_missing_artifact_rows(state),
        "verify_status": str(verify.get("status") or "Unknown"),
    }


def _wizard_apply_remap_to_state(state: dict[str, Any], *, target: str, replacement_path: Path) -> dict[str, Any]:
    resolved = replacement_path.expanduser().resolve()
    if target == "selected_input":
        current_kind = str((state.get("selected_input") or {}).get("kind") or "").strip()
        classification = _wizard_classify_input_path(resolved)
        if current_kind == "ia_archive" and str(classification.get("kind") or "") != "ia_archive":
            raise ValueError("replacement file must be an IA archive")
        if current_kind in WIZARD_VALID_STORE_KINDS and str(classification.get("kind") or "") not in WIZARD_VALID_STORE_KINDS:
            raise ValueError("replacement file must be a valid MNO store")
        _wizard_bind_input_to_state(state, classification)
        return {"target": target, "replacement": dict(classification)}
    if target == "store_validation":
        classification = _wizard_classify_input_path(resolved)
        if str(classification.get("kind") or "") not in WIZARD_VALID_STORE_KINDS or not bool(classification.get("is_valid")):
            raise ValueError("replacement file must be a valid MNO store")
        store_validation = _wizard_empty_store_validation()
        store_validation.update(dict(classification))
        state["store_validation"] = store_validation
        state["store_path"] = str(classification.get("path") or "")
        selected_input = dict(state.get("selected_input") or {})
        if str(selected_input.get("kind") or "") in WIZARD_VALID_STORE_KINDS:
            state["selected_input"] = dict(classification)
        return {"target": target, "replacement": dict(store_validation)}
    if target == "draft_cards":
        artifact = _wizard_validate_episode_artifact(resolved, mode="draft")
        build_info = dict(state.get("build_info") or {})
        build_info["draft_path"] = str(resolved)
        state["build_info"] = build_info
        state["last_built_episode_draft_path"] = str(resolved)
        review_state = dict(state.get("review_state") or _wizard_empty_review_state())
        review_state["source_cards_path"] = str(resolved)
        state["review_state"] = review_state
        return {"target": target, "replacement": artifact}
    if target == "published_set":
        published_set = dict(state.get("published_set") or {})
        artifact = _wizard_validate_episode_artifact(
            resolved,
            mode="published",
            expected_store_fingerprint=str(published_set.get("store_fingerprint") or ""),
            expected_build_id=str(published_set.get("build_id") or ""),
        )
        published_set["episodes_path"] = str(resolved)
        published_set["episode_count"] = int(artifact.get("episode_count") or published_set.get("episode_count") or 0)
        state["published_set"] = published_set
        state["last_compiled_reviewed_path"] = str(resolved)
        published_pointers = dict(state.get("published_pointers") or {})
        published_pointers["episodes_path"] = str(resolved)
        state["published_pointers"] = published_pointers
        return {"target": target, "replacement": artifact}
    raise ValueError("unsupported remap target")


def _wizard_reset_state_to_stage(state: dict[str, Any], *, stage: str, reason: str) -> dict[str, Any]:
    clean_stage = str(stage or "").strip()
    if clean_stage not in {"import", "build_episodes", "review"}:
        raise ValueError("stage must be import, build_episodes, or review")
    _snapshot_published_pointers(state, reason=f"pre_reset_{clean_stage}")
    if clean_stage == "import":
        state["selected_input_archive_path"] = ""
        state["selected_input"] = _wizard_empty_input_selection()
        state["store_validation"] = _wizard_empty_store_validation()
        state["store_path"] = str((REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3").resolve())
    _wizard_reset_downstream_state(state, from_stage=clean_stage)
    _wizard_reset_to_stage(state, stage=clean_stage, note=reason)
    return state

def _quicknote_env_int(name: str, *, default: int, min_value: int, max_value: int) -> int:
    raw = str(os.getenv(name, str(default)) or str(default)).strip()
    return _as_int(raw, default=default, min_value=min_value, max_value=max_value)


def _quicknote_config_from_env() -> dict[str, Any]:
    return {
        "session_cap": _quicknote_env_int("NO_QUICKNOTE_SESSION_CAP", default=24, min_value=1, max_value=500),
        "inactivity_timeout_seconds": _quicknote_env_int(
            "NO_QUICKNOTE_INACTIVITY_TIMEOUT_SECONDS",
            default=3600,
            min_value=60,
            max_value=86_400,
        ),
        "max_note_chars": _quicknote_env_int("NO_QUICKNOTE_MAX_NOTE_CHARS", default=900, min_value=80, max_value=8_000),
        "max_batch_items": _quicknote_env_int("NO_QUICKNOTE_MAX_BATCH_ITEMS", default=24, min_value=1, max_value=200),
        "max_tags": _quicknote_env_int("NO_QUICKNOTE_MAX_TAGS", default=8, min_value=1, max_value=40),
        "max_history_notes": _quicknote_env_int("NO_QUICKNOTE_MAX_HISTORY_NOTES", default=8_000, min_value=100, max_value=250_000),
        "summary_chars": _quicknote_env_int("NO_QUICKNOTE_SUMMARY_CHARS", default=220, min_value=80, max_value=1_000),
    }


def _quicknote_policy_from_env() -> dict[str, Any]:
    mode = str(os.getenv("NO_QUICKNOTE_MODE", "proposal_only") or "proposal_only").strip().lower() or "proposal_only"
    if mode not in {"proposal_only", "auto_apply"}:
        mode = "proposal_only"
    auto_apply_raw = str(os.getenv("NO_QUICKNOTE_AUTO_APPLY", "")).strip()
    auto_apply = _to_bool(auto_apply_raw, default=(mode == "auto_apply"))
    if mode == "proposal_only":
        auto_apply = False
    return {
        "mode": mode,
        "auto_apply": bool(auto_apply),
        "updated_at": _utc_iso(),
    }


def _quicknote_default_state() -> dict[str, Any]:
    now = _utc_iso()
    return {
        "schema": QUICKNOTE_STATE_SCHEMA,
        "updated_at": now,
        "revision": 0,
        "store_signature": "",
        "notes": [],
        "buffers": {},
        "cursors": {},
        "assistant_active_sessions": {},
    }


def _quicknote_load_state(path: Path, *, max_history_notes: int) -> dict[str, Any]:
    if not path.exists():
        return _quicknote_default_state()
    try:
        raw = _load_json_file(path)
    except Exception:
        return _quicknote_default_state()
    state = _quicknote_default_state()
    state.update(raw)
    state["schema"] = QUICKNOTE_STATE_SCHEMA
    state["revision"] = max(0, int(state.get("revision") or 0))
    notes = [row for row in list(state.get("notes") or []) if isinstance(row, dict)]
    if len(notes) > max_history_notes:
        notes = notes[-max_history_notes:]
    state["notes"] = notes
    buffers = dict(state.get("buffers") or {})
    state["buffers"] = {str(key): dict(value) for key, value in buffers.items() if isinstance(value, dict)}
    cursors = dict(state.get("cursors") or {})
    state["cursors"] = {str(key): dict(value) for key, value in cursors.items() if isinstance(value, dict)}
    active = dict(state.get("assistant_active_sessions") or {})
    state["assistant_active_sessions"] = {str(key): str(value) for key, value in active.items() if str(key).strip()}
    state["updated_at"] = str(state.get("updated_at") or _utc_iso())
    state["store_signature"] = str(state.get("store_signature") or "")
    return state


def _quicknote_normalize_identity(value: Any, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = fallback
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-")
    return (cleaned or fallback)[:120]


def _quicknote_normalize_text(value: Any, *, max_chars: int) -> str:
    raw = str(value or "")
    compact = re.sub(r"\s+", " ", raw).strip()
    return compact[:max_chars].strip()


def _quicknote_normalize_importance(value: Any) -> str:
    raw = str(value or "normal").strip().lower() or "normal"
    if raw not in QUICKNOTE_ALLOWED_IMPORTANCE:
        return "normal"
    return raw


def _quicknote_normalize_tags(value: Any, *, max_items: int) -> list[str]:
    tags = _normalize_string_list(value, max_items=max_items, max_chars=64)
    out: list[str] = []
    for tag in tags:
        cleaned = re.sub(r"\s+", " ", str(tag or "")).strip().lower()
        if not cleaned:
            continue
        out.append(cleaned[:64])
    return out[:max_items]


def _quicknote_session_key(assistant_id: str, session_id: str) -> str:
    return f"{assistant_id}::{session_id}"


def _quicknote_text_fingerprint(*, assistant_id: str, session_id: str, text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    payload = f"{assistant_id}|{session_id}|{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _quicknote_resolve_scope(state: dict[str, Any], *, assistant_hint: Any, session_hint: Any) -> tuple[str, str]:
    assistant_id = _quicknote_normalize_identity(assistant_hint, fallback="assistant_default")
    active_sessions = dict(state.get("assistant_active_sessions") or {})
    session_raw = str(session_hint or "").strip()
    if not session_raw:
        session_raw = str(active_sessions.get(assistant_id) or "session_default")
    session_id = _quicknote_normalize_identity(session_raw, fallback="session_default")
    return assistant_id, session_id


def _quicknote_store_signature(runtime: RuntimeSession) -> str:
    atoms = list(runtime.retriever.store.list_atoms())
    atom_count = len(atoms)
    atom_ids = sorted(
        str(getattr(atom, "atom_id", "")).strip()
        for atom in atoms
        if str(getattr(atom, "atom_id", "")).strip()
    )
    sample = atom_ids[:64]
    digest = hashlib.sha256("|".join(sample).encode("utf-8")).hexdigest()[:16] if sample else "none"
    return f"atoms:{atom_count}:sample:{digest}"


def _quicknote_index_notes(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in list(state.get("notes") or []):
        if not isinstance(row, dict):
            continue
        note_id = str(row.get("note_id") or "").strip()
        if not note_id:
            continue
        indexed[note_id] = row
    return indexed


def _quicknote_persist_state(server: Any) -> None:
    state = dict(getattr(server, "quicknote_state", {}) or {})
    state["schema"] = QUICKNOTE_STATE_SCHEMA
    state["updated_at"] = _utc_iso()
    state["store_signature"] = _quicknote_store_signature(server.runtime)
    config = dict(getattr(server, "quicknote_config", {}) or {})
    max_history = max(100, int(config.get("max_history_notes") or 8_000))
    notes = [row for row in list(state.get("notes") or []) if isinstance(row, dict)]
    if len(notes) > max_history:
        notes = notes[-max_history:]
    state["notes"] = notes
    setattr(server, "quicknote_state", state)
    state_path = Path(str(getattr(server, "quicknote_state_path", QUICKNOTE_STATE_PATH)).strip() or str(QUICKNOTE_STATE_PATH))
    _write_json_file(state_path, state)


def _quicknote_ensure_buffer(state: dict[str, Any], *, assistant_id: str, session_id: str, cap: int) -> dict[str, Any]:
    buffers = dict(state.get("buffers") or {})
    key = _quicknote_session_key(assistant_id, session_id)
    row = dict(buffers.get(key) or {})
    if not row:
        row = {
            "assistant_id": assistant_id,
            "session_id": session_id,
            "note_ids": [],
            "notes_proposed": 0,
            "notes_applied": 0,
            "last_activity_at": "",
            "last_flush_at": "",
            "last_flush_reason": "",
            "flush_count": 0,
            "cap": cap,
        }
    row["assistant_id"] = assistant_id
    row["session_id"] = session_id
    row["cap"] = max(1, int(row.get("cap") or cap))
    row["note_ids"] = [str(item).strip() for item in list(row.get("note_ids") or []) if str(item).strip()]
    row["notes_proposed"] = max(0, int(row.get("notes_proposed") or 0))
    row["notes_applied"] = max(0, int(row.get("notes_applied") or 0))
    row["flush_count"] = max(0, int(row.get("flush_count") or 0))
    buffers[key] = row
    state["buffers"] = buffers
    return row


def _quicknote_status_payload(
    *,
    assistant_id: str,
    session_id: str,
    buffer: Mapping[str, Any],
) -> dict[str, Any]:
    cap = max(1, int(buffer.get("cap") or 1))
    cap_used = max(0, int(buffer.get("notes_proposed") or 0))
    pending_count = len([str(item).strip() for item in list(buffer.get("note_ids") or []) if str(item).strip()])
    cap_remaining = max(0, cap - cap_used)
    if cap_remaining == 0:
        recommended = "start_new_session_or_reset_cap"
    elif pending_count > 0:
        recommended = "flush_pending_notes"
    else:
        recommended = "continue"
    return {
        "assistant_id": assistant_id,
        "session_id": session_id,
        "pending_count": pending_count,
        "cap_used": cap_used,
        "cap_remaining": cap_remaining,
        "cap": cap,
        "last_activity_at": str(buffer.get("last_activity_at") or ""),
        "last_flush_at": str(buffer.get("last_flush_at") or ""),
        "last_flush_reason": str(buffer.get("last_flush_reason") or ""),
        "flush_count": max(0, int(buffer.get("flush_count") or 0)),
        "recommended_action": recommended,
    }


def _quicknote_flush_buffer(
    state: dict[str, Any],
    *,
    assistant_id: str,
    session_id: str,
    reason: str,
    auto_apply: bool,
    session_cap: int = 24,
) -> dict[str, Any]:
    safe_reason = str(reason or "manual").strip().lower() or "manual"
    if safe_reason not in QUICKNOTE_ALLOWED_FLUSH_REASONS:
        safe_reason = "manual"
    cap = max(1, int(session_cap))
    buffer = _quicknote_ensure_buffer(state, assistant_id=assistant_id, session_id=session_id, cap=cap)
    note_ids = [str(item).strip() for item in list(buffer.get("note_ids") or []) if str(item).strip()]
    if not note_ids:
        return {
            "ok": True,
            "assistant_id": assistant_id,
            "session_id": session_id,
            "reason": safe_reason,
            "flushed_count": 0,
            "noop": True,
            "status_counts": {},
        }
    now = _utc_iso()
    notes_by_id = _quicknote_index_notes(state)
    status_counts: dict[str, int] = {}
    flushed_count = 0
    for note_id in note_ids:
        note = notes_by_id.get(note_id)
        if note is None:
            continue
        next_status = "applied" if auto_apply else "submitted"
        current_status = str(note.get("status") or "proposed").strip().lower() or "proposed"
        if current_status != next_status:
            state["revision"] = max(0, int(state.get("revision") or 0)) + 1
            note["status"] = next_status
            note["updated_at"] = now
            note["status_revision"] = int(state["revision"])
            note["revision"] = int(state["revision"])
        note["last_flush_reason"] = safe_reason
        note["last_flushed_at"] = now
        status_counts[next_status] = int(status_counts.get(next_status) or 0) + 1
        flushed_count += 1
        if next_status == "applied":
            buffer["notes_applied"] = max(0, int(buffer.get("notes_applied") or 0)) + 1
    buffer["note_ids"] = []
    buffer["last_flush_at"] = now
    buffer["last_flush_reason"] = safe_reason
    buffer["flush_count"] = max(0, int(buffer.get("flush_count") or 0)) + 1
    return {
        "ok": True,
        "assistant_id": assistant_id,
        "session_id": session_id,
        "reason": safe_reason,
        "flushed_count": flushed_count,
        "noop": flushed_count == 0,
        "status_counts": status_counts,
    }


def _quicknote_maybe_flush_inactive(
    state: dict[str, Any],
    *,
    inactivity_timeout_seconds: int,
    auto_apply: bool,
    session_cap: int,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    buffers = dict(state.get("buffers") or {})
    flushed: list[dict[str, Any]] = []
    for row in buffers.values():
        if not isinstance(row, dict):
            continue
        note_ids = [str(item).strip() for item in list(row.get("note_ids") or []) if str(item).strip()]
        if not note_ids:
            continue
        last_activity_raw = str(row.get("last_activity_at") or "").strip()
        if not last_activity_raw:
            continue
        try:
            last_activity = datetime.fromisoformat(last_activity_raw)
        except Exception:
            continue
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)
        elapsed = (now - last_activity).total_seconds()
        if elapsed < float(inactivity_timeout_seconds):
            continue
        assistant_id = str(row.get("assistant_id") or "").strip() or "assistant_default"
        session_id = str(row.get("session_id") or "").strip() or "session_default"
        flushed.append(
            _quicknote_flush_buffer(
                state,
                assistant_id=assistant_id,
                session_id=session_id,
                reason="inactivity_timeout",
                auto_apply=auto_apply,
                session_cap=session_cap,
            )
        )
    return flushed


def _quicknote_usage_guide_payload() -> dict[str, Any]:
    return {
        "version": "quicknote.v1",
        "quick_start": [
            "Use explore.orient once at wake-up.",
            "Use explore.expand_anchor or explore.peek in compact mode for low-token exploration.",
            "Use memory.quicknote.propose for important moments during a session.",
            "Use memory.quicknote.flush at session handoff/end.",
            "Use explore.whats_new at next wake-up to catch deltas.",
        ],
        "default_modes": {
            "explore": "compact",
            "peek_only": False,
            "quicknote_write_mode": "proposal_only",
        },
        "token_budget_tips": [
            "Prefer compact mode unless full excerpts are required.",
            "Batch quicknotes with memory.quicknote.propose_batch when possible.",
            "Use explore.whats_new before deep exploration to avoid redundant calls.",
        ],
    }


def _quicknote_status_for_scope(
    state: dict[str, Any],
    *,
    assistant_id: str,
    session_id: str,
    session_cap: int,
) -> dict[str, Any]:
    buffer = _quicknote_ensure_buffer(state, assistant_id=assistant_id, session_id=session_id, cap=session_cap)
    return _quicknote_status_payload(assistant_id=assistant_id, session_id=session_id, buffer=buffer)


def _quicknote_trim_history(state: dict[str, Any], *, max_history_notes: int) -> None:
    notes = [row for row in list(state.get("notes") or []) if isinstance(row, dict)]
    if len(notes) <= max_history_notes:
        state["notes"] = notes
        return
    overflow = len(notes) - max_history_notes
    removed = notes[:overflow]
    keep = notes[overflow:]
    removed_ids = {str(row.get("note_id") or "").strip() for row in removed}
    buffers = dict(state.get("buffers") or {})
    for key, row in buffers.items():
        if not isinstance(row, dict):
            continue
        note_ids = [str(item).strip() for item in list(row.get("note_ids") or []) if str(item).strip() and str(item).strip() not in removed_ids]
        row["note_ids"] = note_ids
        buffers[key] = row
    state["buffers"] = buffers
    state["notes"] = keep


def _quicknote_find_duplicate(
    state: dict[str, Any],
    *,
    assistant_id: str,
    session_id: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    for row in reversed(list(state.get("notes") or [])):
        if not isinstance(row, dict):
            continue
        if str(row.get("assistant_id") or "") != assistant_id:
            continue
        if str(row.get("session_id") or "") != session_id:
            continue
        if str(row.get("fingerprint") or "") != fingerprint:
            continue
        return row
    return None


def _quicknote_session_rollover_flush(
    state: dict[str, Any],
    *,
    assistant_id: str,
    session_id: str,
    auto_apply: bool,
    session_cap: int,
) -> list[dict[str, Any]]:
    active_map = dict(state.get("assistant_active_sessions") or {})
    previous_session = str(active_map.get(assistant_id) or "").strip()
    flushed: list[dict[str, Any]] = []
    if previous_session and previous_session != session_id:
        previous_key = _quicknote_session_key(assistant_id, previous_session)
        previous_buffer = dict(dict(state.get("buffers") or {}).get(previous_key) or {})
        if list(previous_buffer.get("note_ids") or []):
            flushed.append(
                _quicknote_flush_buffer(
                    state,
                    assistant_id=assistant_id,
                    session_id=previous_session,
                    reason="session_rollover",
                    auto_apply=auto_apply,
                    session_cap=session_cap,
                )
            )
    active_map[assistant_id] = session_id
    state["assistant_active_sessions"] = active_map
    return flushed


def _quicknote_propose(
    state: dict[str, Any],
    *,
    assistant_id: str,
    session_id: str,
    text: str,
    importance: str,
    tags: list[str],
    session_cap: int,
    max_history_notes: int,
    auto_apply: bool,
    summary_chars: int,
    context_pressure: str,
) -> dict[str, Any]:
    _quicknote_session_rollover_flush(
        state,
        assistant_id=assistant_id,
        session_id=session_id,
        auto_apply=auto_apply,
        session_cap=session_cap,
    )
    buffer = _quicknote_ensure_buffer(state, assistant_id=assistant_id, session_id=session_id, cap=session_cap)
    cap_used = max(0, int(buffer.get("notes_proposed") or 0))
    if cap_used >= session_cap:
        overflow_flush = _quicknote_flush_buffer(
            state,
            assistant_id=assistant_id,
            session_id=session_id,
            reason="cap_reached",
            auto_apply=auto_apply,
            session_cap=session_cap,
        )
        status_payload = _quicknote_status_payload(assistant_id=assistant_id, session_id=session_id, buffer=buffer)
        return {
            "ok": False,
            "accepted": False,
            "status": "cap_reached",
            "reason": "cap_reached",
            "status_info": status_payload,
            "flush": overflow_flush,
        }
    fingerprint = _quicknote_text_fingerprint(assistant_id=assistant_id, session_id=session_id, text=text)
    duplicate = _quicknote_find_duplicate(
        state,
        assistant_id=assistant_id,
        session_id=session_id,
        fingerprint=fingerprint,
    )
    if duplicate is not None:
        status_payload = _quicknote_status_payload(assistant_id=assistant_id, session_id=session_id, buffer=buffer)
        return {
            "ok": True,
            "accepted": False,
            "status": "duplicate",
            "reason": "duplicate",
            "duplicate_of": str(duplicate.get("note_id") or ""),
            "status_info": status_payload,
        }
    now = _utc_iso()
    state["revision"] = max(0, int(state.get("revision") or 0)) + 1
    revision = int(state.get("revision") or 0)
    note_id = f"qn_{uuid4().hex[:16]}"
    status = "applied" if auto_apply else "proposed"
    note = {
        "note_id": note_id,
        "assistant_id": assistant_id,
        "session_id": session_id,
        "text": text,
        "summary": _compact_text(text, max_chars=summary_chars),
        "importance": importance,
        "tags": list(tags),
        "status": status,
        "created_at": now,
        "updated_at": now,
        "created_revision": revision,
        "status_revision": revision,
        "revision": revision,
        "fingerprint": fingerprint,
        "source": "quicknote",
    }
    notes = [row for row in list(state.get("notes") or []) if isinstance(row, dict)]
    notes.append(note)
    state["notes"] = notes
    _quicknote_trim_history(state, max_history_notes=max_history_notes)
    buffer["notes_proposed"] = cap_used + 1
    if status == "applied":
        buffer["notes_applied"] = max(0, int(buffer.get("notes_applied") or 0)) + 1
    else:
        note_ids = [str(item).strip() for item in list(buffer.get("note_ids") or []) if str(item).strip()]
        note_ids.append(note_id)
        buffer["note_ids"] = note_ids
    buffer["last_activity_at"] = now
    flush_payload: dict[str, Any] | None = None
    if context_pressure == "high":
        flush_payload = _quicknote_flush_buffer(
            state,
            assistant_id=assistant_id,
            session_id=session_id,
            reason="context_pressure_high",
            auto_apply=auto_apply,
            session_cap=session_cap,
        )
    status_payload = _quicknote_status_payload(assistant_id=assistant_id, session_id=session_id, buffer=buffer)
    out: dict[str, Any] = {
        "ok": True,
        "accepted": True,
        "status": status,
        "note": {
            "note_id": note_id,
            "summary": str(note.get("summary") or ""),
            "importance": importance,
            "tags": list(tags),
            "status": status,
            "created_at": now,
        },
        "status_info": status_payload,
    }
    if flush_payload is not None:
        out["flush"] = flush_payload
    return out


def _quicknote_collect_changes(
    state: dict[str, Any],
    *,
    assistant_id: str,
    since_revision: int,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    counts = {"added": 0, "updated": 0, "resolved": 0}
    tag_counts: dict[str, int] = {}
    unresolved: list[dict[str, Any]] = []
    for note in reversed(list(state.get("notes") or [])):
        if not isinstance(note, dict):
            continue
        if str(note.get("assistant_id") or "") != assistant_id:
            continue
        note_revision = int(note.get("revision") or 0)
        if note_revision <= since_revision:
            continue
        created_revision = int(note.get("created_revision") or 0)
        status_revision = int(note.get("status_revision") or 0)
        status = str(note.get("status") or "proposed").strip().lower() or "proposed"
        if created_revision > since_revision:
            counts["added"] += 1
        else:
            counts["updated"] += 1
        if status in {"submitted", "applied"} and status_revision > since_revision:
            counts["resolved"] += 1
        tags = [str(item).strip().lower() for item in list(note.get("tags") or []) if str(item).strip()]
        for tag in tags:
            tag_counts[tag] = int(tag_counts.get(tag) or 0) + 1
        row = {
            "note_id": str(note.get("note_id") or ""),
            "session_id": str(note.get("session_id") or ""),
            "summary": _compact_text(str(note.get("summary") or note.get("text") or ""), max_chars=220),
            "importance": str(note.get("importance") or "normal"),
            "status": status,
            "updated_at": str(note.get("updated_at") or note.get("created_at") or ""),
            "tags": tags,
        }
        rows.append(row)
        if status == "proposed" and len(unresolved) < limit:
            unresolved.append(row)
        if len(rows) >= limit:
            continue
    anchors = [
        {"anchor_id": tag, "label": tag, "anchor_type": "topic", "change_count": count}
        for tag, count in tag_counts.items()
    ]
    anchors.sort(key=lambda item: (int(item.get("change_count") or 0), str(item.get("label") or "")), reverse=True)
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return rows[:limit], counts, anchors[:limit], unresolved[:limit]


def _quicknote_whats_new_payload(
    state: dict[str, Any],
    *,
    assistant_id: str,
    runtime: RuntimeSession,
    peek_only: bool,
    limit: int,
) -> tuple[dict[str, Any], bool]:
    now = _utc_iso()
    revision = max(0, int(state.get("revision") or 0))
    cursors = dict(state.get("cursors") or {})
    cursor = dict(cursors.get(assistant_id) or {})
    current_signature = _quicknote_store_signature(runtime)
    last_seen_revision = max(0, int(cursor.get("last_seen_revision") or 0))
    cursor_signature = str(cursor.get("store_signature") or "")
    baseline_reset = bool(cursor_signature and cursor_signature != current_signature)
    if baseline_reset:
        last_seen_revision = revision
    changed_notes, counts, top_anchors, unresolved = _quicknote_collect_changes(
        state,
        assistant_id=assistant_id,
        since_revision=last_seen_revision,
        limit=limit,
    )
    advanced = False
    if not peek_only:
        cursor["assistant_id"] = assistant_id
        cursor["last_seen_revision"] = revision
        cursor["last_seen_at"] = now
        cursor["store_signature"] = current_signature
        cursors[assistant_id] = cursor
        state["cursors"] = cursors
        advanced = True
    payload = {
        "ok": True,
        "assistant_id": assistant_id,
        "peek_only": bool(peek_only),
        "cursor": {
            "last_seen_revision": int(last_seen_revision),
            "current_revision": int(revision),
            "last_seen_at": str(cursor.get("last_seen_at") or ""),
            "advanced": bool(advanced),
            "baseline_reset": bool(baseline_reset),
            "store_signature": current_signature,
        },
        "changes": {
            "added_count": int(counts.get("added") or 0),
            "updated_count": int(counts.get("updated") or 0),
            "resolved_count": int(counts.get("resolved") or 0),
            "items": changed_notes,
            "top_changed_anchors": top_anchors,
            "unresolved_highlights": unresolved,
        },
    }
    return payload, advanced


def _latest_wizard_run_id() -> str | None:
    if WIZARD_LATEST_PATH.exists():
        try:
            payload = _load_json_file(WIZARD_LATEST_PATH)
            run_id = str(payload.get("run_id") or "").strip()
            if run_id and _wizard_state_path(run_id).exists():
                return run_id
        except Exception:
            pass
    if not WIZARD_RUNS_ROOT.exists():
        return None
    candidates: list[tuple[float, str]] = []
    for state_path in WIZARD_RUNS_ROOT.glob("wizard_*/wizard_state.json"):
        try:
            mtime = state_path.stat().st_mtime
            run_id = state_path.parent.name
            candidates.append((mtime, run_id))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _load_wizard_state(run_id: str) -> dict[str, Any]:
    path = _wizard_state_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"wizard run not found: {run_id}")
    payload = _load_json_file(path)
    defaults = _wizard_state_defaults(run_id)
    defaults.update(payload)
    defaults["run_id"] = run_id
    if str(defaults.get("current_stage") or "").strip() == "welcome_resume":
        defaults["current_stage"] = "import"
    if not isinstance(defaults.get("history"), list):
        defaults["history"] = []
    if not isinstance(defaults.get("completed_stages"), list):
        defaults["completed_stages"] = []
    if not isinstance(defaults.get("review_decisions"), dict):
        defaults["review_decisions"] = {}
    if not isinstance(defaults.get("published_pointers"), dict):
        defaults["published_pointers"] = {"store_path": "", "episodes_path": ""}
    if not isinstance(defaults.get("published_history"), list):
        defaults["published_history"] = []
    if not isinstance(defaults.get("artifacts"), dict):
        defaults["artifacts"] = {}
    if not isinstance(defaults.get("selected_input"), dict):
        defaults["selected_input"] = _wizard_empty_input_selection()
    if not isinstance(defaults.get("store_validation"), dict):
        defaults["store_validation"] = _wizard_empty_store_validation()
    if not isinstance(defaults.get("build_info"), dict):
        defaults["build_info"] = _wizard_empty_build_info()
    if not isinstance(defaults.get("review_state"), dict):
        defaults["review_state"] = _wizard_empty_review_state()
    if not isinstance(defaults.get("published_set"), dict):
        defaults["published_set"] = _wizard_empty_published_set()
    if not isinstance(defaults.get("activation"), dict):
        defaults["activation"] = _wizard_empty_activation_state()
    verify = defaults.get("verify")
    if not isinstance(verify, dict):
        verify = {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False}
    verify.setdefault("status", "Unknown")
    verify.setdefault("checks", [])
    verify.setdefault("actionable_links", [])
    verify.setdefault("checked_at", "")
    verify.setdefault("remap_required", False)
    defaults["verify"] = verify
    defaults["stage_flow"] = _wizard_stage_state_payload(defaults)
    return defaults


def _save_wizard_state(state: dict[str, Any]) -> dict[str, Any]:
    run_id = str(state.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("wizard state missing run_id")
    state["stage_flow"] = _wizard_stage_state_payload(state)
    state["updated_at"] = _utc_iso()
    _write_json_file(_wizard_state_path(run_id), state)
    _write_json_file(WIZARD_LATEST_PATH, {"run_id": run_id, "updated_at": state["updated_at"]})
    return state


def _start_new_wizard_state() -> dict[str, Any]:
    run_id = f"wizard_{_utc_stamp()}"
    state = _wizard_state_defaults(run_id)
    return _save_wizard_state(state)


def _load_or_create_wizard_state(*, run_id: str | None = None, start_new: bool = False) -> dict[str, Any]:
    if start_new:
        return _start_new_wizard_state()
    if run_id:
        return _load_wizard_state(run_id)
    latest = _latest_wizard_run_id()
    if latest:
        return _load_wizard_state(latest)
    return _start_new_wizard_state()


def _wizard_history(state: dict[str, Any], *, stage: str, note: str, status: str = "ok") -> None:
    history = state.get("history")
    if not isinstance(history, list):
        history = []
        state["history"] = history
    history.append(
        {
            "at": _utc_iso(),
            "stage": str(stage),
            "status": str(status),
            "note": str(note),
        }
    )
    if len(history) > 120:
        state["history"] = history[-120:]


def _mark_wizard_stage(state: dict[str, Any], *, stage: str, note: str) -> None:
    clean_stage = str(stage or "").strip()
    if clean_stage in WIZARD_STAGE_SEQUENCE:
        _wizard_transition(state, stage=clean_stage, note=note, completed=True)
        return
    state["current_stage"] = clean_stage
    completed = state.get("completed_stages")
    if not isinstance(completed, list):
        completed = []
    if clean_stage and clean_stage not in completed:
        completed.append(clean_stage)
    state["completed_stages"] = completed
    _wizard_history(state, stage=clean_stage, note=note, status="ok")


def _snapshot_published_pointers(state: dict[str, Any], *, reason: str) -> None:
    published = state.get("published_pointers")
    if not isinstance(published, dict):
        return
    store_path = str(published.get("store_path") or "").strip()
    episodes_path = str(published.get("episodes_path") or "").strip()
    if not store_path and not episodes_path:
        return
    history = state.get("published_history")
    if not isinstance(history, list):
        history = []
    snapshot = {
        "at": _utc_iso(),
        "reason": str(reason or "").strip() or "snapshot",
        "published_pointers": {
            "store_path": store_path,
            "episodes_path": episodes_path,
        },
        "published_set": dict(state.get("published_set") or {}),
    }
    if history:
        latest = history[-1] if isinstance(history[-1], dict) else {}
        latest_published = latest.get("published_pointers") if isinstance(latest, dict) else {}
        if (
            isinstance(latest_published, dict)
            and str(latest_published.get("store_path") or "").strip() == store_path
            and str(latest_published.get("episodes_path") or "").strip() == episodes_path
        ):
            state["published_history"] = history
            return
    history.append(snapshot)
    if len(history) > 50:
        history = history[-50:]
    state["published_history"] = history


def _resolve_episode_cards_path(runtime: RuntimeSession, wizard_state: dict[str, Any] | None = None) -> Path | None:
    candidates: list[Path] = []
    if wizard_state:
        published = str((wizard_state.get("published_set") or {}).get("episodes_path") or "").strip()
        reviewed = str(wizard_state.get("last_compiled_reviewed_path") or "").strip()
        draft = str((wizard_state.get("build_info") or {}).get("draft_path") or wizard_state.get("last_built_episode_draft_path") or "").strip()
        if published:
            candidates.append(Path(published).expanduser().resolve())
        if reviewed:
            candidates.append(Path(reviewed).expanduser().resolve())
        if draft:
            candidates.append(Path(draft).expanduser().resolve())
    runtime_cards = str(getattr(runtime, "episode_cards_path", "") or "").strip()
    if runtime_cards:
        candidates.append(Path(runtime_cards).expanduser().resolve())
    reviewed_default = (EPISODES_ROOT / "episode_cards.reviewed.json").resolve()
    candidates.append(reviewed_default)
    if EPISODES_ROOT.exists():
        latest = sorted(EPISODES_ROOT.glob("episode_cards_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        candidates.extend(item.resolve() for item in latest[:2])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _load_episode_cards_payload(path: Path) -> dict[str, Any]:
    payload = _load_json_file(path)
    cards = payload.get("cards")
    if not isinstance(cards, list):
        raise ValueError("episode cards payload missing cards[]")
    return payload


def _normalize_episode_card(card: dict[str, Any]) -> dict[str, Any]:
    episode_id = str(card.get("episode_id") or "").strip()
    topics = _normalize_string_list(card.get("topic_tags") or card.get("topics") or [], max_items=32, max_chars=64)
    actors = _normalize_string_list(card.get("actors") or card.get("entities") or [], max_items=32, max_chars=64)
    cue_terms = _normalize_string_list(card.get("cue_terms") or [], max_items=48, max_chars=72)
    citations = _normalize_string_list(card.get("citations") or [], max_items=48, max_chars=120)
    timestamp_start = str(card.get("timestamp_start") or card.get("start_at") or "").strip()
    timestamp_end = str(card.get("timestamp_end") or card.get("end_at") or "").strip()
    return {
        **card,
        "episode_id": episode_id,
        "title": str(card.get("title") or "").strip(),
        "summary": str(card.get("summary") or "").strip(),
        "topic_tags": topics,
        "topics": list(topics),
        "actors": actors,
        "entities": list(actors),
        "cue_terms": cue_terms,
        "citations": citations,
        "timestamp_start": timestamp_start,
        "start_at": timestamp_start,
        "timestamp_end": timestamp_end,
        "end_at": timestamp_end,
        "promotion_status": str(card.get("promotion_status") or "approved").strip().lower() or "approved",
    }


def _compile_reviewed_payload(
    *,
    source_payload: dict[str, Any],
    review_decisions: dict[str, Any],
    reviewer: str,
    source_cards_path: Path,
    store_fingerprint: str,
    schema_version: int | None,
    build_id: str,
) -> dict[str, Any]:
    rows = list(source_payload.get("cards") or [])
    approved_cards: list[dict[str, Any]] = []
    counts = {"approved": 0, "edited": 0, "rejected": 0}
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_episode_card(dict(row))
        episode_id = str(normalized.get("episode_id") or "").strip()
        if not episode_id:
            continue
        decision_payload = review_decisions.get(episode_id)
        if not isinstance(decision_payload, dict):
            raise ValueError(f"episode {episode_id} has no explicit review decision")
        decision = str(decision_payload.get("decision") or "pending").strip().lower()
        if decision not in {"approved", "edited", "rejected"}:
            raise ValueError(f"episode {episode_id} is still pending review")
        if decision in {"reject", "rejected"}:
            counts["rejected"] += 1
            continue
        if decision in {"edit", "edited"}:
            title = str(decision_payload.get("title") or "").strip()
            summary = str(decision_payload.get("summary") or "").strip()
            actors = _normalize_string_list(decision_payload.get("actors"), max_items=32, max_chars=64)
            topic_tags = _normalize_string_list(decision_payload.get("topic_tags"), max_items=32, max_chars=64)
            cue_terms = _normalize_string_list(decision_payload.get("cue_terms"), max_items=48, max_chars=72)
            if title:
                normalized["title"] = title
            if summary:
                normalized["summary"] = summary
            if actors:
                normalized["actors"] = actors
                normalized["entities"] = list(actors)
            if topic_tags:
                normalized["topic_tags"] = topic_tags
                normalized["topics"] = list(topic_tags)
            if cue_terms:
                normalized["cue_terms"] = cue_terms
            counts["edited"] += 1
        elif decision in {"approve", "approved"}:
            counts["approved"] += 1
        normalized["promotion_status"] = "approved"
        normalized["reviewed_by"] = str(reviewer or "runtime_ui")
        normalized["reviewed_at"] = _utc_iso()
        approved_cards.append(normalized)

    return {
        "schema": "numquamoblita.episode_cards.reviewed.v1",
        "generated_at": _utc_iso(),
        "source_cards": str(source_cards_path),
        "review_tsv": "",
        "store_fingerprint": str(store_fingerprint or ""),
        "store_schema_version": schema_version,
        "build_id": str(build_id or ""),
        "episode_count": len(approved_cards),
        "review_counts": counts,
        "cards": approved_cards,
    }


def _write_payload_with_backup(path: Path, payload: dict[str, Any], *, reason: str) -> str | None:
    backup_path: str | None = None
    if path.exists():
        backup_dir = BACKUPS_ROOT / "episode_cards"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = _utc_stamp()
        destination = backup_dir / f"{path.stem}_{stamp}.json"
        shutil.copy2(path, destination)
        backup_path = str(destination.resolve())
    _write_json_file(path, payload)
    if backup_path:
        audit_path = EPISODES_ROOT / "episode_edit_audit.json"
        audit = {"entries": []}
        if audit_path.exists():
            try:
                loaded = _load_json_file(audit_path)
                if isinstance(loaded.get("entries"), list):
                    audit = loaded
            except Exception:
                audit = {"entries": []}
        entries = list(audit.get("entries") or [])
        entries.append(
            {
                "at": _utc_iso(),
                "path": str(path.resolve()),
                "backup_path": backup_path,
                "reason": reason,
            }
        )
        if len(entries) > 200:
            entries = entries[-200:]
        audit["entries"] = entries
        _write_json_file(audit_path, audit)
    return backup_path


def _undo_last_episode_edit() -> dict[str, Any]:
    audit_path = EPISODES_ROOT / "episode_edit_audit.json"
    if not audit_path.exists():
        raise FileNotFoundError("no episode edit audit log found")
    audit = _load_json_file(audit_path)
    entries = list(audit.get("entries") or [])
    if not entries:
        raise FileNotFoundError("no episode edits available to undo")
    last = entries.pop()
    backup_path = Path(str(last.get("backup_path") or "")).expanduser().resolve()
    target_path = Path(str(last.get("path") or "")).expanduser().resolve()
    if not backup_path.exists():
        raise FileNotFoundError(f"backup file missing: {backup_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, target_path)
    audit["entries"] = entries
    _write_json_file(audit_path, audit)
    return {"restored_path": str(target_path), "backup_path": str(backup_path), "remaining": len(entries)}


def _reload_runtime_episode_index(runtime: RuntimeSession, episode_cards_path: Path) -> dict[str, Any]:
    path = episode_cards_path.expanduser().resolve()
    runtime.episode_cards_path = str(path)
    loader = getattr(runtime, "_load_episode_index", None)
    if callable(loader):
        runtime._episode_index = loader(str(path))  # type: ignore[attr-defined]
    index = getattr(runtime, "_episode_index", None)
    card_count = len(list(getattr(index, "cards", []) or [])) if index is not None else 0
    return {"episode_cards_path": str(path), "loaded_cards": card_count}


def _build_why_payload(runtime: RuntimeSession, turn: Any, *, include_citations: bool) -> dict[str, Any]:
    session_id = str(getattr(turn, "session_id", "") or "").strip() or None
    memory_preference = str(getattr(turn, "memory_preference", "") or "").strip() or None
    package = runtime.build_context_package(
        str(getattr(turn, "user_text", "") or ""),
        session_id=session_id,
        package_version="v2",
        memory_preference=memory_preference,
        render_citations=bool(include_citations),
    )
    service_raw = package.get("service_verdict")
    service_verdict = dict(service_raw) if isinstance(service_raw, dict) else {"decision": str(service_raw or "")}
    evidence_raw = package.get("ltm_evidence")
    ltm_evidence_by_section: dict[str, list[dict[str, Any]]] = {}
    if isinstance(evidence_raw, dict):
        for section, entries in evidence_raw.items():
            section_key = str(section or "").strip().lower() or "core"
            if not isinstance(entries, list):
                continue
            rows = [entry for entry in entries if isinstance(entry, dict)]
            if rows:
                ltm_evidence_by_section[section_key] = rows
    elif isinstance(evidence_raw, list):
        for entry in evidence_raw:
            if not isinstance(entry, dict):
                continue
            section_key = str(entry.get("section") or "").strip().lower() or "core"
            ltm_evidence_by_section.setdefault(section_key, []).append(entry)
    diagnostics_raw = package.get("diagnostics")
    diagnostics = diagnostics_raw if isinstance(diagnostics_raw, dict) else {}
    evidence_rows: list[dict[str, Any]] = []
    for section in ("core", "episode", "context", "continuity", "conflict"):
        entries = list(ltm_evidence_by_section.get(section) or [])
        for row in entries[:3]:
            if not isinstance(row, dict):
                continue
            evidence_rows.append(
                {
                    "section": section,
                    "evidence_id": str(row.get("evidence_id") or ""),
                    "summary": str(row.get("summary") or ""),
                    "confidence": float(row.get("confidence") or 0.0),
                    "citations": _normalize_string_list(row.get("citations"), max_items=12, max_chars=120),
                }
            )
    citations: list[str] = []
    seen: set[str] = set()
    if include_citations:
        for token in list(service_verdict.get("citations") or []):
            cleaned = str(token).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                citations.append(cleaned)
        for row in evidence_rows:
            for token in list(row.get("citations") or []):
                cleaned = str(token).strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    citations.append(cleaned)

    return {
        "turn_id": str(getattr(turn, "turn_id", "")),
        "decision": str(service_verdict.get("decision") or getattr(turn, "decision", "")),
        "decision_reason": str(service_verdict.get("reason") or getattr(turn, "route_reason", "")),
        "plain_summary": str(diagnostics.get("status") or ""),
        "evidence_time_window": dict(package.get("evidence_time_window") or {}),
        "top_evidence": evidence_rows,
        "citations": citations if include_citations else [],
        "citations_hidden": not include_citations,
        "open_citation_path": "/api/archive/citation/{citation_token}",
        "package_version": str(package.get("package_version") or "v2"),
    }


def _citation_matches(runtime: RuntimeSession, citation_token: str, *, context_window: int = 3) -> dict[str, Any]:
    token = str(citation_token or "").strip()
    source_id, sep, message_id = token.partition("#")
    source_id = source_id.strip()
    message_id = message_id.strip() if sep else ""
    if not source_id:
        raise ValueError("citation token must include source_id")
    window = max(0, min(5, int(context_window)))
    rows_by_message: dict[str, dict[str, Any]] = {}
    for atom in runtime.retriever.store.list_atoms():
        atom_id = str(getattr(atom, "atom_id", "") or "").strip()
        text = str(getattr(atom, "canonical_text", "") or "")
        excerpt = _compact_text(text, max_chars=320)
        for ref in list(getattr(atom, "source_refs", []) or []):
            ref_source = str(getattr(ref, "source_id", "") or "").strip()
            if ref_source != source_id:
                continue
            ref_message = str(getattr(ref, "message_id", "") or "").strip() or "unknown_message"
            timestamp_obj = getattr(ref, "timestamp", None)
            timestamp_iso = getattr(timestamp_obj, "isoformat", lambda: "")() or ""
            existing = rows_by_message.get(ref_message)
            candidate = {
                "atom_id": atom_id,
                "message_id": ref_message,
                "source_id": ref_source,
                "source_ref": f"{ref_source}#{ref_message}",
                "timestamp": timestamp_iso,
                "excerpt": excerpt,
            }
            if existing is None:
                rows_by_message[ref_message] = candidate
                continue
            current_score = len(str(existing.get("excerpt") or ""))
            candidate_score = len(excerpt)
            if candidate_score > current_score:
                rows_by_message[ref_message] = candidate
    rows = list(rows_by_message.values())

    def _row_sort_key(row: dict[str, Any]) -> tuple[float, int, str]:
        raw_ts = str(row.get("timestamp") or "").strip()
        if raw_ts:
            try:
                parsed = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                ts_key = parsed.astimezone(timezone.utc).timestamp()
            except Exception:
                ts_key = float("inf")
        else:
            ts_key = float("inf")
        ref_message = str(row.get("message_id") or "").strip()
        digit_match = re.findall(r"\d+", ref_message)
        message_order = int(digit_match[-1]) if digit_match else 10**9
        return ts_key, message_order, ref_message

    rows.sort(key=_row_sort_key)
    if not rows:
        return {
            "citation": token,
            "source_id": source_id,
            "message_id": message_id,
            "context_window": window,
            "matches": [],
        }

    if not message_id:
        selected = rows[:60]
        matches = []
        for idx, row in enumerate(selected):
            hydrated = dict(row)
            hydrated["is_target"] = idx == 0
            hydrated["distance"] = idx
            matches.append(hydrated)
        return {
            "citation": token,
            "source_id": source_id,
            "message_id": message_id,
            "context_window": window,
            "matches": matches,
        }

    target_index = None
    for idx, row in enumerate(rows):
        if str(row.get("message_id") or "").strip() == message_id:
            target_index = idx
            break
    if target_index is None:
        return {
            "citation": token,
            "source_id": source_id,
            "message_id": message_id,
            "context_window": window,
            "matches": [],
        }

    start = max(0, target_index - window)
    end = min(len(rows), target_index + window + 1)
    matches = []
    for idx in range(start, end):
        row = dict(rows[idx])
        row["is_target"] = idx == target_index
        row["distance"] = abs(idx - target_index)
        matches.append(row)
    return {
        "citation": token,
        "source_id": source_id,
        "message_id": message_id,
        "context_window": window,
        "matches": matches,
    }


def _provider_model_config(server: "RuntimeHTTPServer") -> dict[str, Any]:
    adapters = server.adapter_registry.names()
    return {
        "model_name": str(getattr(server.runtime, "model_name", "") or ""),
        "adapters": adapters,
        "adapter_count": len(adapters),
        "config_entrypoint": "/api/runtime/provider/config",
        "settings_endpoints": [
            "/api/runtime/provider/config",
            "/api/runtime/packaging/instructions",
        ],
        "operator_guide_path": str(PACKAGING_GUIDE_PATH.resolve()),
    }


def _runtime_health(server: "RuntimeHTTPServer") -> dict[str, Any]:
    runtime = server.runtime
    checks: list[dict[str, Any]] = []
    failed = False
    warned = False

    try:
        atoms = list(runtime.retriever.store.list_atoms())
        checks.append({"id": "store_integrity", "status": "ok", "detail": f"{len(atoms)} atoms loaded"})
    except Exception as exc:
        failed = True
        checks.append({"id": "store_integrity", "status": "fail", "detail": str(exc)})

    try:
        index = getattr(runtime, "_episode_index", None)
        cards = len(list(getattr(index, "cards", []) or [])) if index is not None else 0
        if index is None:
            warned = True
            checks.append({"id": "episode_cards_load", "status": "warn", "detail": "episode index is not loaded"})
        else:
            checks.append({"id": "episode_cards_load", "status": "ok", "detail": f"{cards} episode cards loaded"})
    except Exception as exc:
        failed = True
        checks.append({"id": "episode_cards_load", "status": "fail", "detail": str(exc)})

    try:
        adapters = server.adapter_registry.names()
        if adapters:
            checks.append({"id": "provider_reachable", "status": "ok", "detail": f"{len(adapters)} adapters registered"})
        else:
            warned = True
            checks.append({"id": "provider_reachable", "status": "warn", "detail": "no adapters registered"})
    except Exception as exc:
        failed = True
        checks.append({"id": "provider_reachable", "status": "fail", "detail": str(exc)})

    try:
        usage = shutil.disk_usage(str(REPO_ROOT))
        free_gb = float(usage.free) / float(1024**3)
        status = "ok" if free_gb >= 1.0 else "warn"
        warned = warned or status == "warn"
        checks.append(
            {
                "id": "disk_space",
                "status": status,
                "detail": f"{free_gb:.2f} GiB free",
                "free_bytes": int(usage.free),
            }
        )
    except Exception as exc:
        failed = True
        checks.append({"id": "disk_space", "status": "fail", "detail": str(exc)})

    try:
        DIAGNOSTICS_ROOT.mkdir(parents=True, exist_ok=True)
        probe = DIAGNOSTICS_ROOT / ".health_probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append({"id": "permissions", "status": "ok", "detail": f"writable: {DIAGNOSTICS_ROOT}"})
    except Exception as exc:
        failed = True
        checks.append({"id": "permissions", "status": "fail", "detail": str(exc)})

    status = "safe"
    if failed:
        status = "needs_attention"
    elif warned:
        status = "watch"

    return {
        "status": status,
        "checked_at": _utc_iso(),
        "checks": checks,
        "writeback_policy": dict(server.writeback_policy),
    }


def _export_diagnostics(server: "RuntimeHTTPServer", *, health_payload: dict[str, Any]) -> Path:
    DIAGNOSTICS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = DIAGNOSTICS_ROOT / f"diagnostics_{_utc_stamp()}.zip"
    files: list[Path] = []
    for candidate in [
        REPO_ROOT / "runtime" / "checkpoints" / "LATEST.md",
        REPO_ROOT / "runtime" / "checkpoints" / "LATEST.json",
        PACKAGING_GUIDE_PATH,
    ]:
        if candidate.exists() and candidate.is_file():
            files.append(candidate)
    latest_run_id = _latest_wizard_run_id()
    if latest_run_id:
        wizard_path = _wizard_state_path(latest_run_id)
        if wizard_path.exists():
            files.append(wizard_path)
    runtime_cards = _resolve_episode_cards_path(server.runtime, _load_wizard_state(latest_run_id) if latest_run_id else None)
    if runtime_cards is not None and runtime_cards.exists():
        files.append(runtime_cards)

    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            try:
                rel = path.resolve().relative_to(REPO_ROOT.resolve())
            except Exception:
                rel = path.name
            bundle.write(path, arcname=str(rel))
        bundle.writestr("runtime/health_summary.json", json.dumps(health_payload, indent=2, ensure_ascii=False))

    return out_path.resolve()


def _session_id_from_metadata(metadata: dict[str, Any]) -> str | None:
    return (
        str(
            metadata.get("session_id")
            or metadata.get("conversation_id")
            or metadata.get("thread_id")
            or ""
        ).strip()
        or None
    )


def _serialize_source_ref(ref: Any) -> dict[str, Any]:
    if hasattr(ref, "__dataclass_fields__"):
        payload = asdict(ref)
    elif isinstance(ref, dict):
        payload = dict(ref)
    else:
        payload = {"source_id": str(ref)}
    timestamp = payload.get("timestamp")
    if timestamp is not None and hasattr(timestamp, "isoformat"):
        payload["timestamp"] = timestamp.isoformat()
    return payload


def _serialize_atom(atom: Any) -> dict[str, Any]:
    return {
        "atom_id": str(getattr(atom, "atom_id", "")),
        "atom_type": str(getattr(getattr(atom, "atom_type", ""), "value", getattr(atom, "atom_type", ""))),
        "canonical_text": str(getattr(atom, "canonical_text", "")),
        "entities": list(getattr(atom, "entities", []) or []),
        "topics": list(getattr(atom, "topics", []) or []),
        "confidence": float(getattr(atom, "confidence", 0.0)),
        "salience": float(getattr(atom, "salience", 0.0)),
        "support_count": int(getattr(atom, "support_count", 0)),
        "contradiction_count": int(getattr(atom, "contradiction_count", 0)),
        "status": str(getattr(getattr(atom, "status", ""), "value", getattr(atom, "status", ""))),
        "version_of": getattr(atom, "version_of", None),
        "created_at": getattr(getattr(atom, "created_at", None), "isoformat", lambda: None)(),
        "updated_at": getattr(getattr(atom, "updated_at", None), "isoformat", lambda: None)(),
        "last_reinforced_at": getattr(getattr(atom, "last_reinforced_at", None), "isoformat", lambda: None)(),
        "tombstoned_at": getattr(getattr(atom, "tombstoned_at", None), "isoformat", lambda: None)(),
        "purge_after": getattr(getattr(atom, "purge_after", None), "isoformat", lambda: None)(),
        "source_refs": [_serialize_source_ref(item) for item in list(getattr(atom, "source_refs", []) or [])],
    }


def _card_kind_for_atom(atom: Any) -> str:
    atom_type = str(getattr(getattr(atom, "atom_type", None), "value", getattr(atom, "atom_type", ""))).strip().lower()
    if atom_type == "episode":
        return "event_card"
    if atom_type == "relational":
        return "relationship_card"
    return "fact_card"


def _compact_text(text: str, *, max_chars: int = 220) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3].rstrip()}..."


def _abstractive_card_summary(kind: str, text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return "Memory note: no content available."
    clauses = [piece.strip() for piece in re.split(r"[.\n!?;:]+", cleaned) if piece.strip()]
    lead = clauses[0] if clauses else cleaned
    prefix = {
        "event_card": "Event memory:",
        "relationship_card": "Relationship memory:",
        "fact_card": "Memory note:",
    }.get(str(kind or "").strip().lower(), "Memory note:")
    return _compact_text(f"{prefix} {lead}", max_chars=220)


def _card_citations_for_atom(atom: Any) -> list[str]:
    citations: list[str] = []
    for ref in list(getattr(atom, "source_refs", []) or []):
        source_id = str(getattr(ref, "source_id", "")).strip()
        message_id = str(getattr(ref, "message_id", "")).strip()
        if not source_id:
            continue
        if message_id:
            citations.append(f"{source_id}#{message_id}")
        else:
            citations.append(source_id)
    deduped: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        if citation in seen:
            continue
        seen.add(citation)
        deduped.append(citation)
    return deduped


def _serialize_card(atom: Any) -> dict[str, Any]:
    confidence = max(0.0, min(1.0, float(getattr(atom, "confidence", 0.0))))
    contradiction_count = int(getattr(atom, "contradiction_count", 0))
    status = str(getattr(getattr(atom, "status", None), "value", getattr(atom, "status", ""))).strip().lower()
    contradiction = contradiction_count > 0 or status == "conflicted"
    atom_id = str(getattr(atom, "atom_id", "")).strip()
    citations = _card_citations_for_atom(atom)
    kind = _card_kind_for_atom(atom)
    raw_excerpt = _compact_text(str(getattr(atom, "canonical_text", "")), max_chars=320)
    return {
        "card_id": f"card_{atom_id}",
        "kind": kind,
        "summary": _compact_text(str(getattr(atom, "canonical_text", "")), max_chars=220),
        "summary_abstractive": _abstractive_card_summary(kind, str(getattr(atom, "canonical_text", ""))),
        "raw_excerpt": raw_excerpt,
        "confidence": confidence,
        "contradiction": contradiction,
        "citations": citations,
        "citation_count": len(citations),
        "atom_ids": [atom_id] if atom_id else [],
        "atom_status": status,
        "atom_type": str(getattr(getattr(atom, "atom_type", None), "value", getattr(atom, "atom_type", ""))),
        "updated_at": getattr(getattr(atom, "updated_at", None), "isoformat", lambda: None)(),
    }


def _atom_id_from_card_id(card_id: str) -> str:
    raw = str(card_id or "").strip()
    if raw.startswith("card_"):
        return raw[len("card_") :]
    return raw


def _serialize_event(event: Any) -> dict[str, Any]:
    return {
        "event_id": str(getattr(event, "event_id", "")),
        "event_type": str(getattr(getattr(event, "event_type", ""), "value", getattr(event, "event_type", ""))),
        "atom_id": str(getattr(event, "atom_id", "")),
        "timestamp": getattr(getattr(event, "timestamp", None), "isoformat", lambda: None)(),
        "reason": str(getattr(event, "reason", "")),
        "metadata": dict(getattr(event, "metadata", {}) or {}),
        "source_refs": [_serialize_source_ref(item) for item in list(getattr(event, "source_refs", []) or [])],
    }


def _serialize_proposal(proposal: Any) -> dict[str, Any]:
    replacement = getattr(proposal, "replacement_candidate", None)
    replacement_payload = None
    if replacement is not None:
        replacement_payload = {
            "candidate_id": str(getattr(replacement, "candidate_id", "")),
            "atom_type": str(getattr(getattr(replacement, "atom_type", ""), "value", getattr(replacement, "atom_type", ""))),
            "canonical_text": str(getattr(replacement, "canonical_text", "")),
            "entities": list(getattr(replacement, "entities", []) or []),
            "topics": list(getattr(replacement, "topics", []) or []),
            "confidence": float(getattr(replacement, "confidence", 0.0)),
            "salience": float(getattr(replacement, "salience", 0.0)),
        }
    return {
        "proposal_id": str(getattr(proposal, "proposal_id", "")),
        "action": str(getattr(getattr(proposal, "action", ""), "value", getattr(proposal, "action", ""))),
        "status": str(getattr(getattr(proposal, "status", ""), "value", getattr(proposal, "status", ""))),
        "target_atom_id": str(getattr(proposal, "target_atom_id", "")),
        "reason_code": str(getattr(proposal, "reason_code", "")),
        "retention_days": int(getattr(proposal, "retention_days", 0)),
        "metadata": dict(getattr(proposal, "metadata", {}) or {}),
        "reviewer": getattr(proposal, "reviewer", None),
        "created_at": getattr(getattr(proposal, "created_at", None), "isoformat", lambda: None)(),
        "reviewed_at": getattr(getattr(proposal, "reviewed_at", None), "isoformat", lambda: None)(),
        "replacement_candidate": replacement_payload,
    }


def _proposal_by_id(queue: MutationReviewQueue, proposal_id: str) -> Any:
    for proposal in queue.list_all():
        if str(getattr(proposal, "proposal_id", "")) == proposal_id:
            return proposal
    raise KeyError(proposal_id)


def _iter_snapshot_neighbors(snapshot: Any, atom_id: str) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    constellation_ids: set[str] = set()
    arc_ids: set[str] = set()
    shared: list[dict[str, Any]] = []
    if snapshot is None:
        return constellation_ids, arc_ids, shared
    for item in list(getattr(snapshot, "constellations", []) or []):
        atom_ids = set(getattr(item, "atom_ids", []) or [])
        if atom_id in atom_ids:
            constellation_ids.update(atom_ids)
    for item in list(getattr(snapshot, "narrative_arcs", []) or []):
        atom_ids = set(getattr(item, "atom_ids", []) or [])
        if atom_id in atom_ids:
            arc_ids.update(atom_ids)
    for key in list(getattr(snapshot, "shared_language_keys", []) or []):
        atom_ids = list(getattr(key, "atom_ids", []) or [])
        if atom_id in atom_ids:
            shared.append(
                {
                    "key_id": str(getattr(key, "key_id", "")),
                    "phrase": str(getattr(key, "phrase", "")),
                    "aliases": list(getattr(key, "aliases", []) or []),
                    "domains": list(getattr(key, "domains", []) or []),
                    "atom_ids": atom_ids,
                    "weight": float(getattr(key, "weight", 0.0)),
                    "confidence": float(getattr(key, "confidence", 0.0)),
                }
            )
    constellation_ids.discard(atom_id)
    arc_ids.discard(atom_id)
    return constellation_ids, arc_ids, shared


def _parse_bounded_query_int(
    raw_value: str | None,
    *,
    name: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    text = str(raw_value if raw_value is not None else default).strip()
    if not text:
        return int(default)
    try:
        parsed = int(text)
    except Exception as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")
    return parsed


def _graph_node_summary(atom: Any) -> str:
    return _compact_text(str(getattr(atom, "canonical_text", "")), max_chars=220)


def _graph_node_payload(atom: Any, *, include_detail: bool) -> dict[str, Any]:
    atom_id = str(getattr(atom, "atom_id", "")).strip()
    payload = {
        "atom_id": atom_id,
        "kind": _card_kind_for_atom(atom),
    }
    if include_detail:
        payload.update(
            {
                "card_id": f"card_{atom_id}",
                "status": str(getattr(getattr(atom, "status", None), "value", getattr(atom, "status", ""))),
                "summary": _graph_node_summary(atom),
            }
        )
    return payload


def _graph_relation_targets(
    store: Any,
    snapshot: Any,
    atom_id: str,
    *,
    include_shared_language: bool,
) -> dict[str, list[str]]:
    conflicts = sorted(str(item) for item in set(store.conflict_neighbors(atom_id)))
    constellation_ids, arc_ids, shared = _iter_snapshot_neighbors(snapshot, atom_id)
    payload: dict[str, list[str]] = {
        "conflict": conflicts,
        "constellation": sorted(str(item) for item in constellation_ids),
        "narrative_arc": sorted(str(item) for item in arc_ids),
    }
    if include_shared_language:
        shared_targets: set[str] = set()
        for row in shared:
            for candidate in list(row.get("atom_ids") or []):
                candidate_id = str(candidate).strip()
                if candidate_id and candidate_id != atom_id:
                    shared_targets.add(candidate_id)
        payload["shared_language"] = sorted(shared_targets)
    return payload


def _build_graph_neighbors_payload(
    runtime: RuntimeSession,
    *,
    atom_id: str,
    depth: int = GRAPH_NEIGHBOR_DEFAULT_DEPTH,
    node_limit: int = GRAPH_NEIGHBOR_DEFAULT_NODE_LIMIT,
    link_limit: int = GRAPH_NEIGHBOR_DEFAULT_LINK_LIMIT,
    include_shared_language: bool = False,
    include_root_detail: bool = True,
) -> dict[str, Any]:
    root_atom = runtime.retriever.store.get_atom(atom_id)
    _revision, snapshot = runtime.continuity_store.snapshot_view()

    root_payload = _graph_node_payload(root_atom, include_detail=include_root_detail)
    queue: deque[tuple[str, int]] = deque([(atom_id, 0)])
    expanded: set[str] = {atom_id}
    nodes_by_id: dict[str, dict[str, Any]] = {}
    ordered_neighbors: list[str] = []
    links: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str, str]] = set()
    requests_used = 0
    node_limit_hit = False
    link_limit_hit = False
    request_budget_hit = False
    dropped_shared_language = False

    while queue:
        current, current_distance = queue.popleft()
        if current_distance >= depth:
            continue
        if requests_used >= GRAPH_NEIGHBOR_REQUEST_BUDGET:
            request_budget_hit = True
            break
        requests_used += 1
        relation_map = _graph_relation_targets(
            runtime.retriever.store,
            snapshot,
            current,
            include_shared_language=include_shared_language,
        )
        ordered_edge_kinds = [*GRAPH_NEIGHBOR_EXPANDABLE_EDGE_ORDER]
        if include_shared_language:
            ordered_edge_kinds.extend(GRAPH_NEIGHBOR_RECORD_ONLY_EDGE_ORDER)
        next_distance = current_distance + 1
        for edge_kind in ordered_edge_kinds:
            targets = relation_map.get(edge_kind) or []
            for target in targets:
                target_id = str(target).strip()
                if not target_id or target_id == current:
                    continue
                if target_id == atom_id:
                    continue
                link_key = _canonical_graph_link_key(current, target_id, edge_kind)
                is_new_link = link_key not in seen_links
                if is_new_link and len(links) >= link_limit:
                    link_limit_hit = True
                    if edge_kind == "shared_language":
                        dropped_shared_language = True
                    continue
                target_payload: dict[str, Any] | None = None
                is_new_node = target_id not in nodes_by_id
                if is_new_node:
                    if len(nodes_by_id) >= node_limit:
                        node_limit_hit = True
                        if edge_kind == "shared_language":
                            dropped_shared_language = True
                        continue
                    try:
                        target_atom = runtime.retriever.store.get_atom(target_id)
                    except KeyError:
                        continue
                    target_payload = _graph_node_payload(target_atom, include_detail=True)
                    target_payload["distance"] = next_distance
                    target_payload["via_edge_kind"] = edge_kind
                if is_new_link:
                    seen_links.add(link_key)
                    links.append({"source": current, "target": target_id, "kind": edge_kind})
                if is_new_node and target_payload is not None:
                    nodes_by_id[target_id] = target_payload
                    ordered_neighbors.append(target_id)
                # Record-only edges are still allowed to surface returned neighbor nodes/links;
                # they are only forbidden from driving further BFS expansion.
                if edge_kind in GRAPH_NEIGHBOR_RECORD_ONLY_EDGE_ORDER:
                    continue
                if next_distance >= depth:
                    continue
                if target_id in expanded:
                    continue
                expanded.add(target_id)
                queue.append((target_id, next_distance))
        if request_budget_hit:
            break

    kept_neighbor_ids = set(ordered_neighbors)
    filtered_links = [
        row
        for row in links
        if str(row.get("source") or "") in kept_neighbor_ids.union({atom_id})
        and str(row.get("target") or "") in kept_neighbor_ids.union({atom_id})
    ]
    if len(filtered_links) != len(links):
        link_limit_hit = True
    truncation = {
        "node_limit_hit": bool(node_limit_hit),
        "link_limit_hit": bool(link_limit_hit),
        "request_budget_hit": bool(request_budget_hit),
        "dropped_shared_language": bool(dropped_shared_language),
    }
    return {
        "ok": True,
        "node": root_payload,
        "neighbors": [nodes_by_id[item] for item in ordered_neighbors],
        "links": filtered_links,
        "depth": depth,
        "node_limit": node_limit,
        "link_limit": link_limit,
        "requests_used": requests_used,
        "truncated": any(truncation.values()),
        "truncation": truncation,
    }


def _normalize_anchor_id(value: str) -> str:
    raw = str(value or "").strip().casefold()
    parts: list[str] = []
    pending_dash = False
    for char in raw:
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            if pending_dash and parts:
                parts.append("-")
            parts.append(char)
            pending_dash = False
            continue
        pending_dash = True
    return "".join(parts).strip("-")[:96]


def _is_project_like_token(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    project_terms = (
        "project",
        "roadmap",
        "pipeline",
        "integration",
        "platform",
        "system",
        "module",
        "launch",
        "build",
        "spec",
    )
    return any(term in lowered for term in project_terms)


def _is_event_like_token(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    event_terms = (
        "incident",
        "meeting",
        "conversation",
        "review",
        "checkpoint",
        "day",
        "night",
        "release",
    )
    return any(term in lowered for term in event_terms)


def _anchor_type_for_token(value: str, *, source_kind: str) -> tuple[str, float]:
    token = str(value or "").strip()
    lowered = token.lower()
    if not token:
        return "unknown", 0.0
    if lowered in {"user", "assistant", "system", "team", "unknown"}:
        return "unknown", 0.25
    if _is_project_like_token(token):
        return "project", 0.74 if source_kind == "topic" else 0.7
    if _is_event_like_token(token):
        return "event", 0.66
    if source_kind == "entity":
        return "person", 0.78
    return "topic", 0.62


def _anchor_key(anchor_type: str, anchor_id: str) -> str:
    return f"{str(anchor_type or 'unknown').strip().lower()}:{_normalize_anchor_id(anchor_id)}"


def _exploration_preference_bonus(preferences: dict[str, dict[str, Any]], *, anchor_type: str, anchor_id: str) -> tuple[float, str]:
    key = _anchor_key(anchor_type, anchor_id)
    row = dict(preferences.get(key) or {})
    action = str(row.get("action") or "").strip().lower()
    if action not in EXPLORATION_PREFERENCE_WEIGHTS:
        return 0.0, ""
    return float(EXPLORATION_PREFERENCE_WEIGHTS.get(action) or 0.0), action


def _read_exploration_preferences(server: Any) -> dict[str, dict[str, Any]]:
    lock = getattr(server, "exploration_preferences_lock", None)
    if lock is None:
        return dict(getattr(server, "exploration_preferences", {}) or {})
    with lock:
        return dict(getattr(server, "exploration_preferences", {}) or {})


def _build_exploration_snapshot(
    runtime: RuntimeSession,
    *,
    limit: int,
    preferences: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    atoms = list(runtime.retriever.store.list_atoms())
    atom_by_id = {str(getattr(atom, "atom_id", "")).strip(): atom for atom in atoms}
    grouped: dict[str, dict[str, dict[str, Any]]] = {
        "people": {},
        "projects": {},
        "topics": {},
        "arcs": {},
        "unresolved": {},
    }

    def _bucket_for_type(anchor_type: str) -> str:
        if anchor_type == "person":
            return "people"
        if anchor_type == "project":
            return "projects"
        return "topics"

    def _record_anchor(
        *,
        bucket: str,
        anchor_type: str,
        label: str,
        atom_id: str,
        score: float,
        confidence: float,
        contradiction_count: int = 0,
    ) -> None:
        anchor_id = _normalize_anchor_id(label)
        if not anchor_id:
            return
        entry = grouped[bucket].get(anchor_id)
        if entry is None:
            entry = {
                "anchor_id": anchor_id,
                "label": label[:120],
                "anchor_type": anchor_type,
                "score": 0.0,
                "confidence_sum": 0.0,
                "support_count": 0,
                "contradiction_count": 0,
                "source_atom_ids": [],
            }
            grouped[bucket][anchor_id] = entry
        source_ids = list(entry.get("source_atom_ids") or [])
        is_new_source = bool(atom_id and atom_id not in source_ids)
        if is_new_source:
            source_ids.append(atom_id)
            entry["source_atom_ids"] = source_ids[:16]
            entry["confidence_sum"] = float(entry.get("confidence_sum") or 0.0) + float(confidence)
            entry["support_count"] = int(entry.get("support_count") or 0) + 1
            entry["contradiction_count"] = int(entry.get("contradiction_count") or 0) + int(max(0, contradiction_count))
        elif not atom_id:
            entry["confidence_sum"] = float(entry.get("confidence_sum") or 0.0) + float(confidence)
            entry["support_count"] = int(entry.get("support_count") or 0) + 1
            entry["contradiction_count"] = int(entry.get("contradiction_count") or 0) + int(max(0, contradiction_count))
        entry["score"] = float(entry.get("score") or 0.0) + float(score)

    for atom in atoms:
        atom_id = str(getattr(atom, "atom_id", "")).strip()
        atom_confidence = max(0.0, min(1.0, float(getattr(atom, "confidence", 0.0))))
        atom_salience = max(0.0, min(1.0, float(getattr(atom, "salience", 0.0))))
        contradiction_count = int(getattr(atom, "contradiction_count", 0))
        base_score = 0.2 + (atom_confidence * 0.55) + (atom_salience * 0.45)

        for value in list(getattr(atom, "entities", []) or []):
            label = str(value or "").strip()
            anchor_type, score_weight = _anchor_type_for_token(label, source_kind="entity")
            if anchor_type == "unknown":
                continue
            bucket = _bucket_for_type(anchor_type)
            _record_anchor(
                bucket=bucket,
                anchor_type=anchor_type,
                label=label,
                atom_id=atom_id,
                score=base_score * score_weight,
                confidence=atom_confidence,
                contradiction_count=contradiction_count,
            )

        for value in list(getattr(atom, "topics", []) or []):
            label = str(value or "").strip()
            anchor_type, score_weight = _anchor_type_for_token(label, source_kind="topic")
            if anchor_type == "unknown":
                continue
            bucket = _bucket_for_type(anchor_type)
            _record_anchor(
                bucket=bucket,
                anchor_type=anchor_type,
                label=label,
                atom_id=atom_id,
                score=base_score * score_weight,
                confidence=atom_confidence,
                contradiction_count=contradiction_count,
            )

        if contradiction_count > 0:
            excerpt = _compact_text(str(getattr(atom, "canonical_text", "")), max_chars=96)
            label = excerpt or f"Conflict {atom_id}"
            _record_anchor(
                bucket="unresolved",
                anchor_type="event",
                label=label,
                atom_id=atom_id,
                score=base_score + 0.75 + (0.2 * contradiction_count),
                confidence=max(0.45, atom_confidence),
                contradiction_count=contradiction_count,
            )

    try:
        _revision, snapshot = runtime.continuity_store.snapshot_view()
    except Exception:
        snapshot = None
    for index, arc in enumerate(list(getattr(snapshot, "narrative_arcs", []) or []), start=1):
        atom_ids = [str(item).strip() for item in list(getattr(arc, "atom_ids", []) or []) if str(item).strip()]
        if not atom_ids:
            continue
        label = str(getattr(arc, "label", "") or getattr(arc, "title", "") or "").strip()
        if not label:
            lead_atom = atom_by_id.get(atom_ids[0])
            lead_excerpt = _compact_text(str(getattr(lead_atom, "canonical_text", "")), max_chars=72) if lead_atom else ""
            label = lead_excerpt or f"Narrative arc {index}"
        anchor_id = _normalize_anchor_id(str(getattr(arc, "arc_id", "") or getattr(arc, "cluster_id", "") or f"arc_{index}"))
        if not anchor_id:
            anchor_id = f"arc_{index}"
        grouped["arcs"][anchor_id] = {
            "anchor_id": anchor_id,
            "label": label[:120],
            "anchor_type": "event",
            "score": float(len(atom_ids)) * 0.35 + 0.6,
            "confidence_sum": max(0.5, min(1.0, float(getattr(arc, "coherence", 0.62) or 0.62))),
            "support_count": len(atom_ids),
            "contradiction_count": 0,
            "source_atom_ids": atom_ids[:16],
        }

    buckets_out: dict[str, list[dict[str, Any]]] = {}
    truncated = False
    total_anchors = 0
    for bucket_name, entries in grouped.items():
        rows: list[dict[str, Any]] = []
        for anchor in entries.values():
            support_count = int(anchor.get("support_count") or 0)
            confidence_avg = float(anchor.get("confidence_sum") or 0.0) / float(max(1, support_count))
            preference_bonus, preferred_action = _exploration_preference_bonus(
                preferences,
                anchor_type=str(anchor.get("anchor_type") or ""),
                anchor_id=str(anchor.get("anchor_id") or ""),
            )
            score = float(anchor.get("score") or 0.0) + preference_bonus
            rows.append(
                {
                    "anchor_id": str(anchor.get("anchor_id") or ""),
                    "label": str(anchor.get("label") or ""),
                    "anchor_type": str(anchor.get("anchor_type") or "unknown"),
                    "score": round(score, 4),
                    "confidence": round(confidence_avg, 4),
                    "support_count": support_count,
                    "contradiction_count": int(anchor.get("contradiction_count") or 0),
                    "source_atom_ids": list(anchor.get("source_atom_ids") or []),
                    "preferred_action": preferred_action,
                }
            )
        rows.sort(
            key=lambda row: (
                float(row.get("score") or 0.0),
                float(row.get("confidence") or 0.0),
                int(row.get("support_count") or 0),
                str(row.get("label") or "").lower(),
            ),
            reverse=True,
        )
        total_anchors += len(rows)
        if len(rows) > limit:
            truncated = True
        buckets_out[bucket_name] = rows[:limit]

    return {
        "buckets": buckets_out,
        "total_anchors": total_anchors,
        "truncated": bool(truncated),
        "atom_count": len(atoms),
    }


def _match_anchor_atoms(
    runtime: RuntimeSession,
    *,
    anchor_id: str,
    anchor_type: str,
    limit: int,
) -> list[Any]:
    normalized = _normalize_anchor_id(anchor_id)
    if not normalized:
        return []
    selected: list[tuple[Any, float]] = []
    for atom in list(runtime.retriever.store.list_atoms()):
        entities = [str(item).strip() for item in list(getattr(atom, "entities", []) or []) if str(item).strip()]
        topics = [str(item).strip() for item in list(getattr(atom, "topics", []) or []) if str(item).strip()]
        canon = str(getattr(atom, "canonical_text", "")).strip().lower()
        entity_norm = {_normalize_anchor_id(item) for item in entities}
        topic_norm = {_normalize_anchor_id(item) for item in topics}
        matched = False
        if anchor_type == "person":
            matched = normalized in entity_norm
        elif anchor_type == "project":
            matched = normalized in topic_norm or normalized in entity_norm
        elif anchor_type in {"topic", "event", "unknown"}:
            matched = normalized in topic_norm or normalized in entity_norm
            if not matched and normalized and normalized.replace("-", " ") in canon:
                matched = True
        else:
            matched = normalized in topic_norm or normalized in entity_norm
        if not matched:
            continue
        confidence = max(0.0, min(1.0, float(getattr(atom, "confidence", 0.0))))
        salience = max(0.0, min(1.0, float(getattr(atom, "salience", 0.0))))
        score = (0.6 * confidence) + (0.4 * salience)
        selected.append((atom, score))
    selected.sort(key=lambda item: item[1], reverse=True)
    return [item[0] for item in selected[:limit]]


def _build_exploration_peek_snippets(atoms: list[Any], *, limit: int) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for atom in atoms[:limit]:
        card = _serialize_card(atom)
        citations = [str(item).strip() for item in list(card.get("citations") or []) if str(item).strip()]
        source_ref = citations[0] if citations else ""
        source_id = source_ref.split("#", 1)[0] if source_ref else ""
        snippets.append(
            {
                "atom_id": str(getattr(atom, "atom_id", "")).strip(),
                "card_id": str(card.get("card_id") or "").strip(),
                "snippet": _compact_text(str(card.get("summary_abstractive") or card.get("summary") or ""), max_chars=220),
                "raw_excerpt": _compact_text(str(card.get("raw_excerpt") or card.get("summary") or ""), max_chars=320),
                "confidence": float(card.get("confidence") or 0.0),
                "source_id": source_id,
                "source_ref": source_ref,
            }
        )
    return snippets


def _build_exploration_next_hops(
    runtime: RuntimeSession,
    *,
    matched_atoms: list[Any],
    limit: int,
    preferences: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not matched_atoms:
        return []
    atom_lookup = {str(getattr(atom, "atom_id", "")).strip(): atom for atom in list(runtime.retriever.store.list_atoms())}
    seed_ids = [str(getattr(atom, "atom_id", "")).strip() for atom in matched_atoms if str(getattr(atom, "atom_id", "")).strip()]
    seed_set = set(seed_ids)
    try:
        _revision, snapshot = runtime.continuity_store.snapshot_view()
    except Exception:
        snapshot = None
    candidate_scores: dict[str, float] = {}
    for atom_id in seed_ids:
        conflict_ids = set(runtime.retriever.store.conflict_neighbors(atom_id))
        constellation_ids, arc_ids, _shared = _iter_snapshot_neighbors(snapshot, atom_id)
        for neighbor_id in conflict_ids.union(constellation_ids).union(arc_ids):
            neighbor = str(neighbor_id).strip()
            if not neighbor or neighbor in seed_set:
                continue
            candidate_scores[neighbor] = float(candidate_scores.get(neighbor) or 0.0) + 1.0
    rows: list[dict[str, Any]] = []
    for atom_id, base in candidate_scores.items():
        atom = atom_lookup.get(atom_id)
        if atom is None:
            continue
        entities = [str(item).strip() for item in list(getattr(atom, "entities", []) or []) if str(item).strip()]
        topics = [str(item).strip() for item in list(getattr(atom, "topics", []) or []) if str(item).strip()]
        label = entities[0] if entities else (topics[0] if topics else _compact_text(str(getattr(atom, "canonical_text", "")), max_chars=72))
        source_kind = "entity" if entities else "topic"
        anchor_type, _confidence_hint = _anchor_type_for_token(label, source_kind=source_kind)
        if anchor_type == "unknown":
            anchor_type = "topic"
        anchor_id = _normalize_anchor_id(label) or _normalize_anchor_id(atom_id)
        confidence = max(0.0, min(1.0, float(getattr(atom, "confidence", 0.0))))
        preference_bonus, preferred_action = _exploration_preference_bonus(
            preferences,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
        )
        score = float(base) + confidence + preference_bonus
        rows.append(
            {
                "anchor_id": anchor_id,
                "label": label[:120],
                "anchor_type": anchor_type,
                "score": round(score, 4),
                "confidence": round(confidence, 4),
                "source_atom_id": atom_id,
                "preferred_action": preferred_action,
            }
        )
    rows.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            float(row.get("confidence") or 0.0),
            str(row.get("label") or "").lower(),
        ),
        reverse=True,
    )
    return rows[:limit]


def _wizard_organizer_state(state: dict[str, Any]) -> dict[str, Any]:
    organizer = state.get("organizer")
    if not isinstance(organizer, dict):
        organizer = {}
    if not isinstance(organizer.get("inventory"), dict):
        organizer["inventory"] = {}
    if not isinstance(organizer.get("dedupe"), dict):
        organizer["dedupe"] = {}
    if not isinstance(organizer.get("conflicts"), dict):
        organizer["conflicts"] = {}
    if not isinstance(organizer.get("package"), dict):
        organizer["package"] = {}
    if not isinstance(organizer.get("applied_profile"), dict):
        organizer["applied_profile"] = {}
    if not isinstance(organizer.get("rollback_history"), list):
        organizer["rollback_history"] = []
    if not isinstance(organizer.get("verify"), dict):
        organizer["verify"] = {}
    state["organizer"] = organizer
    return organizer


def _organizer_inventory_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    buckets = dict(snapshot.get("buckets") or {})
    rows: list[dict[str, Any]] = []
    for bucket_name in ("people", "projects", "topics", "arcs", "unresolved"):
        bucket_rows = [row for row in list(buckets.get(bucket_name) or []) if isinstance(row, Mapping)]
        for row in bucket_rows:
            payload = dict(row)
            if not payload:
                continue
            confidence = float(payload.get("confidence") or 0.0)
            support_count = int(payload.get("support_count") or 0)
            contradiction_count = int(payload.get("contradiction_count") or 0)
            is_unresolved = bucket_name == "unresolved"
            risk_class = (
                "safe"
                if (not is_unresolved and contradiction_count <= 0 and confidence >= 0.7 and support_count >= 2)
                else "review"
            )
            payload["bucket"] = bucket_name
            payload["risk_class"] = risk_class
            rows.append(payload)
    rows.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            float(row.get("confidence") or 0.0),
            int(row.get("support_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _organizer_dedupe_proposals(typed_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in typed_candidates:
        label = str(row.get("label") or "").strip()
        anchor_type = str(row.get("anchor_type") or "topic").strip().lower() or "topic"
        if not label:
            continue
        canonical = " ".join(re.split(r"[^A-Za-z0-9]+", label.lower())).strip()
        if not canonical:
            continue
        key = (anchor_type, canonical)
        buckets.setdefault(key, [])
        buckets[key].append(row)
    proposals: list[dict[str, Any]] = []
    index = 0
    for (anchor_type, canonical), rows in buckets.items():
        if len(rows) <= 1:
            continue
        index += 1
        aliases = []
        source_atom_ids: list[str] = []
        support_count = 0
        confidence_values: list[float] = []
        contradiction_count = 0
        for row in rows:
            label = str(row.get("label") or "").strip()
            if label and label not in aliases:
                aliases.append(label)
            support_count += int(row.get("support_count") or 0)
            contradiction_count += int(row.get("contradiction_count") or 0)
            confidence_values.append(float(row.get("confidence") or 0.0))
            for atom_id in list(row.get("source_atom_ids") or []):
                atom_text = str(atom_id).strip()
                if atom_text and atom_text not in source_atom_ids:
                    source_atom_ids.append(atom_text)
        confidence = sum(confidence_values) / float(max(1, len(confidence_values)))
        risk_class = "safe" if confidence >= 0.7 and support_count >= 3 and contradiction_count <= 0 else "review"
        proposals.append(
            {
                "proposal_id": f"org_dedupe_{index:04d}",
                "anchor_type": anchor_type,
                "canonical_label": aliases[0] if aliases else canonical.title(),
                "canonical_key": canonical,
                "aliases": aliases,
                "source_atom_ids": source_atom_ids[:24],
                "support_count": support_count,
                "contradiction_count": contradiction_count,
                "confidence": round(confidence, 4),
                "risk_class": risk_class,
            }
        )
    proposals.sort(
        key=lambda row: (
            int(row.get("support_count") or 0),
            float(row.get("confidence") or 0.0),
        ),
        reverse=True,
    )
    return proposals


def _organizer_conflict_queues(runtime: RuntimeSession, typed_candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conflict_queue: list[dict[str, Any]] = []
    for atom in list(runtime.retriever.store.list_atoms()):
        contradiction_count = int(getattr(atom, "contradiction_count", 0))
        if contradiction_count <= 0:
            continue
        severity = "high" if contradiction_count >= 2 else "medium"
        conflict_queue.append(
            {
                "atom_id": str(getattr(atom, "atom_id", "")).strip(),
                "summary": _compact_text(str(getattr(atom, "canonical_text", "")), max_chars=180),
                "contradiction_count": contradiction_count,
                "severity": severity,
            }
        )
    conflict_queue.sort(key=lambda row: int(row.get("contradiction_count") or 0), reverse=True)

    ambiguity_queue: list[dict[str, Any]] = []
    for row in typed_candidates:
        confidence = float(row.get("confidence") or 0.0)
        support_count = int(row.get("support_count") or 0)
        if confidence >= 0.65 and support_count >= 2:
            continue
        ambiguity_queue.append(
            {
                "anchor_id": str(row.get("anchor_id") or ""),
                "label": str(row.get("label") or ""),
                "anchor_type": str(row.get("anchor_type") or "topic"),
                "confidence": round(confidence, 4),
                "support_count": support_count,
                "risk_class": "review",
            }
        )
    ambiguity_queue.sort(
        key=lambda row: (
            float(row.get("confidence") or 0.0),
            int(row.get("support_count") or 0),
        )
    )
    return conflict_queue, ambiguity_queue


def _organizer_package(
    *,
    dedupe_proposals: list[dict[str, Any]],
    conflict_queue: list[dict[str, Any]],
    ambiguity_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    safe_ops = [row for row in dedupe_proposals if str(row.get("risk_class") or "") == "safe"]
    review_ops = [row for row in dedupe_proposals if str(row.get("risk_class") or "") != "safe"]
    package_id = f"org_pkg_{_utc_stamp().lower()}"
    return {
        "package_id": package_id,
        "created_at": _utc_iso(),
        "safe_operations": safe_ops,
        "review_operations": review_ops,
        "conflict_queue": conflict_queue,
        "ambiguity_queue": ambiguity_queue,
        "counts": {
            "safe_operations": len(safe_ops),
            "review_operations": len(review_ops),
            "conflicts": len(conflict_queue),
            "ambiguities": len(ambiguity_queue),
        },
    }


def _rebuild_snapshot(runtime: RuntimeSession) -> dict[str, Any]:
    policy = default_config().decay
    store = runtime.retriever.store
    consolidator = Consolidator(store, policy=policy)
    registry = SharedLanguageRegistry(store)
    shared_keys = registry.list_keys()
    summary = consolidator.run_with_snapshot(
        runtime.continuity_store,
        builder=ContinuityBuilder(),
        shared_language_keys=shared_keys,
        apply_promotions=False,
    )
    return {
        "snapshot_revision": summary.snapshot_revision,
        "snapshot_stats": dict(summary.snapshot_stats),
    }


def _integration_validate_limits(value: Any) -> None:
    if isinstance(value, str):
        if len(value) > INTEGRATION_MAX_GENERIC_STRING:
            raise IntegrationContractError(
                code="INVALID_INPUT",
                message="string field exceeds max length",
                retryable=False,
                operator_action="reduce_string_field_length",
            )
        return
    if isinstance(value, list):
        if len(value) > INTEGRATION_MAX_ARRAY_ITEMS:
            raise IntegrationContractError(
                code="INVALID_INPUT",
                message="array field exceeds max size",
                retryable=False,
                operator_action="reduce_array_field_size",
            )
        for row in value:
            _integration_validate_limits(row)
        return
    if isinstance(value, dict):
        for row in value.values():
            _integration_validate_limits(row)


def _integration_require_role(*, principal: dict[str, Any], operation: str) -> None:
    normalized_operation = str(operation or "").strip().lower()
    required = INTEGRATION_REQUIRED_ROLES.get(normalized_operation, {"viewer", "operator", "admin"})
    if not _integration_role_allowed(principal=principal, required_roles=required):
        raise IntegrationContractError(
            code="AUTH_FORBIDDEN",
            message="principal role is not authorized for this operation",
            retryable=False,
            operator_action="use_operator_or_admin_token",
            status=HTTPStatus.FORBIDDEN,
        )
    allowed_operations = [
        str(item or "").strip().lower()
        for item in list(principal.get("allowed_operations") or [])
        if str(item or "").strip()
    ]
    if allowed_operations and normalized_operation not in allowed_operations:
        raise IntegrationContractError(
            code="AUTH_FORBIDDEN",
            message="token scope is not authorized for this operation",
            retryable=False,
            operator_action="use_scoped_token_for_requested_operation",
            status=HTTPStatus.FORBIDDEN,
        )


def _integration_parse_get_envelope(
    *,
    parsed_query: str,
    operation: str,
    require_session: bool,
    require_run: bool,
) -> dict[str, Any]:
    query = parse_qs(parsed_query)
    schema_version = str((query.get("schema_version") or [""])[0]).strip()
    if schema_version != INTEGRATION_SCHEMA_VERSION:
        raise IntegrationContractError(
            code="CONTRACT_VERSION_UNSUPPORTED",
            message=f"schema_version must be {INTEGRATION_SCHEMA_VERSION}",
            retryable=False,
            operator_action="set_supported_schema_version",
            status=HTTPStatus.UPGRADE_REQUIRED,
        )
    request_id, request_id_source = _integration_validate_request_id((query.get("request_id") or [""])[0])
    session_id = str((query.get("session_id") or [""])[0]).strip()
    run_id = str((query.get("run_id") or [""])[0]).strip()
    if require_session and not session_id:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="session_id is required",
            retryable=False,
            operator_action="provide_session_id",
        )
    if require_run and not run_id:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="run_id is required",
            retryable=False,
            operator_action="provide_run_id",
        )
    return {
        "schema_version": INTEGRATION_SCHEMA_VERSION,
        "request_id": request_id,
        "request_id_source": request_id_source,
        "operation": operation,
        "session_id": session_id,
        "run_id": run_id,
        "principal": {},
        "data": {},
    }


def _integration_parse_post_envelope(
    *,
    payload: dict[str, Any],
    operation: str,
    require_session: bool,
    require_run: bool,
) -> dict[str, Any]:
    schema_version = str(payload.get("schema_version") or "").strip()
    if schema_version != INTEGRATION_SCHEMA_VERSION:
        raise IntegrationContractError(
            code="CONTRACT_VERSION_UNSUPPORTED",
            message=f"schema_version must be {INTEGRATION_SCHEMA_VERSION}",
            retryable=False,
            operator_action="set_supported_schema_version",
            status=HTTPStatus.UPGRADE_REQUIRED,
        )
    request_id, request_id_source = _integration_validate_request_id(payload.get("request_id"))
    session_id = str(payload.get("session_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    if require_session and not session_id:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="session_id is required",
            retryable=False,
            operator_action="provide_session_id",
        )
    if require_run and not run_id:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="run_id is required",
            retryable=False,
            operator_action="provide_run_id",
        )
    if len(session_id) > 128:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="session_id exceeds max length",
            retryable=False,
            operator_action="reduce_session_id_length",
        )
    if len(run_id) > 128:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="run_id exceeds max length",
            retryable=False,
            operator_action="reduce_run_id_length",
        )
    principal = payload.get("principal")
    if principal is None:
        principal_obj: dict[str, Any] = {}
    elif isinstance(principal, dict):
        principal_obj = dict(principal)
    else:
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="principal must be an object when provided",
            retryable=False,
            operator_action="send_principal_object_or_omit",
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise IntegrationContractError(
            code="INVALID_INPUT",
            message="data must be an object",
            retryable=False,
            operator_action="provide_data_object",
        )
    _integration_validate_depth(data)
    _integration_validate_limits(data)
    _integration_validate_depth(principal_obj)
    _integration_validate_limits(principal_obj)
    return {
        "schema_version": INTEGRATION_SCHEMA_VERSION,
        "request_id": request_id,
        "request_id_source": request_id_source,
        "operation": operation,
        "session_id": session_id,
        "run_id": run_id,
        "principal": principal_obj,
        "data": data,
    }


def _integration_log_event(
    server: "RuntimeHTTPServer",
    *,
    level: str,
    operation: str,
    request_id: str,
    status: str,
    latency_ms: float,
    error_code: str,
    principal: dict[str, Any],
    session_id: str,
    run_id: str,
    proposal_id: str,
    retry_count: int,
    degrade_mode: bool,
    payload: dict[str, Any] | None,
) -> None:
    redacted = _integration_redact_value(payload or {}, key_name="payload")
    log_payload = {
        "timestamp_utc": _utc_iso(),
        "level": str(level),
        "component": "integration.v1",
        "request_id": str(request_id),
        "transport": "http",
        "operation": str(operation),
        "latency_ms": round(max(0.0, float(latency_ms)), 3),
        "status": str(status),
        "error_code": str(error_code),
        "principal": {
            "principal_id": str(principal.get("principal_id") or ""),
            "roles": list(principal.get("roles") or []),
        },
        "session_id": str(session_id),
        "run_id": str(run_id),
        "proposal_id": str(proposal_id),
        "retry_count": int(max(0, retry_count)),
        "degrade_mode": bool(degrade_mode),
        "payload": redacted,
    }
    line = json.dumps(log_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if str(level).lower() == "error":
        LOGGER.error(line)
    else:
        LOGGER.info(line)


def _integration_append_audit(server: "RuntimeHTTPServer", row: dict[str, Any]) -> None:
    path = Path(server.integration_audit_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(row), ensure_ascii=True, separators=(",", ":"))
    with server.integration_audit_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _integration_idempotency_lookup(
    server: "RuntimeHTTPServer",
    *,
    operation: str,
    key: str,
    payload_fingerprint: str,
) -> tuple[dict[str, Any] | None, IntegrationContractError | None]:
    now = time.monotonic()
    with server.integration_idempotency_lock:
        stale_keys = [
            item_key
            for item_key, row in server.integration_idempotency.items()
            if (now - float(row.get("created_at_monotonic") or 0.0)) > INTEGRATION_IDEMPOTENCY_WINDOW_S
        ]
        for item_key in stale_keys:
            server.integration_idempotency.pop(item_key, None)
        state = server.integration_idempotency.get((operation, key))
        if state is None:
            return None, None
        if str(state.get("payload_fingerprint") or "") != payload_fingerprint:
            return None, IntegrationContractError(
                code="INVALID_INPUT",
                message="idempotency key replay has different payload",
                retryable=False,
                operator_action="use_unique_idempotency_key_per_payload",
                status=HTTPStatus.CONFLICT,
            )
        response = state.get("response")
        if isinstance(response, dict):
            replayed = dict(response)
            data = dict(replayed.get("data") or {})
            data["idempotent_replay"] = True
            replayed["data"] = data
            return replayed, None
        return None, None


def _integration_idempotency_store(
    server: "RuntimeHTTPServer",
    *,
    operation: str,
    key: str,
    payload_fingerprint: str,
    response: dict[str, Any],
) -> None:
    with server.integration_idempotency_lock:
        server.integration_idempotency[(operation, key)] = {
            "payload_fingerprint": str(payload_fingerprint),
            "response": dict(response),
            "created_at_monotonic": float(time.monotonic()),
        }


def _integration_dependency_healthy(server: "RuntimeHTTPServer") -> bool:
    try:
        status = str(_runtime_health(server).get("status") or "").strip().lower()
    except Exception:
        return False
    return status in {"safe", "watch"}


class RuntimeRequestHandler(BaseHTTPRequestHandler):
    server: "RuntimeHTTPServer"

    def _integration_send_error(
        self,
        *,
        request_id: str,
        request_id_source: str,
        operation: str,
        error: IntegrationContractError,
        status: HTTPStatus | None = None,
        warnings: list[dict[str, Any]] | None = None,
        degrade_mode: bool = False,
    ) -> None:
        payload = _integration_make_envelope(
            request_id=request_id,
            request_id_source=request_id_source,
            operation=operation,
            ok=False,
            degrade_mode=degrade_mode,
            warnings=list(warnings or [])[:INTEGRATION_MAX_WARNINGS],
            error=_integration_error_payload(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                operator_action=error.operator_action,
            ),
        )
        _json_response(self, status or error.status, payload)

    def _integration_handle_request(self, *, method: str, parsed: Any) -> bool:
        path = str(parsed.path or "").strip()
        if not path.startswith("/api/integration/v1/"):
            return False
        method_upper = str(method or "").strip().upper()
        if method_upper not in {"GET", "POST"}:
            _json_response(self, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method not allowed"})
            return True
        operation_map = {
            ("POST", "/api/integration/v1/context/build"): ("context.build", True, True),
            ("POST", "/api/integration/v1/context/why"): ("context.why", True, True),
            ("POST", "/api/integration/v1/writeback/propose"): ("writeback.propose", True, True),
            ("POST", "/api/integration/v1/writeback/resolve"): ("writeback.resolve", True, False),
            ("GET", "/api/integration/v1/health"): ("health.get", False, False),
            ("GET", "/api/integration/v1/capabilities"): ("capabilities.get", False, False),
        }
        route = operation_map.get((method_upper, path))
        if route is None:
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})
            return True
        operation, require_session, require_run = route

        started = time.perf_counter()
        request_id = _integration_new_request_id()
        request_id_source = "server_generated"
        session_id = ""
        run_id = ""
        proposal_id = ""
        principal: dict[str, Any] = {"principal_id": "", "roles": []}
        request_payload: dict[str, Any] = {}
        error_code = ""
        response_status = HTTPStatus.OK

        try:
            if method_upper == "GET":
                envelope = _integration_parse_get_envelope(
                    parsed_query=str(parsed.query or ""),
                    operation=operation,
                    require_session=require_session,
                    require_run=require_run,
                )
            else:
                payload = _read_json(self)
                envelope = _integration_parse_post_envelope(
                    payload=payload,
                    operation=operation,
                    require_session=require_session,
                    require_run=require_run,
                )
            request_id = str(envelope.get("request_id") or request_id)
            request_id_source = str(envelope.get("request_id_source") or request_id_source)
            session_id = str(envelope.get("session_id") or "")
            run_id = str(envelope.get("run_id") or "")
            request_payload = dict(envelope.get("data") or {})

            principal_row, auth_error = self.server.integration_auth.resolve_authorization(self.headers.get("Authorization"))
            if auth_error is not None:
                raise auth_error
            principal = dict(principal_row or {})
            _integration_require_role(principal=principal, operation=operation)
            envelope_principal = envelope.get("principal")
            if isinstance(envelope_principal, dict):
                envelope_principal_id = str(envelope_principal.get("principal_id") or "").strip()
                token_principal_id = str(principal.get("principal_id") or "").strip()
                if envelope_principal_id and token_principal_id and envelope_principal_id != token_principal_id:
                    _integration_log_event(
                        self.server,
                        level="info",
                        operation=operation,
                        request_id=request_id,
                        status="conflict_logged",
                        latency_ms=0.0,
                        error_code="PRINCIPAL_METADATA_CONFLICT",
                        principal=principal,
                        session_id=session_id,
                        run_id=run_id,
                        proposal_id="",
                        retry_count=0,
                        degrade_mode=False,
                        payload={"envelope_principal_id": envelope_principal_id},
                    )

            if operation == "context.build":
                message = str(request_payload.get("message") or "").strip()
                message_window_raw = request_payload.get("message_window")
                window_snapshot = ""
                if message_window_raw is not None:
                    if not isinstance(message_window_raw, dict):
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="data.message_window must be an object",
                            retryable=False,
                            operator_action="provide_message_window_object",
                        )
                    max_messages_raw = message_window_raw.get("max_messages", 24)
                    max_chars_raw = message_window_raw.get("max_chars", 20000)
                    try:
                        max_messages = int(max_messages_raw)
                    except Exception as exc:
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="message_window.max_messages must be an integer",
                            retryable=False,
                            operator_action="set_message_window_max_messages_in_range",
                        ) from exc
                    try:
                        max_chars = int(max_chars_raw)
                    except Exception as exc:
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="message_window.max_chars must be an integer",
                            retryable=False,
                            operator_action="set_message_window_max_chars_in_range",
                        ) from exc
                    if max_messages < 1 or max_messages > 200:
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="message_window.max_messages must be in range 1..200",
                            retryable=False,
                            operator_action="set_message_window_max_messages_in_range",
                        )
                    if max_chars < 1024 or max_chars > 200000:
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="message_window.max_chars must be in range 1024..200000",
                            retryable=False,
                            operator_action="set_message_window_max_chars_in_range",
                        )
                    history_rows = []
                    try:
                        history_rows = self.server.runtime.get_session_history(session_id)
                    except Exception:
                        history_rows = []
                    snippets: list[str] = []
                    for trace in list(history_rows)[-max_messages:]:
                        user_text = str(getattr(trace, "user_text", "") or "").strip()
                        response_text = str(getattr(trace, "response_text", "") or "").strip()
                        if user_text:
                            snippets.append(f"user: {user_text}")
                        if response_text:
                            snippets.append(f"assistant: {response_text}")
                    if snippets:
                        collapsed = "\n".join(snippets)
                        if len(collapsed) > max_chars:
                            collapsed = collapsed[-max_chars:]
                        window_snapshot = collapsed
                    if not message:
                        for trace in reversed(history_rows):
                            candidate = str(getattr(trace, "user_text", "") or "").strip()
                            if candidate:
                                message = candidate
                                break
                if not message:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.message is required when message_window cannot derive context",
                        retryable=False,
                        operator_action="provide_context_build_message_or_message_window",
                    )
                retrieval_raw = request_payload.get("retrieval")
                if retrieval_raw is None:
                    retrieval: dict[str, Any] = {}
                elif isinstance(retrieval_raw, dict):
                    retrieval = dict(retrieval_raw)
                else:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.retrieval must be an object when provided",
                        retryable=False,
                        operator_action="provide_retrieval_object",
                    )
                top_k_raw = retrieval.get("top_k", 8)
                try:
                    top_k = int(top_k_raw)
                except Exception as exc:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="retrieval.top_k must be an integer",
                        retryable=False,
                        operator_action="set_retrieval_top_k_in_range",
                    ) from exc
                if top_k < 1 or top_k > INTEGRATION_MAX_EVIDENCE:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message=f"retrieval.top_k must be in range 1..{INTEGRATION_MAX_EVIDENCE}",
                        retryable=False,
                        operator_action="set_retrieval_top_k_in_range",
                    )
                memory_preference = str(request_payload.get("memory_preference") or "").strip() or None
                risk_signal = str(request_payload.get("risk_signal") or "low").strip().lower() or "low"
                if risk_signal not in {"low", "medium", "high"}:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.risk_signal must be low|medium|high",
                        retryable=False,
                        operator_action="set_supported_risk_signal",
                    )
                high_risk = risk_signal == "high"
                retrieval_query = str(request_payload.get("retrieval_query") or "").strip() or None
                retrieval_override = _retrieval_override_from_payload(
                    request_payload,
                    default_invoker="engine.runtime.server.integration_context_build",
                    default_scope="integration_context_build",
                    default_reason="integration_requested_override",
                    default_auth_context="integration_context_build",
                )
                package = self.server.runtime.build_context_package(
                    message,
                    high_risk=high_risk,
                    memory_preference=memory_preference,
                    session_id=session_id or None,
                    package_version="v2",
                    retrieval_query=retrieval_query,
                    retrieval_override=retrieval_override,
                    render_citations=False,
                )
                evidence_rows = []
                for row in list(package.get("ltm_evidence") or []):
                    if not isinstance(row, dict):
                        continue
                    citations = [str(item).strip() for item in list(row.get("citations") or []) if str(item).strip()]
                    evidence_rows.append(
                        {
                            "evidence_id": str(row.get("evidence_id") or ""),
                            "section": str(row.get("section") or ""),
                            "kind": str(row.get("kind") or ""),
                            "summary": str(row.get("summary") or ""),
                            "citations": citations[:INTEGRATION_MAX_EVIDENCE],
                            "confidence": float(row.get("confidence") or 0.0),
                        }
                    )
                    if len(evidence_rows) >= top_k:
                        break
                preview = dict(package.get("preview") or {})
                timings = dict(package.get("timing_ms") or {})
                rolling_summary = str(dict(package.get("working_set") or {}).get("rolling_summary") or "").strip()
                context_segments: list[str] = []
                if window_snapshot:
                    context_segments.append(f"Recent window:\n{window_snapshot}")
                if rolling_summary:
                    context_segments.append(f"Session summary: {rolling_summary}")
                for row in evidence_rows:
                    summary = str(row.get("summary") or "").strip()
                    if summary:
                        context_segments.append(f"- {summary}")
                context_text = "\n".join(context_segments).strip()
                original_size = len(context_text.encode("utf-8"))
                truncated = False
                if len(context_text) > INTEGRATION_MAX_CONTEXT_TEXT:
                    context_text = context_text[:INTEGRATION_MAX_CONTEXT_TEXT]
                    truncated = True
                returned_size = len(context_text.encode("utf-8"))
                confidence_values = [float(row.get("confidence") or 0.0) for row in evidence_rows]
                confidence = sum(confidence_values) / float(len(confidence_values)) if confidence_values else 0.0
                response_data = {
                    "context_text": context_text,
                    "evidence": evidence_rows,
                    "route": str(preview.get("route") or "none"),
                    "confidence": round(max(0.0, min(1.0, confidence)), 4),
                    "timings": timings,
                    "truncation": {
                        "truncated": bool(truncated),
                        "original_size_bytes": int(original_size),
                        "returned_size_bytes": int(returned_size),
                    },
                }
            elif operation == "context.why":
                evidence_ids = request_payload.get("evidence_ids")
                if not isinstance(evidence_ids, list) or not evidence_ids:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.evidence_ids must be a non-empty array",
                        retryable=False,
                        operator_action="provide_evidence_id_array",
                    )
                if len(evidence_ids) > INTEGRATION_MAX_EVIDENCE:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.evidence_ids exceeds max size",
                        retryable=False,
                        operator_action="reduce_evidence_ids_array",
                    )
                expand_citations = _to_bool(request_payload.get("expand_citations"), default=False)
                reasons: list[dict[str, Any]] = []
                evidence_rows: list[dict[str, Any]] = []
                citation_expansion: dict[str, Any] = {}
                for raw_id in evidence_ids:
                    evidence_id = str(raw_id or "").strip()
                    if not evidence_id:
                        continue
                    try:
                        atom = self.server.runtime.retriever.store.get_atom(evidence_id)
                    except Exception:
                        atom = None
                    if atom is None:
                        reasons.append(
                            {
                                "evidence_id": evidence_id,
                                "reason": "evidence id not found in current store",
                            }
                        )
                        continue
                    excerpt = str(getattr(atom, "canonical_text", "") or "").strip()
                    citations = []
                    for ref in list(getattr(atom, "source_refs", []) or []):
                        source_id = str(getattr(ref, "source_id", "") or "").strip()
                        message_id = str(getattr(ref, "message_id", "") or "").strip()
                        if source_id:
                            token = source_id if not message_id else f"{source_id}#{message_id}"
                            if token not in citations:
                                citations.append(token)
                    reasons.append(
                        {
                            "evidence_id": evidence_id,
                            "reason": _compact_text(excerpt, max_chars=220),
                        }
                    )
                    evidence_rows.append(
                        {
                            "evidence_id": evidence_id,
                            "excerpt": _compact_text(excerpt, max_chars=320),
                            "citations": citations[:INTEGRATION_MAX_EVIDENCE],
                            "confidence": float(getattr(atom, "confidence", 0.0)),
                        }
                    )
                    if expand_citations and citations:
                        first = citations[0]
                        try:
                            citation_expansion[evidence_id] = _citation_matches(self.server.runtime, first)
                        except Exception:
                            citation_expansion[evidence_id] = {"citation": first, "matches": []}
                response_data = {
                    "reasons": reasons,
                    "evidence": evidence_rows,
                }
                if expand_citations:
                    response_data["citation_expansion"] = citation_expansion
            elif operation == "writeback.propose":
                idem_key = str(self.headers.get("Idempotency-Key") or "").strip()
                if not idem_key:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="Idempotency-Key header is required",
                        retryable=False,
                        operator_action="set_idempotency_key_header",
                    )
                mutation = request_payload.get("mutation")
                if not isinstance(mutation, dict):
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.mutation must be an object",
                        retryable=False,
                        operator_action="provide_mutation_object",
                    )
                evidence = request_payload.get("evidence")
                if not isinstance(evidence, list) or not evidence:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.evidence must be a non-empty array",
                        retryable=False,
                        operator_action="provide_evidence_array",
                    )
                if len(evidence) > INTEGRATION_MAX_EVIDENCE:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.evidence exceeds max size",
                        retryable=False,
                        operator_action="reduce_evidence_array",
                    )
                target_kind = str(mutation.get("target_kind") or "").strip()
                if not target_kind:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="mutation.target_kind is required",
                        retryable=False,
                        operator_action="provide_mutation_target_kind",
                    )
                tags = mutation.get("tags")
                if tags is not None and not isinstance(tags, list):
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="mutation.tags must be an array when provided",
                        retryable=False,
                        operator_action="provide_mutation_tags_array_or_omit",
                    )
                payload_fp = _integration_payload_fingerprint({"mutation": mutation, "evidence": evidence})
                replayed, replay_error = _integration_idempotency_lookup(
                    self.server,
                    operation=operation,
                    key=idem_key,
                    payload_fingerprint=payload_fp,
                )
                if replay_error is not None:
                    raise replay_error
                if replayed is not None:
                    response_data = dict(replayed.get("data") or {})
                    proposal_id = str(response_data.get("proposal_id") or "")
                else:
                    queue = self.server.review_queue
                    if queue is None:
                        raise IntegrationContractError(
                            code="DEPENDENCY_UNAVAILABLE",
                            message="proposal queue unavailable",
                            retryable=True,
                            operator_action="restore_mutation_queue_and_retry",
                            status=HTTPStatus.SERVICE_UNAVAILABLE,
                        )
                    intent = str(mutation.get("intent") or "").strip().lower()
                    if intent not in {"create", "edit", "delete", "conflict"}:
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="mutation.intent must be create|edit|delete|conflict",
                            retryable=False,
                            operator_action="set_supported_mutation_intent",
                        )
                    if intent in {"create", "edit"} and "body" not in mutation:
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="mutation.body is required for create/edit",
                            retryable=False,
                            operator_action="provide_mutation_body",
                        )
                    for row in evidence:
                        if not isinstance(row, dict):
                            raise IntegrationContractError(
                                code="INVALID_INPUT",
                                message="each evidence item must be an object",
                                retryable=False,
                                operator_action="fix_evidence_item_shape",
                            )
                        required_fields = {"provenance_handle", "source_kind", "source_id", "excerpt", "citation", "confidence"}
                        missing = [field for field in required_fields if field not in row]
                        if missing:
                            raise IntegrationContractError(
                                code="INVALID_INPUT",
                                message=f"evidence item missing fields: {', '.join(missing)}",
                                retryable=False,
                                operator_action="provide_complete_evidence_fields",
                            )
                        citation = row.get("citation")
                        if not isinstance(citation, dict):
                            raise IntegrationContractError(
                                code="INVALID_INPUT",
                                message="evidence.citation must be an object",
                                retryable=False,
                                operator_action="provide_evidence_citation_object",
                            )
                        citation_type = str(citation.get("type") or "").strip()
                        citation_ref = str(citation.get("ref") or "").strip()
                        if not citation_type or not citation_ref:
                            raise IntegrationContractError(
                                code="INVALID_INPUT",
                                message="evidence.citation.type and evidence.citation.ref are required",
                                retryable=False,
                                operator_action="provide_citation_type_and_ref",
                            )
                        try:
                            confidence_value = float(row.get("confidence"))
                        except Exception as exc:
                            raise IntegrationContractError(
                                code="INVALID_INPUT",
                                message="evidence.confidence must be a float in range 0..1",
                                retryable=False,
                                operator_action="set_evidence_confidence_in_range",
                            ) from exc
                        if confidence_value < 0.0 or confidence_value > 1.0:
                            raise IntegrationContractError(
                                code="INVALID_INPUT",
                                message="evidence.confidence must be a float in range 0..1",
                                retryable=False,
                                operator_action="set_evidence_confidence_in_range",
                            )
                    target_id = str(mutation.get("target_id") or "").strip()
                    if intent in {"edit", "delete", "conflict"} and not target_id:
                        raise IntegrationContractError(
                            code="INVALID_INPUT",
                            message="mutation.target_id is required for edit/delete/conflict",
                            retryable=False,
                            operator_action="set_target_id_for_mutation_intent",
                        )
                    if intent == "delete":
                        proposal = queue.propose_delete(
                            target_atom_id=target_id,
                            reason_code=f"integration_{intent}",
                            metadata={
                                "session_id": session_id,
                                "run_id": run_id,
                                "principal_id": str(principal.get("principal_id") or ""),
                            },
                        )
                    else:
                        body_value = mutation.get("body")
                        if isinstance(body_value, str):
                            candidate_text = body_value.strip()
                        elif isinstance(body_value, dict):
                            candidate_text = str(body_value.get("canonical_text") or body_value.get("text") or "").strip()
                        else:
                            candidate_text = ""
                        if intent == "conflict":
                            conflict_reason = str(mutation.get("conflict_reason") or "").strip()
                            if not conflict_reason:
                                raise IntegrationContractError(
                                    code="INVALID_INPUT",
                                    message="mutation.conflict_reason is required for conflict intent",
                                    retryable=False,
                                    operator_action="provide_conflict_reason",
                                )
                            resolution_options = mutation.get("resolution_options")
                            if not isinstance(resolution_options, list) or not resolution_options:
                                raise IntegrationContractError(
                                    code="INVALID_INPUT",
                                    message="mutation.resolution_options is required for conflict intent",
                                    retryable=False,
                                    operator_action="provide_resolution_options",
                                )
                            supported_options = {"keep_existing", "replace", "merge", "defer"}
                            for item in resolution_options:
                                option = str(item or "").strip()
                                if option not in supported_options:
                                    raise IntegrationContractError(
                                        code="INVALID_INPUT",
                                        message="mutation.resolution_options contains unsupported values",
                                        retryable=False,
                                        operator_action="use_supported_resolution_options",
                                    )
                            candidate_text = str(mutation.get("candidate_text") or candidate_text or "").strip()
                        if not candidate_text:
                            raise IntegrationContractError(
                                code="INVALID_INPUT",
                                message="mutation body/candidate_text is required for create/edit/conflict",
                                retryable=False,
                                operator_action="provide_candidate_text",
                            )
                        if not target_id:
                            target_id = f"integration_create_{uuid4().hex[:12]}"
                        source_id = str(dict(evidence[0]).get("source_id") or "integration_source").strip() or "integration_source"
                        source_ref = SourceRef(
                            source_id=source_id,
                            message_id=f"integration_{uuid4().hex[:10]}",
                            timestamp=datetime.now(timezone.utc),
                            span_start=0,
                            span_end=max(1, min(len(candidate_text), 512)),
                        )
                        candidate = CandidateAtom(
                            candidate_id=f"cand_{uuid4().hex[:16]}",
                            atom_type=AtomType.EPISODE,
                            canonical_text=candidate_text,
                            source_refs=[source_ref],
                            entities=[],
                            topics=[],
                            confidence=max(0.0, min(1.0, float(dict(evidence[0]).get("confidence") or 0.5))),
                            salience=0.5,
                        )
                        proposal = queue.propose_edit(
                            target_atom_id=target_id,
                            replacement_candidate=candidate,
                            reason_code=f"integration_{intent}",
                            metadata={
                                "session_id": session_id,
                                "run_id": run_id,
                                "principal_id": str(principal.get("principal_id") or ""),
                                "intent": intent,
                            },
                        )
                    proposal_id = str(getattr(proposal, "proposal_id", "") or "")
                    audit_ref = f"audit_{uuid4().hex[:20]}"
                    response_data = {
                        "proposal_id": proposal_id,
                        "status": "pending_review",
                        "idempotent_replay": False,
                        "audit_ref": audit_ref,
                    }
                    _integration_append_audit(
                        self.server,
                        {
                            "audit_ref": audit_ref,
                            "operation": operation,
                            "request_id": request_id,
                            "session_id": session_id,
                            "run_id": run_id,
                            "proposal_id": proposal_id,
                            "decision": "proposed",
                            "actor": str(principal.get("principal_id") or ""),
                            "timestamp_utc": _utc_iso(),
                            "mutation_intent": intent,
                            "affected_ids": [target_id],
                        },
                    )
                    _integration_idempotency_store(
                        self.server,
                        operation=operation,
                        key=idem_key,
                        payload_fingerprint=payload_fp,
                        response={
                            "data": dict(response_data),
                        },
                    )
            elif operation == "writeback.resolve":
                queue = self.server.review_queue
                if queue is None:
                    raise IntegrationContractError(
                        code="DEPENDENCY_UNAVAILABLE",
                        message="proposal queue unavailable",
                        retryable=True,
                        operator_action="restore_mutation_queue_and_retry",
                        status=HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                proposal_id = str(request_payload.get("proposal_id") or "").strip()
                decision = str(request_payload.get("decision") or "").strip().lower()
                decided_by = str(request_payload.get("decided_by") or "").strip()
                reason = str(request_payload.get("reason") or "").strip() or "resolved_by_operator"
                if not proposal_id:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.proposal_id is required",
                        retryable=False,
                        operator_action="provide_proposal_id",
                    )
                if decision not in {"approve", "reject"}:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.decision must be approve|reject",
                        retryable=False,
                        operator_action="set_valid_resolution_decision",
                    )
                if not decided_by:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="data.decided_by is required",
                        retryable=False,
                        operator_action="provide_resolver_identity",
                    )
                try:
                    current = _proposal_by_id(queue, proposal_id)
                except KeyError as exc:
                    raise IntegrationContractError(
                        code="INVALID_INPUT",
                        message="proposal_id not found",
                        retryable=False,
                        operator_action="use_existing_proposal_id",
                    ) from exc
                raw_status = str(getattr(getattr(current, "status", ""), "value", getattr(current, "status", ""))).strip().lower()
                already_resolved = raw_status in {"approved", "rejected", "applied"}
                if not already_resolved:
                    if decision == "approve":
                        current = queue.approve(proposal_id, reviewer=decided_by)
                    else:
                        current = queue.reject(proposal_id, reviewer=decided_by, reason=reason)
                current_status = str(getattr(getattr(current, "status", ""), "value", getattr(current, "status", ""))).strip().lower()
                final_status = "approved" if current_status in {"approved", "applied"} else "rejected"
                reviewed_at = getattr(current, "reviewed_at", None)
                resolved_at_utc = reviewed_at.isoformat() if hasattr(reviewed_at, "isoformat") else _utc_iso()
                audit_ref = f"audit_{uuid4().hex[:20]}"
                response_data = {
                    "proposal_id": proposal_id,
                    "status": final_status,
                    "already_resolved": bool(already_resolved),
                    "resolved_at_utc": resolved_at_utc,
                    "audit_ref": audit_ref,
                }
                _integration_append_audit(
                    self.server,
                    {
                        "audit_ref": audit_ref,
                        "operation": operation,
                        "request_id": request_id,
                        "session_id": session_id,
                        "run_id": run_id,
                        "proposal_id": proposal_id,
                        "decision": decision,
                        "actor": str(principal.get("principal_id") or decided_by),
                        "timestamp_utc": _utc_iso(),
                        "affected_ids": [str(getattr(current, "target_atom_id", "") or "")],
                    },
                )
            elif operation == "health.get":
                health = _runtime_health(self.server)
                health_status = str(health.get("status") or "").strip().lower()
                mapped = "ok"
                if health_status == "needs_attention":
                    mapped = "down"
                elif health_status == "watch":
                    mapped = "degraded"
                checks = [row for row in list(health.get("checks") or []) if isinstance(row, dict)]
                dependencies = [
                    {
                        "id": str(row.get("id") or ""),
                        "status": str(row.get("status") or ""),
                        "detail": str(row.get("detail") or ""),
                    }
                    for row in checks
                ]
                response_data = {
                    "status": mapped,
                    "uptime_ms": int((time.monotonic() - float(self.server.integration_started_monotonic)) * 1000.0),
                    "dependencies": dependencies,
                }
            elif operation == "capabilities.get":
                operations: list[dict[str, Any]] = []
                for name in ["context.build", "context.why", "writeback.propose", "writeback.resolve", "health.get", "capabilities.get"]:
                    enabled = True
                    if name in {"writeback.propose", "writeback.resolve"} and self.server.review_queue is None:
                        enabled = False
                    operations.append(
                        {
                            "name": name,
                            "enabled": enabled,
                            "requires_auth": True,
                            "required_roles": sorted(INTEGRATION_REQUIRED_ROLES.get(name, {"viewer", "operator", "admin"})),
                            "idempotent": name in {"writeback.propose", "writeback.resolve", "health.get", "capabilities.get"},
                        }
                    )
                response_data = {
                    "contract_version": "1.0.0",
                    "supported_schema_versions": [INTEGRATION_SCHEMA_VERSION],
                    "transports": ["http", "mcp"],
                    "mcp_runtime_transports": ["stdio", "streamable_http"],
                    "operations": operations,
                    "feature_flags": {
                        "degrade_detection": True,
                        "idempotency_key_required_for_writeback_propose": True,
                        "jwt_auth_enabled": bool(self.server.integration_auth._jwt_secret),
                        "opaque_token_auth_enabled": True,
                        "secret_manager_auth_enabled": bool(self.server.integration_auth.secret_manager_enabled),
                        "scoped_operation_tokens_enabled": True,
                    },
                    "limits": {
                        "max_generic_string_chars": INTEGRATION_MAX_GENERIC_STRING,
                        "max_context_text_chars": INTEGRATION_MAX_CONTEXT_TEXT,
                        "max_array_items": INTEGRATION_MAX_ARRAY_ITEMS,
                        "max_evidence_items": INTEGRATION_MAX_EVIDENCE,
                        "max_warning_items": INTEGRATION_MAX_WARNINGS,
                        "max_nesting_depth": INTEGRATION_MAX_NESTING_DEPTH,
                        "idempotency_window_seconds": INTEGRATION_IDEMPOTENCY_WINDOW_S,
                    },
                    "deprecations": [],
                }
            else:
                raise IntegrationContractError(
                    code="INVALID_INPUT",
                    message="unsupported integration operation",
                    retryable=False,
                    operator_action="use_supported_operation",
                )

            latency_ms = (time.perf_counter() - started) * 1000.0
            timeout_budget_ms = INTEGRATION_OPERATION_TIMEOUT_MS.get(operation)
            if timeout_budget_ms is not None and latency_ms > float(timeout_budget_ms):
                raise IntegrationContractError(
                    code="TIMEOUT",
                    message=f"{operation} exceeded timeout budget",
                    retryable=True,
                    operator_action="retry_with_backoff",
                    status=HTTPStatus.GATEWAY_TIMEOUT,
                )
            dependency_ok = _integration_dependency_healthy(self.server)
            degrade_mode, warnings = self.server.integration_degrade_tracker.evaluate(
                operation=operation,
                latency_ms=latency_ms,
                dependency_healthy=dependency_ok,
                error_code="",
            )
            response_payload = _integration_make_envelope(
                request_id=request_id,
                request_id_source=request_id_source,
                operation=operation,
                ok=True,
                degrade_mode=degrade_mode,
                warnings=warnings,
                data=response_data,
            )
            _integration_log_event(
                self.server,
                level="info",
                operation=operation,
                request_id=request_id,
                status="ok",
                latency_ms=latency_ms,
                error_code="",
                principal=principal,
                session_id=session_id,
                run_id=run_id,
                proposal_id=proposal_id,
                retry_count=0,
                degrade_mode=degrade_mode,
                payload=request_payload,
            )
            _json_response(self, response_status, response_payload)
            return True
        except IntegrationContractError as exc:
            error_code = str(exc.code)
            latency_ms = (time.perf_counter() - started) * 1000.0
            dependency_ok = _integration_dependency_healthy(self.server)
            degrade_mode, warnings = self.server.integration_degrade_tracker.evaluate(
                operation=operation,
                latency_ms=latency_ms,
                dependency_healthy=dependency_ok,
                error_code=error_code,
            )
            _integration_log_event(
                self.server,
                level="error",
                operation=operation,
                request_id=request_id,
                status="error",
                latency_ms=latency_ms,
                error_code=error_code,
                principal=principal,
                session_id=session_id,
                run_id=run_id,
                proposal_id=proposal_id,
                retry_count=0,
                degrade_mode=degrade_mode,
                payload=request_payload,
            )
            self._integration_send_error(
                request_id=request_id,
                request_id_source=request_id_source,
                operation=operation,
                error=exc,
                status=exc.status,
                warnings=warnings,
                degrade_mode=degrade_mode,
            )
            return True
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            dependency_ok = _integration_dependency_healthy(self.server)
            degrade_mode, warnings = self.server.integration_degrade_tracker.evaluate(
                operation=operation,
                latency_ms=latency_ms,
                dependency_healthy=dependency_ok,
                error_code="INTERNAL_ERROR",
            )
            _integration_log_event(
                self.server,
                level="error",
                operation=operation,
                request_id=request_id,
                status="error",
                latency_ms=latency_ms,
                error_code="INTERNAL_ERROR",
                principal=principal,
                session_id=session_id,
                run_id=run_id,
                proposal_id=proposal_id,
                retry_count=0,
                degrade_mode=degrade_mode,
                payload={"exception": str(exc), "request_payload": request_payload},
            )
            self._integration_send_error(
                request_id=request_id,
                request_id_source=request_id_source,
                operation=operation,
                error=IntegrationContractError(
                    code="INTERNAL_ERROR",
                    message="internal integration error",
                    retryable=False,
                    operator_action="inspect_runtime_logs_and_retry",
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                ),
                warnings=warnings,
                degrade_mode=degrade_mode,
            )
            return True

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if self._integration_handle_request(method="GET", parsed=parsed):
            return
        if path in {"/", "/index.html"}:
            return self._serve_file("index.html", "text/html; charset=utf-8")
        if path == "/assets/styles.css":
            return self._serve_file("styles.css", "text/css; charset=utf-8")
        if path == "/assets/app.js":
            return self._serve_file("app.js", "application/javascript; charset=utf-8")
        if path == "/api/wizard/state":
            q = parse_qs(parsed.query)
            requested_run_id = str((q.get("run_id") or [""])[0]).strip()
            latest_run_id = _latest_wizard_run_id()
            state: dict[str, Any] | None = None
            current_run_id = ""
            if requested_run_id:
                try:
                    state = _load_wizard_state(requested_run_id)
                    current_run_id = requested_run_id
                except FileNotFoundError:
                    state = None
            elif latest_run_id:
                state = _load_wizard_state(latest_run_id)
                current_run_id = latest_run_id
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "has_state": state is not None,
                    "latest_run_id": latest_run_id or "",
                    "current_run_id": current_run_id,
                    "resume_available": bool(latest_run_id),
                    "stages": list(WIZARD_STAGE_SEQUENCE),
                    "policy_presets": BUILD_POLICY_PRESETS,
                    "state": state or {},
                },
            )
        if path == "/api/wizard/organizer/state":
            q = parse_qs(parsed.query)
            requested_run_id = str((q.get("run_id") or [""])[0]).strip()
            resolved_run_id = requested_run_id or (_latest_wizard_run_id() or "")
            if not resolved_run_id:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "wizard run not found"})
            try:
                state = _load_wizard_state(resolved_run_id)
            except FileNotFoundError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "wizard run not found"})
            organizer = _wizard_organizer_state(state)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "run_id": state.get("run_id"),
                    "organizer": organizer,
                },
            )
        if path == "/api/wizard/input/options":
            from tools.mcp_connector_common import discover_memory_candidates, format_memory_candidate_label

            q = parse_qs(parsed.query)
            run_id = str((q.get("run_id") or [""])[0]).strip() or None
            state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
            candidates = discover_memory_candidates(repo_root=REPO_ROOT)
            labels = [format_memory_candidate_label(row) for row in candidates]
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "run_id": state.get("run_id"),
                    "selected_input": dict(state.get("selected_input") or {}),
                    "store_validation": dict(state.get("store_validation") or {}),
                    "memory_candidates": candidates,
                    "memory_candidate_labels": labels,
                },
            )
        if path == "/api/wizard/review/cards":
            q = parse_qs(parsed.query)
            run_id = str((q.get("run_id") or [""])[0]).strip() or None
            status_filter = str((q.get("status") or ["all"])[0]).strip().lower()
            search = str((q.get("q") or [""])[0]).strip().lower()
            try:
                wizard_state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
            except FileNotFoundError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "wizard run not found"})
            draft_path_raw = str((wizard_state.get("build_info") or {}).get("draft_path") or wizard_state.get("last_built_episode_draft_path") or "").strip()
            source_path = Path(draft_path_raw).expanduser().resolve() if draft_path_raw else None
            if source_path is None:
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "cards": [], "total": 0, "source_cards_path": "", "run_id": wizard_state.get("run_id")},
                )
            if not source_path.exists():
                _wizard_reset_downstream_state(wizard_state, from_stage="build_episodes")
                _wizard_reset_to_stage(
                    wizard_state,
                    stage="build_episodes",
                    note="Draft cards moved or deleted; build again or remap the artifact path.",
                )
                _save_wizard_state(wizard_state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "cards": [], "total": 0, "source_cards_path": str(source_path), "run_id": wizard_state.get("run_id")},
                )
            try:
                payload = _load_episode_cards_payload(source_path)
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"failed to load source cards: {exc}"})
            decisions = wizard_state.get("review_decisions")
            if not isinstance(decisions, dict):
                decisions = {}
            cards: list[dict[str, Any]] = []
            for row in list(payload.get("cards") or []):
                if not isinstance(row, dict):
                    continue
                card = _normalize_episode_card(row)
                episode_id = str(card.get("episode_id") or "").strip()
                if not episode_id:
                    continue
                decision_payload = decisions.get(episode_id) if isinstance(decisions, dict) else None
                decision = "pending"
                if isinstance(decision_payload, dict):
                    decision = str(decision_payload.get("decision") or "pending").strip().lower() or "pending"
                card["review_decision"] = decision
                card["review_payload"] = decision_payload if isinstance(decision_payload, dict) else {}
                if status_filter != "all" and decision != status_filter:
                    continue
                if search:
                    hay = " ".join(
                        [
                            str(card.get("episode_id") or ""),
                            str(card.get("title") or ""),
                            str(card.get("summary") or ""),
                            " ".join(str(item) for item in list(card.get("actors") or [])),
                            " ".join(str(item) for item in list(card.get("topic_tags") or [])),
                        ]
                    ).lower()
                    if search not in hay:
                        continue
                cards.append(card)
            _wizard_sync_review_state(wizard_state, source_payload=payload, source_cards_path=source_path)
            _save_wizard_state(wizard_state)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "run_id": wizard_state.get("run_id"),
                    "source_cards_path": str(source_path),
                    "cards": cards,
                    "total": len(cards),
                },
            )
        if path == "/api/wizard/builder/profile":
            q = parse_qs(parsed.query)
            run_id = str((q.get("run_id") or [""])[0]).strip()
            profile_id = str((q.get("profile_id") or [""])[0]).strip()
            if not profile_id and run_id:
                try:
                    wizard_state = _load_wizard_state(run_id)
                    profile_id = str(wizard_state.get("builder_profile_id") or "").strip()
                except Exception:
                    profile_id = ""
            if not profile_id:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "builder profile not selected"})
            profile_path = (BUILDER_PROFILES_ROOT / f"{profile_id}.json").resolve()
            if not profile_path.exists():
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "builder profile not found"})
            try:
                profile = _load_json_file(profile_path)
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"profile load failed: {exc}"})
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "profile_id": profile_id,
                    "profile_path": str(profile_path),
                    "profile": profile,
                },
            )
        if path == "/api/wizard/artifacts":
            q = parse_qs(parsed.query)
            run_id = str((q.get("run_id") or [""])[0]).strip() or None
            try:
                wizard_state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
            except FileNotFoundError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "wizard run not found"})
            run_folder = _wizard_state_path(str(wizard_state.get("run_id") or "")).parent.resolve()
            artifacts = dict(wizard_state.get("artifacts") or {})
            artifacts.update(
                {
                    "run_folder": str(run_folder),
                    "wizard_state_json": str(_wizard_state_path(str(wizard_state.get("run_id") or "")).resolve()),
                    "store_path": str(wizard_state.get("store_path") or ""),
                    "last_built_episode_draft_path": str(wizard_state.get("last_built_episode_draft_path") or ""),
                    "last_built_episode_rejects_path": str(wizard_state.get("last_built_episode_rejects_path") or ""),
                    "last_built_episode_readout_path": str(wizard_state.get("last_built_episode_readout_path") or ""),
                    "last_compiled_reviewed_path": str(wizard_state.get("last_compiled_reviewed_path") or ""),
                }
            )
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "run_id": wizard_state.get("run_id"),
                    "artifacts": artifacts,
                    "open_output_folder_hint": str(run_folder),
                },
            )
        if path == "/api/runtime/health":
            payload = _runtime_health(self.server)
            return _json_response(self, HTTPStatus.OK, {"ok": True, **payload})
        if path == "/api/runtime/writeback/policy":
            return _json_response(self, HTTPStatus.OK, {"ok": True, "policy": dict(self.server.writeback_policy)})
        if path == "/api/runtime/provider/config":
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "provider_config": _provider_model_config(self.server),
                },
            )
        if path == "/api/runtime/packaging/instructions":
            guide_exists = PACKAGING_GUIDE_PATH.exists()
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "windows_entrypoints": [
                        "setup_local.bat",
                        "tools\\run_live_runtime.ps1",
                        "tools\\run_full_export_pilot.ps1",
                    ],
                    "one_click_command": "python3 tools/setup_local.py && python3 tools/run_live_runtime.py",
                    "single_exe": {
                        "supported": True,
                        "build_command": "python3 tools/build_windows_single_exe.py --onefile",
                        "windows_entrypoints": [
                            "tools\\build_windows_single_exe.bat",
                            "tools\\build_windows_single_exe.ps1",
                        ],
                        "packaging_root": str(PACKAGING_ROOT),
                        "artifact_hint": "runtime\\packaging\\windows_<stamp>\\dist\\NumquamOblitaRuntime.exe",
                        "script_available": {
                            "python": WINDOWS_PACKAGING_SCRIPT_PY.exists(),
                            "powershell": WINDOWS_PACKAGING_SCRIPT_PS1.exists(),
                            "batch": WINDOWS_PACKAGING_SCRIPT_BAT.exists(),
                        },
                    },
                    "guide_path": str(PACKAGING_GUIDE_PATH),
                    "guide_available": guide_exists,
                },
            )
        if path.startswith("/api/archive/citation/"):
            citation = unquote(path[len("/api/archive/citation/") :]).strip("/")
            if not citation:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "citation token is required"})
            q = parse_qs(parsed.query)
            context_window = _as_int(
                (q.get("context_window") or [None])[0],
                default=3,
                min_value=0,
                max_value=5,
            )
            try:
                payload = _citation_matches(self.server.runtime, citation, context_window=context_window)
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"citation lookup failed: {exc}"})
            return _json_response(self, HTTPStatus.OK, {"ok": True, **payload})
        if path == "/api/state":
            stats = self.server.runtime.stats()
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "stats": {
                        "turns": stats.turns,
                        "total_input_tokens": stats.total_input_tokens,
                        "total_output_tokens": stats.total_output_tokens,
                        "total_cost_usd": stats.total_cost_usd,
                        "p95_latency_ms": stats.p95_latency_ms,
                        "stm_primary_turns": stats.stm_primary_turns,
                        "hybrid_turns": stats.hybrid_turns,
                        "ltm_only_turns": stats.ltm_only_turns,
                        "route_none_turns": stats.route_none_turns,
                        "route_stm_only_turns": stats.route_stm_only_turns,
                        "route_ltm_light_turns": stats.route_ltm_light_turns,
                        "route_ltm_deep_turns": stats.route_ltm_deep_turns,
                        "recognition_events": stats.recognition_events,
                        "recognition_rate": stats.recognition_rate,
                    },
                    "model_name": self.server.runtime.model_name,
                },
            )
        if path == "/api/runtime/decision-reasons":
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "routes": {
                        "none": "No memory retrieval.",
                        "stm_only": "Short-term memory only.",
                        "ltm_light": "Light long-term retrieval probe.",
                        "ltm_deep": "Deep long-term retrieval.",
                    },
                    "memory_preferences": {
                        "auto": "Balanced mode (recommended).",
                        "chat_first": "Prefer normal chat and minimize memory retrieval.",
                        "memory_assist": "Prefer stronger memory assistance when relevant.",
                    },
                    "reasons": dict(ROUTE_REASON_DESCRIPTIONS),
                },
            )
        if path == "/api/runtime/telemetry/summary":
            q = parse_qs(parsed.query)
            limit = _as_int((q.get("limit") or ["200"])[0], default=200, min_value=1, max_value=5000)
            summary = self.server.runtime.get_runtime_telemetry_summary(limit=limit)
            return _json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "limit": limit, "summary": summary},
            )
        if path == "/api/runtime/telemetry/turns":
            q = parse_qs(parsed.query)
            limit = _as_int((q.get("limit") or ["40"])[0], default=40, min_value=1, max_value=200)
            turns = self.server.runtime.get_runtime_telemetry_turns(limit=limit)
            warn_turns = sum(1 for row in turns if str(row.get("warning_state") or "ok") == "warn")
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "limit": limit,
                    "turns": turns,
                    "warn_turns": warn_turns,
                },
            )
        if path == "/api/adapters":
            return _json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "adapters": self.server.adapter_registry.names()},
            )
        if path == "/api/chat/sessions":
            sessions = self.server.runtime.list_sessions()
            return _json_response(self, HTTPStatus.OK, {"ok": True, "sessions": sessions})
        if path.startswith("/api/chat/session/") and path.endswith("/history"):
            session_id = unquote(path[len("/api/chat/session/") : -len("/history")]).strip("/")
            if not session_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "session_id is required"})
            try:
                history = [
                    self.server.runtime.trace_to_dict(turn)
                    for turn in self.server.runtime.get_session_history(session_id)
                ]
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
            return _json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "session_id": session_id, "history": history},
            )
        if path.startswith("/api/chat/session/") and path.endswith("/telemetry"):
            session_id = unquote(path[len("/api/chat/session/") : -len("/telemetry")]).strip("/")
            if not session_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "session_id is required"})
            try:
                telemetry = self.server.runtime.get_session_telemetry(session_id)
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
            return _json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "session_id": session_id, "telemetry": telemetry},
            )
        if path == "/api/explore/preferences":
            preferences = _read_exploration_preferences(self.server)
            rows: list[dict[str, Any]] = []
            for key, row in preferences.items():
                if not isinstance(row, dict):
                    continue
                rows.append(
                    {
                        "key": str(key),
                        "anchor_id": str(row.get("anchor_id") or ""),
                        "anchor_type": str(row.get("anchor_type") or "topic"),
                        "action": str(row.get("action") or ""),
                        "weight": float(row.get("weight") or 0.0),
                        "updated_at": str(row.get("updated_at") or ""),
                    }
                )
            rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "preferences": rows,
                    "count": len(rows),
                },
            )
        if path == "/api/explore/start-here":
            q = parse_qs(parsed.query)
            limit = _as_int((q.get("limit") or ["12"])[0], default=12, min_value=1, max_value=40)
            preferences = _read_exploration_preferences(self.server)
            snapshot = _build_exploration_snapshot(
                self.server.runtime,
                limit=limit,
                preferences=preferences,
            )
            total_anchors = int(snapshot.get("total_anchors") or 0)
            status = "ready" if total_anchors > 0 else "insufficient_support"
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "status": status,
                    "generated_at": _utc_iso(),
                    "buckets": dict(snapshot.get("buckets") or {}),
                    "stats": {
                        "atom_count": int(snapshot.get("atom_count") or 0),
                        "total_anchors": total_anchors,
                        "truncated": bool(snapshot.get("truncated")),
                    },
                    "guardrails": {
                        "bounded": True,
                        "max_bucket_items": 40,
                        "fail_closed": True,
                    },
                },
            )
        if path == "/api/explore/expand":
            q = parse_qs(parsed.query)
            anchor_id = str((q.get("anchor_id") or [""])[0]).strip()
            if not anchor_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "anchor_id is required"})
            anchor_type = str((q.get("anchor_type") or ["topic"])[0]).strip().lower() or "topic"
            if anchor_type not in EXPLORATION_ALLOWED_TYPES:
                anchor_type = "topic"
            limit = _as_int((q.get("limit") or ["10"])[0], default=10, min_value=1, max_value=30)
            hop_depth = _as_int((q.get("hop_depth") or ["1"])[0], default=1, min_value=1, max_value=3)
            match_limit = min(120, max(10, limit * max(1, hop_depth) * 2))
            matched_atoms = _match_anchor_atoms(
                self.server.runtime,
                anchor_id=anchor_id,
                anchor_type=anchor_type,
                limit=match_limit,
            )
            if not matched_atoms:
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "status": "insufficient_support",
                        "anchor": {
                            "anchor_id": _normalize_anchor_id(anchor_id),
                            "label": anchor_id,
                            "anchor_type": anchor_type,
                        },
                        "connected_atoms": [],
                        "next_hops": [],
                        "guardrails": {
                            "bounded": True,
                            "max_hop_depth": 3,
                            "fail_closed": True,
                        },
                    },
                )
            connected_atoms: list[dict[str, Any]] = []
            for atom in matched_atoms[:limit]:
                card = _serialize_card(atom)
                citations = [str(item).strip() for item in list(card.get("citations") or []) if str(item).strip()]
                connected_atoms.append(
                    {
                        "atom_id": str(getattr(atom, "atom_id", "")).strip(),
                        "card_id": str(card.get("card_id") or ""),
                        "summary": _compact_text(str(card.get("summary_abstractive") or card.get("summary") or ""), max_chars=220),
                        "confidence": float(card.get("confidence") or 0.0),
                        "contradiction": bool(card.get("contradiction")),
                        "source_ref": citations[0] if citations else "",
                    }
                )
            next_hops = _build_exploration_next_hops(
                self.server.runtime,
                matched_atoms=matched_atoms[: max(8, limit)],
                limit=limit,
                preferences=_read_exploration_preferences(self.server),
            )
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "status": "ready",
                    "anchor": {
                        "anchor_id": _normalize_anchor_id(anchor_id),
                        "label": anchor_id,
                        "anchor_type": anchor_type,
                        "matched_atom_count": len(matched_atoms),
                    },
                    "connected_atoms": connected_atoms,
                    "next_hops": next_hops,
                    "truncated": len(matched_atoms) > len(connected_atoms),
                    "guardrails": {
                        "bounded": True,
                        "max_hop_depth": 3,
                        "fail_closed": True,
                    },
                },
            )
        if path == "/api/explore/peek":
            q = parse_qs(parsed.query)
            anchor_id = str((q.get("anchor_id") or [""])[0]).strip()
            if not anchor_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "anchor_id is required"})
            anchor_type = str((q.get("anchor_type") or ["topic"])[0]).strip().lower() or "topic"
            if anchor_type not in EXPLORATION_ALLOWED_TYPES:
                anchor_type = "topic"
            limit = _as_int((q.get("limit") or ["5"])[0], default=5, min_value=1, max_value=12)
            matched_atoms = _match_anchor_atoms(
                self.server.runtime,
                anchor_id=anchor_id,
                anchor_type=anchor_type,
                limit=max(12, limit * 3),
            )
            snippets = _build_exploration_peek_snippets(matched_atoms, limit=limit)
            status = "ready" if snippets else "insufficient_support"
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "status": status,
                    "anchor": {
                        "anchor_id": _normalize_anchor_id(anchor_id),
                        "label": anchor_id,
                        "anchor_type": anchor_type,
                    },
                    "mode": "lightweight",
                    "snippets": snippets,
                    "count": len(snippets),
                    "truncated": len(matched_atoms) > len(snippets),
                    "guardrails": {
                        "bounded": True,
                        "max_snippets": 12,
                        "fail_closed": True,
                    },
                },
            )
        if path == "/api/memory/quicknote/status":
            q = parse_qs(parsed.query)
            with self.server.quicknote_lock:
                state = getattr(self.server, "quicknote_state", None)
                if not isinstance(state, dict):
                    state = _quicknote_default_state()
                    self.server.quicknote_state = state
                config = dict(getattr(self.server, "quicknote_config", {}) or {})
                policy = dict(getattr(self.server, "quicknote_policy", {}) or {})
                session_cap = max(1, int(config.get("session_cap") or 24))
                inactivity_timeout = max(60, int(config.get("inactivity_timeout_seconds") or 3600))
                auto_apply = bool(policy.get("auto_apply"))
                timeout_flushes = _quicknote_maybe_flush_inactive(
                    state,
                    inactivity_timeout_seconds=inactivity_timeout,
                    auto_apply=auto_apply,
                    session_cap=session_cap,
                )
                assistant_id, session_id = _quicknote_resolve_scope(
                    state,
                    assistant_hint=(q.get("assistant_id") or [""])[0],
                    session_hint=(q.get("session_id") or [""])[0],
                )
                status_payload = _quicknote_status_for_scope(
                    state,
                    assistant_id=assistant_id,
                    session_id=session_id,
                    session_cap=session_cap,
                )
                _quicknote_persist_state(self.server)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "status": status_payload,
                    "policy": {
                        "mode": str(policy.get("mode") or "proposal_only"),
                        "auto_apply": bool(policy.get("auto_apply")),
                    },
                    "config": {
                        "session_cap": session_cap,
                        "inactivity_timeout_seconds": inactivity_timeout,
                    },
                },
            )
        if path == "/api/explore/whats-new":
            q = parse_qs(parsed.query)
            peek_only = _to_bool((q.get("peek_only") or [None])[0], default=False)
            limit = _as_int((q.get("limit") or [None])[0], default=8, min_value=1, max_value=40)
            with self.server.quicknote_lock:
                state = getattr(self.server, "quicknote_state", None)
                if not isinstance(state, dict):
                    state = _quicknote_default_state()
                    self.server.quicknote_state = state
                config = dict(getattr(self.server, "quicknote_config", {}) or {})
                policy = dict(getattr(self.server, "quicknote_policy", {}) or {})
                session_cap = max(1, int(config.get("session_cap") or 24))
                inactivity_timeout = max(60, int(config.get("inactivity_timeout_seconds") or 3600))
                auto_apply = bool(policy.get("auto_apply"))
                timeout_flushes = _quicknote_maybe_flush_inactive(
                    state,
                    inactivity_timeout_seconds=inactivity_timeout,
                    auto_apply=auto_apply,
                    session_cap=session_cap,
                )
                assistant_id, _session_id = _quicknote_resolve_scope(
                    state,
                    assistant_hint=(q.get("assistant_id") or [""])[0],
                    session_hint=(q.get("session_id") or [""])[0],
                )
                payload, advanced = _quicknote_whats_new_payload(
                    state,
                    assistant_id=assistant_id,
                    runtime=self.server.runtime,
                    peek_only=peek_only,
                    limit=limit,
                )
                if advanced or timeout_flushes:
                    _quicknote_persist_state(self.server)
            if timeout_flushes:
                payload["inactivity_flushes"] = timeout_flushes
            return _json_response(self, HTTPStatus.OK, payload)
        if path == "/api/system/usage-guide":
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "guide": _quicknote_usage_guide_payload(),
                },
            )
        if path == "/api/methodology/records":
            q = parse_qs(parsed.query)
            status_filter = str((q.get("status") or ["all"])[0]).strip().lower() or "all"
            limit = _as_int((q.get("limit") or ["40"])[0], default=40, min_value=1, max_value=250)
            offset = _as_int((q.get("offset") or ["0"])[0], default=0, min_value=0, max_value=1_000_000)
            with self.server.methodology_lock:
                state = getattr(self.server, "methodology_state", None)
                if not isinstance(state, dict):
                    state = load_methodology_state(Path(self.server.methodology_state_path))
                    self.server.methodology_state = state
                payload = list_methodology_records(
                    state,
                    status=status_filter,
                    limit=limit,
                    offset=offset,
                )
                active_methodology_id = str(state.get("active_methodology_id") or "")
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    **payload,
                    "status_filter": status_filter,
                    "active_methodology_id": active_methodology_id,
                },
            )
        if path.startswith("/api/methodology/records/"):
            methodology_id = unquote(path[len("/api/methodology/records/") :]).strip("/")
            if not methodology_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "methodology_id is required"})
            with self.server.methodology_lock:
                state = getattr(self.server, "methodology_state", None)
                if not isinstance(state, dict):
                    state = load_methodology_state(Path(self.server.methodology_state_path))
                    self.server.methodology_state = state
                target = None
                for row in list(state.get("records") or []):
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("methodology_id") or "") == methodology_id:
                        target = dict(row)
                        break
                active_methodology_id = str(state.get("active_methodology_id") or "")
            if target is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "methodology not found"})
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "record": target,
                    "active_methodology_id": active_methodology_id,
                },
            )
        if path == "/api/methodology/corrections/clusters":
            q = parse_qs(parsed.query)
            limit = _as_int((q.get("limit") or ["20"])[0], default=20, min_value=1, max_value=250)
            with self.server.methodology_lock:
                state = getattr(self.server, "methodology_state", None)
                if not isinstance(state, dict):
                    state = load_methodology_state(Path(self.server.methodology_state_path))
                    self.server.methodology_state = state
                clusters = list_correction_clusters(state, limit=limit)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "clusters": clusters,
                    "count": len(clusters),
                },
            )
        if path == "/api/methodology/maintenance/history":
            q = parse_qs(parsed.query)
            limit = _as_int((q.get("limit") or ["10"])[0], default=10, min_value=1, max_value=250)
            with self.server.methodology_lock:
                state = getattr(self.server, "methodology_state", None)
                if not isinstance(state, dict):
                    state = load_methodology_state(Path(self.server.methodology_state_path))
                    self.server.methodology_state = state
                history = [dict(item) for item in list(state.get("maintenance_history") or []) if isinstance(item, dict)]
            history.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
            history_page = history[:limit]
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "maintenance_history": history_page,
                    "count": len(history_page),
                },
            )
        if path == "/api/methodology/readout":
            with self.server.methodology_lock:
                state = getattr(self.server, "methodology_state", None)
                if not isinstance(state, dict):
                    state = load_methodology_state(Path(self.server.methodology_state_path))
                    self.server.methodology_state = state
                readout = build_operator_readout(state, runtime=self.server.runtime)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "readout": readout,
                },
            )
        if path.startswith("/api/turns/") and path.endswith("/why"):
            turn_id = unquote(path[len("/api/turns/") : -len("/why")]).strip("/")
            if not turn_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "turn_id is required"})
            trace = self.server.runtime.get_turn(turn_id)
            if trace is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "turn not found"})
            q = parse_qs(parsed.query)
            include_citations = _to_bool((q.get("citations") or ["false"])[0], default=False)
            try:
                payload = _build_why_payload(self.server.runtime, trace, include_citations=include_citations)
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"why panel build failed: {exc}"})
            return _json_response(self, HTTPStatus.OK, {"ok": True, "why": payload})
        if path == "/api/turns":
            turns = [self.server.runtime.trace_to_dict(turn) for turn in self.server.runtime.list_turns()]
            return _json_response(self, HTTPStatus.OK, {"ok": True, "turns": turns})
        if path.startswith("/api/turns/"):
            turn_id = path.rsplit("/", 1)[-1]
            trace = self.server.runtime.get_turn(turn_id)
            if trace is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "turn not found"})
            payload = self.server.runtime.trace_to_dict(trace)
            if trace.writeback_event_id:
                writeback = self.server.runtime.get_writeback(trace.writeback_event_id)
                if writeback:
                    payload["writeback"] = {
                        "event_id": writeback.event_id,
                        "status": writeback.status,
                        "created_at": writeback.created_at.isoformat(),
                        "processed_at": writeback.processed_at.isoformat() if writeback.processed_at else None,
                        "error": writeback.error,
                    }
            return _json_response(self, HTTPStatus.OK, {"ok": True, "turn": payload})
        if path == "/api/memory/episodes":
            q = parse_qs(parsed.query)
            run_id = str((q.get("run_id") or [""])[0]).strip()
            search = str((q.get("q") or [""])[0]).strip().lower()
            status_filter = str((q.get("status") or ["all"])[0]).strip().lower()
            try:
                wizard_state = _load_wizard_state(run_id) if run_id else None
            except Exception:
                wizard_state = None
            source_path = _resolve_episode_cards_path(self.server.runtime, wizard_state)
            if source_path is None:
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "episodes": [], "total": 0, "source_cards_path": "", "status_filter": status_filter},
                )
            try:
                payload = _load_episode_cards_payload(source_path)
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"episode cards load failed: {exc}"})
            rows: list[dict[str, Any]] = []
            for raw in list(payload.get("cards") or []):
                if not isinstance(raw, dict):
                    continue
                card = _normalize_episode_card(raw)
                status = str(card.get("promotion_status") or "").strip().lower() or "approved"
                if status_filter != "all" and status != status_filter:
                    continue
                if search:
                    hay = " ".join(
                        [
                            str(card.get("episode_id") or ""),
                            str(card.get("title") or ""),
                            str(card.get("summary") or ""),
                            " ".join(str(item) for item in list(card.get("actors") or [])),
                            " ".join(str(item) for item in list(card.get("topic_tags") or [])),
                            " ".join(str(item) for item in list(card.get("cue_terms") or [])),
                        ]
                    ).lower()
                    if search not in hay:
                        continue
                rows.append(card)
            rows.sort(key=lambda item: str(item.get("episode_id") or ""))
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "source_cards_path": str(source_path),
                    "episodes": rows,
                    "total": len(rows),
                    "status_filter": status_filter,
                },
            )
        if path == "/api/memory/atoms":
            q = parse_qs(parsed.query)
            search = str((q.get("q") or [""])[0]).strip().lower()
            status_filter = str((q.get("status") or ["all"])[0]).strip().lower()
            limit = _as_int((q.get("limit") or ["60"])[0], default=60, min_value=1, max_value=250)
            offset = _as_int((q.get("offset") or ["0"])[0], default=0, min_value=0, max_value=1_000_000)
            allowed_status = {item.value for item in AtomStatus}
            if status_filter != "all" and status_filter not in allowed_status:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "status must be 'all' or a valid atom status"})
            atoms = []
            for atom in self.server.runtime.retriever.store.list_atoms():
                payload = _serialize_atom(atom)
                if status_filter != "all" and payload["status"] != status_filter:
                    continue
                if search:
                    hay = " ".join(
                        [
                            payload["canonical_text"],
                            " ".join(payload["entities"]),
                            " ".join(payload["topics"]),
                        ]
                    ).lower()
                    if search not in hay:
                        continue
                atoms.append(payload)
            atoms.sort(key=lambda item: (item.get("updated_at") or "", item.get("atom_id") or ""), reverse=True)
            page = atoms[offset : offset + limit]
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "atoms": page,
                    "offset": offset,
                    "limit": limit,
                    "total": len(atoms),
                    "has_more": offset + len(page) < len(atoms),
                },
            )
        if path == "/api/memory/cards":
            q = parse_qs(parsed.query)
            search = str((q.get("q") or [""])[0]).strip().lower()
            status_filter = str((q.get("status") or ["all"])[0]).strip().lower()
            kind_filter = str((q.get("kind") or ["all"])[0]).strip().lower()
            contradiction_filter = str((q.get("contradiction") or ["all"])[0]).strip().lower()
            limit = _as_int((q.get("limit") or ["60"])[0], default=60, min_value=1, max_value=250)
            offset = _as_int((q.get("offset") or ["0"])[0], default=0, min_value=0, max_value=1_000_000)
            allowed_status = {item.value for item in AtomStatus}
            allowed_kind = {"fact_card", "event_card", "relationship_card"}
            if status_filter != "all" and status_filter not in allowed_status:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "status must be 'all' or a valid atom status"})
            if kind_filter != "all" and kind_filter not in allowed_kind:
                return _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": "kind must be one of: all, fact_card, event_card, relationship_card"},
                )
            if contradiction_filter not in {"all", "true", "false"}:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "contradiction must be one of: all, true, false"})
            cards = []
            for atom in self.server.runtime.retriever.store.list_atoms():
                card = _serialize_card(atom)
                if status_filter != "all" and card["atom_status"] != status_filter:
                    continue
                if kind_filter != "all" and card["kind"] != kind_filter:
                    continue
                if contradiction_filter != "all":
                    expected = contradiction_filter == "true"
                    if bool(card["contradiction"]) != expected:
                        continue
                if search:
                    hay = " ".join(
                        [
                            str(card["summary"]),
                            " ".join(str(item) for item in list(card["citations"])),
                            " ".join(str(item) for item in list(getattr(atom, "entities", []) or [])),
                            " ".join(str(item) for item in list(getattr(atom, "topics", []) or [])),
                        ]
                    ).lower()
                    if search not in hay:
                        continue
                cards.append(card)
            cards.sort(key=lambda item: (item.get("updated_at") or "", item.get("card_id") or ""), reverse=True)
            page = cards[offset : offset + limit]
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "cards": page,
                    "offset": offset,
                    "limit": limit,
                    "total": len(cards),
                    "has_more": offset + len(page) < len(cards),
                },
            )
        if path.startswith("/api/memory/cards/"):
            card_id = unquote(path[len("/api/memory/cards/") :]).strip("/")
            atom_id = _atom_id_from_card_id(card_id)
            if not atom_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "card_id is required"})
            try:
                atom = self.server.runtime.retriever.store.get_atom(atom_id)
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "card not found"})
            except Exception:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "card lookup failed"})
            ledger = self.server.runtime.retriever.store.ledger
            events = [_serialize_event(item) for item in ledger.events_for_atom(atom_id)]
            conflicts = sorted(self.server.runtime.retriever.store.conflict_neighbors(atom_id))
            _revision, snapshot = self.server.runtime.continuity_store.snapshot_view()
            constellation_ids, arc_ids, shared = _iter_snapshot_neighbors(snapshot, atom_id)
            card = _serialize_card(atom)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "card": card,
                    "atom": _serialize_atom(atom),
                    "provenance_events": events,
                    "graph": {
                        "conflicts": conflicts,
                        "constellation_neighbors": sorted(constellation_ids),
                        "arc_neighbors": sorted(arc_ids),
                        "shared_language_keys": shared,
                    },
                },
            )
        if path.startswith("/api/memory/atom/"):
            atom_id = unquote(path[len("/api/memory/atom/") :]).strip("/")
            if not atom_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "atom_id is required"})
            try:
                atom = self.server.runtime.retriever.store.get_atom(atom_id)
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "atom not found"})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"atom lookup failed: {exc}"})
            ledger = self.server.runtime.retriever.store.ledger
            events = [_serialize_event(item) for item in ledger.events_for_atom(atom_id)]
            conflicts = sorted(self.server.runtime.retriever.store.conflict_neighbors(atom_id))
            _revision, snapshot = self.server.runtime.continuity_store.snapshot_view()
            constellation_ids, arc_ids, shared = _iter_snapshot_neighbors(snapshot, atom_id)
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "atom": _serialize_atom(atom),
                    "provenance_events": events,
                    "graph": {
                        "conflicts": conflicts,
                        "constellation_neighbors": sorted(constellation_ids),
                        "arc_neighbors": sorted(arc_ids),
                        "shared_language_keys": shared,
                    },
                },
            )
        if path == "/api/memory/proposals":
            queue = self.server.review_queue
            if queue is None:
                return _json_response(self, HTTPStatus.OK, {"ok": True, "proposals": [], "status": "queue_unavailable"})
            q = parse_qs(parsed.query)
            status_filter = str((q.get("status") or ["all"])[0]).strip().lower()
            valid = {item.value for item in ProposalStatus}
            if status_filter != "all" and status_filter not in valid:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid proposal status"})
            proposals = []
            for item in queue.list_all():
                payload = _serialize_proposal(item)
                if status_filter != "all" and payload["status"] != status_filter:
                    continue
                proposals.append(payload)
            proposals.sort(key=lambda item: item.get("created_at") or "", reverse=True)
            return _json_response(self, HTTPStatus.OK, {"ok": True, "proposals": proposals})
        if path == "/api/memory/graph/neighbors":
            q = parse_qs(parsed.query)
            atom_id = str((q.get("atom_id") or [""])[0]).strip()
            if not atom_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "atom_id is required"})
            try:
                depth = _parse_bounded_query_int(
                    (q.get("depth") or [str(GRAPH_NEIGHBOR_DEFAULT_DEPTH)])[0],
                    name="depth",
                    default=GRAPH_NEIGHBOR_DEFAULT_DEPTH,
                    min_value=1,
                    max_value=GRAPH_NEIGHBOR_MAX_DEPTH,
                )
                node_limit = _parse_bounded_query_int(
                    (q.get("node_limit") or [str(GRAPH_NEIGHBOR_DEFAULT_NODE_LIMIT)])[0],
                    name="node_limit",
                    default=GRAPH_NEIGHBOR_DEFAULT_NODE_LIMIT,
                    min_value=1,
                    max_value=GRAPH_NEIGHBOR_MAX_NODE_LIMIT,
                )
                link_limit = _parse_bounded_query_int(
                    (q.get("link_limit") or [str(GRAPH_NEIGHBOR_DEFAULT_LINK_LIMIT)])[0],
                    name="link_limit",
                    default=GRAPH_NEIGHBOR_DEFAULT_LINK_LIMIT,
                    min_value=1,
                    max_value=GRAPH_NEIGHBOR_MAX_LINK_LIMIT,
                )
                payload = _build_graph_neighbors_payload(
                    self.server.runtime,
                    atom_id=atom_id,
                    depth=depth,
                    node_limit=node_limit,
                    link_limit=link_limit,
                    include_shared_language=_to_bool((q.get("include_shared_language") or ["false"])[0], default=False),
                    include_root_detail=_to_bool((q.get("include_root_detail") or ["true"])[0], default=True),
                )
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "atom not found"})
            except Exception as exc:
                LOGGER.exception("graph neighbors lookup failed", exc_info=exc)
                return _json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "graph neighbors lookup failed"},
                )
            return _json_response(self, HTTPStatus.OK, payload)
        if path == "/api/memory/graph":
            q = parse_qs(parsed.query)
            atom_id = str((q.get("atom_id") or [""])[0]).strip()
            if not atom_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "atom_id is required"})
            try:
                atom = self.server.runtime.retriever.store.get_atom(atom_id)
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "atom not found"})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"graph lookup failed: {exc}"})
            _revision, snapshot = self.server.runtime.continuity_store.snapshot_view()
            conflicts = set(self.server.runtime.retriever.store.conflict_neighbors(atom_id))
            constellation_ids, arc_ids, shared = _iter_snapshot_neighbors(snapshot, atom_id)
            links: list[dict[str, Any]] = []
            for other in sorted(conflicts):
                links.append({"source": atom_id, "target": other, "kind": "conflict"})
            for other in sorted(constellation_ids):
                links.append({"source": atom_id, "target": other, "kind": "constellation"})
            for other in sorted(arc_ids):
                links.append({"source": atom_id, "target": other, "kind": "narrative_arc"})
            for key in shared:
                key_node = f"slk:{key['key_id']}"
                links.append({"source": atom_id, "target": key_node, "kind": "shared_language"})
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "atom": _serialize_atom(atom),
                    "links": links,
                    "shared_language_keys": shared,
                },
            )
        if path == "/api/memory/graph-map":
            q = parse_qs(parsed.query)
            search = str((q.get("q") or [""])[0]).strip().lower()
            status_filter = str((q.get("status") or ["all"])[0]).strip().lower()
            kind_filter = str((q.get("kind") or ["all"])[0]).strip().lower()
            contradiction_filter = str((q.get("contradiction") or ["all"])[0]).strip().lower()
            limit = _as_int((q.get("limit") or ["180"])[0], default=180, min_value=1, max_value=600)
            allowed_status = {item.value for item in AtomStatus}
            allowed_kind = {"fact_card", "event_card", "relationship_card"}
            if status_filter != "all" and status_filter not in allowed_status:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "status must be 'all' or a valid atom status"})
            if kind_filter != "all" and kind_filter not in allowed_kind:
                return _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": "kind must be one of: all, fact_card, event_card, relationship_card"},
                )
            if contradiction_filter not in {"all", "true", "false"}:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "contradiction must be one of: all, true, false"})

            selected: list[tuple[Any, dict[str, Any]]] = []
            for atom in self.server.runtime.retriever.store.list_atoms():
                card = _serialize_card(atom)
                if status_filter != "all" and card["atom_status"] != status_filter:
                    continue
                if kind_filter != "all" and card["kind"] != kind_filter:
                    continue
                if contradiction_filter != "all":
                    expected = contradiction_filter == "true"
                    if bool(card["contradiction"]) != expected:
                        continue
                if search:
                    hay = " ".join(
                        [
                            str(card["summary"]),
                            " ".join(str(item) for item in list(card["citations"])),
                            " ".join(str(item) for item in list(getattr(atom, "entities", []) or [])),
                            " ".join(str(item) for item in list(getattr(atom, "topics", []) or [])),
                        ]
                    ).lower()
                    if search not in hay:
                        continue
                selected.append((atom, card))
            selected.sort(key=lambda item: ((item[1].get("updated_at") or ""), (item[0].atom_id or "")), reverse=True)
            total = len(selected)
            selected = selected[:limit]
            selected_ids = {str(atom.atom_id) for atom, _card in selected}

            snapshot_available = True
            try:
                _revision, snapshot = self.server.runtime.continuity_store.snapshot_view()
            except Exception:
                snapshot = None
                snapshot_available = False

            links: list[dict[str, Any]] = []
            link_seen: set[tuple[str, str, str]] = set()

            def add_link(source: str, target: str, kind: str) -> None:
                if source == target:
                    return
                if source not in selected_ids or target not in selected_ids:
                    return
                left, right = sorted([source, target])
                key = (left, right, kind)
                if key in link_seen:
                    return
                link_seen.add(key)
                links.append({"source": source, "target": target, "kind": kind})

            for atom, _card in selected:
                atom_id = str(atom.atom_id)
                for other in self.server.runtime.retriever.store.conflict_neighbors(atom_id):
                    add_link(atom_id, str(other), "conflict")
                constellation_ids, arc_ids, _shared = _iter_snapshot_neighbors(snapshot, atom_id)
                for other in constellation_ids:
                    add_link(atom_id, str(other), "constellation")
                for other in arc_ids:
                    add_link(atom_id, str(other), "narrative_arc")

            degree: dict[str, int] = {atom_id: 0 for atom_id in selected_ids}
            for link in links:
                source = str(link.get("source") or "")
                target = str(link.get("target") or "")
                if source in degree:
                    degree[source] += 1
                if target in degree:
                    degree[target] += 1

            nodes = [
                {
                    "atom_id": str(atom.atom_id),
                    "card_id": str(card.get("card_id") or f"card_{atom.atom_id}"),
                    "summary": str(card.get("summary") or ""),
                    "kind": str(card.get("kind") or ""),
                    "status": str(card.get("atom_status") or ""),
                    "confidence": float(card.get("confidence") or 0.0),
                    "contradiction": bool(card.get("contradiction")),
                    "citation_count": int(card.get("citation_count") or 0),
                    "entities": list(getattr(atom, "entities", []) or []),
                    "topics": list(getattr(atom, "topics", []) or []),
                    "degree": int(degree.get(str(atom.atom_id), 0)),
                }
                for atom, card in selected
            ]
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "nodes": nodes,
                    "links": links,
                    "total": total,
                    "truncated": total > len(nodes),
                    "snapshot_available": snapshot_available,
                },
            )
        return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if self._integration_handle_request(method="POST", parsed=parsed):
            return
        if path == "/api/explore/preferences":
            try:
                data = _read_json(self)
                anchor_id_raw = str(data.get("anchor_id") or "").strip()
                if not anchor_id_raw:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "anchor_id is required"})
                anchor_id = _normalize_anchor_id(anchor_id_raw)
                if not anchor_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "anchor_id is invalid"})
                anchor_type = str(data.get("anchor_type") or "topic").strip().lower() or "topic"
                if anchor_type not in EXPLORATION_ALLOWED_TYPES:
                    anchor_type = "topic"
                action = str(data.get("action") or "").strip().lower()
                if action not in EXPLORATION_ALLOWED_ACTIONS:
                    return _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {"error": "action must be one of: pin, more, less, ignore, clear"},
                    )
                key = _anchor_key(anchor_type, anchor_id)
                lock = getattr(self.server, "exploration_preferences_lock", None)
                if lock is None:
                    lock = threading.Lock()
                    self.server.exploration_preferences_lock = lock
                with lock:
                    pref_store = dict(getattr(self.server, "exploration_preferences", {}) or {})
                    if action == "clear":
                        pref_store.pop(key, None)
                        self.server.exploration_preferences = pref_store
                        return _json_response(
                            self,
                            HTTPStatus.OK,
                            {
                                "ok": True,
                                "applied": True,
                                "removed": True,
                                "anchor_id": anchor_id,
                                "anchor_type": anchor_type,
                                "count": len(pref_store),
                            },
                        )
                    weight = float(EXPLORATION_PREFERENCE_WEIGHTS.get(action) or 0.0)
                    pref_store[key] = {
                        "anchor_id": anchor_id,
                        "anchor_type": anchor_type,
                        "action": action,
                        "weight": weight,
                        "updated_at": _utc_iso(),
                    }
                    self.server.exploration_preferences = pref_store
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "applied": True,
                        "removed": False,
                        "preference": dict(self.server.exploration_preferences.get(key) or {}),
                        "count": len(dict(getattr(self.server, "exploration_preferences", {}) or {})),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"explore preference update failed: {exc}"})
        if path == "/api/methodology/create":
            try:
                data = _read_json(self)
                actor = str(data.get("actor") or "operator").strip() or "operator"
                provenance_refs = [str(item).strip() for item in list(data.get("provenance_refs") or []) if str(item).strip()]
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    record = create_methodology_record(
                        state,
                        trigger_condition=str(data.get("trigger_condition") or ""),
                        action=str(data.get("action") or ""),
                        rationale=str(data.get("rationale") or ""),
                        actor=actor,
                        provenance_refs=provenance_refs,
                        supersedes_id=str(data.get("supersedes_id") or "").strip() or None,
                        metadata=dict(data.get("metadata") or {}),
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "record": record})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("methodology create failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "methodology create failed"})
        if path == "/api/methodology/review":
            try:
                data = _read_json(self)
                methodology_id = str(data.get("methodology_id") or "").strip()
                if not methodology_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "methodology_id is required"})
                decision = str(data.get("decision") or "").strip().lower()
                reviewer = str(data.get("reviewer") or "").strip()
                note = str(data.get("note") or "").strip()
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    record = review_methodology_record(
                        state,
                        methodology_id=methodology_id,
                        decision=decision,
                        reviewer=reviewer,
                        note=note,
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "record": record})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "methodology not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("methodology review failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "methodology review failed"})
        if path == "/api/methodology/canary/start":
            try:
                data = _read_json(self)
                methodology_id = str(data.get("methodology_id") or "").strip()
                if not methodology_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "methodology_id is required"})
                actor = str(data.get("actor") or "operator").strip() or "operator"
                auto_rollback = _to_bool(data.get("auto_rollback"), default=True)
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    record = promote_methodology_to_canary(
                        state,
                        methodology_id=methodology_id,
                        runtime=self.server.runtime,
                        actor=actor,
                        auto_rollback=auto_rollback,
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "record": record})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "methodology not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("methodology canary start failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "methodology canary start failed"})
        if path == "/api/methodology/canary/evaluate":
            try:
                data = _read_json(self)
                methodology_id = str(data.get("methodology_id") or "").strip()
                if not methodology_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "methodology_id is required"})
                actor = str(data.get("actor") or "operator").strip() or "operator"
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    result = evaluate_methodology_canary(
                        state,
                        methodology_id=methodology_id,
                        runtime=self.server.runtime,
                        actor=actor,
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, **result})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "methodology not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("methodology canary evaluate failed")
                return _json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "methodology canary evaluate failed"},
                )
        if path == "/api/methodology/activate":
            try:
                data = _read_json(self)
                methodology_id = str(data.get("methodology_id") or "").strip()
                if not methodology_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "methodology_id is required"})
                actor = str(data.get("actor") or "operator").strip() or "operator"
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    record = activate_methodology_record(
                        state,
                        methodology_id=methodology_id,
                        actor=actor,
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                    active_methodology_id = str(state.get("active_methodology_id") or "")
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "record": record,
                        "active_methodology_id": active_methodology_id,
                    },
                )
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "methodology not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("methodology activate failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "methodology activate failed"})
        if path == "/api/methodology/rollback":
            try:
                data = _read_json(self)
                methodology_id = str(data.get("methodology_id") or "").strip()
                if not methodology_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "methodology_id is required"})
                actor = str(data.get("actor") or "operator").strip() or "operator"
                reason = str(data.get("reason") or "manual_rollback").strip() or "manual_rollback"
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    payload = rollback_methodology_record(
                        state,
                        methodology_id=methodology_id,
                        actor=actor,
                        reason=reason,
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, **payload})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "methodology not found"})
            except Exception:
                LOGGER.exception("methodology rollback failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "methodology rollback failed"})
        if path == "/api/methodology/corrections/record":
            try:
                data = _read_json(self)
                text = str(data.get("text") or "").strip()
                if not text:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "text is required"})
                actor = str(data.get("actor") or "operator").strip() or "operator"
                assistant_id = str(data.get("assistant_id") or "").strip()
                session_id = str(data.get("session_id") or "").strip()
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    payload = record_correction_event(
                        state,
                        text=text,
                        assistant_id=assistant_id,
                        session_id=session_id,
                        actor=actor,
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, **payload})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("correction record failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "correction record failed"})
        if path == "/api/methodology/maintenance/evaluate":
            try:
                data = _read_json(self)
                actor = str(data.get("actor") or "operator").strip() or "operator"
                force = _to_bool(data.get("force"), default=False)
                with self.server.methodology_lock:
                    state = getattr(self.server, "methodology_state", None)
                    if not isinstance(state, dict):
                        state = load_methodology_state(Path(self.server.methodology_state_path))
                        self.server.methodology_state = state
                    evaluation = evaluate_maintenance_triggers(
                        state,
                        runtime=self.server.runtime,
                        actor=actor,
                        force=force,
                    )
                    persist_methodology_state(Path(self.server.methodology_state_path), state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "evaluation": evaluation})
            except Exception:
                LOGGER.exception("maintenance evaluation failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "maintenance evaluation failed"})
        if path == "/api/memory/quicknote/propose":
            try:
                data = _read_json(self)
                with self.server.quicknote_lock:
                    state = getattr(self.server, "quicknote_state", None)
                    if not isinstance(state, dict):
                        state = _quicknote_default_state()
                        self.server.quicknote_state = state
                    config = dict(getattr(self.server, "quicknote_config", {}) or {})
                    policy = dict(getattr(self.server, "quicknote_policy", {}) or {})
                    session_cap = max(1, int(config.get("session_cap") or 24))
                    inactivity_timeout = max(60, int(config.get("inactivity_timeout_seconds") or 3600))
                    max_note_chars = max(80, int(config.get("max_note_chars") or 900))
                    max_tags = max(1, int(config.get("max_tags") or 8))
                    max_history_notes = max(100, int(config.get("max_history_notes") or 8_000))
                    summary_chars = max(80, int(config.get("summary_chars") or 220))
                    auto_apply = bool(policy.get("auto_apply"))
                    timeout_flushes = _quicknote_maybe_flush_inactive(
                        state,
                        inactivity_timeout_seconds=inactivity_timeout,
                        auto_apply=auto_apply,
                        session_cap=session_cap,
                    )
                    assistant_id, session_id = _quicknote_resolve_scope(
                        state,
                        assistant_hint=data.get("assistant_id"),
                        session_hint=data.get("session_id"),
                    )
                    text = _quicknote_normalize_text(data.get("text"), max_chars=max_note_chars)
                    if not text:
                        return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "text is required"})
                    importance = _quicknote_normalize_importance(data.get("importance"))
                    tags = _quicknote_normalize_tags(data.get("tags"), max_items=max_tags)
                    context_pressure = str(data.get("context_pressure") or "low").strip().lower() or "low"
                    if context_pressure not in QUICKNOTE_ALLOWED_CONTEXT_PRESSURE:
                        context_pressure = "low"
                    proposed = _quicknote_propose(
                        state,
                        assistant_id=assistant_id,
                        session_id=session_id,
                        text=text,
                        importance=importance,
                        tags=tags,
                        session_cap=session_cap,
                        max_history_notes=max_history_notes,
                        auto_apply=auto_apply,
                        summary_chars=summary_chars,
                        context_pressure=context_pressure,
                    )
                    _quicknote_persist_state(self.server)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        **proposed,
                        "inactivity_flushes": timeout_flushes,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"quicknote propose failed: {exc}"})
        if path == "/api/memory/quicknote/propose-batch":
            try:
                data = _read_json(self)
                rows_raw = data.get("notes")
                if rows_raw is None:
                    rows_raw = data.get("items")
                if not isinstance(rows_raw, list):
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "notes must be an array"})
                with self.server.quicknote_lock:
                    state = getattr(self.server, "quicknote_state", None)
                    if not isinstance(state, dict):
                        state = _quicknote_default_state()
                        self.server.quicknote_state = state
                    config = dict(getattr(self.server, "quicknote_config", {}) or {})
                    policy = dict(getattr(self.server, "quicknote_policy", {}) or {})
                    session_cap = max(1, int(config.get("session_cap") or 24))
                    inactivity_timeout = max(60, int(config.get("inactivity_timeout_seconds") or 3600))
                    max_note_chars = max(80, int(config.get("max_note_chars") or 900))
                    max_tags = max(1, int(config.get("max_tags") or 8))
                    max_batch_items = max(1, int(config.get("max_batch_items") or 24))
                    max_history_notes = max(100, int(config.get("max_history_notes") or 8_000))
                    summary_chars = max(80, int(config.get("summary_chars") or 220))
                    auto_apply = bool(policy.get("auto_apply"))
                    if len(rows_raw) > max_batch_items:
                        return _json_response(
                            self,
                            HTTPStatus.BAD_REQUEST,
                            {"error": f"batch too large (max {max_batch_items})"},
                        )
                    timeout_flushes = _quicknote_maybe_flush_inactive(
                        state,
                        inactivity_timeout_seconds=inactivity_timeout,
                        auto_apply=auto_apply,
                        session_cap=session_cap,
                    )
                    assistant_id, session_id = _quicknote_resolve_scope(
                        state,
                        assistant_hint=data.get("assistant_id"),
                        session_hint=data.get("session_id"),
                    )
                    default_importance = _quicknote_normalize_importance(data.get("importance"))
                    shared_tags = _quicknote_normalize_tags(data.get("tags"), max_items=max_tags)
                    context_pressure = str(data.get("context_pressure") or "low").strip().lower() or "low"
                    if context_pressure not in QUICKNOTE_ALLOWED_CONTEXT_PRESSURE:
                        context_pressure = "low"
                    item_results: list[dict[str, Any]] = []
                    accepted = 0
                    duplicates = 0
                    rejected = 0
                    for index, row in enumerate(rows_raw):
                        if not isinstance(row, dict):
                            item_results.append({"index": index, "accepted": False, "status": "invalid_item"})
                            rejected += 1
                            continue
                        text = _quicknote_normalize_text(row.get("text"), max_chars=max_note_chars)
                        if not text:
                            item_results.append({"index": index, "accepted": False, "status": "missing_text"})
                            rejected += 1
                            continue
                        item_importance = _quicknote_normalize_importance(row.get("importance") or default_importance)
                        item_tags = _quicknote_normalize_tags(row.get("tags"), max_items=max_tags)
                        merged_tags = _quicknote_normalize_tags(shared_tags + item_tags, max_items=max_tags)
                        proposed = _quicknote_propose(
                            state,
                            assistant_id=assistant_id,
                            session_id=session_id,
                            text=text,
                            importance=item_importance,
                            tags=merged_tags,
                            session_cap=session_cap,
                            max_history_notes=max_history_notes,
                            auto_apply=auto_apply,
                            summary_chars=summary_chars,
                            context_pressure=context_pressure,
                        )
                        item_results.append(
                            {
                                "index": index,
                                "accepted": bool(proposed.get("accepted")),
                                "status": str(proposed.get("status") or ""),
                                "note": dict(proposed.get("note") or {}),
                            }
                        )
                        if bool(proposed.get("accepted")):
                            accepted += 1
                        elif str(proposed.get("status") or "") == "duplicate":
                            duplicates += 1
                        else:
                            rejected += 1
                    status_payload = _quicknote_status_for_scope(
                        state,
                        assistant_id=assistant_id,
                        session_id=session_id,
                        session_cap=session_cap,
                    )
                    _quicknote_persist_state(self.server)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "assistant_id": assistant_id,
                        "session_id": session_id,
                        "accepted_count": accepted,
                        "duplicate_count": duplicates,
                        "rejected_count": rejected,
                        "results": item_results,
                        "status": status_payload,
                        "inactivity_flushes": timeout_flushes,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"quicknote batch failed: {exc}"})
        if path == "/api/memory/quicknote/flush":
            try:
                data = _read_json(self)
                with self.server.quicknote_lock:
                    state = getattr(self.server, "quicknote_state", None)
                    if not isinstance(state, dict):
                        state = _quicknote_default_state()
                        self.server.quicknote_state = state
                    config = dict(getattr(self.server, "quicknote_config", {}) or {})
                    policy = dict(getattr(self.server, "quicknote_policy", {}) or {})
                    session_cap = max(1, int(config.get("session_cap") or 24))
                    inactivity_timeout = max(60, int(config.get("inactivity_timeout_seconds") or 3600))
                    auto_apply = bool(policy.get("auto_apply"))
                    timeout_flushes = _quicknote_maybe_flush_inactive(
                        state,
                        inactivity_timeout_seconds=inactivity_timeout,
                        auto_apply=auto_apply,
                        session_cap=session_cap,
                    )
                    assistant_id, session_id = _quicknote_resolve_scope(
                        state,
                        assistant_hint=data.get("assistant_id"),
                        session_hint=data.get("session_id"),
                    )
                    reason = str(data.get("reason") or "manual").strip().lower() or "manual"
                    if reason not in QUICKNOTE_ALLOWED_FLUSH_REASONS:
                        reason = "manual"
                    flushed = _quicknote_flush_buffer(
                        state,
                        assistant_id=assistant_id,
                        session_id=session_id,
                        reason=reason,
                        auto_apply=auto_apply,
                        session_cap=session_cap,
                    )
                    status_payload = _quicknote_status_for_scope(
                        state,
                        assistant_id=assistant_id,
                        session_id=session_id,
                        session_cap=session_cap,
                    )
                    _quicknote_persist_state(self.server)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        **flushed,
                        "status": status_payload,
                        "inactivity_flushes": timeout_flushes,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"quicknote flush failed: {exc}"})
        if path == "/api/wizard/organizer/inventory":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                limit = _as_int(str(data.get("limit") or "24"), default=24, min_value=1, max_value=80)
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                snapshot = _build_exploration_snapshot(
                    self.server.runtime,
                    limit=limit,
                    preferences={},
                )
                typed_candidates = _organizer_inventory_candidates(snapshot)
                organizer = _wizard_organizer_state(state)
                organizer["inventory"] = {
                    "generated_at": _utc_iso(),
                    "status": "ready" if typed_candidates else "insufficient_support",
                    "limit": limit,
                    "counts": {
                        "atom_count": int(snapshot.get("atom_count") or 0),
                        "total_anchors": int(snapshot.get("total_anchors") or 0),
                        "typed_candidates": len(typed_candidates),
                    },
                    "typed_candidates": typed_candidates,
                    "snapshot": dict(snapshot.get("buckets") or {}),
                }
                _mark_wizard_stage(state, stage="organizer_inventory", note=f"Organizer inventory generated ({len(typed_candidates)} typed candidates).")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "inventory": organizer["inventory"],
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"organizer inventory failed: {exc}"})
        if path == "/api/wizard/organizer/dedupe":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                organizer = _wizard_organizer_state(state)
                inventory = dict(organizer.get("inventory") or {})
                typed_candidates = [row for row in list(inventory.get("typed_candidates") or []) if isinstance(row, dict)]
                if not typed_candidates:
                    snapshot = _build_exploration_snapshot(
                        self.server.runtime,
                        limit=24,
                        preferences={},
                    )
                    typed_candidates = _organizer_inventory_candidates(snapshot)
                    organizer["inventory"] = {
                        "generated_at": _utc_iso(),
                        "status": "ready" if typed_candidates else "insufficient_support",
                        "limit": 24,
                        "counts": {
                            "atom_count": int(snapshot.get("atom_count") or 0),
                            "total_anchors": int(snapshot.get("total_anchors") or 0),
                            "typed_candidates": len(typed_candidates),
                        },
                        "typed_candidates": typed_candidates,
                        "snapshot": dict(snapshot.get("buckets") or {}),
                    }
                proposals = _organizer_dedupe_proposals(typed_candidates)
                organizer["dedupe"] = {
                    "generated_at": _utc_iso(),
                    "status": "ready",
                    "counts": {
                        "proposal_count": len(proposals),
                        "safe_count": len([row for row in proposals if str(row.get("risk_class") or "") == "safe"]),
                        "review_count": len([row for row in proposals if str(row.get("risk_class") or "") != "safe"]),
                    },
                    "proposals": proposals,
                }
                _mark_wizard_stage(state, stage="organizer_dedupe", note=f"Organizer dedupe proposals generated ({len(proposals)} proposals).")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "run_id": state.get("run_id"), "dedupe": organizer["dedupe"]},
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"organizer dedupe failed: {exc}"})
        if path == "/api/wizard/organizer/conflicts":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                organizer = _wizard_organizer_state(state)
                inventory = dict(organizer.get("inventory") or {})
                typed_candidates = [row for row in list(inventory.get("typed_candidates") or []) if isinstance(row, dict)]
                if not typed_candidates:
                    snapshot = _build_exploration_snapshot(
                        self.server.runtime,
                        limit=24,
                        preferences={},
                    )
                    typed_candidates = _organizer_inventory_candidates(snapshot)
                    organizer["inventory"] = {
                        "generated_at": _utc_iso(),
                        "status": "ready" if typed_candidates else "insufficient_support",
                        "limit": 24,
                        "counts": {
                            "atom_count": int(snapshot.get("atom_count") or 0),
                            "total_anchors": int(snapshot.get("total_anchors") or 0),
                            "typed_candidates": len(typed_candidates),
                        },
                        "typed_candidates": typed_candidates,
                        "snapshot": dict(snapshot.get("buckets") or {}),
                    }
                conflict_queue, ambiguity_queue = _organizer_conflict_queues(self.server.runtime, typed_candidates)
                organizer["conflicts"] = {
                    "generated_at": _utc_iso(),
                    "status": "ready",
                    "conflict_queue": conflict_queue,
                    "ambiguity_queue": ambiguity_queue,
                    "counts": {
                        "conflicts": len(conflict_queue),
                        "ambiguities": len(ambiguity_queue),
                    },
                }
                _mark_wizard_stage(
                    state,
                    stage="organizer_conflicts",
                    note=f"Organizer conflict/ambiguity queues generated ({len(conflict_queue)} conflicts, {len(ambiguity_queue)} ambiguities).",
                )
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "run_id": state.get("run_id"), "conflicts": organizer["conflicts"]},
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"organizer conflict queue failed: {exc}"})
        if path == "/api/wizard/organizer/package":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                organizer = _wizard_organizer_state(state)
                dedupe = dict(organizer.get("dedupe") or {})
                conflicts = dict(organizer.get("conflicts") or {})
                dedupe_proposals = [row for row in list(dedupe.get("proposals") or []) if isinstance(row, dict)]
                conflict_queue = [row for row in list(conflicts.get("conflict_queue") or []) if isinstance(row, dict)]
                ambiguity_queue = [row for row in list(conflicts.get("ambiguity_queue") or []) if isinstance(row, dict)]
                package = _organizer_package(
                    dedupe_proposals=dedupe_proposals,
                    conflict_queue=conflict_queue,
                    ambiguity_queue=ambiguity_queue,
                )
                organizer["package"] = package
                _mark_wizard_stage(
                    state,
                    stage="organizer_package",
                    note=f"Organizer package assembled ({int(package.get('counts', {}).get('safe_operations', 0))} safe ops).",
                )
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "run_id": state.get("run_id"), "package": package},
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"organizer package failed: {exc}"})
        if path == "/api/wizard/organizer/apply":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                dry_run = _to_bool(data.get("dry_run"), default=False)
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                organizer = _wizard_organizer_state(state)
                package = dict(organizer.get("package") or {})
                package_id = str(package.get("package_id") or "").strip()
                if not package_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "organizer package is not available"})
                safe_operations = [row for row in list(package.get("safe_operations") or []) if isinstance(row, dict)]
                current_profile = dict(organizer.get("applied_profile") or {})
                aliases: list[dict[str, Any]] = []
                applied_ids: list[str] = []
                for row in safe_operations:
                    canonical_label = str(row.get("canonical_label") or "").strip()
                    alias_values = _normalize_string_list(row.get("aliases"), max_items=24, max_chars=120)
                    proposal_id = str(row.get("proposal_id") or "").strip()
                    if canonical_label and alias_values:
                        aliases.append({"canonical_label": canonical_label, "aliases": alias_values})
                    if proposal_id:
                        applied_ids.append(proposal_id)
                profile = {
                    "package_id": package_id,
                    "updated_at": _utc_iso(),
                    "safe_operation_count": len(safe_operations),
                    "applied_operation_ids": applied_ids,
                    "aliases": aliases,
                }
                if not dry_run:
                    rollback_history = list(organizer.get("rollback_history") or [])
                    rollback_id = f"org_rb_{_utc_stamp().lower()}"
                    rollback_history.append(
                        {
                            "rollback_id": rollback_id,
                            "at": _utc_iso(),
                            "package_id": package_id,
                            "applied_profile": current_profile,
                        }
                    )
                    organizer["rollback_history"] = rollback_history[-40:]
                    organizer["applied_profile"] = profile
                    _mark_wizard_stage(state, stage="organizer_apply", note=f"Organizer safe operations applied ({len(safe_operations)}).")
                    _save_wizard_state(state)
                    return _json_response(
                        self,
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "run_id": state.get("run_id"),
                            "applied": True,
                            "dry_run": False,
                            "rollback_id": rollback_id,
                            "profile": profile,
                            "safe_operation_count": len(safe_operations),
                        },
                    )
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "applied": False,
                        "dry_run": True,
                        "profile_preview": profile,
                        "safe_operation_count": len(safe_operations),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"organizer apply failed: {exc}"})
        if path == "/api/wizard/organizer/restore-last":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                organizer = _wizard_organizer_state(state)
                rollback_history = list(organizer.get("rollback_history") or [])
                if not rollback_history:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "no organizer rollback snapshot available"})
                snapshot = rollback_history.pop()
                organizer["rollback_history"] = rollback_history
                restored_profile = dict(snapshot.get("applied_profile") or {})
                organizer["applied_profile"] = restored_profile
                _mark_wizard_stage(state, stage="organizer_apply", note="Organizer rollback snapshot restored.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "restored": True,
                        "snapshot": snapshot,
                        "applied_profile": restored_profile,
                        "remaining_snapshots": len(rollback_history),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"organizer restore failed: {exc}"})
        if path == "/api/wizard/organizer/verify":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                organizer = _wizard_organizer_state(state)
                inventory = dict(organizer.get("inventory") or {})
                dedupe = dict(organizer.get("dedupe") or {})
                conflicts = dict(organizer.get("conflicts") or {})
                package = dict(organizer.get("package") or {})
                applied = dict(organizer.get("applied_profile") or {})
                typed_candidates = [row for row in list(inventory.get("typed_candidates") or []) if isinstance(row, dict)]
                dedupe_proposals = [row for row in list(dedupe.get("proposals") or []) if isinstance(row, dict)]
                conflict_queue = [row for row in list(conflicts.get("conflict_queue") or []) if isinstance(row, dict)]
                ambiguity_queue = [row for row in list(conflicts.get("ambiguity_queue") or []) if isinstance(row, dict)]
                safe_operations = [row for row in list(package.get("safe_operations") or []) if isinstance(row, dict)]
                applied_ids = [str(item).strip() for item in list(applied.get("applied_operation_ids") or []) if str(item).strip()]
                duplicate_before = sum(max(0, len(_normalize_string_list(row.get("aliases"), max_items=24, max_chars=120)) - 1) for row in dedupe_proposals)
                duplicate_after = max(0, duplicate_before - len(applied_ids))
                quality_delta = duplicate_before - duplicate_after
                status = "safe"
                if conflict_queue or ambiguity_queue:
                    status = "needs_attention"
                verify_payload = {
                    "checked_at": _utc_iso(),
                    "status": status,
                    "metrics": {
                        "typed_candidates": len(typed_candidates),
                        "dedupe_proposals": len(dedupe_proposals),
                        "safe_operations": len(safe_operations),
                        "applied_safe_operations": len(applied_ids),
                        "conflicts_open": len(conflict_queue),
                        "ambiguities_open": len(ambiguity_queue),
                        "duplicate_before": duplicate_before,
                        "duplicate_after": duplicate_after,
                        "quality_delta": quality_delta,
                    },
                    "recommendation": (
                        "review_conflicts_and_ambiguities"
                        if status != "safe"
                        else "ready_for_next_cycle"
                    ),
                }
                organizer["verify"] = verify_payload
                _mark_wizard_stage(state, stage="organizer_verify", note=f"Organizer verification status: {status}.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "verify": verify_payload,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"organizer verify failed: {exc}"})
        if path == "/api/wizard/start":
            try:
                data = _read_json(self)
                mode = str(data.get("mode") or "").strip().lower()
                run_id = str(data.get("run_id") or "").strip() or None
                if mode in {"new", "start_new", "start-new"}:
                    state = _start_new_wizard_state()
                else:
                    try:
                        state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                    except FileNotFoundError:
                        state = _start_new_wizard_state()
                note = "Wizard session started." if mode in {"new", "start_new", "start-new"} else "Wizard session resumed."
                _wizard_history(state, stage=str(state.get("current_stage") or "import"), note=note, status="ok")
                _save_wizard_state(state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "state": state, "run_id": state.get("run_id")})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"wizard start failed: {exc}"})
        if path == "/api/wizard/input/upload":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                file_name = Path(str(data.get("file_name") or "").strip()).name
                content_b64 = str(data.get("content_base64") or "").strip()
                if not file_name or not content_b64:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "file_name and content_base64 are required"})
                upload_root = RUNTIME_ROOT / "wizard_uploads" / str(state.get("run_id") or "unknown")
                upload_root.mkdir(parents=True, exist_ok=True)
                target_path = (upload_root / file_name).resolve()
                if upload_root.resolve() not in target_path.parents and target_path != upload_root.resolve():
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid upload target"})
                decoded = base64.b64decode(content_b64.encode("ascii"), validate=True)
                target_path.write_bytes(decoded)
                classification = _wizard_classify_input_path(target_path)
                _wizard_bind_input_to_state(state, classification)
                state.setdefault("artifacts", {})["uploaded_input"] = {
                    "path": str(target_path),
                    "size_bytes": len(decoded),
                    "at": _utc_iso(),
                    "classification": classification,
                }
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "uploaded_path": str(target_path),
                        "size_bytes": len(decoded),
                        "classification": classification,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"input upload failed: {exc}"})
        if path == "/api/wizard/import/validate":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                raw_input_path = str(
                    data.get("input_path")
                    or data.get("archive_path")
                    or data.get("store_path")
                    or (state.get("selected_input") or {}).get("path")
                    or state.get("selected_input_archive_path")
                    or ""
                ).strip()
                if not raw_input_path:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "input_path is required"})
                classification = _wizard_classify_input_path(Path(raw_input_path))
                previous = dict(state.get("selected_input") or {})
                selection_changed = any(
                    str(previous.get(key) or "").strip() != str(classification.get(key) or "").strip()
                    for key in ("path", "kind", "store_fingerprint")
                )
                _wizard_bind_input_to_state(state, classification)
                if selection_changed:
                    _wizard_reset_downstream_state(state, from_stage="import")
                    _wizard_reset_to_stage(
                        state,
                        stage="import",
                        note="Selected input changed; cleared downstream build, review, publish, verify, and activation state.",
                    )
                status = "blocked"
                if bool(classification.get("is_valid")):
                    status = str(classification.get("status") or "safe").strip().lower() or "safe"
                state.setdefault("artifacts", {})["import_validation"] = {
                    "at": _utc_iso(),
                    **classification,
                }
                label = str(classification.get("kind") or "input").replace("_", " ")
                issue_count = len(list(classification.get("issues") or []))
                _wizard_history(state, stage="import", note=f"Validated {label} ({issue_count} issues).", status="ok" if status == "safe" else "warn")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "status": status,
                        **classification,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"import validation failed: {exc}"})
        if path == "/api/wizard/import/run":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                raw_input_path = str(
                    data.get("input_path")
                    or data.get("archive_path")
                    or data.get("store_path")
                    or (state.get("selected_input") or {}).get("path")
                    or state.get("selected_input_archive_path")
                    or state.get("store_path")
                    or ""
                ).strip()
                if not raw_input_path:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "input_path is required"})
                classification = _wizard_classify_input_path(Path(raw_input_path))
                _wizard_bind_input_to_state(state, classification)
                selected_kind = str(classification.get("kind") or "").strip()
                if not bool(classification.get("is_valid")):
                    return _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {"error": "; ".join(str(item) for item in list(classification.get("issues") or []) if str(item).strip()) or "selected input is invalid"},
                    )
                _snapshot_published_pointers(state, reason="pre_import_publish_update")
                _wizard_reset_downstream_state(state, from_stage="import")
                result: dict[str, Any] = {"ok": True, "mode": "existing_store"}
                if selected_kind == "ia_archive":
                    archive_path = Path(str(classification.get("path") or "")).expanduser().resolve()
                    store_path = Path(
                        str(data.get("store_path") or state.get("store_path") or "").strip() or (REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3")
                    ).expanduser().resolve()
                    out_dir = Path(str(data.get("out_dir") or (REPO_ROOT / ".runtime" / "imports"))).expanduser().resolve()
                    cmd = [
                        sys.executable,
                        str((REPO_ROOT / "tools" / "import_ia_db.py").resolve()),
                        "--input",
                        str(archive_path),
                        "--store",
                        str(store_path),
                        "--out-dir",
                        str(out_dir),
                    ]
                    result = _run_repo_tool(cmd, timeout_s=600.0)
                    if not result["ok"]:
                        return _json_response(
                            self,
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                            {
                                "error": "import tool failed",
                                "tool": result,
                            },
                        )
                    kv = dict(result.get("kv") or {})
                    state["selected_input_archive_path"] = str(archive_path)
                    resolved_store_path = Path(str(kv.get("store_path") or store_path)).expanduser().resolve()
                    store_validation = _wizard_validate_sqlite_store(resolved_store_path)
                    state["store_path"] = str(resolved_store_path)
                    state["store_validation"] = dict(_wizard_empty_store_validation() | store_validation)
                    state.setdefault("artifacts", {})["import_report_json"] = str(kv.get("report_json") or "")
                    state.setdefault("artifacts", {})["import_report_md"] = str(kv.get("report_md") or "")
                else:
                    state["store_path"] = str(classification.get("path") or "")
                    state["store_validation"] = dict(_wizard_empty_store_validation() | classification)
                state["published_pointers"] = {
                    "store_path": str(state.get("store_path") or ""),
                    "episodes_path": "",
                }
                _mark_wizard_stage(state, stage="import", note="Input accepted and store is ready.")
                _wizard_transition(state, stage="build_episodes", note="Import complete. Ready to build episode drafts.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "store_path": state.get("store_path"),
                        "input_kind": selected_kind,
                        "store_validation": state.get("store_validation"),
                        "reports": {
                            "json": state.get("artifacts", {}).get("import_report_json", ""),
                            "md": state.get("artifacts", {}).get("import_report_md", ""),
                        },
                        "tool": result,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"import run failed: {exc}"})
        if path == "/api/wizard/build/run":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                if str(data.get("store_path") or "").strip():
                    override_validation = _wizard_classify_input_path(Path(str(data.get("store_path") or "").strip()))
                    if str(override_validation.get("kind") or "") not in WIZARD_VALID_STORE_KINDS or not bool(override_validation.get("is_valid")):
                        return _json_response(
                            self,
                            HTTPStatus.BAD_REQUEST,
                            {"error": "; ".join(str(item) for item in list(override_validation.get("issues") or []) if str(item).strip()) or "store path is not a valid MNO store"},
                        )
                    _wizard_bind_input_to_state(state, override_validation)
                _wizard_require(state, action="build_run")
                store_path = Path(str((state.get("store_validation") or {}).get("path") or state.get("store_path") or "").strip()).expanduser().resolve()
                if not store_path.exists():
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"store path not found: {store_path}"})
                preset_key = str(data.get("policy_preset") or "strict").strip().lower()
                preset = BUILD_POLICY_PRESETS.get(preset_key) or BUILD_POLICY_PRESETS["strict"]
                builder_profile_raw = str(
                    data.get("builder_profile_path")
                    or (state.get("artifacts") or {}).get("builder_profile_path")
                    or ""
                ).strip()
                builder_profile_path = Path(builder_profile_raw).expanduser().resolve() if builder_profile_raw else None
                stamp = _utc_stamp()
                out_path = (EPISODES_ROOT / f"episode_cards_{stamp}.json").resolve()
                rejects_path = out_path.with_name(f"{out_path.stem}.rejects.json")
                readout_path = out_path.with_name(f"{out_path.stem}.readout.md")
                cmd = [
                    sys.executable,
                    str((REPO_ROOT / "tools" / "build_episode_cards.py").resolve()),
                    "--memories",
                    str(store_path),
                    "--out",
                    str(out_path),
                    "--rejects-out",
                    str(rejects_path),
                    "--min-atoms",
                    str(int(preset["min_atoms"])),
                    "--min-meaningful-tokens",
                    str(int(preset["min_meaningful_tokens"])),
                    "--min-evidence-strength",
                    str(float(preset["min_evidence_strength"])),
                ]
                if bool(preset.get("allow_single_strong")):
                    cmd.append("--allow-single-strong")
                if builder_profile_path is not None and builder_profile_path.exists():
                    cmd.extend(["--builder-profile", str(builder_profile_path)])
                build_result = _run_repo_tool(cmd, timeout_s=900.0)
                if not build_result["ok"]:
                    return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "episode build failed", "tool": build_result})
                readout_cmd = [
                    sys.executable,
                    str((REPO_ROOT / "tools" / "build_episode_card_readout.py").resolve()),
                    "--episodes",
                    str(out_path),
                    "--out",
                    str(readout_path),
                ]
                readout_result = _run_repo_tool(readout_cmd, timeout_s=120.0)
                counts: dict[str, Any] = {}
                if out_path.exists():
                    try:
                        draft_payload = _load_episode_cards_payload(out_path)
                        counts = dict(draft_payload.get("counts") or {})
                    except Exception:
                        draft_payload = None
                        counts = {}
                _snapshot_published_pointers(state, reason="pre_build_publish_update")
                _wizard_reset_downstream_state(state, from_stage="build_episodes")
                state["last_built_episode_draft_path"] = str(out_path)
                state["last_built_episode_rejects_path"] = str(rejects_path)
                state["last_built_episode_readout_path"] = str(readout_path)
                state["build_info"] = {
                    "build_id": f"build_{stamp.lower()}",
                    "store_fingerprint": str((state.get("store_validation") or {}).get("store_fingerprint") or ""),
                    "schema_version": (state.get("store_validation") or {}).get("schema_version"),
                    "draft_path": str(out_path),
                    "rejects_path": str(rejects_path),
                    "readout_path": str(readout_path),
                    "counts": counts,
                }
                state.setdefault("artifacts", {})["build_policy_preset"] = preset_key
                if builder_profile_path is not None and builder_profile_path.exists():
                    state.setdefault("artifacts", {})["builder_profile_path"] = str(builder_profile_path)
                state.setdefault("artifacts", {})["last_build_counts"] = counts
                _wizard_sync_review_state(state, source_cards_path=out_path, source_payload=draft_payload)
                _mark_wizard_stage(state, stage="build_episodes", note=f"Built episodes using preset={preset_key}.")
                _wizard_transition(state, stage="review", note="Draft episodes are ready for review.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "policy_preset": preset_key,
                        "draft_path": str(out_path),
                        "rejects_path": str(rejects_path),
                        "readout_path": str(readout_path),
                        "builder_profile_path": str(builder_profile_path) if builder_profile_path is not None else "",
                        "counts": counts,
                        "build_info": state.get("build_info"),
                        "tool": build_result,
                        "readout_tool": readout_result,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"episode build failed: {exc}"})
        if path == "/api/wizard/builder/profile/save":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                profile_id = str(data.get("profile_id") or "").strip() or f"profile_{_utc_stamp().lower()}"
                profile_path = (BUILDER_PROFILES_ROOT / f"{profile_id}.json").resolve()
                existing_profile: dict[str, Any] = {}
                if profile_path.exists():
                    try:
                        existing_profile = _load_json_file(profile_path)
                    except Exception:
                        existing_profile = {}

                entities_entries = _normalize_builder_profile_entries(
                    (data.get("entities") if "entities" in data else data.get("entity_include")),
                    default_kind="entity",
                    allow_aliases=True,
                )
                if isinstance(data.get("entities"), dict):
                    entities_entries = _normalize_builder_profile_entries(
                        data.get("entities"),
                        default_kind="entity",
                        allow_aliases=True,
                    )
                elif isinstance(data.get("entities"), list):
                    entities_entries = _normalize_builder_profile_entries(
                        data.get("entities"),
                        default_kind="entity",
                        allow_aliases=True,
                    )
                elif not entities_entries:
                    entities_entries = _normalize_builder_profile_entries(
                        {
                            "include": data.get("entity_include"),
                            "exclude": data.get("entity_exclude"),
                            "aliases": data.get("entity_aliases"),
                        },
                        default_kind="entity",
                        allow_aliases=True,
                    )

                cue_entries = _normalize_builder_profile_entries(
                    (data.get("cue_phrases") if "cue_phrases" in data else data.get("cues")),
                    default_kind="cue_phrase",
                    allow_aliases=False,
                )
                if not cue_entries:
                    cue_entries = _normalize_builder_profile_entries(
                        {
                            "include": data.get("cue_include"),
                            "exclude": data.get("cue_exclude"),
                        },
                        default_kind="cue_phrase",
                        allow_aliases=False,
                    )

                domain_entries = _normalize_builder_domain_rules(data.get("domain_rules"))
                if not domain_entries:
                    domain_entries = _normalize_builder_domain_rules(
                        {
                            "include": data.get("domain_include"),
                            "exclude": data.get("domain_exclude"),
                        }
                    )

                entities_legacy = _profile_entries_to_legacy(entities_entries, include_aliases=True)
                cues_legacy = _profile_entries_to_legacy(cue_entries, include_aliases=False)
                domain_rules_legacy = _profile_entries_to_legacy(domain_entries, include_aliases=False)
                profile = {
                    "schema": "numquamoblita.builder_profile.v1",
                    "profile_id": profile_id,
                    "name": str(data.get("name") or profile_id).strip()[:120],
                    "created_at": str(existing_profile.get("created_at") or _utc_iso()),
                    "updated_at": _utc_iso(),
                    "entities": entities_entries,
                    "cue_phrases": cue_entries,
                    "domain_rules": domain_entries,
                    "entities_legacy": entities_legacy,
                    "cues_legacy": cues_legacy,
                    "domain_rules_legacy": domain_rules_legacy,
                }
                _write_json_file(profile_path, profile)
                state["builder_profile_id"] = profile_id
                state.setdefault("artifacts", {})["builder_profile_path"] = str(profile_path)
                _mark_wizard_stage(state, stage="builder_curation", note=f"Saved builder profile {profile_id}.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "profile_id": profile_id,
                        "profile_path": str(profile_path),
                        "profile": profile,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"profile save failed: {exc}"})
        if path == "/api/wizard/review/update":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                _wizard_require(state, action="review_update")
                episode_id = str(data.get("episode_id") or "").strip()
                if not episode_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "episode_id is required"})
                decision = str(data.get("decision") or "pending").strip().lower()
                if decision not in {"pending", "approved", "edited", "rejected"}:
                    return _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {"error": "decision must be one of: pending, approved, edited, rejected"},
                    )
                review_decisions = state.get("review_decisions")
                if not isinstance(review_decisions, dict):
                    review_decisions = {}
                review_decisions[episode_id] = {
                    "decision": decision,
                    "title": str(data.get("title") or "").strip(),
                    "summary": str(data.get("summary") or "").strip(),
                    "actors": _normalize_string_list(data.get("actors"), max_items=32, max_chars=64),
                    "topic_tags": _normalize_string_list(data.get("topic_tags"), max_items=32, max_chars=64),
                    "cue_terms": _normalize_string_list(data.get("cue_terms"), max_items=48, max_chars=72),
                }
                state["review_decisions"] = review_decisions
                _wizard_sync_review_state(state)
                if str((state.get("published_set") or {}).get("version_id") or "").strip():
                    _snapshot_published_pointers(state, reason="pre_review_change_publish_update")
                    _wizard_reset_downstream_state(state, from_stage="review")
                    _wizard_reset_to_stage(
                        state,
                        stage="review",
                        note="Review changed after publish; cleared published set, verify result, and activation state.",
                    )
                _mark_wizard_stage(state, stage="review", note=f"Updated review decision for {episode_id}.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "episode_id": episode_id,
                        "decision": review_decisions[episode_id],
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"review update failed: {exc}"})
        if path in {"/api/wizard/review/compile", "/api/wizard/publish/run"}:
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                reviewer = str(data.get("reviewer") or "runtime_ui").strip() or "runtime_ui"
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                _wizard_require(state, action="publish_run")
                source_path = _resolve_episode_cards_path(self.server.runtime, state)
                if source_path is None:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "no episode cards available to compile"})
                source_payload = _load_episode_cards_payload(source_path)
                review_state = _wizard_sync_review_state(state, source_payload=source_payload, source_cards_path=source_path)
                review_decisions = state.get("review_decisions")
                if not isinstance(review_decisions, dict):
                    review_decisions = {}
                build_info = dict(state.get("build_info") or {})
                compiled = _compile_reviewed_payload(
                    source_payload=source_payload,
                    review_decisions=review_decisions,
                    reviewer=reviewer,
                    source_cards_path=source_path,
                    store_fingerprint=str(build_info.get("store_fingerprint") or ""),
                    schema_version=build_info.get("schema_version"),
                    build_id=str(build_info.get("build_id") or ""),
                )
                reviewed_path = (EPISODES_ROOT / "episode_cards.reviewed.json").resolve()
                stamp_path = (EPISODES_ROOT / f"episode_cards.reviewed_{_utc_stamp()}.json").resolve()
                backup_path = _write_payload_with_backup(reviewed_path, compiled, reason="wizard_review_compile")
                _write_json_file(stamp_path, compiled)
                state["last_compiled_reviewed_path"] = str(reviewed_path)
                _snapshot_published_pointers(state, reason="pre_review_compile_publish_update")
                state["published_pointers"] = {
                    "store_path": str(state.get("store_path") or (state.get("store_validation") or {}).get("path") or ""),
                    "episodes_path": str(reviewed_path),
                }
                version_id = _wizard_publish_version_id(
                    build_id=str(build_info.get("build_id") or ""),
                    store_fingerprint=str(build_info.get("store_fingerprint") or ""),
                    published_path=reviewed_path,
                )
                state["published_set"] = {
                    "version_id": version_id,
                    "episodes_path": str(reviewed_path),
                    "snapshot_path": str(stamp_path),
                    "store_fingerprint": str(build_info.get("store_fingerprint") or ""),
                    "schema_version": build_info.get("schema_version"),
                    "build_id": str(build_info.get("build_id") or ""),
                    "episode_count": int(compiled.get("episode_count") or 0),
                    "review_counts": dict(compiled.get("review_counts") or {}),
                    "status": "published",
                    "published_at": _utc_iso(),
                }
                state.setdefault("artifacts", {})["last_compiled_reviewed_snapshot"] = str(stamp_path)
                state["review_state"] = review_state
                state["verify"] = {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False}
                state["activation"] = _wizard_empty_activation_state()
                _mark_wizard_stage(state, stage="publish", note="Published reviewed episode set.")
                _wizard_transition(state, stage="verify", note="Published reviewed set. Ready for verification.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "version_id": version_id,
                        "reviewed_path": str(reviewed_path),
                        "reviewed_snapshot_path": str(stamp_path),
                        "backup_path": backup_path,
                        "episode_count": int(compiled.get("episode_count") or 0),
                        "review_counts": dict(compiled.get("review_counts") or {}),
                        "published_set": state.get("published_set"),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"publish failed: {exc}"})
        if path == "/api/wizard/verify/run":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                _wizard_require(state, action="verify_run")
                verify_payload = _wizard_verify_payload(self.server, state)
                state["verify"] = verify_payload
                _mark_wizard_stage(state, stage="verify", note=f"Verification status: {verify_payload['status']}.")
                if str(verify_payload.get("status") or "") == "Safe":
                    _wizard_transition(state, stage="activate", note="Verification passed. Ready to activate.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        **verify_payload,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"verify failed: {exc}"})
        if path == "/api/wizard/restore-last-published":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                history = state.get("published_history")
                if not isinstance(history, list) or not history:
                    return _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {"error": "no prior published snapshot available to restore"},
                    )
                snapshot = history.pop()
                pointers_raw = snapshot.get("published_pointers") if isinstance(snapshot, dict) else {}
                pointers = pointers_raw if isinstance(pointers_raw, dict) else {}
                published_set_raw = snapshot.get("published_set") if isinstance(snapshot, dict) else {}
                published_set = dict(published_set_raw) if isinstance(published_set_raw, dict) else {}
                restored_store = str(pointers.get("store_path") or "").strip()
                restored_episodes = str(pointers.get("episodes_path") or "").strip()

                state["published_history"] = history
                state["published_pointers"] = {
                    "store_path": restored_store,
                    "episodes_path": restored_episodes,
                }
                if restored_store:
                    state["store_path"] = restored_store
                if restored_episodes:
                    episode_path = Path(restored_episodes).expanduser().resolve()
                    if not episode_path.exists():
                        return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"published set not found: {episode_path}"})
                    state["last_compiled_reviewed_path"] = str(episode_path)
                state["published_set"] = published_set if published_set else {
                    "version_id": "",
                    "episodes_path": restored_episodes,
                    "snapshot_path": "",
                    "store_fingerprint": "",
                    "schema_version": None,
                    "build_id": "",
                    "episode_count": 0,
                    "review_counts": {},
                    "status": "published" if restored_episodes else "unpublished",
                    "published_at": "",
                }
                state["verify"] = {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False}
                state["activation"] = _wizard_empty_activation_state()
                _mark_wizard_stage(state, stage="publish", note="Restored last published set.")
                _wizard_transition(state, stage="verify", note="Published set restored. Verification is required again.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "restored_snapshot": snapshot if isinstance(snapshot, dict) else {},
                        "published_pointers": state.get("published_pointers"),
                        "published_set": state.get("published_set"),
                        "remaining_snapshots": len(history),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"restore failed: {exc}"})
        if path in {"/api/wizard/go-live", "/api/wizard/activate/direct"}:
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                _wizard_require(state, action="activate_direct")
                store_validation = dict(state.get("store_validation") or {})
                store_path = Path(str(store_validation.get("path") or state.get("store_path") or "").strip()).expanduser().resolve()
                episodes_path = Path(str((state.get("published_set") or {}).get("episodes_path") or state.get("last_compiled_reviewed_path") or "").strip()).expanduser().resolve()
                activation_result = _wizard_activate_direct(
                    self.server,
                    store_path=store_path,
                    episodes_path=episodes_path,
                    store_validation=store_validation,
                    artifact_mode="published",
                    build_id=str((state.get("published_set") or {}).get("build_id") or ""),
                )
                provider_config = _provider_model_config(self.server)
                state["activation"] = {
                    **_wizard_empty_activation_state(),
                    "direct": {
                        "status": str(activation_result.get("status") or "running"),
                        "checked_at": str((activation_result.get("binding") or {}).get("checked_at") or _utc_iso()),
                        "store_fingerprint": str((activation_result.get("binding") or {}).get("store_fingerprint") or ""),
                        "episodes_path": str((activation_result.get("binding") or {}).get("episodes_path") or ""),
                        "runtime_url": str(activation_result.get("runtime_url") or ""),
                        "issues": [],
                        "lock": dict(activation_result.get("lock") or {}),
                    },
                    "mcp": dict((state.get("activation") or {}).get("mcp") or _wizard_empty_activation_state()["mcp"]),
                    "developer_mode": bool((state.get("activation") or {}).get("developer_mode")),
                    "draft_override": {},
                }
                _mark_wizard_stage(state, stage="activate", note="Direct runtime activation succeeded.")
                _wizard_transition(state, stage="operate", note="Runtime is live and ready to operate.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "runtime_url": activation_result.get("runtime_url"),
                        "model_name": self.server.runtime.model_name,
                        "adapters": self.server.adapter_registry.names(),
                        "provider_config": provider_config,
                        "config_entrypoint": "/api/runtime/provider/config",
                        "published_pointers": state.get("published_pointers"),
                        "activation": state.get("activation"),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"go-live failed: {exc}"})
        if path == "/api/wizard/activate/developer-mode":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                enabled = bool(data.get("enabled"))
                activation = dict(state.get("activation") or _wizard_empty_activation_state())
                draft_override = dict(activation.get("draft_override") or {})
                if not enabled and bool(draft_override.get("active")):
                    return _json_response(
                        self,
                        HTTPStatus.CONFLICT,
                        {"error": "draft runtime is active; reactivate the published set before turning developer mode off"},
                    )
                activation["developer_mode"] = enabled
                state["activation"] = activation
                _save_wizard_state(state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "run_id": state.get("run_id"), "activation": activation})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"developer mode update failed: {exc}"})
        if path == "/api/wizard/activate/direct/draft":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                activation = dict(state.get("activation") or _wizard_empty_activation_state())
                if not bool(activation.get("developer_mode")):
                    return _json_response(self, HTTPStatus.CONFLICT, {"error": "enable developer mode before draft activation"})
                verify_status = str((state.get("verify") or {}).get("status") or "Unknown")
                if verify_status == "Blocked":
                    return _json_response(self, HTTPStatus.CONFLICT, {"error": "blocked verification state cannot use draft activation"})
                acknowledgement = bool(data.get("acknowledged"))
                reason = str(data.get("reason") or "").strip()
                operator = str(data.get("operator") or "local_developer").strip() or "local_developer"
                if not acknowledgement or not reason:
                    return _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {"error": "draft activation requires acknowledgement=true and a non-empty reason"},
                    )
                build_info = dict(state.get("build_info") or {})
                draft_path_raw = str(build_info.get("draft_path") or state.get("last_built_episode_draft_path") or "").strip()
                if not draft_path_raw:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "build draft episode cards before draft activation"})
                draft_path = Path(draft_path_raw).expanduser().resolve()
                _wizard_validate_episode_artifact(draft_path, mode="draft")
                store_validation = dict(state.get("store_validation") or {})
                if not bool(store_validation.get("is_valid")):
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "a valid MNO store is required before draft activation"})
                store_path = Path(str(store_validation.get("path") or state.get("store_path") or "").strip()).expanduser().resolve()
                activation_result = _wizard_activate_direct(
                    self.server,
                    store_path=store_path,
                    episodes_path=draft_path,
                    store_validation=store_validation,
                    artifact_mode="draft",
                    build_id=str(build_info.get("build_id") or ""),
                )
                provider_config = _provider_model_config(self.server)
                draft_override = {
                    "active": True,
                    "label": "Unreviewed draft",
                    "acknowledged": True,
                    "reason": reason,
                    "operator": operator,
                    "target": "direct",
                    "timestamp": _utc_iso(),
                    "store_fingerprint": str(store_validation.get("store_fingerprint") or ""),
                    "build_id": str(build_info.get("build_id") or ""),
                    "episodes_path": str(draft_path),
                }
                state["activation"] = {
                    **_wizard_empty_activation_state(),
                    "direct": {
                        "status": "draft_active",
                        "checked_at": str((activation_result.get("binding") or {}).get("checked_at") or _utc_iso()),
                        "store_fingerprint": str((activation_result.get("binding") or {}).get("store_fingerprint") or ""),
                        "episodes_path": str((activation_result.get("binding") or {}).get("episodes_path") or ""),
                        "runtime_url": str(activation_result.get("runtime_url") or ""),
                        "issues": ["Unreviewed draft is active. This is unsafe local developer mode."],
                        "lock": dict(activation_result.get("lock") or {}),
                        "artifact_mode": "draft",
                        "build_id": str(build_info.get("build_id") or ""),
                    },
                    "mcp": dict((state.get("activation") or {}).get("mcp") or _wizard_empty_activation_state()["mcp"]),
                    "developer_mode": True,
                    "draft_override": draft_override,
                }
                _mark_wizard_stage(state, stage="activate", note="Developer-only draft runtime activation succeeded.")
                _wizard_transition(state, stage="operate", note="Draft runtime is live for local developer testing.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "runtime_url": activation_result.get("runtime_url"),
                        "model_name": self.server.runtime.model_name,
                        "adapters": self.server.adapter_registry.names(),
                        "provider_config": provider_config,
                        "config_entrypoint": "/api/runtime/provider/config",
                        "activation": state.get("activation"),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"draft activation failed: {exc}"})
        if path == "/api/wizard/activate/status":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                activation = _wizard_activation_status(self.server, state)
                panel = _wizard_connector_panel()
                mcp_payload = _wizard_mcp_payload(state, data)
                preview = panel.build_preview(mcp_payload)
                targets_payload = _wizard_mcp_targets_payload(panel, mcp_payload)
                target_statuses: dict[str, Any] = {}
                for target, target_payload in targets_payload.items():
                    existing = _wizard_mcp_existing_entry(
                        target,
                        {"config_path": target_payload.get("config_path"), "server_name": mcp_payload.get("server_name")},
                        target_payload.get("entry") or {},
                    )
                    target_status = _wizard_mcp_status_for_target(
                        state,
                        target=target,
                        existing=existing,
                        expected_entry=target_payload.get("entry") or {},
                    )
                    target_status["install_context"] = target_payload.get("install_context")
                    target_status["display"] = target_payload.get("display")
                    target_statuses[target] = target_status
                issues = [issue for row in target_statuses.values() for issue in list(row.get("issues") or []) if str(issue).strip()]
                activation["mcp"] = {
                    "status": "installed"
                    if any(str(row.get("status") or "") == "installed" for row in target_statuses.values())
                    else "not_installed",
                    "checked_at": _utc_iso(),
                    "issues": issues,
                    "owned_targets": dict((state.get("activation") or {}).get("mcp", {}).get("owned_targets") or {}),
                    "targets": target_statuses,
                    "preview": {
                        "server_name": preview.get("server_name"),
                        "claude_code_scope": preview.get("claude_code_scope"),
                        "default_role": preview.get("default_role"),
                        "compat_mode": preview.get("compat_mode"),
                    },
                }
                state["activation"] = activation
                _save_wizard_state(state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "run_id": state.get("run_id"), "activation": activation})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"activation status failed: {exc}"})
        if path == "/api/wizard/remap/status":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                remap = _wizard_remap_status_payload(state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "run_id": state.get("run_id"), "remap": remap, "verify": state.get("verify")})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"remap status failed: {exc}"})
        if path == "/api/wizard/remap/apply":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                target = str(data.get("target") or "").strip()
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                replacement_path_raw = str(data.get("replacement_path") or "").strip()
                if replacement_path_raw:
                    replacement_path = Path(replacement_path_raw).expanduser().resolve()
                else:
                    file_name = Path(str(data.get("file_name") or "").strip()).name
                    content_b64 = str(data.get("content_base64") or "").strip()
                    if not file_name or not content_b64:
                        return _json_response(
                            self,
                            HTTPStatus.BAD_REQUEST,
                            {"error": "replacement_path or file_name + content_base64 are required"},
                        )
                    upload_root = RUNTIME_ROOT / "wizard_uploads" / str(state.get("run_id") or "unknown") / "remap" / target
                    upload_root.mkdir(parents=True, exist_ok=True)
                    replacement_path = (upload_root / file_name).resolve()
                    if upload_root.resolve() not in replacement_path.parents and replacement_path != upload_root.resolve():
                        return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid remap upload target"})
                    decoded = base64.b64decode(content_b64.encode("ascii"), validate=True)
                    replacement_path.write_bytes(decoded)
                result = _wizard_apply_remap_to_state(state, target=target, replacement_path=replacement_path)
                state["verify"] = {"status": "Unknown", "checks": [], "actionable_links": [], "checked_at": "", "remap_required": False}
                _mark_wizard_stage(state, stage=str(state.get("current_stage") or "import"), note=f"Remapped {target} artifact.")
                _save_wizard_state(state)
                remap = _wizard_remap_status_payload(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "run_id": state.get("run_id"), "result": result, "remap": remap, "state": state},
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"remap apply failed: {exc}"})
        if path == "/api/wizard/reset":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                stage = str(data.get("stage") or "").strip()
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                _wizard_reset_state_to_stage(state, stage=stage, reason=f"Reset stale wizard state to {stage}.")
                _save_wizard_state(state)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "run_id": state.get("run_id"), "state": state})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"wizard reset failed: {exc}"})
        if path == "/api/wizard/activate/direct/cleanup":
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                cleanup = _wizard_repair_or_clear_runtime_lock(self.server, state)
                activation = _wizard_activation_status(self.server, state)
                state["activation"] = activation
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "run_id": state.get("run_id"), "cleanup": cleanup, "activation": activation},
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"direct runtime cleanup failed: {exc}"})
        if path in {"/api/wizard/activate/mcp/install", "/api/wizard/activate/mcp/remove", "/api/wizard/activate/mcp/export"}:
            try:
                from tools.mcp_connector_common import load_json_object

                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                target = str(data.get("target") or "claude_code").strip().lower() or "claude_code"
                if target not in {"claude_code", "claude_desktop"} and path != "/api/wizard/activate/mcp/export":
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "target must be claude_code or claude_desktop"})
                state = _load_or_create_wizard_state(run_id=run_id, start_new=False)
                panel = _wizard_connector_panel()
                mcp_payload = _wizard_mcp_payload(state, data)
                preview = panel.build_preview(mcp_payload)
                targets_payload = _wizard_mcp_targets_payload(panel, mcp_payload)

                if path == "/api/wizard/activate/mcp/export":
                    _wizard_require(state, action="mcp_export")
                    export_path_raw = str(data.get("export_path") or "").strip()
                    if export_path_raw:
                        export_result = panel.save_export_bundle(mcp_payload, export_path=export_path_raw)
                    else:
                        export_result = panel.export_bundle(mcp_payload)
                    activation = _wizard_activation_status(self.server, state)
                    activation["mcp"] = {
                        "status": "export_ready",
                        "checked_at": _utc_iso(),
                        "issues": [],
                        "owned_targets": dict((state.get("activation") or {}).get("mcp", {}).get("owned_targets") or {}),
                    }
                    state["activation"] = activation
                    _save_wizard_state(state)
                    return _json_response(
                        self,
                        HTTPStatus.OK,
                        {"ok": True, "run_id": state.get("run_id"), "export": export_result, "activation": activation},
                    )

                target_payload = dict(targets_payload.get(target) or {})
                expected_entry = dict(target_payload.get("entry") or {})
                existing = _wizard_mcp_existing_entry(
                    target,
                    {"config_path": target_payload.get("config_path"), "server_name": mcp_payload.get("server_name")},
                    expected_entry,
                )
                target_status = _wizard_mcp_status_for_target(state, target=target, existing=existing, expected_entry=expected_entry)
                activation = _wizard_activation_status(self.server, state)
                mcp_state = dict(activation.get("mcp") or {})
                owned_targets = dict(mcp_state.get("owned_targets") or {})

                if path == "/api/wizard/activate/mcp/remove":
                    if target_status.get("ownership") not in {"app_owned", "adopted"}:
                        return _json_response(
                            self,
                            HTTPStatus.CONFLICT,
                            {
                                "error": "cannot remove an MCP entry that is not app-owned or explicitly adopted",
                                "target": target,
                                "ownership": target_status,
                            },
                        )
                    remove_result = panel.remove_claude_code(mcp_payload) if target == "claude_code" else panel.remove_claude_desktop(mcp_payload)
                    owned_targets.pop(target, None)
                    activation["mcp"] = {
                        "status": "not_installed",
                        "checked_at": _utc_iso(),
                        "issues": [],
                        "owned_targets": owned_targets,
                    }
                    state["activation"] = activation
                    _save_wizard_state(state)
                    return _json_response(
                        self,
                        HTTPStatus.OK,
                        {"ok": True, "run_id": state.get("run_id"), "target": target, "result": remove_result, "activation": activation},
                    )

                _wizard_require(state, action="activate_mcp")
                ownership_action = str(data.get("ownership_action") or "").strip().lower()
                existing_entry = dict(existing.get("existing_entry") or {})
                if target_status.get("ownership") == "unknown":
                    if ownership_action == "cancel" or not ownership_action:
                        return _json_response(
                            self,
                            HTTPStatus.CONFLICT,
                            {"error": "unknown mcp ownership", "target": target, "ownership": target_status},
                        )
                    if ownership_action == "adopt":
                        if existing_entry != expected_entry:
                            return _json_response(
                                self,
                                HTTPStatus.CONFLICT,
                                {
                                    "error": "cannot adopt an incompatible MCP entry; use overwrite or cancel",
                                    "target": target,
                                    "ownership": target_status,
                                },
                            )
                        handshake = _wizard_mcp_handshake(existing_entry)
                        owned_targets[target] = str(mcp_payload.get("server_name") or "")
                        activation["mcp"] = {
                            "status": "installed",
                            "checked_at": _utc_iso(),
                            "issues": [],
                            "owned_targets": owned_targets,
                            "last_handshake": handshake,
                        }
                        state["activation"] = activation
                        _save_wizard_state(state)
                        return _json_response(
                            self,
                            HTTPStatus.OK,
                            {"ok": True, "run_id": state.get("run_id"), "target": target, "ownership": "adopted", "handshake": handshake, "activation": activation},
                        )
                    if ownership_action != "overwrite":
                        return _json_response(
                            self,
                            HTTPStatus.BAD_REQUEST,
                            {"error": "ownership_action must be adopt, overwrite, or cancel", "target": target},
                        )

                config_path_raw = str(target_payload.get("config_path") or "").strip()
                config_path = Path(config_path_raw).expanduser().resolve() if config_path_raw else None
                previous_config = load_json_object(config_path) if config_path is not None and config_path.exists() else {}
                install_result = panel.install_claude_code(mcp_payload) if target == "claude_code" else panel.install_claude_desktop(mcp_payload)
                try:
                    handshake = _wizard_mcp_handshake(expected_entry)
                except Exception as exc:
                    if config_path is not None:
                        _wizard_restore_json_config(config_path, previous_config)
                    raise RuntimeError(f"MCP handshake failed after install and the config was rolled back: {exc}") from exc
                owned_targets[target] = str(mcp_payload.get("server_name") or "")
                activation["mcp"] = {
                    "status": "installed",
                    "checked_at": _utc_iso(),
                    "issues": [],
                    "owned_targets": owned_targets,
                    "last_handshake": handshake,
                }
                state["activation"] = activation
                _mark_wizard_stage(state, stage="activate", note=f"MCP activation installed for {target}.")
                _wizard_transition(state, stage="operate", note="Activation targets are ready to use.")
                _save_wizard_state(state)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "run_id": state.get("run_id"),
                        "target": target,
                        "result": install_result,
                        "handshake": handshake,
                        "activation": activation,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"mcp activation failed: {exc}"})
        if path == "/api/runtime/writeback/policy":
            try:
                data = _read_json(self)
                enabled = _to_bool(data.get("enabled"), default=bool(self.server.writeback_policy.get("enabled")))
                mode = str(data.get("mode") or self.server.writeback_policy.get("mode") or "proposal_only").strip().lower()
                auto_apply = _to_bool(data.get("auto_apply"), default=False)
                self.server.writeback_policy = {
                    "enabled": bool(enabled),
                    "mode": "proposal_only" if mode != "proposal_only" else mode,
                    "auto_apply": bool(auto_apply),
                    "updated_at": _utc_iso(),
                }
                return _json_response(self, HTTPStatus.OK, {"ok": True, "policy": dict(self.server.writeback_policy)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"writeback policy update failed: {exc}"})
        if path == "/api/runtime/health/export":
            try:
                health_payload = _runtime_health(self.server)
                export_path = _export_diagnostics(self.server, health_payload=health_payload)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "status": health_payload.get("status"),
                        "export_path": str(export_path),
                        "checks": health_payload.get("checks"),
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"diagnostics export failed: {exc}"})
        if path == "/api/memory/proposals/create-delete":
            if not bool(self.server.writeback_policy.get("enabled")):
                return _json_response(self, HTTPStatus.FORBIDDEN, {"error": "writeback policy is disabled"})
            queue = self.server.review_queue
            if queue is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "proposal queue not available"})
            try:
                data = _read_json(self)
                atom_id = str(data.get("target_atom_id") or "").strip()
                reason_code = str(data.get("reason_code") or "manual_disable").strip() or "manual_disable"
                retention_days = int(data.get("retention_days") or queue.default_retention_days)
                proposal = queue.propose_delete(
                    target_atom_id=atom_id,
                    reason_code=reason_code,
                    retention_days=retention_days,
                    metadata={"source": "runtime_ui"},
                )
                return _json_response(self, HTTPStatus.OK, {"ok": True, "proposal": _serialize_proposal(proposal)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"create-delete proposal failed: {exc}"})
        if path == "/api/memory/proposals/create-edit":
            if not bool(self.server.writeback_policy.get("enabled")):
                return _json_response(self, HTTPStatus.FORBIDDEN, {"error": "writeback policy is disabled"})
            queue = self.server.review_queue
            if queue is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "proposal queue not available"})
            try:
                data = _read_json(self)
                atom_id = str(data.get("target_atom_id") or "").strip()
                canonical_text = str(data.get("canonical_text") or "").strip()
                if not atom_id or not canonical_text:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "target_atom_id and canonical_text are required"})
                atom = self.server.runtime.retriever.store.get_atom(atom_id)
                refs: list[SourceRef] = []
                for ref in list(getattr(atom, "source_refs", []) or []):
                    source_id = str(getattr(ref, "source_id", "") or "").strip()
                    if not source_id:
                        continue
                    refs.append(
                        SourceRef(
                            source_id=source_id,
                            message_id=str(getattr(ref, "message_id", "") or "").strip() or None,
                            timestamp=getattr(ref, "timestamp", None),
                            span_start=getattr(ref, "span_start", None),
                            span_end=getattr(ref, "span_end", None),
                        )
                    )
                if not refs:
                    refs = [SourceRef(source_id="runtime_ui", message_id=atom_id)]
                atom_type_raw = str(data.get("atom_type") or getattr(getattr(atom, "atom_type", None), "value", "episode")).strip().lower()
                try:
                    atom_type = AtomType(atom_type_raw)
                except Exception:
                    atom_type = AtomType.EPISODE
                candidate = CandidateAtom(
                    candidate_id=f"cand_{_utc_stamp().lower()}",
                    atom_type=atom_type,
                    canonical_text=canonical_text,
                    source_refs=refs,
                    entities=_normalize_string_list(data.get("entities") or getattr(atom, "entities", []), max_items=32, max_chars=64),
                    topics=_normalize_string_list(data.get("topics") or getattr(atom, "topics", []), max_items=32, max_chars=64),
                    confidence=float(data.get("confidence") if data.get("confidence") is not None else getattr(atom, "confidence", 0.7)),
                    salience=float(data.get("salience") if data.get("salience") is not None else getattr(atom, "salience", 0.6)),
                )
                reason_code = str(data.get("reason_code") or "manual_edit").strip() or "manual_edit"
                proposal = queue.propose_edit(
                    target_atom_id=atom_id,
                    replacement_candidate=candidate,
                    reason_code=reason_code,
                    metadata={"source": "runtime_ui"},
                )
                return _json_response(self, HTTPStatus.OK, {"ok": True, "proposal": _serialize_proposal(proposal)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"create-edit proposal failed: {exc}"})
        if path == "/api/memory/episodes/undo-last":
            try:
                restored = _undo_last_episode_edit()
                reload_info = _reload_runtime_episode_index(self.server.runtime, Path(str(restored.get("restored_path") or "")))
                return _json_response(self, HTTPStatus.OK, {"ok": True, "undo": restored, "reload": reload_info})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"undo failed: {exc}"})
        if path.startswith("/api/memory/episodes/"):
            tail = unquote(path[len("/api/memory/episodes/") :]).strip("/")
            if not tail or "/" not in tail:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "episode path must be /api/memory/episodes/<episode_id>/<action>"})
            episode_id, action = tail.rsplit("/", 1)
            episode_id = episode_id.strip()
            action = action.strip().lower()
            if action not in {"disable", "enable", "edit"}:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "unsupported episode action"})
            try:
                data = _read_json(self)
                run_id = str(data.get("run_id") or "").strip() or None
                wizard_state = None
                if run_id:
                    try:
                        wizard_state = _load_wizard_state(run_id)
                    except Exception:
                        wizard_state = None
                source_path = _resolve_episode_cards_path(self.server.runtime, wizard_state)
                if source_path is None:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "episode cards source is unavailable"})
                payload = _load_episode_cards_payload(source_path)
                cards = list(payload.get("cards") or [])
                updated = None
                for idx, row in enumerate(cards):
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("episode_id") or "").strip() != episode_id:
                        continue
                    card = _normalize_episode_card(row)
                    if action == "disable":
                        card["promotion_status"] = "disabled"
                        card["promotion_reason"] = str(data.get("reason") or "disabled_from_ui").strip() or "disabled_from_ui"
                    elif action == "enable":
                        card["promotion_status"] = "approved"
                        card["promotion_reason"] = str(data.get("reason") or "enabled_from_ui").strip() or "enabled_from_ui"
                    elif action == "edit":
                        title = str(data.get("title") or "").strip()
                        summary = str(data.get("summary") or "").strip()
                        actors = _normalize_string_list(data.get("actors"), max_items=32, max_chars=64)
                        topics = _normalize_string_list(data.get("topic_tags"), max_items=32, max_chars=64)
                        cue_terms = _normalize_string_list(data.get("cue_terms"), max_items=48, max_chars=72)
                        if title:
                            card["title"] = title
                        if summary:
                            card["summary"] = summary
                        if actors:
                            card["actors"] = actors
                            card["entities"] = list(actors)
                        if topics:
                            card["topic_tags"] = topics
                            card["topics"] = list(topics)
                        if cue_terms:
                            card["cue_terms"] = cue_terms
                        card["promotion_status"] = str(card.get("promotion_status") or "approved").strip().lower() or "approved"
                    cards[idx] = card
                    updated = card
                    break
                if updated is None:
                    return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "episode_id not found"})
                payload["cards"] = cards
                payload["generated_at"] = _utc_iso()
                backup_path = _write_payload_with_backup(source_path, payload, reason=f"episode_{action}")
                reload_info = _reload_runtime_episode_index(self.server.runtime, source_path)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "action": action,
                        "episode": updated,
                        "source_cards_path": str(source_path),
                        "backup_path": backup_path,
                        "reload": reload_info,
                    },
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"episode update failed: {exc}"})
        if path.startswith("/api/memory/atoms/") and path.endswith("/conflict"):
            atom_id = unquote(path[len("/api/memory/atoms/") : -len("/conflict")]).strip("/")
            if not atom_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "atom_id is required"})
            try:
                data = _read_json(self)
                other_atom_id = str(data.get("other_atom_id") or "").strip()
                reason = str(data.get("reason") or "manual_conflict_from_ui").strip() or "manual_conflict_from_ui"
                if not other_atom_id:
                    return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "other_atom_id is required"})
                edge = self.server.runtime.retriever.store.mark_conflict(atom_id, other_atom_id, reason=reason)
                snapshot_info = _rebuild_snapshot(self.server.runtime)
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "conflict": {
                            "left_atom_id": edge.left_atom_id,
                            "right_atom_id": edge.right_atom_id,
                            "created_at": edge.created_at.isoformat(),
                            "reason": edge.reason,
                        },
                        **snapshot_info,
                    },
                )
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "atom not found"})
            except Exception as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"conflict mark failed: {exc}"})
        if path == "/api/chat/route-preview":
            try:
                data = _read_json(self)
                message = str(data.get("message") or "").strip()
                high_risk = bool(data.get("high_risk"))
                memory_preference = str(data.get("memory_preference") or "").strip() or None
                session_id = str(data.get("session_id") or "").strip() or None
                preview = self.server.runtime.preview_route(
                    message,
                    high_risk=high_risk,
                    memory_preference=memory_preference,
                    session_id=session_id,
                )
                return _json_response(self, HTTPStatus.OK, {"ok": True, "preview": preview})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"route preview failed: {exc}"})
        if path == "/api/chat/context-package":
            try:
                data = _read_json(self)
                message = str(data.get("message") or "").strip()
                high_risk = bool(data.get("high_risk"))
                memory_preference = str(data.get("memory_preference") or "").strip() or None
                session_id = str(data.get("session_id") or "").strip() or None
                package_version = str(data.get("package_version") or "").strip() or None
                retrieval_query = str(data.get("retrieval_query") or "").strip() or None
                retrieval_override = _retrieval_override_from_payload(
                    data,
                    default_invoker="engine.runtime.server.api.chat.context_package",
                    default_scope="runtime_api_context_package",
                    default_reason="api_requested_override",
                    default_auth_context="runtime_api_context_package",
                )
                render_citations_raw = data.get("render_citations")
                render_citations = bool(render_citations_raw) if isinstance(render_citations_raw, bool) else None
                package = self.server.runtime.build_context_package(
                    message,
                    high_risk=high_risk,
                    memory_preference=memory_preference,
                    session_id=session_id,
                    package_version=package_version,
                    retrieval_query=retrieval_query,
                    retrieval_override=retrieval_override,
                    render_citations=render_citations,
                )
                return _json_response(self, HTTPStatus.OK, {"ok": True, "package": package})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("context package failed")
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "context package failed"})
        if path == "/api/chat":
            try:
                data = _read_json(self)
                message = str(data.get("message") or "").strip()
                high_risk = bool(data.get("high_risk"))
                retrieval_query = str(data.get("retrieval_query") or "").strip() or None
                retrieval_override = _retrieval_override_from_payload(
                    data,
                    default_invoker="engine.runtime.server.api.chat",
                    default_scope="runtime_api_chat",
                    default_reason="api_requested_override",
                    default_auth_context="runtime_api_chat",
                )
                memory_preference = str(data.get("memory_preference") or "").strip() or None
                session_id = str(data.get("session_id") or "").strip() or None
                trace = self.server.runtime.handle_turn(
                    message,
                    high_risk=high_risk,
                    retrieval_query=retrieval_query,
                    retrieval_override=retrieval_override,
                    memory_preference=memory_preference,
                    session_id=session_id,
                )
                return _json_response(self, HTTPStatus.OK, {"ok": True, "turn": self.server.runtime.trace_to_dict(trace)})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"chat failed: {exc}"})
        if path == "/api/chat/session/start":
            try:
                data = _read_json(self)
                label = str(data.get("label") or "").strip() or None
                session = self.server.runtime.start_session(label=label)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "session": session})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"session start failed: {exc}"})
        if path.startswith("/api/chat/session/") and path.endswith("/label"):
            session_id = unquote(path[len("/api/chat/session/") : -len("/label")]).strip("/")
            if not session_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "session_id is required"})
            try:
                data = _read_json(self)
                label = str(data.get("label") or "").strip()
                session = self.server.runtime.rename_session(session_id, label=label)
                return _json_response(self, HTTPStatus.OK, {"ok": True, "session": session})
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"session label update failed: {exc}"})
        if path.startswith("/api/chat/session/") and path.endswith("/turn"):
            session_id = unquote(path[len("/api/chat/session/") : -len("/turn")]).strip("/")
            if not session_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "session_id is required"})
            try:
                data = _read_json(self)
                message = str(data.get("message") or "").strip()
                high_risk = bool(data.get("high_risk"))
                retrieval_query = str(data.get("retrieval_query") or "").strip() or None
                retrieval_override = _retrieval_override_from_payload(
                    data,
                    default_invoker="engine.runtime.server.api.chat.session_turn",
                    default_scope="runtime_api_session_turn",
                    default_reason="api_requested_override",
                    default_auth_context="runtime_api_session_turn",
                )
                memory_preference = str(data.get("memory_preference") or "").strip() or None
                trace = self.server.runtime.handle_turn(
                    message,
                    high_risk=high_risk,
                    retrieval_query=retrieval_query,
                    retrieval_override=retrieval_override,
                    memory_preference=memory_preference,
                    session_id=session_id,
                )
                return _json_response(self, HTTPStatus.OK, {"ok": True, "turn": self.server.runtime.trace_to_dict(trace)})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"session turn failed: {exc}"})

        if path.startswith("/api/adapters/") and path.endswith("/chat"):
            adapter_name = unquote(path[len("/api/adapters/") : -len("/chat")]).strip("/")
            adapter = self.server.adapter_registry.get(adapter_name)
            if adapter is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": f"unknown adapter: {adapter_name}"})
            try:
                payload = _read_json(self)
                adapted = adapter.normalize_request(payload)
                session_id = _session_id_from_metadata(adapted.metadata)
                retrieval_override = _retrieval_override_from_payload(
                    adapted.metadata,
                    default_invoker=f"engine.runtime.server.adapter.{adapter_name}.chat",
                    default_scope="adapter_chat",
                    default_reason="adapter_requested_override",
                    default_auth_context="adapter_chat",
                )
                trace = self.server.runtime.handle_turn(
                    adapted.message,
                    high_risk=adapted.high_risk,
                    retrieval_query=str(adapted.metadata.get("retrieval_query") or "").strip() or None,
                    retrieval_override=retrieval_override,
                    memory_preference=str(adapted.metadata.get("memory_preference") or "").strip() or None,
                    session_id=session_id,
                )
                return _json_response(self, HTTPStatus.OK, adapter.format_response(trace, self.server.runtime))
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"adapter chat failed: {exc}"})
        if path.startswith("/api/adapters/") and path.endswith("/context-package"):
            adapter_name = unquote(path[len("/api/adapters/") : -len("/context-package")]).strip("/")
            adapter = self.server.adapter_registry.get(adapter_name)
            if adapter is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": f"unknown adapter: {adapter_name}"})
            try:
                payload = _read_json(self)
                adapted = adapter.normalize_request(payload)
                session_id = _session_id_from_metadata(adapted.metadata)
                package_version = str(adapted.metadata.get("package_version") or "").strip() or None
                retrieval_query = str(adapted.metadata.get("retrieval_query") or "").strip() or None
                retrieval_override = _retrieval_override_from_payload(
                    adapted.metadata,
                    default_invoker=f"engine.runtime.server.adapter.{adapter_name}.context_package",
                    default_scope="adapter_context_package",
                    default_reason="adapter_requested_override",
                    default_auth_context="adapter_context_package",
                )
                render_citations = adapted.metadata.get("render_citations")
                render_citations_flag = bool(render_citations) if isinstance(render_citations, bool) else None
                package = self.server.runtime.build_context_package(
                    adapted.message,
                    high_risk=adapted.high_risk,
                    memory_preference=str(adapted.metadata.get("memory_preference") or "").strip() or None,
                    session_id=session_id,
                    package_version=package_version,
                    retrieval_query=retrieval_query,
                    retrieval_override=retrieval_override,
                    render_citations=render_citations_flag,
                )
                formatter = getattr(adapter, "format_context_package", None)
                if callable(formatter):
                    return _json_response(self, HTTPStatus.OK, formatter(package, self.server.runtime))
                return _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "adapter": adapter_name, "context_package": package},
                )
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                LOGGER.exception("adapter context package failed")
                return _json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "adapter context package failed"},
                )
        if path.startswith("/api/memory/proposals/") and path.endswith("/approve"):
            queue = self.server.review_queue
            if queue is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "proposal queue not available"})
            proposal_id = unquote(path[len("/api/memory/proposals/") : -len("/approve")]).strip("/")
            if not proposal_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "proposal_id is required"})
            try:
                data = _read_json(self)
                reviewer = str(data.get("reviewer") or "runtime_operator").strip() or "runtime_operator"
                apply_now = bool(data.get("apply", False))
                queue.approve(proposal_id, reviewer=reviewer)
                proposal = queue.apply(proposal_id) if apply_now else _proposal_by_id(queue, proposal_id)
                snapshot_info = _rebuild_snapshot(self.server.runtime) if apply_now else {}
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "proposal not found"})
            except PermissionError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"approve failed: {exc}"})
            return _json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "proposal": _serialize_proposal(proposal), **snapshot_info},
            )
        if path.startswith("/api/memory/proposals/") and path.endswith("/reject"):
            queue = self.server.review_queue
            if queue is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "proposal queue not available"})
            proposal_id = unquote(path[len("/api/memory/proposals/") : -len("/reject")]).strip("/")
            if not proposal_id:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "proposal_id is required"})
            try:
                data = _read_json(self)
                reviewer = str(data.get("reviewer") or "runtime_operator").strip() or "runtime_operator"
                reason = str(data.get("reason") or "").strip() or "rejected_by_operator"
                proposal = queue.reject(proposal_id, reviewer=reviewer, reason=reason)
            except KeyError:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "proposal not found"})
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"reject failed: {exc}"})
            return _json_response(self, HTTPStatus.OK, {"ok": True, "proposal": _serialize_proposal(proposal)})
        if path == "/api/memory/decay/recompute":
            try:
                data = _read_json(self)
                apply_promotions = bool(data.get("apply_promotions", False))
                policy = default_config().decay
                store = self.server.runtime.retriever.store
                consolidator = Consolidator(store, policy=policy)
                registry = SharedLanguageRegistry(store)
                shared_keys = registry.list_keys()
                summary = consolidator.run_with_snapshot(
                    self.server.runtime.continuity_store,
                    builder=ContinuityBuilder(),
                    shared_language_keys=shared_keys,
                    apply_promotions=apply_promotions,
                )
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"decay recompute failed: {exc}"})
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "summary": {
                        "decayed_atoms": int(summary.decayed_atoms),
                        "archived_atoms": int(summary.archived_atoms),
                        "applied_promotions": int(summary.applied_promotions),
                        "promoted_candidates": len(summary.promoted_candidates),
                        "snapshot_revision": summary.snapshot_revision,
                        "snapshot_stats": dict(summary.snapshot_stats),
                    },
                },
            )

        return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _serve_file(self, filename: str, content_type: str) -> None:
        path = (UI_ROOT / filename).resolve()
        if not path.exists() or not path.is_file() or path.parent != UI_ROOT:
            return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "asset missing"})
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RuntimeHTTPServer(ThreadingHTTPServer):
    """HTTP server wrapper that carries runtime and adapter dependencies."""
    daemon_threads = True
    block_on_close = False

    def __init__(
        self,
        server_address: tuple[str, int],
        runtime: RuntimeSession,
        adapter_registry: AdapterRegistry | None = None,
        review_queue: MutationReviewQueue | None = None,
    ):
        super().__init__(server_address, RuntimeRequestHandler)
        self.runtime = runtime
        self.adapter_registry = adapter_registry or build_default_registry()
        self.review_queue = review_queue
        self.integration_auth = IntegrationAuthManager.from_env()
        self.integration_degrade_tracker = IntegrationDegradeTracker(
            manual_override=str(os.getenv("NO_INTEGRATION_DEGRADE_OVERRIDE", "")).strip().lower()
            in {"1", "true", "yes"}
        )
        self.integration_started_monotonic = float(time.monotonic())
        self.integration_idempotency: dict[tuple[str, str], dict[str, Any]] = {}
        self.integration_idempotency_lock = threading.Lock()
        self.integration_audit_lock = threading.Lock()
        self.integration_audit_path = str((RUNTIME_ROOT / "reports" / "integration_audit.jsonl").resolve())
        self.writeback_policy: dict[str, Any] = {
            "enabled": False,
            "mode": "proposal_only",
            "auto_apply": False,
            "updated_at": _utc_iso(),
        }
        self.latest_wizard_run_id = _latest_wizard_run_id() or ""
        self.exploration_preferences_lock = threading.Lock()
        self.exploration_preferences: dict[str, dict[str, Any]] = {}
        self.quicknote_lock = threading.Lock()
        self.quicknote_config = _quicknote_config_from_env()
        self.quicknote_policy = _quicknote_policy_from_env()
        self.quicknote_state_path = str(Path(str(QUICKNOTE_STATE_PATH)).resolve())
        self.quicknote_state = _quicknote_load_state(
            Path(self.quicknote_state_path),
            max_history_notes=max(100, int(self.quicknote_config.get("max_history_notes") or 8_000)),
        )
        self.quicknote_state["store_signature"] = _quicknote_store_signature(self.runtime)
        _quicknote_persist_state(self)
        self.methodology_lock = threading.Lock()
        self.methodology_state_path = str(Path(str(METHODOLOGY_STATE_PATH)).resolve())
        Path(self.methodology_state_path).parent.mkdir(parents=True, exist_ok=True)
        self.methodology_state = load_methodology_state(Path(self.methodology_state_path))
        persist_methodology_state(Path(self.methodology_state_path), self.methodology_state)
        self.active_runtime_lock: dict[str, Any] = {}
        self.active_runtime_binding = {
            "store_path": "",
            "store_fingerprint": _wizard_runtime_store_fingerprint(runtime),
            "episodes_path": str(getattr(runtime, "episode_cards_path", "") or ""),
            "checked_at": _utc_iso(),
        }
def start_runtime_server(
    runtime: RuntimeSession,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    adapter_registry: AdapterRegistry | None = None,
    review_queue: MutationReviewQueue | None = None,
    daemon: bool = False,
) -> tuple[RuntimeHTTPServer, threading.Thread]:
    server = RuntimeHTTPServer((host, port), runtime, adapter_registry=adapter_registry, review_queue=review_queue)
    thread = threading.Thread(target=server.serve_forever, daemon=bool(daemon), name="runtime-http")
    thread.start()
    return server, thread


def stop_runtime_server(
    server: RuntimeHTTPServer,
    thread: threading.Thread | None,
    *,
    runtime: RuntimeSession | None = None,
    join_timeout_s: float = 2.0,
) -> None:
    """Best-effort runtime server shutdown that avoids orphaned server threads."""

    _wizard_release_runtime_lock(server)
    server.shutdown()
    server.server_close()
    if thread is not None and thread.is_alive():
        thread.join(timeout=max(0.1, float(join_timeout_s)))
    if runtime is not None:
        runtime.close(wait_timeout_s=max(0.1, float(join_timeout_s)))
