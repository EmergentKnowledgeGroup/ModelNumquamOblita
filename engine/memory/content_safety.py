"""Content safety primitives for provisional persistence.

The sanitizer deliberately runs before normalization or hashing.  It returns no
content-derived identifier for rejected material, which keeps a failed capture
from becoming an accidental secret side channel.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from typing import Any


class SecretDetectedError(ValueError):
    """Raised before unsafe content can reach persistence or a digest."""

    code = "LEGACY_SECRET_DETECTED"

    def __init__(self, reason: str = "secret_like_content") -> None:
        super().__init__(self.code)
        self.reason = reason


_SECRET_PATTERNS = (
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|bearer|password|secret)\s*[:=]\s*[^\s]{8,}", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
)


def _looks_secret(value: str) -> bool:
    text = str(value or "")
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return True
    # Catch obvious encoded credential fixtures without decoding arbitrary prose.
    compact = text.strip()
    if len(compact) >= 24 and re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        try:
            decoded = base64.b64decode(compact, validate=True).decode("utf-8", "ignore")
        except Exception:
            return False
        return any(pattern.search(decoded) for pattern in _SECRET_PATTERNS)
    return False


def assert_safe_content(value: Any) -> None:
    """Recursively reject secret-like material without exposing it."""

    if isinstance(value, str):
        if _looks_secret(value):
            raise SecretDetectedError()
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert_safe_content(str(key))
            assert_safe_content(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            assert_safe_content(item)


def scrub_content(value: Any, *, marker: str = "[REDACTED_LEGACY_SECRET]") -> Any:
    """Return a recursive safe replacement for explicit offline scrub mode."""

    if isinstance(value, str):
        return marker if _looks_secret(value) else value
    if isinstance(value, Mapping):
        return {str(key): scrub_content(item, marker=marker) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_content(item, marker=marker) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_content(item, marker=marker) for item in value)
    return value


__all__ = ["SecretDetectedError", "assert_safe_content", "scrub_content"]
