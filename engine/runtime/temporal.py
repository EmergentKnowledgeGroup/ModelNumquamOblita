"""Deterministic clock and prospective-time primitives.

This module intentionally contains no scheduler, background loop, natural-language
parser, or model-facing behavioral guidance.  It converts structured temporal
intent into auditable UTC windows and renders compact facts from a server clock.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
Clock = Callable[[], datetime]


class TemporalResolutionError(ValueError):
    """A safe, stable temporal resolution failure."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = str(code)
        super().__init__(f"{self.code}: {message}" if message else self.code)


@dataclass(frozen=True, slots=True)
class ResolvedTimezone:
    name: str
    zone: ZoneInfo
    source: str


@dataclass(frozen=True, slots=True)
class TemporalWindow:
    start_utc: datetime
    end_utc: datetime
    timezone: str
    precision: str
    resolution_kind: str

    def as_dict(self) -> dict[str, str]:
        return {
            "due_window_start_utc": self.start_utc.isoformat(),
            "due_window_end_utc": self.end_utc.isoformat(),
            "timezone": self.timezone,
            "precision": self.precision,
            "resolution_kind": self.resolution_kind,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TemporalResolutionError("TEMPORAL_NAIVE_DATETIME", f"{field} requires an offset")
    return value.astimezone(UTC)


def resolve_timezone(
    configured_timezone: str | None,
    *,
    system_timezone: str | None = None,
) -> ResolvedTimezone:
    """Resolve configured -> system IANA -> visible UTC fallback."""

    configured = str(configured_timezone or "").strip()
    if configured:
        try:
            return ResolvedTimezone(configured, ZoneInfo(configured), "configured")
        except ZoneInfoNotFoundError as exc:
            raise TemporalResolutionError("TEMPORAL_TIMEZONE_INVALID", configured) from exc

    candidate = str(system_timezone or "").strip()
    if not candidate:
        try:
            from tzlocal import get_localzone_name

            candidate = str(get_localzone_name() or "").strip()
        except Exception:
            candidate = ""
    if not candidate:
        local_tz = datetime.now().astimezone().tzinfo
        candidate = str(getattr(local_tz, "key", "") or "").strip()
    if candidate:
        try:
            return ResolvedTimezone(candidate, ZoneInfo(candidate), "system_iana")
        except ZoneInfoNotFoundError:
            pass
    return ResolvedTimezone("UTC", ZoneInfo("UTC"), "utc_fallback")


def _parse_naive_local(value: object, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise TemporalResolutionError("TEMPORAL_INPUT_REQUIRED", field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TemporalResolutionError("TEMPORAL_DATETIME_INVALID", field) from exc
    if parsed.tzinfo is not None:
        raise TemporalResolutionError("TEMPORAL_LOCAL_DATETIME_HAS_OFFSET", field)
    return parsed


def _resolve_local_datetime(naive: datetime, zone: ZoneInfo, *, fold: object = None) -> datetime:
    candidates: list[datetime] = []
    for fold_value in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold_value)
        roundtrip = local.astimezone(UTC).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == naive and roundtrip.fold == fold_value:
            candidates.append(local)
    unique = {item.utcoffset() for item in candidates}
    if not candidates:
        raise TemporalResolutionError("TEMPORAL_LOCAL_TIME_GAP")
    if len(unique) > 1:
        if fold not in {0, 1, "0", "1"}:
            raise TemporalResolutionError("TEMPORAL_LOCAL_TIME_AMBIGUOUS")
        selected_fold = int(fold)
        for item in candidates:
            if item.fold == selected_fold:
                return item
        raise TemporalResolutionError("TEMPORAL_LOCAL_TIME_AMBIGUOUS")
    return candidates[0]


def _parse_offset_datetime(value: object, *, field: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TemporalResolutionError("TEMPORAL_DATETIME_INVALID", field) from exc
    return _as_utc(parsed, field=field)


def _calendar_add(local_now: datetime, *, amount: int, unit: str) -> datetime:
    if unit == "days":
        return local_now + timedelta(days=amount)
    if unit == "weeks":
        return local_now + timedelta(weeks=amount)
    if unit not in {"months", "years"}:
        raise TemporalResolutionError("TEMPORAL_CALENDAR_UNIT_UNSUPPORTED", unit)
    months = amount if unit == "months" else amount * 12
    absolute_month = local_now.year * 12 + (local_now.month - 1) + months
    target_year, month_zero = divmod(absolute_month, 12)
    target_month = month_zero + 1
    if target_year < 1 or target_year > 9999:
        raise TemporalResolutionError("TEMPORAL_HORIZON_INVALID")
    target_day = min(local_now.day, calendar.monthrange(target_year, target_month)[1])
    return local_now.replace(year=target_year, month=target_month, day=target_day)


def resolve_temporal_window(
    request: Mapping[str, Any],
    *,
    now_utc: datetime,
    default_timezone: str = "UTC",
) -> TemporalWindow:
    """Resolve one strict structured request into an honest UTC window."""

    now = _as_utc(now_utc, field="now_utc")
    requested_zone = str(request.get("timezone") or default_timezone or "UTC").strip()
    resolved_zone = resolve_timezone(requested_zone)
    zone = resolved_zone.zone
    precision = str(request.get("precision") or "").strip().lower()

    if "local_datetime" in request:
        local = _resolve_local_datetime(
            _parse_naive_local(request.get("local_datetime"), field="local_datetime"),
            zone,
            fold=request.get("fold"),
        )
        start = local.astimezone(UTC)
        end = start + timedelta(hours=1)
        return TemporalWindow(start, end, resolved_zone.name, precision or "exact", "local_datetime")

    if "local_date" in request:
        try:
            target_date = date.fromisoformat(str(request.get("local_date") or ""))
        except ValueError as exc:
            raise TemporalResolutionError("TEMPORAL_DATE_INVALID") from exc
        start_local = _resolve_local_datetime(datetime.combine(target_date, time.min), zone, fold=0)
        next_local = _resolve_local_datetime(datetime.combine(target_date + timedelta(days=1), time.min), zone, fold=0)
        return TemporalWindow(
            start_local.astimezone(UTC),
            next_local.astimezone(UTC),
            resolved_zone.name,
            precision or "date",
            "local_date",
        )

    if "window_start" in request or "window_end" in request:
        start = _parse_offset_datetime(request.get("window_start"), field="window_start")
        end = _parse_offset_datetime(request.get("window_end"), field="window_end")
        if end <= start:
            raise TemporalResolutionError("TEMPORAL_WINDOW_INVALID")
        if precision not in {"exact", "date", "month", "approximate"}:
            raise TemporalResolutionError("TEMPORAL_PRECISION_INVALID")
        return TemporalWindow(start, end, resolved_zone.name, precision, "explicit_window")

    if "relative_duration" in request:
        raw = request.get("relative_duration")
        if not isinstance(raw, Mapping):
            raise TemporalResolutionError("TEMPORAL_RELATIVE_INVALID")
        try:
            amount = int(raw.get("amount"))
        except (TypeError, ValueError) as exc:
            raise TemporalResolutionError("TEMPORAL_RELATIVE_INVALID") from exc
        unit = str(raw.get("unit") or "").strip().lower()
        units = {"minutes": "minutes", "hours": "hours", "days": "days", "weeks": "weeks"}
        if amount <= 0 or unit not in units:
            raise TemporalResolutionError("TEMPORAL_RELATIVE_INVALID")
        start = now + timedelta(**{units[unit]: amount})
        return TemporalWindow(start, start + timedelta(hours=1), resolved_zone.name, precision or "exact", "relative_duration")

    if "calendar_offset" in request:
        raw = request.get("calendar_offset")
        if not isinstance(raw, Mapping):
            raise TemporalResolutionError("TEMPORAL_CALENDAR_INVALID")
        try:
            amount = int(raw.get("amount"))
        except (TypeError, ValueError) as exc:
            raise TemporalResolutionError("TEMPORAL_CALENDAR_INVALID") from exc
        unit = str(raw.get("unit") or "").strip().lower()
        if amount <= 0 or unit not in {"days", "weeks", "months", "years"}:
            raise TemporalResolutionError("TEMPORAL_CALENDAR_INVALID")
        local_now = now.astimezone(zone)
        target_naive = _calendar_add(local_now.replace(tzinfo=None), amount=amount, unit=unit)
        local_time_value = str(raw.get("local_time") or "").strip()
        if local_time_value:
            try:
                parsed_time = time.fromisoformat(local_time_value)
            except ValueError as exc:
                raise TemporalResolutionError("TEMPORAL_TIME_INVALID") from exc
            target_naive = datetime.combine(target_naive.date(), parsed_time)
        target = _resolve_local_datetime(target_naive, zone, fold=raw.get("fold"))
        start = target.astimezone(UTC)
        return TemporalWindow(start, start + timedelta(hours=1), resolved_zone.name, precision or "exact", "calendar_offset")

    raise TemporalResolutionError("TEMPORAL_INPUT_UNSUPPORTED")


def _turn_clock_fact(now: datetime, previous: datetime | None, *, provenance: str) -> dict[str, Any]:
    if previous is None:
        return {
            "status": "unavailable",
            "timestamp_utc": None,
            "elapsed_seconds": None,
            "provenance": provenance,
            "reason_code": "TEMPORAL_OBSERVATION_MISSING",
        }
    observed = _as_utc(previous, field="previous_turn")
    elapsed = (now - observed).total_seconds()
    if elapsed < 0:
        return {
            "status": "anomaly",
            "timestamp_utc": observed.isoformat(),
            "elapsed_seconds": None,
            "provenance": provenance,
            "reason_code": "TEMPORAL_CLOCK_ROLLBACK",
        }
    return {
        "status": "available",
        "timestamp_utc": observed.isoformat(),
        "elapsed_seconds": int(elapsed),
        "provenance": provenance,
        "reason_code": "",
    }


def build_temporal_context(
    *,
    now_utc: datetime,
    timezone_name: str | None,
    previous_user_utc: datetime | None,
    previous_assistant_utc: datetime | None,
    timezone_source: str | None = None,
) -> dict[str, Any]:
    """Build neutral, content-minimal clock facts from one server snapshot."""

    now = _as_utc(now_utc, field="now_utc")
    zone = resolve_timezone(timezone_name)
    previous_user = _turn_clock_fact(now, previous_user_utc, provenance="server_receipt")
    previous_assistant = _turn_clock_fact(
        now,
        previous_assistant_utc,
        provenance="server_completion_receipt",
    )
    anomaly = any(item["status"] == "anomaly" for item in (previous_user, previous_assistant))
    return {
        "schema_version": "mno.temporal-context.v1",
        "now_utc": now.isoformat(),
        "now_local": now.astimezone(zone.zone).isoformat(),
        "timezone": zone.name,
        "timezone_source": str(timezone_source or zone.source),
        "clock_source": "server",
        "clock_anomaly": anomaly,
        "previous_user_turn": previous_user,
        "previous_assistant_turn": previous_assistant,
        "due": [],
        "upcoming": {"count": 0, "next_window_start_utc": None},
        "expansion": {
            "context_operation": "context.why",
            "temporal_operations": ["memory.temporal.list", "memory.temporal.get"],
        },
    }


__all__ = [
    "Clock",
    "ResolvedTimezone",
    "TemporalResolutionError",
    "TemporalWindow",
    "build_temporal_context",
    "resolve_temporal_window",
    "resolve_timezone",
    "utc_now",
]
