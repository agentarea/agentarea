import re
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    PlainSerializer,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema


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


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


# Request-side counterpart for values compared against DB timestamps, which are
# naive UTC: an offset-carrying input is converted to UTC and made naive, since
# asyncpg refuses to bind an aware datetime to TIMESTAMP WITHOUT TIME ZONE.
NaiveUtcDatetime = Annotated[datetime, AfterValidator(_to_naive_utc)]


def _reject_null(value: Any) -> Any:
    if value is None:
        raise ValueError("may be omitted, but not set to null")
    return value


class _NotNull:
    """Marks a partial-update field that may be left out but never set to null.

    ``Annotated[str | None, NotNull] = None`` keeps "unset" expressible while an
    explicit ``null`` for a NOT NULL column is refused as a 422 instead of
    reaching the database. The published schema drops the ``null`` branch so
    clients are told the same thing the validator enforces.
    """

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(_reject_null, handler(source))

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        variants = json_schema.get("anyOf")
        if not variants:
            return json_schema
        kept = [variant for variant in variants if variant != {"type": "null"}]
        rest = {key: value for key, value in json_schema.items() if key != "anyOf"}
        if len(kept) == 1:
            return {**kept[0], **rest}
        return {**rest, "anyOf": kept}


NotNull = _NotNull()


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
