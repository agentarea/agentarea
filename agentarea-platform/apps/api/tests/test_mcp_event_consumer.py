"""Tests for the MCP status-change consumer on the new event bus (ADR-0018).

The Go MCP manager XADDs CloudEvents-shaped stream fields; the API consumes
them via ``RedisStreamsEventBus`` and logs them (observability only). These
tests pin the Go->Python wire contract and the handler behaviour without a
live Redis.
"""

import json
import logging
from uuid import uuid4

import pytest
from agentarea_api.api.events.mcp_events import (
    MCP_STATUS_CHANGED_TYPE,
    handle_mcp_status_changed,
)
from agentarea_common.events.adapters.redis_streams import decode
from agentarea_common.events.ports import IntegrationEvent


def _go_style_fields(instance_id: str = "inst-1", status: str = "running") -> dict[str, str]:
    """Mimic the Redis stream fields the Go MCP manager XADDs."""
    return {
        "ce_id": str(uuid4()),
        "ce_type": MCP_STATUS_CHANGED_TYPE,
        "ce_source": "agentarea-mcp-manager",
        "ce_time": "2026-06-29T10:00:00Z",
        "ce_specversion": "1.0",
        "ce_datacontenttype": "application/json",
        "ce_subject": instance_id,
        "data": json.dumps(
            {
                "instance_id": instance_id,
                "name": "svc",
                "status": status,
                "container_id": "c-1",
                "url": "http://localhost:8080",
            }
        ),
    }


def test_go_fields_decode_to_integration_event():
    evt = decode(_go_style_fields(instance_id="inst-9", status="failed"))
    assert isinstance(evt, IntegrationEvent)
    assert evt.type == MCP_STATUS_CHANGED_TYPE
    assert evt.subject == "inst-9"
    assert evt.data["instance_id"] == "inst-9"
    assert evt.data["status"] == "failed"


@pytest.mark.asyncio
async def test_handler_logs_status(caplog):
    evt = decode(_go_style_fields(instance_id="inst-2", status="running"))
    with caplog.at_level(logging.INFO):
        await handle_mcp_status_changed(evt)
    assert "inst-2" in caplog.text
    assert "running" in caplog.text


@pytest.mark.asyncio
async def test_handler_skips_missing_instance_id(caplog):
    evt = IntegrationEvent(
        type=MCP_STATUS_CHANGED_TYPE, source="agentarea-mcp-manager", data={"status": "running"}
    )
    with caplog.at_level(logging.WARNING):
        await handle_mcp_status_changed(evt)
    assert "missing instance_id" in caplog.text
