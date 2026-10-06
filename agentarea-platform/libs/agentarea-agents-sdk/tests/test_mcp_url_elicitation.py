"""A tool sends the user to a URL through the client only when the client said it can."""

import json
from types import SimpleNamespace

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    ElicitResult,
    FormElicitationCapability,
    UrlElicitationCapability,
)

from agentarea_agents_sdk.mcp_server import create_mcp_server
from agentarea_agents_sdk.mcp_server.elicitation import mcp_call_context, url_elicitation
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

_CONNECT_URL = "https://app.example/w/acme/connect/0b6f"
_MESSAGE = f"Open this link to connect GitHub: {_CONNECT_URL}"


class _ConnectToolset(Toolset):
    @tool_method
    async def verify(self) -> str:
        """Report whether the connection works, asking the user to connect it if not."""
        elicitation = url_elicitation(_CONNECT_URL, _MESSAGE)
        if elicitation is not None:
            return elicitation
        return json.dumps({"status": "failed", "action_required": {"url": _CONNECT_URL}})


def _server_app(server):
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


async def _call_verify(**client_kwargs):
    server = create_mcp_server(toolsets=[_ConnectToolset()], name="Test", workspace_argument=False)
    app = _server_app(server)
    async with server.session_manager.run():
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            async with Client(
                streamable_http_client("http://test/", http_client=http_client), **client_kwargs
            ) as client:
                result = await client.call_tool("__connect_verify", {})
                return client.protocol_version, result


@pytest.mark.asyncio
async def test_a_client_that_declares_url_elicitation_is_asked_to_open_the_link():
    asked = []

    async def elicit(_context, params):
        asked.append(params)
        return ElicitResult(action="accept")

    version, result = await _call_verify(elicitation_callback=elicit)

    assert version == "2026-07-28"
    assert len(asked) == 1
    assert (asked[0].mode, asked[0].url, asked[0].message) == ("url", _CONNECT_URL, _MESSAGE)
    # The retry after the user consented answers with the tool's own result.
    assert json.loads(result.content[0].text)["action_required"] == {"url": _CONNECT_URL}


@pytest.mark.asyncio
async def test_a_client_without_elicitation_gets_the_link_in_the_result():
    version, result = await _call_verify()

    assert version == "2026-07-28"
    assert not result.is_error
    assert json.loads(result.content[0].text)["action_required"] == {"url": _CONNECT_URL}


@pytest.mark.asyncio
async def test_a_handshake_client_on_a_stateless_mount_gets_the_link_in_the_result():
    """Its capabilities ride ``initialize`` only, which no later tool call can see."""
    asked = []

    async def elicit(_context, params):
        asked.append(params)
        return ElicitResult(action="accept")

    version, result = await _call_verify(mode="legacy", elicitation_callback=elicit)

    assert version == "2025-11-25"
    assert asked == []
    assert not result.is_error
    assert json.loads(result.content[0].text)["action_required"] == {"url": _CONNECT_URL}


def _context(protocol_version: str, elicitation: ElicitationCapability | None) -> Context:
    request = SimpleNamespace(
        protocol_version=protocol_version,
        session=SimpleNamespace(
            client_capabilities=ClientCapabilities(elicitation=elicitation),
        ),
    )
    return Context(request_context=request)


def test_a_handshake_client_that_declared_url_elicitation_gets_the_required_error():
    context = _context("2025-11-25", ElicitationCapability(url=UrlElicitationCapability()))

    with mcp_call_context(context), pytest.raises(UrlElicitationRequiredError) as raised:
        url_elicitation(_CONNECT_URL, _MESSAGE)

    (elicitation,) = raised.value.elicitations
    assert (elicitation.url, elicitation.message) == (_CONNECT_URL, _MESSAGE)
    assert elicitation.elicitation_id


def test_a_client_with_form_elicitation_only_is_not_sent_a_url():
    context = _context("2026-07-28", ElicitationCapability(form=FormElicitationCapability()))

    with mcp_call_context(context):
        assert url_elicitation(_CONNECT_URL, _MESSAGE) is None


def test_outside_an_mcp_call_there_is_no_elicitation():
    assert url_elicitation(_CONNECT_URL, _MESSAGE) is None
