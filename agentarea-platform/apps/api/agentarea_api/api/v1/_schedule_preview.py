"""Preview when a cron trigger fires, in the timezone its schedule runs in.

Temporal fires the schedule with ``time_zone_name=trigger.timezone``; the
preview has to expand it the same way or every non-UTC trigger shows at the
wrong hour.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def _zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {tz_name!r}") from exc


def cron_runs(
    cron_expression: str,
    tz_name: str | None,
    start: datetime,
    end: datetime,
    *,
    limit: int,
) -> list[datetime]:
    """Firings after ``start`` and up to ``end``, at most ``limit``, as aware UTC."""
    itr = croniter(cron_expression, start.astimezone(_zone(tz_name)))
    runs: list[datetime] = []
    while len(runs) < limit:
        fires_at = itr.get_next(datetime).astimezone(UTC)
        if fires_at > end:
            break
        runs.append(fires_at)
    return runs


def runs_per_day(cron_expression: str, tz_name: str | None, start: datetime) -> int:
    """How many times the schedule fires in the day that starts at its next run."""
    first = cron_runs(cron_expression, tz_name, start, start + timedelta(days=366), limit=1)
    if not first:
        return 0
    window_start = first[0] - timedelta(microseconds=1)
    return len(
        cron_runs(
            cron_expression,
            tz_name,
            window_start,
            window_start + timedelta(days=1),
            limit=24 * 60,
        )
    )
