"""Deterministic, bounded provisional-memory maintenance.

This module intentionally owns no daemon.  Callers invoke one pass explicitly
after an observation or at a session boundary and provide the server clock in
tests (production defaults to UTC now).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from .provisional_store import (
    ProvisionalLifecycle,
    ProvisionalMemoryKind,
    ProvisionalMemoryStatus,
    SqliteProvisionalMemoryStore,
    TemporalDisposition,
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
    run_id: str | None = None,
    dry_run: bool = False,
    return_result: bool = False,
) -> list[MaintenanceTransition] | dict[str, object]:
    """Run a durable, fair maintenance pass (or a read-only preview)."""
    server_now = now or datetime.now(timezone.utc)
    cap = max_records if max_records is not None else policy.max_records
    if not 1 <= int(cap) <= 100:
        raise ValueError("max_records must be in 1..100")

    def process(rows, *, apply: bool) -> list[MaintenanceTransition]:
        transitions: list[MaintenanceTransition] = []
        for record in rows:
            if (
                record.temporal_disposition in {TemporalDisposition.SCHEDULED, TemporalDisposition.SNOOZED}
                and record.decay_not_before_utc is not None
                and server_now >= record.decay_not_before_utc.astimezone(timezone.utc)
            ):
                if apply:
                    store.expire_temporal(
                        record.record_id,
                        record.principal_id,
                        record.runtime_id,
                        expected_revision=record.temporal_revision,
                        idempotency_key=(
                            f"maintenance-expire:{record.record_id}:"
                            f"{record.decay_not_before_utc.astimezone(timezone.utc).isoformat()}"
                        ),
                        now_utc=server_now,
                    )
                    disposition = "expired"
                else:
                    disposition = "would_expire"
                transitions.append(MaintenanceTransition(record.record_id, disposition, "temporal_grace_elapsed"))
                continue
            last = record.last_independent_support_at or record.last_reinforced_at or record.updated_at
            temporal_protected = False
            if (
                record.temporal_disposition in {TemporalDisposition.SCHEDULED, TemporalDisposition.SNOOZED}
                and record.decay_not_before_utc is not None
            ):
                temporal_anchor = record.decay_not_before_utc.astimezone(timezone.utc)
                if server_now < temporal_anchor:
                    temporal_protected = True
                else:
                    last = max(last.astimezone(timezone.utc), temporal_anchor)
            elif (
                record.temporal_disposition is TemporalDisposition.EXPIRED
                and record.decay_not_before_utc is not None
            ):
                last = max(
                    last.astimezone(timezone.utc),
                    record.decay_not_before_utc.astimezone(timezone.utc),
                )
            age = server_now - last.astimezone(timezone.utc)
            if (
                not temporal_protected
                and record.lifecycle is ProvisionalLifecycle.ACTIVE
                and age >= timedelta(days=policy.dormant_days)
            ):
                if apply:
                    store.set_lifecycle(record.record_id, ProvisionalLifecycle.DORMANT, reason="inactivity_window")
                    disposition = "dormant"
                else:
                    disposition = "would_dormant"
                transitions.append(MaintenanceTransition(record.record_id, disposition, "inactivity_window"))
                continue
            if (
                not temporal_protected
                and record.lifecycle is ProvisionalLifecycle.DORMANT
                and age >= timedelta(days=policy.archive_days)
            ):
                if apply:
                    store.set_lifecycle(record.record_id, ProvisionalLifecycle.ARCHIVED, reason="archive_window")
                    disposition = "archived"
                else:
                    disposition = "would_archive"
                transitions.append(MaintenanceTransition(record.record_id, disposition, "archive_window"))
                continue
            if not consolidation_enabled or record.derived or record.lifecycle is not ProvisionalLifecycle.ACTIVE:
                continue
            required_support, required_sessions = policy.threshold_for(record.kind)
            if record.independent_support_count < required_support or record.distinct_session_count < required_sessions:
                continue
            if (
                not temporal_protected
                and record.kind is ProvisionalMemoryKind.PLAN
                and age >= timedelta(days=policy.plan_currentness_days)
            ):
                if apply:
                    store.set_lifecycle(record.record_id, ProvisionalLifecycle.DORMANT, reason="plan_currentness_window")
                    disposition = "historical_plan"
                else:
                    disposition = "would_historical_plan"
                transitions.append(MaintenanceTransition(record.record_id, disposition, "plan_currentness_window"))
                continue
            if apply:
                derived = store.create_consolidated_revision(record_ids=[record.record_id], policy_version=policy.policy_version)
                if derived is not None:
                    transitions.append(MaintenanceTransition(derived.record_id, "consolidated", "threshold_met"))
            else:
                transitions.append(MaintenanceTransition(record.record_id, "would_consolidate", "threshold_met"))
        return transitions

    if dry_run:
        cursor = store.maintenance_cursor()
        rows, next_cursor = store.maintenance_candidates(cursor=cursor, limit=int(cap))
        transitions = process(rows, apply=False)
        temporal_retention = store.maintain_temporal_retention(now=server_now, dry_run=True)
        result: dict[str, object] = {
            "state": "preview",
            "dry_run": True,
            "transitions": transitions,
            "processed_count": len(rows),
            "cursor": cursor,
            "next_cursor": next_cursor,
            "temporal_retention": temporal_retention,
        }
        return result if return_result else transitions

    durable_run_id = str(run_id or f"maint_{uuid4().hex}").strip()
    started = store.maintenance_begin(durable_run_id)
    state = str(started.get("state") or "")
    if state == "replay":
        transitions = [MaintenanceTransition(**dict(item)) for item in list(started.get("transitions") or [])]
        result = {"state": "replay", "dry_run": False, "transitions": transitions, "processed_count": len(transitions)}
        return result if return_result else transitions
    if state in {"join", "conflict"}:
        result = {"state": state, "dry_run": False, "transitions": [], "processed_count": 0}
        return result if return_result else []
    if state != "acquired":
        raise RuntimeError("MAINTENANCE_RUN_ACQUISITION_FAILED")

    cursor = dict(started.get("cursor") or {})
    try:
        rows, next_cursor = store.maintenance_candidates(cursor=cursor, limit=int(cap))
        transitions = process(rows, apply=True)
        serialized = [
            {"record_id": item.record_id, "disposition": item.disposition, "reason": item.reason}
            for item in transitions
        ]
        store.maintenance_complete(durable_run_id, cursor=next_cursor, transitions=serialized)
        temporal_retention = store.maintain_temporal_retention(now=server_now)
    except Exception:
        store.maintenance_fail(durable_run_id, error_code="MAINTENANCE_FAILED")
        raise
    result = {
        "state": "completed",
        "dry_run": False,
        "transitions": transitions,
        "processed_count": len(rows),
        "cursor": cursor,
        "next_cursor": next_cursor,
        "temporal_retention": temporal_retention,
    }
    return result if return_result else transitions


__all__ = ["MaintenancePolicy", "MaintenanceTransition", "run_maintenance"]
