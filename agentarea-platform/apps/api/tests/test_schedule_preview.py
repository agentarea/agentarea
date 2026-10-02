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


def test_runs_per_day_counts_one_day_from_the_first_run():
    assert runs_per_day("*/15 * * * *", "UTC", START) == 96


def test_runs_per_day_of_a_daily_schedule_is_one():
    assert runs_per_day("30 8 * * *", "Asia/Tokyo", START) == 1


def test_bad_expression_raises():
    with pytest.raises(ValueError, match="columns"):
        cron_runs("not a cron", "UTC", START, START + timedelta(days=1), limit=10)


def test_unknown_timezone_raises():
    with pytest.raises(ValueError, match="unknown timezone"):
        cron_runs("0 9 * * *", "Mars/Olympus", START, START + timedelta(days=1), limit=10)
