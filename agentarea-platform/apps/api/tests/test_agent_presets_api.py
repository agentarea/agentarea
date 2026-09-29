"""Presets are served ready to fill the agent-create form, and the tools list says what groups.

A preset is a catalog agent tagged ``preset``: its tools, the catalog skills it
names, its trigger templates and instruction. The form applies it as is, so the
API validates it on the way out; a broken catalog entry is an error, not a
preset that quietly loses its triggers.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_agents.application.agent_service import AgentPreset
from agentarea_agents.infrastructure.catalog_agent_repository import CatalogAgentItem
from agentarea_api.api.deps.services import get_read_agent_service
from agentarea_api.api.v1 import agents
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _preset(spec: dict, *, skills=(), unavailable=()) -> AgentPreset:
    item = CatalogAgentItem(
        id="11111111-1111-1111-1111-111111111111",
        name="AgentArea Claw",
        description="Personal assistant",
        version="1.0.0",
        spec=spec,
        installed_entity_id=None,
        installed_version=None,
    )
    return AgentPreset(
        item=item,
        skills=list(skills),
        unavailable_skills=list(unavailable),
        triggers=list(spec.get("triggers") or []),
    )


@pytest.fixture
def service():
    return AsyncMock()


@pytest.fixture
def app(service):
    app = FastAPI()
    app.include_router(agents.router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-a", workspace_id="workspace-a"
    )
    app.dependency_overrides[get_read_agent_service] = lambda: service
    return app


async def _get(app, path):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_a_preset_carries_tools_skills_triggers_and_instruction(app, service):
    skill = SimpleNamespace(id="skill-1", name="brainstorming--obra--abc", description="Ideas")
    service.list_presets.return_value = [
        _preset(
            {
                "instruction": "Be helpful.",
                "preferred_models": ["gpt-4o"],
                "tools": [{"type": "code", "name": "agentarea/shell"}],
                "triggers": [
                    {
                        "name": "Heartbeat",
                        "trigger_type": "cron",
                        "cron_expression": "*/30 * * * *",
                        "task_parameters": {"text": "Check in."},
                    }
                ],
            },
            skills=[skill],
            unavailable=["writing-plans--obra"],
        )
    ]

    response = await _get(app, "/v1/agents/presets")

    assert response.status_code == 200, response.text
    (preset,) = response.json()
    assert preset["instruction"] == "Be helpful."
    assert preset["tools"] == [{"type": "code", "name": "agentarea/shell", "settings": None}]
    assert preset["skills"] == [
        {"id": "skill-1", "name": "brainstorming--obra--abc", "description": "Ideas"}
    ]
    assert preset["unavailable_skills"] == ["writing-plans--obra"]
    assert preset["triggers"][0]["cron_expression"] == "*/30 * * * *"


async def test_a_malformed_catalog_preset_is_an_error_not_a_smaller_preset(app, service):
    service.list_presets.return_value = [
        _preset({"tools": [], "triggers": [{"name": "Broken", "trigger_type": "sometimes"}]})
    ]

    response = await _get(app, "/v1/agents/presets")

    assert response.status_code == 500
    assert "AgentArea Claw" in response.json()["detail"]


async def test_toolsets_that_only_work_together_share_a_group(app):
    response = await _get(app, "/v1/agents/tools?include=code")

    assert response.status_code == 200, response.text
    groups = {tool["name"]: tool["group"] for tool in response.json()}
    assert groups["agentarea/shell"] == "sandbox"
    assert groups["agentarea/files"] == "sandbox"
    assert groups["agentarea/workspace_files"] == "sandbox"
    assert groups["agentarea/web"] is None
