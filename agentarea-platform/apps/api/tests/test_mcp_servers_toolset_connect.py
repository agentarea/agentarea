"""An agent that provisions a connection hands the person a link to connect it.

The MCP tools that create, change, read or verify an instance say so when it
waits on a credential, and to a client that declared URL elicitation the read
and verify tools ask it to open the link directly.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import agentarea_common.auth.permission as permission
import agentarea_mcp.application.service as mcp_service
import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_agents_sdk.mcp_server.elicitation import mcp_call_context
from agentarea_api.api.v1 import mcp_oauth_connect
from agentarea_api.tools import mcp_servers_toolset
from agentarea_api.tools.mcp_servers_toolset import MCPServersToolset
from agentarea_common.auth.context import UserContext
from mcp.server.mcpserver import Context
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    InputRequiredResult,
    UrlElicitationCapability,
)

CALLER = UserContext(user_id="user-a", workspace_id="ws-a", workspace_slug="acme")
FAILED = {"status": "failed", "error": {"code": "list_tools_failed", "message": "HTTP 401"}}


def _instance(verification: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="GitHub",
        description=None,
        verification=verification,
        server_spec_id=str(uuid4()),
        last_dispatch=None,
        tools=[],
    )


@pytest.fixture
def harness(monkeypatch):
    @asynccontextmanager
    async def _ctx():
        yield AsyncMock(), CALLER, MagicMock(), AsyncMock(), AsyncMock()

    monkeypatch.setattr(mcp_servers_toolset, "platform_context", _ctx)
    monkeypatch.setattr(mcp_servers_toolset, "platform_read_context", _ctx)
    monkeypatch.setattr(
        mcp_oauth_connect,
        "get_settings",
        lambda: SimpleNamespace(app=SimpleNamespace(APP_URL="https://app.example")),
    )
    service = MagicMock()

    def _build(**_kwargs):
        return service

    monkeypatch.setattr(mcp_service, "MCPServerInstanceService", _build)
    monkeypatch.setattr(permission, "require_permission", AsyncMock())
    with use_mcp_user_context(CALLER):
        yield service


def _connect_url(instance) -> str:
    return f"https://app.example/w/acme/connect/{instance.id}"


def _modern_elicitation_context() -> Context:
    request = SimpleNamespace(
        protocol_version="2026-07-28",
        session=SimpleNamespace(
            client_capabilities=ClientCapabilities(
                elicitation=ElicitationCapability(url=UrlElicitationCapability())
            )
        ),
    )
    return Context(request_context=request)


@pytest.mark.asyncio
async def test_create_returns_the_instance_with_a_connect_link(harness):
    instance = _instance(FAILED)
    harness.create_instance = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=True)

    with mcp_call_context(_modern_elicitation_context()):
        raw = await MCPServersToolset().create(
            name="GitHub", json_spec_json="{}", server_spec_id=str(uuid4())
        )

    result = json.loads(raw)
    assert result["id"] == str(instance.id)
    assert result["action_required"] == {
        "type": "connect",
        "url": _connect_url(instance),
        "message": f"Open this link to connect GitHub: {_connect_url(instance)}",
    }
    harness.needs_connecting.assert_awaited_once_with(instance, probe=True)


@pytest.mark.asyncio
async def test_update_returns_a_connect_link_while_the_instance_waits_on_one(harness):
    instance = _instance(FAILED)
    harness.update_instance = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=True)

    result = json.loads(await MCPServersToolset().update(str(instance.id), name="GitHub"))

    assert result["action_required"]["url"] == _connect_url(instance)
    harness.needs_connecting.assert_awaited_once_with(instance, probe=True)


@pytest.mark.asyncio
async def test_get_of_a_working_instance_has_no_action(harness):
    instance = _instance({"status": "succeeded"})
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=False)

    result = json.loads(await MCPServersToolset().get(str(instance.id)))

    assert "action_required" not in result


@pytest.mark.asyncio
async def test_verify_gives_the_link_to_a_client_without_elicitation(harness):
    instance = _instance(FAILED)
    harness.verify_instance = AsyncMock(return_value=dict(FAILED))
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=True)

    result = json.loads(await MCPServersToolset().verify(str(instance.id)))

    assert result["status"] == "failed"
    assert result["action_required"]["url"] == _connect_url(instance)
    harness.needs_connecting.assert_awaited_once_with(instance, probe=True)


@pytest.mark.asyncio
async def test_verify_asks_an_eliciting_client_to_open_the_link(harness):
    instance = _instance(FAILED)
    harness.verify_instance = AsyncMock(return_value=dict(FAILED))
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=True)

    with mcp_call_context(_modern_elicitation_context()):
        result = await MCPServersToolset().verify(str(instance.id))

    assert isinstance(result, InputRequiredResult)
    (request,) = result.input_requests.values()
    assert (request.params.mode, request.params.url) == ("url", _connect_url(instance))


@pytest.mark.asyncio
async def test_get_asks_an_eliciting_client_to_open_the_link(harness):
    instance = _instance(FAILED)
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=True)

    with mcp_call_context(_modern_elicitation_context()):
        result = await MCPServersToolset().get(str(instance.id))

    assert isinstance(result, InputRequiredResult)


@pytest.mark.asyncio
async def test_get_never_probes_the_upstream(harness):
    instance = _instance({"status": "in_progress"})
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=False)

    result = json.loads(await MCPServersToolset().get(str(instance.id)))

    assert "action_required" not in result
    harness.needs_connecting.assert_awaited_once_with(instance, probe=False)
    harness.probe_instance_auth.assert_not_called()


AUTH_REQUIRED = {
    "status": "failed",
    "error": {"code": "auth_required", "message": "GitHub requires sign-in or a key"},
}


def _records_auth_required(instance):
    async def _needs_connecting(_instance, *, probe):
        instance.verification = AUTH_REQUIRED
        return True

    return _needs_connecting


@pytest.mark.asyncio
async def test_create_reports_the_verification_the_probe_recorded(harness):
    instance = _instance(FAILED)
    harness.create_instance = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(side_effect=_records_auth_required(instance))

    raw = await MCPServersToolset().create(
        name="GitHub", json_spec_json="{}", server_spec_id=str(uuid4())
    )

    assert json.loads(raw)["verification"] == AUTH_REQUIRED


@pytest.mark.asyncio
async def test_update_reports_the_verification_the_probe_recorded(harness):
    instance = _instance(FAILED)
    harness.update_instance = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(side_effect=_records_auth_required(instance))

    raw = await MCPServersToolset().update(str(instance.id), name="GitHub")

    assert json.loads(raw)["verification"] == AUTH_REQUIRED


@pytest.mark.asyncio
async def test_verify_reports_the_verification_the_probe_recorded(harness):
    instance = _instance(FAILED)
    harness.verify_instance = AsyncMock(return_value=dict(FAILED))
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(side_effect=_records_auth_required(instance))

    result = json.loads(await MCPServersToolset().verify(str(instance.id)))

    assert {key: result[key] for key in AUTH_REQUIRED} == AUTH_REQUIRED
    assert result["action_required"]["url"] == _connect_url(instance)


def _tools_fixture() -> list[dict]:
    return [
        {
            "name": "list_leads",
            "description": "List leads in a campaign",
            "inputSchema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "delete_lead",
            "description": "Delete a lead",
            "inputSchema": {"type": "object", "properties": {"lead_id": {"type": "string"}}},
            "annotations": {"destructiveHint": True},
        },
        {
            "name": "send_email",
            "description": "Send an email",
            "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}}},
        },
    ]


@pytest.mark.asyncio
async def test_get_default_tool_list_is_compact_names_with_safety_hints(harness):
    instance = _instance({"status": "succeeded"})
    instance.tools = _tools_fixture()
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=False)

    result = json.loads(await MCPServersToolset().get(str(instance.id)))

    assert result["tool_count"] == 3
    assert result["tools"] == [
        "list_leads (read-only)",
        "delete_lead (destructive)",
        "send_email",
    ]
    assert "tool_details" not in result
    assert "unknown_tools" not in result
    assert all(isinstance(entry, str) for entry in result["tools"])
    assert "inputSchema" not in json.dumps(result)


@pytest.mark.asyncio
async def test_get_with_tools_param_returns_details_for_named_tools_only(harness):
    instance = _instance({"status": "succeeded"})
    instance.tools = _tools_fixture()
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=False)

    result = json.loads(
        await MCPServersToolset().get(
            str(instance.id), tools=["list_leads", "send_email", "does_not_exist"]
        )
    )

    assert result["tool_details"] == [
        {
            "name": "list_leads",
            "description": "List leads in a campaign",
            "annotations": {"readOnlyHint": True},
        },
        {"name": "send_email", "description": "Send an email"},
    ]
    assert result["unknown_tools"] == ["does_not_exist"]
    for detail in result["tool_details"]:
        assert "inputSchema" not in detail
    # the compact default list is still present alongside the details
    assert result["tool_count"] == 3
    assert result["tools"] == [
        "list_leads (read-only)",
        "delete_lead (destructive)",
        "send_email",
    ]


@pytest.mark.asyncio
async def test_verify_of_an_instance_needing_nothing_reports_what_verification_returned(harness):
    succeeded = {"status": "succeeded", "error": None}
    instance = _instance({"status": "in_progress"})
    harness.verify_instance = AsyncMock(return_value=dict(succeeded))
    harness.get = AsyncMock(return_value=instance)
    harness.needs_connecting = AsyncMock(return_value=False)

    result = json.loads(await MCPServersToolset().verify(str(instance.id)))

    assert result == succeeded
