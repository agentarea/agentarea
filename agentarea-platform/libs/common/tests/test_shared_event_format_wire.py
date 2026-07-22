"""Wire-format contract tests for SharedEventFormat (Python <-> Go).

These lock the exact JSON shape that `RedisEventBroker` publishes onto Redis
channels consumed by the Go MCP Manager. If any of these assertions change,
the Python->Go contract has changed and the Go decoder must be updated in
lockstep. Pure tests: no Redis, no broker.
"""

from __future__ import annotations

import json
import re
from uuid import UUID

from agentarea_common.events.shared_event_format import (
    SharedEventFormat,
    get_channel_for_event_type,
)


def test_create_event_key_set_is_stable():
    event = SharedEventFormat.create_event(
        event_type="com.agentarea.mcp.instance.created",
        data={"instance_id": "abc", "name": "my-mcp"},
        correlation_id="req-123",
        event_id="550e8400-e29b-41d4-a716-446655440000",
    )
    assert set(event.keys()) == {
        "specversion",
        "type",
        "source",
        "id",
        "time",
        "datacontenttype",
        "correlationid",
        "data",
    }


def test_create_event_field_values():
    event = SharedEventFormat.create_event(
        event_type="com.agentarea.mcp.instance.created",
        data={"instance_id": "abc"},
        correlation_id="req-123",
        event_id="550e8400-e29b-41d4-a716-446655440000",
    )
    assert event["specversion"] == "1.0"
    assert event["type"] == "com.agentarea.mcp.instance.created"
    assert event["source"] == "agentarea-api"
    assert event["id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert event["datacontenttype"] == "application/json"
    assert event["correlationid"] == "req-123"
    assert event["data"] == {"instance_id": "abc"}


def test_time_is_utc_second_precision_iso8601():
    event = SharedEventFormat.create_event(
        event_type="com.agentarea.mcp.instance.created",
        data={},
    )
    # e.g. 2026-02-19T10:00:00Z — seconds precision, trailing Z, no offset.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", event["time"])


def test_event_id_defaults_to_uuid4_string():
    event = SharedEventFormat.create_event(event_type="x", data={})
    # Must be a valid UUID string when not provided.
    UUID(event["id"])


def test_serialize_produces_expected_json_shape():
    event = SharedEventFormat.create_event(
        event_type="com.agentarea.mcp.instance.created",
        data={"instance_id": "abc", "name": "my-mcp", "server_spec_id": "spec-1"},
        correlation_id="req-123",
        event_id="550e8400-e29b-41d4-a716-446655440000",
    )
    payload = SharedEventFormat.serialize(event)
    decoded = json.loads(payload)
    assert decoded == {
        "specversion": "1.0",
        "type": "com.agentarea.mcp.instance.created",
        "source": "agentarea-api",
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "time": event["time"],
        "datacontenttype": "application/json",
        "correlationid": "req-123",
        "data": {"instance_id": "abc", "name": "my-mcp", "server_spec_id": "spec-1"},
    }


def test_channel_routing_for_reverse_dns_types():
    # Reverse-DNS com.agentarea.* maps to agentarea.events.*
    assert (
        get_channel_for_event_type("com.agentarea.mcp.instance.created")
        == "agentarea.events.mcp.instance.created"
    )
    # Non-com types are namespaced under agentarea.events.
    assert get_channel_for_event_type("workflow.TaskStarted") == (
        "agentarea.events.workflow.TaskStarted"
    )
