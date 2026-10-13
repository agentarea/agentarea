"""How long a tool call on one MCP instance may take.

An instance declares it as ``tool_timeout_seconds`` in its ``json_spec``; a call
waits that long for the result, progress notifications included, then fails as
timed out. The platform maximum stays inside the tool activity's own budget
(``TOOL_EXECUTION_TIMEOUT``) together with a cold start of a container instance,
so the activity never outlives the call it is waiting on.
"""

from __future__ import annotations

from typing import Any

TOOL_TIMEOUT_KEY = "tool_timeout_seconds"
DEFAULT_TOOL_TIMEOUT_SECONDS = 300
MAX_TOOL_TIMEOUT_SECONDS = 1800
# How much longer than the call a response may stay silent, so the call's own
# timeout is the one that fires and the server is told to stop.
TOOL_TIMEOUT_GRACE_SECONDS = 30


def tool_timeout_error(spec: dict[str, Any]) -> str | None:
    """Why the spec's tool timeout is not acceptable, or ``None`` when it is."""
    if TOOL_TIMEOUT_KEY not in spec:
        return None
    value = spec[TOOL_TIMEOUT_KEY]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return f"Field '{TOOL_TIMEOUT_KEY}' must be a number of seconds"
    if not 1 <= value <= MAX_TOOL_TIMEOUT_SECONDS:
        return f"Field '{TOOL_TIMEOUT_KEY}' must be between 1 and {MAX_TOOL_TIMEOUT_SECONDS}"
    return None


def tool_timeout_seconds(spec: dict[str, Any]) -> float:
    """The instance's tool call timeout; a stored value outside the range is refused."""
    error = tool_timeout_error(spec)
    if error is not None:
        raise ValueError(error)
    return float(spec.get(TOOL_TIMEOUT_KEY, DEFAULT_TOOL_TIMEOUT_SECONDS))
