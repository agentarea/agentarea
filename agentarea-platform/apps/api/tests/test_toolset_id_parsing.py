"""An id the caller typed is parsed where it enters the tool, not deep in the service.

The MCP tools take ids as strings. A malformed one used to reach a DTO typed
``UUID`` and surface as a raw validation traceback; it is now refused with a
message that names the argument, before any database work.
"""

import json
from contextlib import asynccontextmanager

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.tools import mcp_servers_toolset, projects_toolset
from agentarea_api.tools.mcp_servers_toolset import MCPServersToolset
from agentarea_api.tools.projects_toolset import ProjectsToolset
from agentarea_common.auth.context import UserContext


@pytest.fixture(autouse=True)
def caller(monkeypatch):
    @asynccontextmanager
    async def _no_database():
        raise AssertionError("a malformed id must be refused before any database work")
        yield

    monkeypatch.setattr(projects_toolset, "platform_context", _no_database)
    monkeypatch.setattr(mcp_servers_toolset, "platform_context", _no_database)
    member = UserContext(user_id="user-1", workspace_id="ws-1", admin_workspaces=["ws-1"])
    with use_mcp_user_context(member):
        yield


@pytest.mark.asyncio
async def test_project_create_refuses_a_parent_that_is_not_a_uuid():
    result = json.loads(await ProjectsToolset().create(name="p", parent_project_id="nope"))

    assert "parent_project_id" in result["error"]


@pytest.mark.asyncio
async def test_project_update_refuses_a_parent_that_is_not_a_uuid():
    result = json.loads(
        await ProjectsToolset().update(
            project_id="00000000-0000-4000-8000-000000000001", parent_project_id="nope"
        )
    )

    assert "parent_project_id" in result["error"]


@pytest.mark.asyncio
async def test_mcp_instance_create_refuses_a_spec_id_that_is_not_a_uuid():
    result = json.loads(
        await MCPServersToolset().create(
            name="i", json_spec_json='{"type": "url"}', server_spec_id="nope"
        )
    )

    assert "server_spec_id" in result["error"]
