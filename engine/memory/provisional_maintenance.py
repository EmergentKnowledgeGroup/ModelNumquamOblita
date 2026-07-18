"""Deterministic, bounded provisional-memory maintenance.

This module intentionally owns no daemon.  Callers invoke one pass explicitly
after an observation or at a session boundary and provide the server clock in
tests (production defaults to UTC now).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from .provisional_store import (
    ProvisionalLifecycle,
    ProvisionalMemoryKind,
    ProvisionalMemoryStatus,
    SqliteProvisionalMemoryStore,
)


@dataclass(frozen=True, slots=True)
class MaintenancePolicy:
    dormant_days: int = 90
    archive_days: int = 365
    plan_currentness_days: int = 30
    max_records: int = 25
    policy_version: str = "v0.2"
    fact_support: int = 3
    preference_support: int = 3
    plan_support: int = 3
    event_note_support: int = 3
    correction_support: int = 2
    self_claim_support: int = 4
    ordinary_distinct_sessions: int = 2
    self_claim_distinct_sessions: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.dormant_days <= 3650:
            raise ValueError("dormant_days must be in 1..3650")
        if not self.dormant_days < self.archive_days <= 7300:
            raise ValueError("archive_days must be greater than dormant_days and <= 7300")
        if not 1 <= self.plan_currentness_days <= 365:
            raise ValueError("plan_currentness_days must be in 1..365")
        if not 1 <= self.max_records <= 100:
            raise ValueError("max_records must be in 1..100")

    def threshold_for(self, kind: ProvisionalMemoryKind) -> tuple[int, int]:
        supports = {
            ProvisionalMemoryKind.FACT: self.fact_support,
            ProvisionalMemoryKind.PREFERENCE: self.preference_support,
            ProvisionalMemoryKind.PLAN: self.plan_support,
            ProvisionalMemoryKind.EVENT_NOTE: self.event_note_support,
            ProvisionalMemoryKind.CORRECTION: self.correction_support,
            ProvisionalMemoryKind.SELF_CLAIM: self.self_claim_support,
        }[kind]
        sessions = self.self_claim_distinct_sessions if kind is ProvisionalMemoryKind.SELF_CLAIM else self.ordinary_distinct_sessions
        return supports, sessions


@dataclass(frozen=True, slots=True)
class MaintenanceTransition:
    record_id: str
    disposition: str
    reason: str


def run_maintenance(
    store: SqliteProvisionalMemoryStore,
    *,
    policy: MaintenancePolicy = MaintenancePolicy(),
    now: datetime | None = None,
    max_records: int | None = None,
    consolidation_enabled: bool = True,
) -> list[MaintenanceTransition]:
    """Run a stable-order pass and return only durable state transitions."""
    server_now = now or datetime.now(timezone.utc)
    cap = max_records if max_records is not None else policy.max_records
    if not 1 <= int(cap) <= 100:
        raise ValueError("max_records must be in 1..100")
    transitions: list[MaintenanceTransition] = []
    rows = sorted(store.list_records(status="all"), key=lambda r: (r.created_at, r.record_id))[: int(cap)]
    for record in rows:
        if record.status in {ProvisionalMemoryStatus.SUPERSEDED, ProvisionalMemoryStatus.CONFLICTED}:
            continue
        last = record.last_independent_support_at or record.last_reinforced_at or record.updated_at
        age = server_now - last.astimezone(timezone.utc)
        if record.lifecycle is ProvisionalLifecycle.ACTIVE and age >= timedelta(days=policy.dormant_days):
            store.set_lifecycle(record.record_id, ProvisionalLifecycle.DORMANT, reason="inactivity_window")
            transitions.append(MaintenanceTransition(record.record_id, "dormant", "inactivity_window"))
            continue
        if record.lifecycle is ProvisionalLifecycle.DORMANT and age >= timedelta(days=policy.archive_days):
            store.set_lifecycle(record.record_id, ProvisionalLifecycle.ARCHIVED, reason="archive_window")
            transitions.append(MaintenanceTransition(record.record_id, "archived", "archive_window"))
            continue
        if not consolidation_enabled or record.derived or record.lifecycle is not ProvisionalLifecycle.ACTIVE:
            continue
        required_support, required_sessions = policy.threshold_for(record.kind)
        if record.independent_support_count < required_support or record.distinct_session_count < required_sessions:
            continue
        if record.kind is ProvisionalMemoryKind.PLAN and age >= timedelta(days=policy.plan_currentness_days):
            transitions.append(MaintenanceTransition(record.record_id, "historical_plan", "plan_currentness_window"))
            continue
        derived = store.create_consolidated_revision(record_ids=[record.record_id], policy_version=policy.policy_version)
        if derived is not None:
            transitions.append(MaintenanceTransition(derived.record_id, "consolidated", "threshold_met"))
    return transitions


__all__ = ["MaintenancePolicy", "MaintenanceTransition", "run_maintenance"]
