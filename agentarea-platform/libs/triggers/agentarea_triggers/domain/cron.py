"""What a cron trigger's schedule must look like before it is stored.

Temporal reads the expression only when the schedule is created, and the
trigger service treats that step as best effort, so a malformed expression or
an unknown time zone used to be stored as an active trigger that never fires.
These checks run where a trigger is created or updated, never where a stored
one is loaded: a row saved before them must still read back.

The grammar is the one Temporal's cron strings share with classic cron:
five fields (minute, hour, day of month, month, day of week) or six with a
trailing year. Each field is a comma list of ``*``, ``?``, a value or a
``low-high`` range, each optionally followed by ``/step``.
"""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]

# name, lowest, highest, value names (index + lowest is the value)
_FIELDS: list[tuple[str, int, int, list[str]]] = [
    ("minute", 0, 59, []),
    ("hour", 0, 23, []),
    ("day of month", 1, 31, []),
    ("month", 1, 12, _MONTHS),
    ("day of week", 0, 7, _DAYS),
    ("year", 1970, 2199, []),
]

_ITEM = re.compile(r"^(?P<base>\*|\?|[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)(?:/(?P<step>\d+))?$")


def _value(token: str, lowest: int, highest: int, names: list[str]) -> int | None:
    if token.isdigit():
        number = int(token)
    elif token.lower() in names:
        number = names.index(token.lower()) + lowest
    else:
        return None
    return number if lowest <= number <= highest else None


def _field_error(field: str, name: str, lowest: int, highest: int, names: list[str]) -> str | None:
    for item in field.split(","):
        match = _ITEM.match(item)
        if match is None:
            return f"invalid {name} field {field!r}"
        step = match.group("step")
        if step is not None and int(step) == 0:
            return f"{name} step cannot be 0"
        base = match.group("base")
        if base in ("*", "?"):
            continue
        bounds = base.split("-")
        values = [_value(token, lowest, highest, names) for token in bounds]
        if any(value is None for value in values):
            return f"{name} must be between {lowest} and {highest}, got {base!r}"
        if len(values) == 2 and values[0] > values[1]:  # type: ignore[operator]
            return f"{name} range {base!r} runs backwards"
    return None


def cron_expression_error(expression: str) -> str | None:
    """Why ``expression`` is not a schedule Temporal can run, or ``None``."""
    fields = expression.split()
    if len(fields) not in (5, 6):
        return "Cron expression must have 5 or 6 parts"
    for field, (name, lowest, highest, names) in zip(fields, _FIELDS, strict=False):
        error = _field_error(field, name, lowest, highest, names)
        if error is not None:
            return f"Invalid cron expression: {error}"
    return None


def timezone_error(timezone: str) -> str | None:
    """Why ``timezone`` is not an IANA time zone name, or ``None``."""
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return f"Unknown time zone {timezone!r}; use an IANA name such as 'Europe/Berlin'"
    return None
