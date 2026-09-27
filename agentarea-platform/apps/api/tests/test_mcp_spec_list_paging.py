"""Paging of the MCP spec list, as the REST route and the platform tool ask for it."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import mcp_servers_specifications
from agentarea_api.tools.mcp_servers_toolset import MCPServersToolset
from agentarea_common.auth.context import UserContext
from agentarea_common.base.pagination import PaginationParams

CALLER = UserContext(user_id="user-a", workspace_id="ws-a")


async def test_asking_by_id_returns_every_spec_asked_for(monkeypatch):
    """The default page size is 50; a page asking for 60 specs by id wants all 60."""
    monkeypatch.setattr(
        mcp_servers_specifications, "readable_resource_ids", AsyncMock(return_value=set())
    )
    service = AsyncMock()
    service.list_servers.return_value = ([], 0)
    ids = [uuid4() for _ in range(60)]

    await mcp_servers_specifications.list_mcp_servers(
        user_context=CALLER,
        pagination=PaginationParams(page=3, page_size=50, search=None),
        status=None,
        is_public=None,
        tag=None,
        ids=ids,
        mcp_server_service=service,
    )

    kwargs = service.list_servers.await_args.kwargs
    assert (kwargs["limit"], kwargs["offset"]) == (60, 0)
    assert kwargs["spec_ids"] == [str(i) for i in ids]


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (-1, 0), (10, -5)])
async def test_the_spec_tool_refuses_a_page_it_cannot_serve(limit, offset):
    result = json.loads(await MCPServersToolset().list_specs(limit=limit, offset=offset))

    assert "error" in result
