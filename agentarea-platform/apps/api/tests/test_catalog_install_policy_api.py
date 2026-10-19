"""A catalog install the policy refuses answers 403 through the HTTP routes (ADR-0044).

The routes ask nothing themselves: the services' one enforcement point
(``CatalogInstallGuard``) refuses before anything is written, and the refusal
reaches the caller as 403 with the rule that decided it. The decision and
every install path are covered at the service
(``libs/agents/tests/test_catalog_install_policy_paths.py``); here the service
is a stand-in that refuses.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.skill_service import SkillService
from agentarea_api.api.deps.services import get_agent_service
from agentarea_api.api.v1 import agents, skills
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.exceptions import register_error_handlers
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

CALLER = UserContext(user_id="u", workspace_id="acme", admin_workspaces=["acme"])
REFUSAL = CatalogInstallRefusedError(
    "Install refused by policy: rule registry_trust:community denies it"
)


@pytest.fixture
async def client():
    skill_service = AsyncMock(spec=SkillService)
    skill_service.install_catalog_skill.side_effect = REFUSAL
    agent_service = AsyncMock(spec=AgentService)
    agent_service.get.return_value = None
    agent_service.install_catalog_agent.side_effect = REFUSAL
    app = FastAPI()
    register_error_handlers(app)
    for module in (skills, agents):
        app.include_router(module.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_user_context] = lambda: CALLER
    app.dependency_overrides[skills.get_skill_service] = lambda: skill_service
    app.dependency_overrides[get_agent_service] = lambda: agent_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("kind", ["skills", "agents"])
async def test_a_refused_install_answers_403_with_the_rule(client, kind):
    response = await client.post(f"/v1/workspaces/acme/{kind}/{uuid4()}/install")

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == str(REFUSAL)
