"""Creating an agent creates the triggers that start it, or nothing at all.

The agent form used to write "event subscriptions" onto the agent that nothing
ever acted on. Now the create request carries real trigger specs: each is
checked before the agent exists, and a failure part-way through removes what
was already made, so no agent is left silently missing its schedule or channel.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_secret_catalog_service,
    get_secret_manager,
    get_trigger_service,
)
from agentarea_api.api.v1 import _trigger_creation, agents
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.config.database import get_db_session
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets.catalog_service import SecretCatalogService
from agentarea_triggers.trigger_service import TriggerService, TriggerValidationError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_HEARTBEAT = {
    "name": "Heartbeat",
    "trigger_type": "cron",
    "cron_expression": "*/30 * * * *",
    "timezone": "UTC",
    "task_parameters": {"text": "Work through HEARTBEAT.md."},
}
_TELEGRAM = {
    "name": "Telegram",
    "trigger_type": "webhook",
    "webhook_type": "telegram",
    "channel_credentials": {"bot_token": "123:abc"},
    "task_parameters": {"text": "Reply to the message."},
}


_CHAT_MODEL, _DECISION_MODEL, _IMAGE_MODEL = str(uuid4()), str(uuid4()), str(uuid4())


class _ModelInstances:
    """The workspace's model instances an LLM condition may name."""

    _KINDS = {_CHAT_MODEL: "chat", _DECISION_MODEL: "decision", _IMAGE_MODEL: "image"}

    async def get_by_id(self, instance_id):
        kind = self._KINDS.get(str(instance_id))
        return SimpleNamespace(model_spec=SimpleNamespace(kind=kind)) if kind else None


async def _real_validation(trigger_data):
    # The route's pre-check runs the service's real configuration rules.
    service = object.__new__(TriggerService)
    service.trigger_repository = SimpleNamespace(
        webhook_id_in_use=AsyncMock(return_value=False)
    )
    service.model_instance_repository = _ModelInstances()
    await TriggerService._validate_trigger_configuration(service, trigger_data)


def _with_condition(**condition) -> dict:
    return {**_HEARTBEAT, "conditions": {"type": "llm", "description": "a refund", **condition}}


@pytest.fixture
def harness(monkeypatch):
    agent = Agent(name="Claw", slug="claw", instruction="", tools=[])
    agent.id = uuid4()
    agent.status = "active"
    agent_service = AsyncMock()
    agent_service.create_agent.return_value = agent

    created: list[SimpleNamespace] = []

    async def create_trigger(trigger_data):
        trigger = SimpleNamespace(
            id=uuid4(),
            agent_id=trigger_data.agent_id,
            webhook_type=trigger_data.webhook_type,
            webhook_id=trigger_data.webhook_id,
            is_active=True,
        )
        created.append(trigger)
        return trigger

    trigger_service = AsyncMock()
    trigger_service.validate_configuration.side_effect = _real_validation
    trigger_service.create_trigger.side_effect = create_trigger

    secret_manager = AsyncMock(spec=BaseSecretManager)
    webhook_service = AsyncMock()

    app = FastAPI()
    app.include_router(agents.router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-a", workspace_id="workspace-a"
    )
    app.dependency_overrides[get_agent_service] = lambda: agent_service
    app.dependency_overrides[get_trigger_service] = lambda: trigger_service
    app.dependency_overrides[get_secret_manager] = lambda: secret_manager
    app.dependency_overrides[get_secret_catalog_service] = lambda: AsyncMock(
        spec=SecretCatalogService
    )
    app.dependency_overrides[_trigger_creation.get_channel_webhook_service] = lambda: (
        webhook_service
    )
    app.dependency_overrides[get_db_session] = lambda: None
    monkeypatch.setattr(agents, "_grant_agent_owner", AsyncMock())
    monkeypatch.setattr(agents, "_overlay_approval_flags", AsyncMock())

    return SimpleNamespace(
        app=app,
        agent=agent,
        agent_service=agent_service,
        trigger_service=trigger_service,
        secret_manager=secret_manager,
        webhook_service=webhook_service,
        created=created,
    )


async def _post(harness, body):
    transport = ASGITransport(app=harness.app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/v1/agents/", json=body)


async def test_agent_and_its_triggers_are_created_together(harness):
    response = await _post(
        harness, {"name": "Claw", "tools": [], "triggers": [_HEARTBEAT, _TELEGRAM]}
    )

    assert response.status_code == 200, response.text
    payload = harness.agent_service.create_agent.await_args.args[0]
    assert not hasattr(payload, "triggers")
    assert [t.agent_id for t in harness.created] == [harness.agent.id, harness.agent.id]
    harness.secret_manager.set_secret.assert_awaited_once()
    harness.webhook_service.register.assert_awaited_once()


async def test_tools_must_be_given_explicitly(harness):
    response = await _post(harness, {"name": "Claw"})

    assert response.status_code == 422
    harness.agent_service.create_agent.assert_not_awaited()


async def test_a_bad_trigger_is_refused_before_the_agent_exists(harness):
    bad = {**_HEARTBEAT, "cron_expression": "*/30 * *"}

    response = await _post(harness, {"name": "Claw", "tools": [], "triggers": [_TELEGRAM, bad]})

    assert response.status_code == 400
    assert "Heartbeat" in response.json()["detail"]
    harness.agent_service.create_agent.assert_not_awaited()
    harness.trigger_service.create_trigger.assert_not_awaited()


async def test_a_trigger_failing_on_create_takes_the_agent_with_it(harness):
    original = harness.trigger_service.create_trigger.side_effect

    async def fail_second(trigger_data):
        if harness.created:
            raise TriggerValidationError("agent vanished")
        return await original(trigger_data)

    harness.trigger_service.create_trigger.side_effect = fail_second

    response = await _post(
        harness, {"name": "Claw", "tools": [], "triggers": [_HEARTBEAT, _TELEGRAM]}
    )

    assert response.status_code == 400
    (first,) = harness.created
    harness.trigger_service.delete_trigger.assert_awaited_once_with(first.id)
    harness.agent_service.delete_agent.assert_awaited_once_with(harness.agent.id)
    agents._grant_agent_owner.assert_not_awaited()


async def test_a_disabled_trigger_is_created_switched_off(harness):
    response = await _post(
        harness, {"name": "Claw", "tools": [], "triggers": [{**_HEARTBEAT, "enabled": False}]}
    )

    assert response.status_code == 200, response.text
    (trigger,) = harness.created
    harness.trigger_service.disable_trigger.assert_awaited_once_with(trigger.id)


@pytest.mark.parametrize("model_id", [_CHAT_MODEL, _DECISION_MODEL])
async def test_a_trigger_whose_condition_names_a_chat_or_decision_model_is_created(
    harness, model_id
):
    response = await _post(
        harness,
        {"name": "Claw", "tools": [], "triggers": [_with_condition(model_id=model_id)]},
    )

    assert response.status_code == 200, response.text
    assert len(harness.created) == 1


@pytest.mark.parametrize(
    "condition, reason",
    [({"model_id": _IMAGE_MODEL}, "image model"), ({}, "needs a model_id")],
)
async def test_a_condition_without_a_usable_model_is_refused_before_the_agent_exists(
    harness, condition, reason
):
    response = await _post(
        harness, {"name": "Claw", "tools": [], "triggers": [_with_condition(**condition)]}
    )

    assert response.status_code == 400
    assert reason in response.json()["detail"]
    harness.agent_service.create_agent.assert_not_awaited()
    harness.trigger_service.create_trigger.assert_not_awaited()
