"""Cron firings as the dashboard calendar and agent overview preview them."""

from datetime import UTC, datetime, timedelta

import pytest
from agentarea_api.api.v1._schedule_preview import cron_runs, runs_per_day

START = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def test_runs_fire_in_the_trigger_timezone():
    # 09:00 in Moscow is 06:00 UTC; the first one after noon UTC is tomorrow's.
    runs = cron_runs("0 9 * * *", "Europe/Moscow", START, START + timedelta(days=2), limit=10)
    assert runs == [
        datetime(2026, 10, 3, 6, 0, tzinfo=UTC),
        datetime(2026, 10, 4, 6, 0, tzinfo=UTC),
    ]


def test_missing_timezone_reads_as_utc():
    runs = cron_runs("0 9 * * *", None, START, START + timedelta(days=1), limit=10)
    assert runs == [datetime(2026, 10, 3, 9, 0, tzinfo=UTC)]


def test_runs_stop_at_the_window_end():
    runs = cron_runs("0 * * * *", "UTC", START, START + timedelta(hours=3), limit=100)
    assert runs == [START + timedelta(hours=h) for h in (1, 2, 3)]


def test_runs_stop_at_the_limit():
    runs = cron_runs("* * * * *", "UTC", START, START + timedelta(days=14), limit=5)
    assert len(runs) == 5


def test_runs_per_day_counts_the_firings_of_a_day_it_runs():
    assert runs_per_day("*/15 * * * *") == 96


def test_runs_per_day_of_a_daily_schedule_is_one():
    assert runs_per_day("30 8 * * *") == 1


def test_runs_per_day_of_an_every_minute_schedule_is_exact():
    assert runs_per_day("* * * * *") == 24 * 60


def test_runs_per_day_ignores_the_days_the_schedule_skips():
    # Every 5 minutes, only on October 20: 288 on the day it runs.
    assert runs_per_day("*/5 * 20 10 *") == 288


def test_bad_expression_raises():
    with pytest.raises(ValueError, match="5 or 6 fields"):
        cron_runs("not a cron", "UTC", START, START + timedelta(days=1), limit=10)


def test_unknown_timezone_raises():
    with pytest.raises(ValueError, match="unknown timezone"):
        cron_runs("0 9 * * *", "Mars/Olympus", START, START + timedelta(days=1), limit=10)


def test_restricted_day_of_month_and_day_of_week_must_both_match():
    # "First Monday of the month", as Temporal reads it — not every day 1-7
    # plus every Monday.
    runs = cron_runs(
        "0 9 1-7 * 1", "America/New_York", START, datetime(2026, 11, 1, tzinfo=UTC), limit=10
    )
    assert runs == [datetime(2026, 10, 5, 13, 0, tzinfo=UTC)]


def test_a_local_time_skipped_by_spring_forward_does_not_fire():
    start = datetime(2026, 3, 7, tzinfo=UTC)
    runs = cron_runs(
        "30 2 * * *", "America/New_York", start, datetime(2026, 3, 10, tzinfo=UTC), limit=10
    )
    # 2026-03-08 has no 02:30 in New York.
    assert runs == [
        datetime(2026, 3, 7, 7, 30, tzinfo=UTC),
        datetime(2026, 3, 9, 6, 30, tzinfo=UTC),
    ]


def test_a_sixth_field_is_the_year():
    weekly = cron_runs("0 9 * * 1 *", "UTC", START, START + timedelta(days=14), limit=100)
    assert weekly == [
        datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
    ]
    assert runs_per_day("0 9 * * 1 *") == 1
    assert cron_runs("0 9 * * 1 2027", "UTC", START, START + timedelta(days=120), limit=1) == [
        datetime(2027, 1, 4, 9, 0, tzinfo=UTC)
    ]
