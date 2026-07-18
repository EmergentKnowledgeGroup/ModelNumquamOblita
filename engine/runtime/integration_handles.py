from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from ..memory.content_safety import assert_safe_content
from ..memory.sqlite_store import SqliteAtomStore


class IntegrationHandleError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalized_content_digest(value: str) -> str:
    assert_safe_content(value)
    normalized = " ".join(str(value or "").split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class IntegrationHandleSigner:
    """Stateless HMAC handles bound to one protected atom store."""

    def __init__(self, store: SqliteAtomStore, *, clock: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        identity = store.runtime_control_identity()
        self.store_uuid = identity["store_uuid"]
        self.key_id = identity["signing_key_id"]

    @staticmethod
    def _b64encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64decode(raw: str) -> bytes:
        try:
            padded = raw + "=" * ((4 - len(raw) % 4) % 4)
            return base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception as exc:
            raise IntegrationHandleError("HANDLE_INVALID") from exc

    def issue(self, kind: str, payload: dict[str, Any], *, ttl_seconds: int) -> dict[str, Any]:
        if not 60 <= int(ttl_seconds) <= 2_592_000:
            raise ValueError("ttl_seconds must be in 60..2592000")
        assert_safe_content(payload)
        now = self._clock().astimezone(timezone.utc)
        body = {
            "v": 1,
            "kind": str(kind),
            "store_uuid": self.store_uuid,
            "key_id": self.key_id,
            "issued_at_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(seconds=int(ttl_seconds))).isoformat(),
            "nonce": uuid4().hex,
            "payload": payload,
        }
        encoded = self._b64encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(self._store.runtime_signing_key(), encoded.encode("ascii"), hashlib.sha256).digest()
        return {
            "handle": f"mnoh1.{encoded}.{self._b64encode(signature)}",
            "kind": str(kind),
            "key_id": self.key_id,
            "issued_at_utc": body["issued_at_utc"],
            "expires_at_utc": body["expires_at_utc"],
            **payload,
        }

    def verify(self, handle: str, *, expected_kind: str) -> dict[str, Any]:
        parts = str(handle or "").split(".")
        if len(parts) != 3 or parts[0] != "mnoh1":
            raise IntegrationHandleError("HANDLE_INVALID")
        encoded, supplied_signature = parts[1], parts[2]
        expected_signature = hmac.new(
            self._store.runtime_signing_key(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(self._b64encode(expected_signature), supplied_signature):
            raise IntegrationHandleError("HANDLE_INVALID")
        try:
            body = json.loads(self._b64decode(encoded).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrationHandleError("HANDLE_INVALID") from exc
        if not isinstance(body, dict) or body.get("kind") != expected_kind:
            raise IntegrationHandleError("HANDLE_INVALID")
        if body.get("store_uuid") != self.store_uuid or body.get("key_id") != self.key_id:
            raise IntegrationHandleError("HANDLE_STORE_MISMATCH")
        try:
            expires = datetime.fromisoformat(str(body["expires_at_utc"])).astimezone(timezone.utc)
        except (KeyError, ValueError) as exc:
            raise IntegrationHandleError("HANDLE_INVALID") from exc
        if expires <= self._clock().astimezone(timezone.utc):
            raise IntegrationHandleError("HANDLE_EXPIRED")
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise IntegrationHandleError("HANDLE_INVALID")
        return dict(payload)


__all__ = [
    "IntegrationHandleError",
    "IntegrationHandleSigner",
    "normalized_content_digest",
]
