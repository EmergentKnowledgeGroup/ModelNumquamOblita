from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .model import SharedLanguageKey


class _SharedLanguageStore(Protocol):
    def upsert_shared_language_key(self, **kwargs: Any) -> dict[str, Any]: ...

    def list_shared_language_keys(self) -> list[dict[str, Any]]: ...


@dataclass(slots=True)
class SharedLanguageRegistry:
    """Provenance-bound shared language registry."""

    store: _SharedLanguageStore

    def register(
        self,
        *,
        phrase: str,
        atom_ids: list[str],
        aliases: list[str] | None = None,
        domains: list[str] | None = None,
        support_count: int = 1,
        weight: float = 0.8,
        confidence: float = 0.8,
        curated: bool = True,
        key_id: str | None = None,
    ) -> SharedLanguageKey:
        row = self.store.upsert_shared_language_key(
            phrase=phrase,
            atom_ids=atom_ids,
            aliases=aliases,
            domains=domains,
            support_count=support_count,
            weight=weight,
            confidence=confidence,
            curated=curated,
            key_id=key_id,
        )
        return _row_to_key(row)

    def list_keys(self) -> list[SharedLanguageKey]:
        return [_row_to_key(row) for row in self.store.list_shared_language_keys()]


def _row_to_key(row: dict[str, Any]) -> SharedLanguageKey:
    return SharedLanguageKey(
        key_id=str(row.get("key_id") or ""),
        phrase=str(row.get("phrase") or ""),
        atom_ids=[str(item) for item in row.get("atom_ids") or []],
        support_count=max(1, int(row.get("support_count") or 1)),
        weight=max(0.0, min(1.0, float(row.get("weight") or 0.0))),
        aliases=[str(item) for item in row.get("aliases") or []],
        domains=[str(item) for item in row.get("domains") or []],
        confidence=max(0.0, min(1.0, float(row.get("confidence") or 0.0))),
        curated=bool(row.get("curated")),
    )


def build_shared_language_snapshot(registry: SharedLanguageRegistry) -> list[SharedLanguageKey]:
    """Return current key set for continuity snapshot composition."""

    return registry.list_keys()
