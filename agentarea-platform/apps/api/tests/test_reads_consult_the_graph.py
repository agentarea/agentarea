"""A workspace member reads what the graph says they may read, not the table.

Until 2026-09-23 every read endpoint answered from the workspace column alone.
That column says *whose* data a row is; it never said which member may see it,
so "member of the workspace" and "may read everything in it" were the same
sentence and neither was written down anywhere.

They are now separate: joining a workspace grants ``project:<ws>-root#reader``
(``workspaces.memberships.workspace_baseline_role``), and reads consult the
graph. The usual answer is still "all of it" -- the point is that revoking the
role now removes the rows instead of leaving a tuple nobody consults.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service
from agentarea_api.main import app
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.openfga_permission import OpenFGAPermissionService
from agentarea_common.auth.permission import PermissionService
from agentarea_common.config.database import get_db_session
from agentarea_common.di.container import get_container
from agentarea_common.rebac.openfga_client import OpenFGAClient
from httpx import ASGITransport, AsyncClient

WORKSPACE = "ws-acme"


def _agent(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        slug=name.lower(),
        description="",
        instruction="",
        model_id=str(uuid4()),
        status="active",
        tools=[],
        events_config={},
        planning=False,
        a2ui_enabled=False,
        agent_type="stateless",
        skills=[],
        is_catalog=False,
        registry_item_id=None,
        update_available=False,
    )


@pytest.fixture
def graph():
    """The real PDP over a stubbed graph, so the verb mapping is exercised too."""
    client = AsyncMock(spec=OpenFGAClient)
    client.list_objects.return_value = []
    container = get_container()
    container.register_singleton(OpenFGAClient, client)
    container.register_singleton(PermissionService, OpenFGAPermissionService(client))
    yield client
    container.clear()


@pytest.fixture
def agent_service(monkeypatch):
    service = AsyncMock()
    app.dependency_overrides[get_read_agent_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-member", workspace_id=WORKSPACE
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    # Approval flags are read from the database and are not what is under test.
    monkeypatch.setattr(
        "agentarea_api.api.v1.agents._overlay_approval_flags", AsyncMock(return_value=None)
    )
    yield service
    for dependency in (get_read_agent_service, get_user_context, get_db_session):
        app.dependency_overrides.pop(dependency, None)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.mark.asyncio
async def test_the_list_returns_only_the_rows_the_graph_allows(client, agent_service, graph):
    mine, theirs = _agent("Mine"), _agent("Theirs")
    agent_service.list.return_value = [mine, theirs]
    graph.list_objects.return_value = [str(mine.id)]

    response = await client.get("/v1/agents/")

    assert response.status_code == 200, response.text
    assert [item["name"] for item in response.json()] == ["Mine"]


@pytest.mark.asyncio
async def test_a_catalog_projection_stays_visible(client, agent_service, graph):
    """Catalog items are platform data with no tuples; gating them empties Explore."""
    builtin = _agent("Builtin")
    builtin.is_catalog = True
    agent_service.list.return_value = [builtin]
    graph.list_objects.return_value = []

    response = await client.get("/v1/agents/")

    assert response.status_code == 200, response.text
    assert [item["name"] for item in response.json()] == ["Builtin"]


@pytest.mark.asyncio
async def test_reading_one_agent_the_graph_refuses_is_403(client, agent_service, graph):
    hidden = _agent("Hidden")
    agent_service.get_by_slug.return_value = hidden
    agent_service.get_with_skills.return_value = hidden
    graph.check.return_value = MagicMock(allowed=False)

    response = await client.get(f"/v1/agents/{hidden.id}")

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_reading_one_agent_the_graph_allows_succeeds(client, agent_service, graph):
    """The gate must not lock out the person it exists to protect."""
    visible = _agent("Visible")
    agent_service.get_with_skills.return_value = visible
    graph.check.return_value = MagicMock(allowed=True)

    response = await client.get(f"/v1/agents/{visible.id}")

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Visible"
