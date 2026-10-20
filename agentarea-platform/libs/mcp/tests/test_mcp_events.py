"""MCP Events (SEP-3415) as a client: the capability, events/list and a source's choice."""

from types import SimpleNamespace
from typing import Any

import pytest
from agentarea_mcp.mcp_events import (
    EVENTS_EXTENSION,
    EventSourceError,
    check_event_source,
    events_record,
    events_settings,
    list_event_types,
    parse_arguments,
)

TICKET = {
    "name": "ticket.created",
    "description": "A ticket was opened",
    "delivery": ["poll", "webhook"],
    "inputSchema": {
        "type": "object",
        "properties": {"queue": {"type": "string"}, "priority": {"enum": ["low", "high"]}},
        "required": ["queue"],
    },
    "payloadSchema": {"type": "object"},
}
CLOSED = {"name": "ticket.closed", "delivery": ["poll"], "inputSchema": {"type": "object"}}


def _record(*types: dict[str, Any]) -> dict[str, Any]:
    return events_record({"listChanged": False}, list(types), "2026-07-28")


def test_settings_come_from_the_extensions_entry():
    capabilities = SimpleNamespace(extensions={EVENTS_EXTENSION: {"listChanged": True}})
    assert events_settings(capabilities) == {"listChanged": True}


def test_a_server_without_the_extension_offers_no_events():
    assert events_settings(SimpleNamespace(extensions=None)) is None
    assert events_settings(SimpleNamespace(extensions={"io.example/other": {}})) is None
    assert events_settings(None) is None


class _Session:
    def __init__(self, pages: list[dict[str, Any]]):
        self.pages = pages
        self.sent: list[dict[str, Any]] = []

    async def send_request(self, request, result_type):
        self.sent.append(request.model_dump(by_alias=True, exclude_none=True))
        return self.pages.pop(0)


@pytest.mark.asyncio
async def test_list_follows_next_cursor_and_keeps_named_types_only():
    session = _Session(
        [
            {"resultType": "complete", "events": [TICKET, {"description": "no name"}], "nextCursor": "p2"},
            {"resultType": "complete", "events": [CLOSED]},
        ]
    )

    listed = await list_event_types(session)

    assert [t["name"] for t in listed] == ["ticket.created", "ticket.closed"]
    assert session.sent[0]["method"] == "events/list"
    assert "params" not in session.sent[0] or not session.sent[0]["params"].get("cursor")
    assert session.sent[1]["params"]["cursor"] == "p2"


@pytest.mark.asyncio
async def test_list_stops_on_a_cursor_that_repeats():
    page = {"resultType": "complete", "events": [TICKET], "nextCursor": "same"}
    session = _Session([page, dict(page), dict(page)])

    with pytest.raises(ValueError, match="repeats"):
        await list_event_types(session)


def test_record_keeps_what_a_source_needs():
    record = _record(TICKET)
    assert record["extension"] == EVENTS_EXTENSION
    assert record["protocol_version"] == "2026-07-28"
    assert record["settings"] == {"listChanged": False}
    assert record["events"][0]["name"] == "ticket.created"
    assert record["listed_at"]


def test_a_listed_event_in_an_offered_mode_with_valid_arguments_passes():
    chosen = check_event_source(
        _record(TICKET, CLOSED), event="ticket.created", arguments={"queue": "support"}, mode="webhook"
    )
    assert chosen["name"] == "ticket.created"


def test_an_instance_without_events_is_refused():
    with pytest.raises(EventSourceError, match="does not offer MCP Events"):
        check_event_source(None, event="ticket.created", arguments={}, mode="poll")


def test_an_event_the_server_did_not_list_is_refused():
    with pytest.raises(EventSourceError, match="no event 'ticket.moved'"):
        check_event_source(_record(TICKET), event="ticket.moved", arguments={}, mode="poll")


def test_a_mode_the_event_does_not_offer_is_refused_not_switched():
    with pytest.raises(EventSourceError, match="poll only"):
        check_event_source(_record(CLOSED), event="ticket.closed", arguments={}, mode="webhook")


def test_arguments_are_checked_against_the_input_schema():
    with pytest.raises(EventSourceError, match="queue"):
        check_event_source(_record(TICKET), event="ticket.created", arguments={}, mode="poll")
    with pytest.raises(EventSourceError, match="priority"):
        check_event_source(
            _record(TICKET),
            event="ticket.created",
            arguments={"queue": "q", "priority": "urgent"},
            mode="poll",
        )


def test_arguments_are_a_json_object():
    assert parse_arguments(None) == {}
    assert parse_arguments("") == {}
    assert parse_arguments('{"queue": "q"}') == {"queue": "q"}
    with pytest.raises(EventSourceError, match="JSON object"):
        parse_arguments("[1]")
    with pytest.raises(EventSourceError, match="JSON object"):
        parse_arguments("{not json")
