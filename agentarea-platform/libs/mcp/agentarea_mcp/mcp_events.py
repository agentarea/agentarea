"""MCP Events as a client (SEP-3415, draft PR #3415 at 2ec39b9c, protocol 2026-07-28).

A server that offers events says so in ``capabilities.extensions`` and lists its
event types with ``events/list``. Verification stores both on the instance
(``MCPServerInstance.events``); a source of the ``mcp_events`` entry names one
of those types, its arguments and a delivery mode the type offers. Polling and
subscribing are the Go event-service's (ADR-0040 §3), through the mcp-manager
gateway.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

import mcp_types as types
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import TypeAdapter

EVENTS_EXTENSION = "io.modelcontextprotocol/events"

_MAX_PAGES = 20
_MAX_EVENT_TYPES = 500
_RESULT = TypeAdapter(dict[str, Any])


class ListEventsRequest(types.PaginatedRequest[Literal["events/list"]]):
    method: Literal["events/list"] = "events/list"


class EventSourceError(ValueError):
    """A source cannot be made of this instance, event, arguments and mode."""


def events_settings(capabilities: Any) -> dict[str, Any] | None:
    """The server's settings for the events extension, or None when it does not offer it."""
    extensions = getattr(capabilities, "extensions", None) or {}
    settings = extensions.get(EVENTS_EXTENSION)
    return dict(settings) if isinstance(settings, dict) else None


async def list_event_types(session: Any) -> list[dict[str, Any]]:
    """Every event type ``events/list`` returns, page by page."""
    listed: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(_MAX_PAGES):
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        page = await session.send_request(ListEventsRequest(params=params), _RESULT)
        for event_type in page.get("events") or []:
            if isinstance(event_type, dict) and isinstance(event_type.get("name"), str):
                listed.append(event_type)
        cursor = page.get("nextCursor")
        if not cursor:
            return listed[:_MAX_EVENT_TYPES]
        if cursor in seen:
            raise ValueError(f"events/list cursor {cursor!r} repeats")
        seen.add(cursor)
    raise ValueError(f"events/list has more than {_MAX_PAGES} pages")


def events_record(
    settings: dict[str, Any],
    event_types: list[dict[str, Any]],
    protocol_version: str,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    """What the instance stores: the extension's settings and the listed event types.

    ``error`` says why events/list failed on a server that advertises events.
    """
    record: dict[str, Any] = {
        "extension": EVENTS_EXTENSION,
        "settings": settings,
        "protocol_version": protocol_version,
        "events": event_types,
        "listed_at": datetime.now(UTC).isoformat(),
    }
    if error is not None:
        record["error"] = error
    return record


def parse_arguments(raw: str | None) -> dict[str, Any]:
    """A source's ``arguments`` setting: a JSON object, empty when unset."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError as error:
        raise EventSourceError("arguments must be a JSON object") from error
    if not isinstance(value, dict):
        raise EventSourceError("arguments must be a JSON object")
    return value


def check_event_source(
    record: dict[str, Any] | None, *, event: str, arguments: dict[str, Any], mode: str
) -> dict[str, Any]:
    """The event type a source subscribes to; raise unless the server offers it this way."""
    if not record or not isinstance(record.get("events"), list):
        raise EventSourceError(
            "This MCP server does not offer MCP Events; verify it again if it does now"
        )
    if record.get("error"):
        raise EventSourceError(
            f"The MCP server offers events but listing them failed: {record['error']}"
        )
    offered = {t["name"]: t for t in record["events"] if isinstance(t, dict) and "name" in t}
    event_type = offered.get(event)
    if event_type is None:
        raise EventSourceError(
            f"The MCP server has no event {event!r}; it offers {sorted(offered)}"
        )
    delivery = [m for m in event_type.get("delivery") or [] if isinstance(m, str)]
    if mode not in delivery:
        raise EventSourceError(
            f"{event!r} is delivered by {' or '.join(delivery) or 'no mode'} only, not {mode}"
        )
    schema = event_type.get("inputSchema")
    if isinstance(schema, dict):
        try:
            errors = sorted(
                Draft202012Validator(schema).iter_errors(arguments), key=lambda e: list(e.path)
            )
        except SchemaError as error:
            raise EventSourceError(f"The server's input schema for {event!r} is invalid") from error
        if errors:
            where = ".".join(str(step) for step in errors[0].path)
            raise EventSourceError(
                f"arguments for {event!r}: {where + ': ' if where else ''}{errors[0].message}"
            )
    return event_type
