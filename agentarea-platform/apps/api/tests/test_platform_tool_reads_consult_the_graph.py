"""Platform tools read through the graph the same way the REST listings do.

``GET /v1/agents``, ``/v1/skills``, ``/v1/clients`` and ``/v1/mcp-servers``
narrow their rows to what OpenFGA says the caller may read, and the detail
routes ask the PDP. The matching tools returned every row the workspace held,
so revoking someone's read on an agent removed it from the UI and left it in
``agents_list``. Here the real PDP runs over a stubbed graph.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.tools import skills_toolset
from agentarea_agents.tools.skills_toolset import SkillsToolset
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.tools import agents_toolset, clients_toolset, mcp_servers_toolset
from agentarea_api.tools.agents_toolset import AgentsToolset
from agentarea_api.tools.clients_toolset import ClientsToolset
from agentarea_api.tools.mcp_servers_toolset import MCPServersToolset
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.openfga_permission import OpenFGAPermissionService
from agentarea_common.auth.permission import PermissionService
from agentarea_common.di.container import get_container
from agentarea_common.rebac.openfga_client import OpenFGAClient

CALLER = UserContext(user_id="user-member", workspace_id="ws-acme", admin_workspaces=[])


@pytest.fixture
def graph():
    client = AsyncMock(spec=OpenFGAClient)
    client.list_objects.return_value = []
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(OpenFGAClient, client)
    container.register_singleton(PermissionService, OpenFGAPermissionService(client))
    with use_mcp_user_context(CALLER):
        yield client
    container._singletons.clear()
    container._singletons.update(saved)


def _context(monkeypatch, module) -> None:
    @asynccontextmanager
    async def _ctx():
        yield AsyncMock(), CALLER, MagicMock(), AsyncMock(), AsyncMock()

    monkeypatch.setattr(module, "platform_context", _ctx)
    monkeypatch.setattr(module, "platform_read_context", _ctx)


def _row(name: str, **extra) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name=name, description="", **extra)


@pytest.mark.asyncio
async def test_agents_list_returns_only_the_rows_the_graph_allows(graph, monkeypatch) -> None:
    mine, theirs = _row("Mine"), _row("Theirs")
    service = MagicMock(list=AsyncMock(return_value=[mine, theirs]))
    _context(monkeypatch, agents_toolset)
    monkeypatch.setattr(agents_toolset, "_build_service", lambda *_: service)
    graph.list_objects.return_value = [str(mine.id)]

    result = json.loads(await AgentsToolset().list())

    assert [row["name"] for row in result] == ["Mine"]


@pytest.mark.asyncio
async def test_skills_list_returns_only_the_rows_the_graph_allows(graph, monkeypatch) -> None:
    mine, theirs = _row("mine"), _row("theirs")

    class _Skills:
        def __init__(self, **_kwargs) -> None:
            pass

        async def list(self):
            return [mine, theirs]

    _context(monkeypatch, skills_toolset)
    monkeypatch.setattr("agentarea_agents.application.skill_service.SkillService", _Skills)
    monkeypatch.setattr(skills_toolset, "_skill_summary", lambda s: {"name": s.name})
    graph.list_objects.return_value = [str(mine.id)]

    result = json.loads(await SkillsToolset().list())

    assert [row["name"] for row in result] == ["mine"]


@pytest.mark.asyncio
async def test_clients_list_is_narrowed_to_the_readable_ids(graph, monkeypatch) -> None:
    readable = str(uuid4())
    service = MagicMock(list=AsyncMock(return_value=[]))
    _context(monkeypatch, clients_toolset)
    monkeypatch.setattr(clients_toolset, "_build_service", lambda *_: service)
    graph.list_objects.return_value = [readable]

    await ClientsToolset().list()

    assert service.list.await_args.kwargs["ids"] == {readable}


def _spec_service(monkeypatch, server) -> MagicMock:
    service = MagicMock(
        get=AsyncMock(return_value=server),
        list_servers=AsyncMock(return_value=([], 0)),
    )
    monkeypatch.setattr(
        "agentarea_mcp.application.service.MCPServerService", lambda **_kwargs: service
    )
    _context(monkeypatch, mcp_servers_toolset)
    return service


def _spec(**overrides) -> SimpleNamespace:
    fields = {
        "id": uuid4(),
        "name": "github",
        "description": "",
        "version": "1",
        "tags": [],
        "is_public": False,
        "remote_url": None,
        "docker_image_url": None,
        "status": "active",
        "env_schema": [],
        "registry_url": None,
        "is_catalog": False,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.mark.asyncio
async def test_reading_a_tenant_spec_the_graph_refuses_is_refused(graph, monkeypatch) -> None:
    spec = _spec()
    _spec_service(monkeypatch, spec)
    graph.check.return_value = MagicMock(allowed=False)

    result = json.loads(await MCPServersToolset().get_spec(spec_id=str(spec.id)))

    assert result == {"error": "Permission denied"}


@pytest.mark.asyncio
async def test_a_catalog_spec_stays_readable(graph, monkeypatch) -> None:
    """Catalog specs are platform data with no tuples; gating them empties Explore."""
    spec = _spec(is_catalog=True)
    _spec_service(monkeypatch, spec)
    graph.check.return_value = MagicMock(allowed=False)

    result = json.loads(await MCPServersToolset().get_spec(spec_id=str(spec.id)))

    assert result["name"] == "github"
    graph.check.assert_not_called()


@pytest.mark.asyncio
async def test_spec_list_is_narrowed_to_the_readable_ids(graph, monkeypatch) -> None:
    readable = str(uuid4())
    service = _spec_service(monkeypatch, None)
    graph.list_objects.return_value = [readable]

    await MCPServersToolset().list_specs()

    assert service.list_servers.await_args.kwargs["ids"] == {readable}
