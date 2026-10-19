"""An mcp_events source names an instance that offers the event, its arguments and a mode it offers."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.api.v1._stream_sources import mcp_events_config
from agentarea_mcp.mcp_events import events_record
from agentarea_streams.domain.enums import SourceKind
from agentarea_streams.schemas import SourceCreate
from fastapi import HTTPException

TICKET = {
    "name": "ticket.created",
    "delivery": ["poll", "webhook"],
    "inputSchema": {
        "type": "object",
        "properties": {"queue": {"type": "string"}},
        "required": ["queue"],
    },
}
CLOSED = {"name": "ticket.closed", "delivery": ["poll"], "inputSchema": {"type": "object"}}


def _instance(**overrides):
    values = {
        "id": uuid4(),
        "events": events_record({}, [TICKET, CLOSED], "2026-07-28"),
        "auth_config_id": None,
        "managed_by": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _payload(instance_id, *, event="ticket.created", arguments='{"queue": "support"}', kind="poll"):
    config = {"mcp_instance_id": str(instance_id), "event": event}
    if arguments is not None:
        config["arguments"] = arguments
    return SourceCreate(source_type="mcp_events", kind=SourceKind(kind), config=config)


async def _config(payload, instance, authorized=True):
    checked: list[str] = []

    async def load(instance_id):
        return instance if instance is not None and instance.id == instance_id else None

    async def authorize(instance_id):
        checked.append(str(instance_id))
        if not authorized:
            raise HTTPException(status_code=403, detail="no use")

    config = await mcp_events_config(payload, load_instance=load, authorize=authorize)
    return config, checked


async def test_a_listed_event_in_an_offered_mode_is_stored_with_canonical_arguments():
    instance = _instance()
    config, checked = await _config(
        _payload(instance.id, arguments='{ "queue":"support" }', kind="webhook"), instance
    )
    assert config == {
        "mcp_instance_id": str(instance.id),
        "event": "ticket.created",
        "arguments": json.dumps({"queue": "support"}, sort_keys=True, separators=(",", ":")),
    }
    assert checked == [str(instance.id)]


@pytest.mark.parametrize(
    ("overrides", "payload_kwargs", "status", "message"),
    [
        ({"events": None}, {}, 422, "does not offer MCP Events"),
        ({}, {"event": "ticket.moved"}, 422, "no event"),
        ({}, {"event": "ticket.closed", "arguments": None, "kind": "webhook"}, 422, "poll only"),
        ({}, {"arguments": "{}"}, 422, "queue"),
        ({}, {"arguments": "[1]"}, 422, "JSON object"),
        ({"auth_config_id": uuid4()}, {}, 422, "auth config"),
        ({"managed_by": "platform"}, {}, 422, "platform"),
    ],
)
async def test_what_the_server_does_not_offer_is_refused(overrides, payload_kwargs, status, message):
    instance = _instance(**overrides)
    with pytest.raises(HTTPException) as refused:
        await _config(_payload(instance.id, **payload_kwargs), instance)
    assert refused.value.status_code == status
    assert message in str(refused.value.detail)


async def test_an_instance_of_another_workspace_or_none_is_not_found():
    with pytest.raises(HTTPException) as refused:
        await _config(_payload(uuid4()), _instance())
    assert refused.value.status_code == 422
    assert "not found" in str(refused.value.detail)
    with pytest.raises(HTTPException) as malformed:
        await _config(_payload("not-a-uuid"), _instance())
    assert malformed.value.status_code == 422


async def test_a_member_who_may_not_use_the_instance_is_refused():
    instance = _instance()
    with pytest.raises(HTTPException) as refused:
        await _config(_payload(instance.id), instance, authorized=False)
    assert refused.value.status_code == 403
