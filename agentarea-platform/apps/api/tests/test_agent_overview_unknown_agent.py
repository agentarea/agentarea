"""An agent's overview exists only for an agent that does.

Every figure on the overview is a filter on ``agent_id``, so an id the
workspace has never had answered 200 with zero spend, no tasks and nothing
upcoming: indistinguishable from an idle agent.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_read_agent_service
from agentarea_api.api.v1 import agent_overview
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.config.database import get_db_session
from fastapi import FastAPI
from fastapi.testclient import TestClient

AGENT_ID = uuid4()
URL = f"/v1/workspaces/acme/agents/{AGENT_ID}/overview"


@pytest.fixture
def env():
    result = MagicMock()
    result.one.return_value = SimpleNamespace(
        cost_today=0, cost_mtd=0, done_today=0, failed_today=0, last_activity=None
    )
    result.all.return_value = []
    result.scalars.return_value.all.return_value = []
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    agents = AsyncMock()

    app = FastAPI()
    app.include_router(agent_overview.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="u", workspace_id="ws"
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_read_agent_service] = lambda: agents
    return SimpleNamespace(client=TestClient(app), session=session, agents=agents)


def test_an_agent_not_in_the_workspace_is_a_404(env) -> None:
    env.agents.get.return_value = None

    response = env.client.get(URL)

    assert response.status_code == 404, response.text
    env.agents.get.assert_awaited_once_with(AGENT_ID)
    env.session.execute.assert_not_awaited()


def test_an_idle_agent_still_gets_its_overview(env) -> None:
    env.agents.get.return_value = SimpleNamespace(id=AGENT_ID, name="Helper")

    response = env.client.get(URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tasks_done_today"] == 0
    assert body["upcoming"] == []
