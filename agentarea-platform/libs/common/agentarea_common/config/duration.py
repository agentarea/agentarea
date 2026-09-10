"""Duration values expressed as strings with an explicit unit.

Env names used to carry the unit (``..._TIMEOUT_SECONDS``, ``..._IDLE_MS``),
which made every rename a chance to change meaning silently. The unit now lives
in the value: ``30s``, ``500ms``, ``5m``, ``2h``, ``7d``. A bare number is
rejected rather than assumed to be seconds.
"""

import re
from datetime import timedelta
from typing import Annotated

from pydantic import BeforeValidator

_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m|h|d)$")


def parse_duration(value: object) -> timedelta:
    """Parse ``30s`` / ``500ms`` / ``2h`` into a timedelta."""
    if isinstance(value, timedelta):
        return value
    text = str(value).strip()
    match = _PATTERN.match(text)
    if match is None:
        raise ValueError(
            f"duration must be a number followed by ms/s/m/h/d (e.g. '30s', '500ms'), got {text!r}"
        )
    return timedelta(seconds=float(match.group(1)) * _UNITS[match.group(2)])


Duration = Annotated[timedelta, BeforeValidator(parse_duration)]
