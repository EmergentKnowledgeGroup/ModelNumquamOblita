from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Any, Mapping, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .session import RuntimeSession, TurnTrace


@dataclass(slots=True)
class AdapterTurnInput:
    message: str
    high_risk: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(Protocol):
    name: str

    def normalize_request(self, payload: Mapping[str, Any]) -> AdapterTurnInput:
        ...

    def format_response(self, trace: TurnTrace, runtime: RuntimeSession) -> dict[str, Any]:
        ...

    def format_context_package(self, package: Mapping[str, Any], runtime: RuntimeSession) -> dict[str, Any]:
        ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RuntimeAdapter] = {}

    def register(self, adapter: RuntimeAdapter) -> None:
        key = str(getattr(adapter, "name", "") or "").strip().lower()
        if not key:
            raise ValueError("adapter name is required")
        self._adapters[key] = adapter

    def get(self, name: str) -> RuntimeAdapter | None:
        return self._adapters.get(str(name or "").strip().lower())

    def names(self) -> list[str]:
        return sorted(self._adapters.keys())


class ReferenceChatAdapter:
    """Canonical adapter contract for generic stateless chat payloads."""

    name = "reference"

    def normalize_request(self, payload: Mapping[str, Any]) -> AdapterTurnInput:
        message = str(payload.get("message") or "").strip()
        if not message:
            message = self._latest_user_message(payload.get("messages"))
        if not message:
            raise ValueError("message is required")

        high_risk = bool(payload.get("high_risk", False))
        metadata = payload.get("metadata")
        if metadata is None:
            metadata_dict: dict[str, Any] = {}
        elif isinstance(metadata, Mapping):
            metadata_dict = dict(metadata)
        else:
            raise ValueError("metadata must be an object when provided")

        return AdapterTurnInput(message=message, high_risk=high_risk, metadata=metadata_dict)

    def format_response(self, trace: TurnTrace, runtime: RuntimeSession) -> dict[str, Any]:
        return {
            "ok": True,
            "adapter": self.name,
            "turn": runtime.trace_to_dict(trace),
        }

    def format_context_package(self, package: Mapping[str, Any], runtime: RuntimeSession) -> dict[str, Any]:
        return {
            "ok": True,
            "adapter": self.name,
            "model": runtime.model_name,
            "context_package": dict(package),
        }

    def _latest_user_message(self, messages: Any) -> str:
        if not isinstance(messages, list):
            return ""
        for item in reversed(messages):
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role != "user":
                continue
            content = self._content_text(item.get("content"))
            if content:
                return content
        return ""

    def _content_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, Mapping):
            text = value.get("text")
            return str(text or "").strip()
        if isinstance(value, list):
            chunks: list[str] = []
            for item in value:
                if isinstance(item, str):
                    txt = item.strip()
                    if txt:
                        chunks.append(txt)
                    continue
                if isinstance(item, Mapping):
                    txt = str(item.get("text") or "").strip()
                    if txt:
                        chunks.append(txt)
            return "\n".join(chunks).strip()
        return ""


class OpenClawAdapter:
    """OpenClaw-compatible stateless chat envelope adapter."""

    name = "openclaw"

    def normalize_request(self, payload: Mapping[str, Any]) -> AdapterTurnInput:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ValueError("messages array is required")

        message = ReferenceChatAdapter()._latest_user_message(messages)
        if not message:
            raise ValueError("messages must include a user message with text content")

        metadata_raw = payload.get("metadata")
        metadata: dict[str, Any]
        if metadata_raw is None:
            metadata = {}
        elif isinstance(metadata_raw, Mapping):
            metadata = dict(metadata_raw)
        else:
            raise ValueError("metadata must be an object when provided")

        high_risk_raw = payload.get("high_risk")
        if isinstance(high_risk_raw, bool):
            high_risk = high_risk_raw
        else:
            risk_level = str(payload.get("risk_level") or "").strip().lower()
            high_risk = risk_level in {"high", "critical"}

        return AdapterTurnInput(message=message, high_risk=high_risk, metadata=metadata)

    def format_response(self, trace: TurnTrace, runtime: RuntimeSession) -> dict[str, Any]:
        trace_payload = runtime.trace_to_dict(trace)
        prompt_tokens = trace.telemetry.input_tokens
        completion_tokens = trace.telemetry.output_tokens
        return {
            "id": f"chatcmpl_{trace.turn_id}",
            "object": "chat.completion",
            "created": int(trace.timestamp.timestamp()),
            "model": runtime.model_name,
            "adapter": self.name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": trace.response_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "memory": {
                "session_id": trace.session_id,
                "decision": trace.decision,
                "citations": trace.citations,
                "pack_confidence": trace.pack_confidence,
                "retrieved_atom_ids": trace.retrieved_atom_ids,
                "memory_mode": trace.memory_mode,
                "memory_route": trace.memory_route,
                "route_reason": trace.route_reason,
                "route_reason_text": trace_payload.get("route_reason_text", ""),
                "retrieval_passes": trace.retrieval_passes,
                "retrieval_query_tokens": trace_payload.get("retrieval_query_tokens", 0),
                "retrieval_stop_reason": trace.retrieval_stop_reason,
                "short_term_hits": trace.short_term_hits,
                "memory_cards": trace.memory_cards,
                "budget": trace_payload.get("budget", {}),
                "writeback_event_id": trace.writeback_event_id,
            },
        }

    def format_context_package(self, package: Mapping[str, Any], runtime: RuntimeSession) -> dict[str, Any]:
        return {
            "id": f"ctxpkg_{uuid.uuid4().hex[:12]}",
            "object": "memory.context_package",
            "model": runtime.model_name,
            "adapter": self.name,
            "context_package": dict(package),
        }


class NanobotAdapter:
    """Nanobot-compatible retrieval/chat envelope adapter."""

    name = "nanobot"

    def normalize_request(self, payload: Mapping[str, Any]) -> AdapterTurnInput:
        query = str(payload.get("query") or "").strip()
        if not query:
            query = ReferenceChatAdapter()._latest_user_message(payload.get("messages"))
        if not query:
            raise ValueError("query is required")

        metadata_raw = payload.get("meta")
        if metadata_raw is None:
            metadata_raw = payload.get("metadata")
        metadata: dict[str, Any]
        if metadata_raw is None:
            metadata = {}
        elif isinstance(metadata_raw, Mapping):
            metadata = dict(metadata_raw)
        else:
            raise ValueError("meta/metadata must be an object when provided")

        safety = payload.get("safety")
        if isinstance(safety, Mapping):
            high_risk = bool(safety.get("high_risk", False))
        else:
            high_risk = bool(payload.get("high_risk", False))

        return AdapterTurnInput(message=query, high_risk=high_risk, metadata=metadata)

    def format_response(self, trace: TurnTrace, runtime: RuntimeSession) -> dict[str, Any]:
        trace_payload = runtime.trace_to_dict(trace)
        prompt_tokens = trace.telemetry.input_tokens
        completion_tokens = trace.telemetry.output_tokens
        return {
            "ok": True,
            "adapter": self.name,
            "trace_id": trace.turn_id,
            "answer": trace.response_text,
            "decision": trace.decision,
            "sources": trace.citations,
            "memory": {
                "session_id": trace.session_id,
                "decision": trace.decision,
                "citations": trace.citations,
                "pack_confidence": trace.pack_confidence,
                "confidence": trace.pack_confidence,
                "retrieved_atom_ids": trace.retrieved_atom_ids,
                "memory_mode": trace.memory_mode,
                "memory_route": trace.memory_route,
                "route_reason": trace.route_reason,
                "route_reason_text": trace_payload.get("route_reason_text", ""),
                "retrieval_passes": trace.retrieval_passes,
                "retrieval_query_tokens": trace_payload.get("retrieval_query_tokens", 0),
                "retrieval_stop_reason": trace.retrieval_stop_reason,
                "short_term_hits": trace.short_term_hits,
                "memory_cards": trace.memory_cards,
                "budget": trace_payload.get("budget", {}),
                "writeback_event_id": trace.writeback_event_id,
            },
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": runtime.model_name,
        }

    def format_context_package(self, package: Mapping[str, Any], runtime: RuntimeSession) -> dict[str, Any]:
        return {
            "ok": True,
            "adapter": self.name,
            "model": runtime.model_name,
            "context_package": dict(package),
        }


def build_default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(ReferenceChatAdapter())
    registry.register(OpenClawAdapter())
    registry.register(NanobotAdapter())
    return registry
