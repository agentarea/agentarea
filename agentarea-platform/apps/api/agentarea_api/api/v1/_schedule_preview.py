"""Preview when a cron trigger fires, in the timezone its schedule runs in.

Temporal fires the schedule with ``time_zone_name=trigger.timezone``; the
preview has to expand it the same way or the calendar shows runs that never
happen. Where croniter's defaults differ from Temporal's reading of a cron
string, Temporal wins:

- a restricted day-of-month and day-of-week must both match (croniter ORs them
  unless ``day_or=False``);
- a sixth field is the year (croniter reads it as seconds);
- a local time removed by a DST spring-forward does not fire (croniter moves it
  to the next valid instant).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def _zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {tz_name!r}") from exc


def _schedule(cron_expression: str, start: datetime) -> croniter:
    fields = cron_expression.split()
    if len(fields) == 6:
        # croniter's seven-field form is "... day_of_week second year".
        fields = [*fields[:5], "0", fields[5]]
    elif len(fields) != 5:
        raise ValueError(f"cron expression {cron_expression!r} must have 5 or 6 fields")
    return croniter(" ".join(fields), start, day_or=False)


def _allows(values: Sequence[int | str], value: int) -> bool:
    return values[0] == "*" or value in values


def cron_runs(
    cron_expression: str,
    tz_name: str | None,
    start: datetime,
    end: datetime,
    *,
    limit: int,
) -> list[datetime]:
    """Firings after ``start`` and up to ``end``, at most ``limit``, as aware UTC."""
    itr = _schedule(cron_expression, start.astimezone(_zone(tz_name)))
    minutes, hours = itr.expanded[0], itr.expanded[1]
    runs: list[datetime] = []
    while len(runs) < limit:
        local_fire = itr.get_next(datetime)
        fires_at = local_fire.astimezone(UTC)
        if fires_at > end:
            break
        # A wall time the DST gap removed comes back shifted off the schedule.
        if _allows(minutes, local_fire.minute) and _allows(hours, local_fire.hour):
            runs.append(fires_at)
    return runs


def runs_per_day(cron_expression: str) -> int:
    """How many times the schedule fires on a day it runs."""
    minutes, hours = _schedule(cron_expression, datetime.now(UTC)).expanded[:2]
    return (60 if minutes[0] == "*" else len(minutes)) * (24 if hours[0] == "*" else len(hours))
