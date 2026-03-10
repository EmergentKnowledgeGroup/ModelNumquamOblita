from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Mapping, Protocol

from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

_CITATION_TOKEN_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}#[0-9A-Za-z_-]+",
    re.IGNORECASE,
)


def _validate_http_scheme(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"url scheme must be http or https, got: {scheme or '<empty>'}")
    if not str(parsed.hostname or "").strip():
        raise ValueError("url must include host")


@dataclass(slots=True)
class ChatResponse:
    text: str
    model: str
    provider: str
    latency_ms: float
    usage: dict[str, Any]
    raw: dict[str, Any]


class ChatProvider(Protocol):
    name: str

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_s: float = 60.0,
    ) -> ChatResponse:
        ...


@dataclass(slots=True)
class ChatProviderConfig:
    provider: str
    base_url: str = ""
    api_key: str = ""
    chat_path: str = ""
    models_path: str = ""


class MockProvider:
    name = "mock"

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_s: float = 60.0,
    ) -> ChatResponse:
        _ = temperature, max_tokens, timeout_s
        blob = "\n".join(str(item.get("content") or "") for item in list(messages or []) if isinstance(item, dict))
        verdict = "UNKNOWN"
        # NOTE: This is a regex, not a literal string match; keep escaping minimal.
        m = re.search(r"Service verdict \(follow this\):\s*([A-Za-z_]+)", blob)
        if m:
            verdict = str(m.group(1) or "UNKNOWN").strip().upper()

        citation = ""
        for line in blob.splitlines():
            if "Sources:" not in line:
                continue
            _, _, tail = line.partition("Sources:")
            tokens = [item.strip() for item in tail.split(",") if item.strip()]
            if tokens:
                citation = tokens[0]
                break
        if not citation:
            citation_tokens = _CITATION_TOKEN_RE.findall(blob)
            citation = citation_tokens[0] if citation_tokens else ""

        user = ""
        for msg in reversed(list(messages or [])):
            if str(msg.get("role") or "").strip().lower() == "user":
                user = str(msg.get("content") or "").strip()
                break

        evidence_summary = ""
        for line in blob.splitlines():
            stripped = str(line).strip()
            if not stripped:
                continue
            if re.match(r"^\d+\.\s+", stripped):
                evidence_summary = re.sub(r"^\d+\.\s+", "", stripped).strip()
                break
        if evidence_summary:
            evidence_summary = re.sub(r"^(?:User|Assistant|Memory):\s*", "", evidence_summary, flags=re.IGNORECASE).strip()
            evidence_summary = evidence_summary[:320].rstrip()

        if verdict == "NO_MEMORY":
            text = "Not much. How can I help?" if user else "Not much."
        elif verdict == "ABSTAIN":
            text = "I don't have that memory yet. Can you share one more detail so I can look it up?"
        elif verdict == "CLARIFY":
            text = "Which part do you mean, and what detail should I anchor on?"
        else:
            base = evidence_summary or "I remember discussing that."
            text = base
            if citation:
                text = f"{text} {citation}".strip()

        return ChatResponse(
            text=text,
            model=model,
            provider=self.name,
            latency_ms=0.0,
            usage={},
            raw={"mock": True, "messages": messages},
        )


class LMStudioProvider:
    name = "lmstudio"

    def __init__(self, *, base_url: str, chat_path: str = "/api/v1/chat") -> None:
        self.base_url = str(base_url or "").rstrip("/")
        if self.base_url:
            _validate_http_scheme(self.base_url)
        self.chat_path = chat_path if str(chat_path or "").strip() else "/api/v1/chat"

    @staticmethod
    def _messages_to_input(messages: list[dict[str, str]]) -> str:
        # LM Studio's /api/v1/chat currently expects an OpenAI-Responses-style
        # payload with an `input` field (string). We translate our chat-style
        # message list into a single prompt.
        #
        # This is intentionally simple: it is for regression evals and local
        # provider interoperability, not perfect prompt engineering.
        parts: list[str] = []
        for msg in list(messages or []):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower() or "user"
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            label = role.capitalize()
            parts.append(f"{label}:\n{content}".rstrip())
        # Add an assistant turn marker when the last turn was the user.
        if parts:
            last_role = str((list(messages or [])[-1] or {}).get("role") or "").strip().lower()
            if last_role in {"user", "tool"}:
                parts.append("Assistant:")
        return "\n\n".join(parts).strip()

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_s: float = 60.0,
    ) -> ChatResponse:
        url = f"{self.base_url}{self.chat_path}"
        prompt = self._messages_to_input(messages)
        payload: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        started = time.perf_counter()
        data = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib_request.urlopen(req, timeout=timeout_s) as resp:
                latency_ms = (time.perf_counter() - started) * 1000.0
                content_type = str(resp.headers.get("content-type", "")).lower()
                body = resp.read()
        except HTTPError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            body = exc.read() if hasattr(exc, "read") else b""
            detail = body.decode("utf-8", errors="replace")[:600].strip()
            raise RuntimeError(f"lmstudio_http_error status={exc.code} url={url} body={detail}") from exc
        except URLError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            raise RuntimeError(f"lmstudio_connection_error url={url} err={exc}") from exc

        if content_type.startswith("application/json"):
            raw = json.loads(body.decode("utf-8", errors="replace") or "{}")
        else:
            raw = {"text": body.decode("utf-8", errors="replace")}
        text = _extract_chat_text(raw)
        usage: Mapping[str, Any] | dict[str, Any] = {}
        if isinstance(raw, Mapping):
            usage = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else {}
            if not usage and isinstance(raw.get("stats"), Mapping):
                usage = raw.get("stats")  # LM Studio: tokens/time stats.
        return ChatResponse(
            text=str(text or "").strip(),
            model=model,
            provider=self.name,
            latency_ms=float(latency_ms),
            usage=dict(usage) if isinstance(usage, Mapping) else {},
            raw=dict(raw) if isinstance(raw, Mapping) else {"raw": raw},
        )


class OpenAIChatCompletionsProvider:
    name = "openai_chat_completions"

    def __init__(self, *, base_url: str, api_key: str, chat_path: str = "/v1/chat/completions") -> None:
        self.base_url = str(base_url or "").rstrip("/")
        if self.base_url:
            _validate_http_scheme(self.base_url)
        self.api_key = str(api_key or "").strip()
        self.chat_path = chat_path if str(chat_path or "").strip() else "/v1/chat/completions"

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_s: float = 60.0,
    ) -> ChatResponse:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for openai provider")
        url = f"{self.base_url}{self.chat_path}"
        payload: dict[str, Any] = {"model": model, "messages": list(messages or [])}
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = time.perf_counter()
        data = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(url, data=data, method="POST")
        for key, value in headers.items():
            req.add_header(str(key), str(value))
        try:
            with urllib_request.urlopen(req, timeout=timeout_s) as resp:
                latency_ms = (time.perf_counter() - started) * 1000.0
                body = resp.read()
        except HTTPError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            body = exc.read() if hasattr(exc, "read") else b""
            detail = body.decode("utf-8", errors="replace")[:600].strip()
            raise RuntimeError(f"openai_http_error status={exc.code} url={url} body={detail}") from exc
        except URLError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            raise RuntimeError(f"openai_connection_error url={url} err={exc}") from exc

        raw = json.loads(body.decode("utf-8", errors="replace") or "{}")
        text = _extract_chat_text(raw)
        usage = raw.get("usage") if isinstance(raw, Mapping) else {}
        return ChatResponse(
            text=str(text or "").strip(),
            model=model,
            provider=self.name,
            latency_ms=float(latency_ms),
            usage=dict(usage) if isinstance(usage, Mapping) else {},
            raw=dict(raw) if isinstance(raw, Mapping) else {"raw": raw},
        )


def _extract_chat_text(payload: Any) -> str:
    if isinstance(payload, Mapping):
        # LM Studio (/api/v1/chat) returns OpenAI-Responses-like payloads:
        # { output: [ {type: 'message', content: '...'}, ... ] }
        output = payload.get("output")
        if isinstance(output, list) and output:
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                if str(item.get("type") or "").strip().lower() != "message":
                    continue
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    return content
        # OpenAI-style
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice0 = choices[0]
            if isinstance(choice0, Mapping):
                message = choice0.get("message")
                if isinstance(message, Mapping):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                text = choice0.get("text")
                if isinstance(text, str):
                    return text
        # Some local servers return { content: "..."} or { message: "..." }
        for key in ("content", "message", "response", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    if isinstance(payload, str):
        return payload
    return ""


def build_provider(cfg: ChatProviderConfig) -> ChatProvider:
    name = str(cfg.provider or "").strip().lower()
    if name in {"mock", "test"}:
        return MockProvider()
    if name in {"lmstudio", "lm_studio"}:
        base_url = str(cfg.base_url or "http://127.0.0.1:1234").strip()
        return LMStudioProvider(base_url=base_url, chat_path=str(cfg.chat_path or "/api/v1/chat"))
    if name in {"openai", "openai_chat", "openai_chat_completions"}:
        base_url = str(cfg.base_url or "https://api.openai.com").strip()
        return OpenAIChatCompletionsProvider(
            base_url=base_url,
            api_key=str(cfg.api_key or "").strip(),
            chat_path=str(cfg.chat_path or "/v1/chat/completions"),
        )
    raise ValueError(f"unknown provider: {cfg.provider}")
