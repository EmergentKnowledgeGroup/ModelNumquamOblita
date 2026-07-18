from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.config import RuntimeEfficiencyPolicy, default_config
from engine.runtime.temporal import (
    TemporalResolutionError,
    build_temporal_context,
    resolve_temporal_window,
    resolve_timezone,
)


UTC = timezone.utc


def test_locked_temporal_budgets_and_total_context_hard_cap() -> None:
    config = default_config()
    policy = config.provisional_memory

    assert config.efficiency.context_token_budget == 2800
    assert policy.temporal_context_token_budget == 192
    assert policy.temporal_due_max_items == 3
    assert policy.temporal_due_summary_max_bytes == 160
    with pytest.raises(ValueError, match="context_token_budget must be <= 4096"):
        RuntimeEfficiencyPolicy(context_token_budget=4097)


def test_timezone_policy_uses_configured_iana_and_visible_utc_fallback() -> None:
    configured = resolve_timezone("America/Chicago")
    fallback = resolve_timezone("", system_timezone="Not/AZone")

    assert configured.name == "America/Chicago"
    assert configured.source == "configured"
    assert fallback.name == "UTC"
    assert fallback.source == "utc_fallback"


def test_resolver_rejects_dst_gap_and_requires_fold_disambiguation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(TemporalResolutionError, match="TEMPORAL_LOCAL_TIME_GAP"):
        resolve_temporal_window(
            {"local_datetime": "2026-03-08T02:30:00", "timezone": "America/New_York"},
            now_utc=now,
        )

    with pytest.raises(TemporalResolutionError, match="TEMPORAL_LOCAL_TIME_AMBIGUOUS"):
        resolve_temporal_window(
            {"local_datetime": "2026-11-01T01:30:00", "timezone": "America/New_York"},
            now_utc=now,
        )

    first = resolve_temporal_window(
        {"local_datetime": "2026-11-01T01:30:00", "timezone": "America/New_York", "fold": 0},
        now_utc=now,
    )
    second = resolve_temporal_window(
        {"local_datetime": "2026-11-01T01:30:00", "timezone": "America/New_York", "fold": 1},
        now_utc=now,
    )
    assert second.start_utc.timestamp() - first.start_utc.timestamp() == 3600


def test_relative_duration_and_calendar_month_clamping_are_distinct() -> None:
    now = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
    duration = resolve_temporal_window(
        {"relative_duration": {"amount": 24, "unit": "hours"}, "timezone": "UTC"},
        now_utc=now,
    )
    calendar = resolve_temporal_window(
        {"calendar_offset": {"amount": 1, "unit": "months"}, "timezone": "UTC"},
        now_utc=now,
    )

    assert duration.start_utc == datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    assert (duration.end_utc - duration.start_utc).total_seconds() == 3600
    assert calendar.start_utc == datetime(2026, 2, 28, 12, 0, tzinfo=UTC)


def test_date_and_approximate_inputs_remain_windows() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    date_window = resolve_temporal_window(
        {"local_date": "2026-07-18", "timezone": "America/Chicago"},
        now_utc=now,
    )
    approximate = resolve_temporal_window(
        {
            "window_start": "2026-07-01T00:00:00-05:00",
            "window_end": "2026-08-01T00:00:00-05:00",
            "timezone": "America/Chicago",
            "precision": "approximate",
        },
        now_utc=now,
    )

    assert date_window.precision == "date"
    assert (date_window.end_utc - date_window.start_utc).total_seconds() == 86400
    assert approximate.precision == "approximate"
    assert approximate.end_utc > approximate.start_utc


def test_local_date_window_tracks_calendar_day_across_dst() -> None:
    window = resolve_temporal_window(
        {"local_date": "2026-03-08", "timezone": "America/New_York"},
        now_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert (window.end_utc - window.start_utc).total_seconds() == 23 * 3600


def test_temporal_context_reports_clock_rollback_without_fabricating_elapsed() -> None:
    context = build_temporal_context(
        now_utc=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        timezone_name="America/Chicago",
        previous_user_utc=datetime(2026, 7, 18, 13, 0, tzinfo=UTC),
        previous_assistant_utc=None,
    )

    assert context["schema_version"] == "mno.temporal-context.v1"
    assert context["clock_anomaly"] is True
    assert context["previous_user_turn"]["elapsed_seconds"] is None
    assert context["previous_user_turn"]["reason_code"] == "TEMPORAL_CLOCK_ROLLBACK"
    assert context["previous_assistant_turn"]["status"] == "unavailable"
