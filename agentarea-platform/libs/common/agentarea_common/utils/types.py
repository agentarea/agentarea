import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def _utc_z_isoformat(dt: datetime) -> str:
    """Render a datetime as RFC 3339 UTC with a trailing ``Z``.

    DB timestamps are naive UTC (``TIMESTAMP WITHOUT TIME ZONE``); serialized
    plainly they come out without an offset (``...042386``), which strict clients
    reject — notably Zod's ``z.string().datetime()``, which requires a ``Z``. We
    treat naive values as UTC and emit ``...042386Z``.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# Reusable field type for API response datetimes: JSON-serializes as UTC ``Z``.
UtcDatetime = Annotated[
    datetime, PlainSerializer(_utc_z_isoformat, return_type=str, when_used="json")
]


class MissingAPIKeyError(Exception):
    """Exception for missing API key."""


def sanitize_agent_name(name: str) -> str:
    """Sanitize agent name to be a valid Python identifier.

    A valid Python identifier:
    - Must start with a letter (a-z, A-Z) or underscore (_)
    - Can only contain letters, digits (0-9), and underscores

    Args:
        name: The original agent name

    Returns:
        Sanitized agent name that is a valid Python identifier

    Examples:
        >>> sanitize_agent_name("test-agent-123")
        'test_agent_123'
        >>> sanitize_agent_name("123-agent")
        'agent_123'
        >>> sanitize_agent_name("my-cool-agent!")
        'my_cool_agent_'
    """
    if not name:
        return "agent"

    # Replace hyphens and other invalid characters with underscores
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)

    # Ensure it starts with a letter or underscore
    if sanitized and sanitized[0].isdigit():
        sanitized = f"agent_{sanitized}"

    # Ensure it's not empty
    if not sanitized:
        return "agent"

    # Remove consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)

    # Remove trailing underscores (but keep leading ones)
    sanitized = sanitized.rstrip("_")

    # Ensure it's not empty after cleanup
    if not sanitized:
        return "agent"

    return sanitized
