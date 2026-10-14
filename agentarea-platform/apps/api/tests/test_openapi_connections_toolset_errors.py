"""A connection the platform cannot create tells the MCP caller why."""

import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_api.tools import openapi_connections_toolset as module
from agentarea_api.tools.openapi_connections_toolset import OpenAPIConnectionsToolset

CAUSE = (
    "Could not fetch the spec from https://enter.tochka.com/doc/openapi/swagger.json: "
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
)


class _RefusingService:
    async def create_connection(self, _payload):
        raise ValueError(CAUSE)

    async def update_connection(self, _connection_id, _payload):
        raise ValueError(CAUSE)

    async def discover_tools(self, _connection_id):
        raise ValueError(CAUSE)


@pytest.fixture(autouse=True)
def _refusing_service(monkeypatch):
    @asynccontextmanager
    async def context():
        yield (None, SimpleNamespace(user_id="u1", workspace_id="ws-1"), object(), None, None)

    monkeypatch.setattr(module, "platform_context", context)
    monkeypatch.setattr(module, "_build_service", lambda *_args: _RefusingService())


async def test_create_reports_why_the_spec_could_not_be_fetched():
    with pytest.raises(ToolError, match="CERTIFICATE_VERIFY_FAILED"):
        await OpenAPIConnectionsToolset().create(
            name="Tochka",
            base_url="https://enter.tochka.com/uapi",
            spec_url="https://enter.tochka.com/doc/openapi/swagger.json",
        )


async def test_update_reports_why_it_was_refused():
    with pytest.raises(ToolError, match="CERTIFICATE_VERIFY_FAILED"):
        # Past the edit-permission check, which the tool-authz tests own.
        update = inspect.unwrap(OpenAPIConnectionsToolset.update)
        await update(
            OpenAPIConnectionsToolset(),
            connection_id="00000000-0000-0000-0000-000000000001",
            spec_url="https://enter.tochka.com/doc/openapi/swagger.json",
        )


async def test_discover_tools_reports_why_the_spec_could_not_be_fetched():
    with pytest.raises(ToolError, match="CERTIFICATE_VERIFY_FAILED"):
        discover_tools = inspect.unwrap(OpenAPIConnectionsToolset.discover_tools)
        await discover_tools(
            OpenAPIConnectionsToolset(), connection_id="00000000-0000-0000-0000-000000000001"
        )
