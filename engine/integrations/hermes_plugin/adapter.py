"""Stdlib-only, fail-open Hermes automatic turn adapter.

This module intentionally knows only the integration-v1 HTTP contract.  It
never imports MNO's runtime, persists transcript material, or retries an
observation whose delivery outcome could be ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import unicodedata
import uuid


_SCHEMA = "mno.hermes-adapter.v1"
_CONTEXT_FORMAT = "mno.agent_context.v2"
_MAX_TEXT = 4096
_MAX_CONTEXT = 8192
_MAX_TOKENS = 4096
_MAX_HTTP_RESPONSE_BYTES = 262144
_OPERATIONS = frozenset({"health.get", "capabilities.get", "context.build", "memory.observe"})
_PATHS = {
    "health.get": ("GET", "/api/integration/v1/health"),
    "capabilities.get": ("GET", "/api/integration/v1/capabilities"),
    "context.build": ("POST", "/api/integration/v1/context/build"),
    "memory.observe": ("POST", "/api/integration/v1/memory/observe"),
}


def normalize_text(value: Any) -> str | None:
    """Accept text only, replace invalid scalars, NFC/LF/trim, then bound."""
    if not isinstance(value, str):
        return None
    value = "".join("\ufffd" if 0xD800 <= ord(char) <= 0xDFFF else char for char in value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", value).strip()[:_MAX_TEXT]


def _opaque_id(prefix: str, *parts: str) -> str:
    raw = "\0".join(parts).encode("utf-8", "surrogatepass")
    return f"{prefix}{hashlib.sha256(raw).hexdigest()}"


def _valid_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        if parsed.path not in ("", "/") or parsed.port is None or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        if host != "localhost":
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                return None
            if not address.is_loopback or (address.version == 4 and not host.startswith("127.")):
                return None
        return f"http://{parsed.netloc}"
    except (TypeError, ValueError):
        return None


def _bounded_int(data: Mapping[str, Any], key: str, default: int, low: int, high: int) -> int | None:
    value = data.get(key, default)
    if isinstance(value, bool):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


@dataclass(frozen=True)
class AdapterConfig:
    runtime_base_url: str
    token_env: str
    context_timeout_ms: int
    context_response_max_characters: int
    observe_timeout_ms: int
    observe_queue_max_items: int
    observe_queue_max_age_seconds: int
    pending_max_items: int
    pending_ttl_seconds: int
    capability_cache_ttl_seconds: int

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "AdapterConfig | None":
        if value.get("schema_version") != _SCHEMA or value.get("enabled") is not True:
            return None
        url = _valid_url(value.get("runtime_base_url"))
        token_env = value.get("token_env")
        if (
            not url
            or not isinstance(token_env, str)
            or not token_env
            or token_env == "NO_INTEGRATION_REVIEW_APPLY_TOKEN"
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env) is None
        ):
            return None
        ints = {
            "context_timeout_ms": _bounded_int(value, "context_timeout_ms", 2500, 100, 2500),
            "context_response_max_characters": _bounded_int(value, "context_response_max_characters", 8192, 1, 8192),
            "observe_timeout_ms": _bounded_int(value, "observe_timeout_ms", 5500, 100, 5500),
            "observe_queue_max_items": _bounded_int(value, "observe_queue_max_items", 16, 1, 16),
            "observe_queue_max_age_seconds": _bounded_int(value, "observe_queue_max_age_seconds", 60, 1, 60),
            "pending_max_items": _bounded_int(value, "pending_max_items", 256, 1, 256),
            "pending_ttl_seconds": _bounded_int(value, "pending_ttl_seconds", 600, 1, 600),
            "capability_cache_ttl_seconds": _bounded_int(value, "capability_cache_ttl_seconds", 30, 1, 30),
        }
        if any(item is None for item in ints.values()):
            return None
        return cls(url, token_env, **ints)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PendingTurn:
    session_id: str
    raw_session_digest: str
    run_id: str
    turn_id_digest: str
    user_text: str
    source_registration: Mapping[str, Any]
    retrieval_receipt: Mapping[str, Any]
    expires_at: float


@dataclass(frozen=True)
class ObservationSnapshot:
    session_id: str
    run_id: str
    user_text: str
    assistant_text: str
    source_registration: Mapping[str, Any]
    retrieval_receipt: Mapping[str, Any]
    created_at: float
    expires_at: float


class HermesMemoryAdapter:
    """One in-memory adapter instance; every public hook is fail-open."""

    def __init__(self, config: AdapterConfig | Mapping[str, Any] | None, *, token: str = "", transport: Callable[..., Any] | None = None, start_worker: bool = True):
        self.config = config if isinstance(config, AdapterConfig) else AdapterConfig.parse(config or {})
        self._token = token
        self._transport = transport or self._http_request
        self._pending: dict[tuple[str, str], PendingTurn] = {}
        self._tombstones: dict[tuple[str, str], float] = {}
        self._state_lock = threading.Lock()
        max_queue = self.config.observe_queue_max_items if self.config else 1
        self._queue: queue.Queue[ObservationSnapshot] = queue.Queue(maxsize=max_queue)
        # Queue mutation is a separate transaction from pending-map mutation.
        # Every producer, consumer, and session filter takes this lock, but it
        # is always released before network I/O.
        self._queue_lock = threading.Lock()
        self._capabilities: tuple[float, dict[str, bool]] | None = None
        self._diagnostics: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        if self.config and self._token and start_worker:
            self._worker = threading.Thread(target=self._run_worker, name="mno-hermes-observe", daemon=True)
            self._worker.start()

    @classmethod
    def disabled(cls) -> "HermesMemoryAdapter":
        return cls(None, start_worker=False)

    def close(self) -> None:
        """Stop the daemon worker without flushing or retrying queued work."""
        self._stop.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=0.25)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, environ: Mapping[str, str] | None = None) -> "HermesMemoryAdapter | None":
        config = AdapterConfig.parse(value)
        if not config:
            return None
        token = (environ or os.environ).get(config.token_env, "")
        return cls(config, token=token) if isinstance(token, str) and token else None

    @classmethod
    def from_path(cls, path: Path) -> "HermesMemoryAdapter | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, Mapping):
                return None
            config = AdapterConfig.parse(data)
            if not config:
                return None
            token = os.environ.get(config.token_env, "")
            if not token:
                token_path = path.with_name("adapter-token")
                if token_path.is_file() and not token_path.is_symlink():
                    if os.name != "nt" and token_path.stat().st_mode & 0o077:
                        return None
                    credential = json.loads(token_path.read_text(encoding="utf-8"))
                    if (
                        not isinstance(credential, Mapping)
                        or credential.get("schema_version")
                        != "mno.hermes-credential.v1"
                    ):
                        return None
                    token = str(credential.get("token") or "").strip()
            return cls(config, token=token) if token else None
        except Exception:
            return None

    def _record(self, operation: str, reason: str, *, status: str = "") -> None:
        # Deliberately metadata-only: never insert body, token, context, handles, or exception text.
        self._diagnostics.append({"at": time.time(), "operation": operation, "reason": reason[:48], "status": status[:24]})
        del self._diagnostics[:-64]

    @staticmethod
    def _eligible_pre(kwargs: Mapping[str, Any]) -> bool:
        text = normalize_text(kwargs.get("user_message"))
        if not text or not isinstance(kwargs.get("turn_id"), str) or not kwargs.get("turn_id", "").strip():
            return False
        if not isinstance(kwargs.get("session_id"), str) or not isinstance(kwargs.get("platform"), str):
            return False
        if kwargs.get("is_subagent") or kwargs.get("parent_task_id") or kwargs.get("background"):
            return False
        thread_name = str(kwargs.get("thread_name") or threading.current_thread().name).strip().lower()
        if thread_name == "bg-review":
            return False
        platform = str(kwargs.get("platform") or "").strip().lower()
        if platform in {"subagent", "cron", "curator"}:
            return False
        origin = str(kwargs.get("origin") or kwargs.get("origin_type") or "").strip().lower()
        if origin in {"subagent", "cron", "curator", "gateway", "internal", "background-review", "gateway-dispatch"}:
            return False
        # Pinned Hermes CLI has no sender metadata. Gateway human turns carry
        # sender_id in pre_llm_call; post relies on the pending state created here.
        sender_id = str(kwargs.get("sender_id") or "").strip()
        return origin in {"human", "user"} or (not origin and (platform == "cli" or bool(sender_id)))

    @staticmethod
    def _eligible_post(kwargs: Mapping[str, Any]) -> bool:
        if not normalize_text(kwargs.get("assistant_response")):
            return False
        if not isinstance(kwargs.get("turn_id"), str) or not kwargs.get("turn_id", "").strip():
            return False
        if not isinstance(kwargs.get("session_id"), str) or not isinstance(kwargs.get("platform"), str):
            return False
        if kwargs.get("interrupted") or kwargs.get("failed") or kwargs.get("completed") is False:
            return False
        if str(kwargs.get("platform") or "").strip().lower() in {"subagent", "cron", "curator"}:
            return False
        return str(kwargs.get("thread_name") or threading.current_thread().name).strip().lower() != "bg-review"

    @staticmethod
    def _handles(data: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
        source = data.get("source_registration")
        receipt = data.get("retrieval_receipt")
        if not isinstance(source, Mapping) or not isinstance(receipt, Mapping):
            return None
        now_utc = datetime.now(timezone.utc)
        for row in (source, receipt):
            handle = row.get("handle")
            expires = row.get("expires_at_utc")
            if not isinstance(handle, str) or not handle.strip() or not isinstance(expires, str):
                return None
            try:
                parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            except (OverflowError, ValueError):
                return None
            if parsed.tzinfo is None or parsed.astimezone(timezone.utc) <= now_utc:
                return None
        return dict(source), dict(receipt)

    def _capability_flags(self, deadline: float) -> dict[str, bool] | None:
        if not self.config:
            return None
        cached = self._capabilities
        if cached and cached[0] > time.monotonic():
            return cached[1]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        raw = self._transport("capabilities.get", {}, remaining, f"req_{uuid.uuid4().hex}")
        rows = raw.get("operations") if isinstance(raw, Mapping) else None
        if not isinstance(rows, list):
            return None
        flags = {str(row.get("name")): bool(row.get("available")) and bool(row.get("authorized")) for row in rows if isinstance(row, Mapping)}
        self._capabilities = (time.monotonic() + self.config.capability_cache_ttl_seconds, flags)
        return flags

    @staticmethod
    def _context_wrapper(data: Mapping[str, Any], maximum: int) -> str | None:
        raw_context = data.get("agent_context")
        if data.get("agent_context_format") != _CONTEXT_FORMAT or not isinstance(raw_context, str):
            return None
        try:
            context = json.loads(raw_context)
        except (TypeError, ValueError):
            return None
        if not isinstance(context, Mapping) or context.get("schema_version") != _CONTEXT_FORMAT:
            return None
        tokens = data.get("agent_context_tokens")
        if isinstance(tokens, bool) or not isinstance(tokens, (int, float)) or tokens < 0 or tokens > _MAX_TOKENS:
            return None
        try:
            compact = json.dumps(dict(context), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            return None
        safe = compact.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        if len(safe) > maximum:
            return None
        wrapper = f"<MNO_MEMORY_CONTEXT_V1>\n{{\"format\":\"{_CONTEXT_FORMAT}\",\"context\":{safe}}}\n</MNO_MEMORY_CONTEXT_V1>"
        return wrapper

    def pre_llm_call(self, **kwargs: Any) -> dict[str, str] | None:
        try:
            if not self.config or not self._token or not self._eligible_pre(kwargs):
                return None
            user_text = normalize_text(kwargs.get("user_message"))
            if not user_text:
                return None
            platform, raw_session, raw_turn = str(kwargs["platform"]), str(kwargs["session_id"]), str(kwargs["turn_id"])
            session_id = _opaque_id("hermes_session_", platform, raw_session)
            run_id = _opaque_id("hermes_turn_", platform, raw_session, raw_turn)
            deadline = time.monotonic() + (self.config.context_timeout_ms / 1000.0)
            flags = self._capability_flags(deadline)
            if not flags or not flags.get("context.build"):
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            data = self._transport(
                "context.build",
                {"session_id": session_id, "run_id": run_id, "message": user_text},
                remaining,
                f"req_{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:32]}",
            )
            if not isinstance(data, Mapping):
                return None
            wrapper = self._context_wrapper(data, self.config.context_response_max_characters)
            if wrapper is None:
                self._capabilities = None
            if flags.get("memory.observe"):
                handles = self._handles(data)
                if handles:
                    now = time.monotonic()
                    expiry = now + self.config.pending_ttl_seconds
                    for handle in handles:
                        raw_expiry = handle.get("expires_at_utc")
                        if isinstance(raw_expiry, str):
                            try:
                                parsed_expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
                                if parsed_expiry.tzinfo is None:
                                    continue
                                utc_expiry = parsed_expiry.astimezone(timezone.utc)
                                expiry = min(expiry, now + max(0.0, utc_expiry.timestamp() - time.time()))
                            except (OverflowError, ValueError):
                                pass
                    key = (session_id, hashlib.sha256(raw_turn.encode("utf-8", "surrogatepass")).hexdigest())
                    with self._state_lock:
                        self._purge_locked(now)
                        if len(self._pending) < self.config.pending_max_items:
                            self._pending[key] = PendingTurn(session_id, hashlib.sha256(raw_session.encode()).hexdigest(), run_id, key[1], user_text, *handles, expiry)
            return {"context": wrapper} if wrapper else None
        except Exception:
            self._record("context.build", "failed")
            self._capabilities = None
            return None

    def post_llm_call(self, **kwargs: Any) -> None:
        try:
            if not self.config or not self._eligible_post(kwargs):
                return None
            platform, raw_session, raw_turn = str(kwargs["platform"]), str(kwargs["session_id"]), str(kwargs["turn_id"])
            session_id = _opaque_id("hermes_session_", platform, raw_session)
            turn_digest = hashlib.sha256(raw_turn.encode("utf-8", "surrogatepass")).hexdigest()
            key = (session_id, turn_digest)
            now = time.monotonic()
            with self._state_lock:
                self._purge_locked(now)
                pending = self._pending.get(key)
                if pending is None or key in self._tombstones:
                    return None
                assistant = normalize_text(kwargs.get("assistant_response"))
                if not assistant:
                    return None
                snapshot = self._snapshot_from_values(pending.session_id, pending.run_id, pending.user_text, assistant, pending.source_registration, pending.retrieval_receipt, now, pending.expires_at)
                try:
                    with self._queue_lock:
                        self._queue.put_nowait(snapshot)
                except queue.Full:
                    self._record("memory.observe", "queue_full")
                    return None
                del self._pending[key]
                self._tombstones[key] = now + self.config.pending_ttl_seconds
            return None
        except Exception:
            self._record("memory.observe", "enqueue_failed")
            return None

    def _snapshot_from_values(self, session_id: str, run_id: str, user_text: str, assistant_text: str, source_registration: Mapping[str, Any], retrieval_receipt: Mapping[str, Any], created_at: float, expires_at: float) -> ObservationSnapshot:
        return ObservationSnapshot(session_id, run_id, user_text, assistant_text, dict(source_registration), dict(retrieval_receipt), created_at, expires_at)

    def _record_snapshot(self, snapshot: ObservationSnapshot) -> bool:
        try:
            with self._queue_lock:
                self._queue.put_nowait(snapshot)
            return True
        except queue.Full:
            return False

    def _queue_items(self) -> list[ObservationSnapshot]:
        with self._queue_lock:
            with self._queue.mutex:
                return list(self._queue.queue)

    def _purge_locked(self, now: float) -> None:
        self._pending = {key: value for key, value in self._pending.items() if value.expires_at > now}
        self._tombstones = {key: value for key, value in self._tombstones.items() if value > now}
        while len(self._tombstones) > (self.config.pending_max_items if self.config else 0):
            del self._tombstones[next(iter(self._tombstones))]

    def _drop_session_queue(self, session_id: str) -> None:
        # Filtering is one transaction shared with enqueue and dequeue. This
        # prevents reset/finalize for one session from dropping observations
        # concurrently added for another session.
        with self._queue_lock:
            retained = []
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item.session_id != session_id:
                    retained.append(item)
            for item in retained:
                self._queue.put_nowait(item)

    def _cleanup_turn(self, **kwargs: Any) -> None:
        """Drop unmatched state for one completed run_conversation call.

        Hermes v0.19.0 fires on_session_end later in the same turn finalizer,
        after post_llm_call and before run_conversation returns. A successfully
        queued observation must survive it.
        """
        try:
            if (
                not self.config
                or not isinstance(kwargs.get("session_id"), str)
                or not isinstance(kwargs.get("platform"), str)
                or not isinstance(kwargs.get("turn_id"), str)
            ):
                return
            session_id = _opaque_id("hermes_session_", str(kwargs["platform"]), str(kwargs["session_id"]))
            turn_digest = hashlib.sha256(str(kwargs["turn_id"]).encode("utf-8", "surrogatepass")).hexdigest()
            now = time.monotonic()
            with self._state_lock:
                self._purge_locked(now)
                self._pending.pop((session_id, turn_digest), None)
        except Exception:
            self._record("lifecycle", "turn_cleanup_failed")

    def _cleanup_session(self, **kwargs: Any) -> None:
        try:
            if not self.config or not isinstance(kwargs.get("session_id"), str) or not isinstance(kwargs.get("platform"), str):
                return
            session_id = _opaque_id("hermes_session_", str(kwargs["platform"]), str(kwargs["session_id"]))
            now = time.monotonic()
            with self._state_lock:
                self._purge_locked(now)
                self._pending = {key: value for key, value in self._pending.items() if value.session_id != session_id}
            self._drop_session_queue(session_id)
        except Exception:
            self._record("lifecycle", "cleanup_failed")

    def on_session_end(self, **kwargs: Any) -> None:
        self._cleanup_turn(**kwargs)

    def on_session_finalize(self, **kwargs: Any) -> None:
        self._cleanup_session(**kwargs)

    def on_session_reset(self, **kwargs: Any) -> None:
        self._cleanup_session(**kwargs)

    def _drain_one_for_test(self) -> None:
        with self._queue_lock:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
        self._send_once(item)

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            with self._queue_lock:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    item = None
            if item is None:
                self._stop.wait(0.05)
                continue
            self._send_once(item)

    def _send_once(self, item: ObservationSnapshot) -> None:
        if not self.config or time.monotonic() - item.created_at > self.config.observe_queue_max_age_seconds or item.expires_at <= time.monotonic():
            self._record("memory.observe", "expired")
            return
        payload = {
            "session_id": item.session_id,
            "run_id": item.run_id,
            "messages": [
                {"role": "user", "content": item.user_text, "source_registration": item.source_registration},
                {"role": "assistant", "content": item.assistant_text},
            ],
            "retrieval_receipt": item.retrieval_receipt,
            "remember_intent": "model_observed",
        }
        try:
            self._transport(
                "memory.observe",
                payload,
                self.config.observe_timeout_ms / 1000.0,
                f"req_{hashlib.sha256((item.run_id + ':observe').encode('utf-8')).hexdigest()[:32]}",
            )
        except Exception:
            self._record("memory.observe", "outcome_unknown")

    def _http_request(self, operation: str, payload: Mapping[str, Any], timeout: float, request_id: str) -> Mapping[str, Any]:
        if not self.config or operation not in _OPERATIONS:
            raise ValueError("operation")
        method, path = _PATHS[operation]
        if method == "GET":
            url = self.config.runtime_base_url + path + "?" + urlencode({"schema_version": "integration.v1", "request_id": request_id})
            body = None
        else:
            url = self.config.runtime_base_url + path
            body = json.dumps(
                {"schema_version": "integration.v1", "request_id": request_id, "session_id": str(payload.get("session_id") or ""), "run_id": str(payload.get("run_id") or ""), "data": {key: value for key, value in payload.items() if key not in {"session_id", "run_id"}}},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        request = Request(url, data=body, method=method, headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json", "X-Request-Id": request_id})
        class _NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
                return None

        # Empty proxy policy plus redirect denial keeps the scoped bearer token
        # on the validated loopback origin.
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=max(0.001, timeout)) as response:
            if response.geturl() != request.full_url:
                raise ValueError("redirect")
            raw = response.read(_MAX_HTTP_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_HTTP_RESPONSE_BYTES:
                raise ValueError("response_too_large")
            decoded = json.loads(raw.decode("utf-8"))
            return decoded.get("data", decoded) if isinstance(decoded, Mapping) else {}
