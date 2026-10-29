"""A run's ``model_override`` reaches the agent configuration it is built with."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from agentarea_execution.workflows.constants import Activities
from agentarea_execution.workflows.models import AgentGoal

MODEL = "aad7c8d9-756e-58e0-b42f-80ba341616df"


class _Built(Exception):
    pass


async def _config_request(monkeypatch, parameters: dict):
    from agentarea_execution.workflows import agent_execution_workflow as workflow_module

    seen = {}

    async def execute_activity(name, *, args, **_kwargs):
        assert name == Activities.BUILD_AGENT_CONFIG
        seen["request"] = args[0]
        raise _Built

    monkeypatch.setattr(workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflow_module.workflow, "logger", MagicMock())
    flow = workflow_module.AgentExecutionWorkflow()
    flow.state.agent_id = str(uuid4())
    flow.state.task_id = str(uuid4())
    flow.state.goal = AgentGoal(
        id="goal",
        description="Work",
        context=parameters,
        success_criteria=[],
        max_iterations=10,
        requires_human_approval=False,
    )
    with pytest.raises(_Built):
        await flow._initialize_agent_config()
    return seen["request"]


@pytest.mark.asyncio
async def test_the_override_is_the_model_the_config_is_built_with(monkeypatch):
    request = await _config_request(monkeypatch, {"model_override": MODEL})

    assert request.override_model == MODEL


@pytest.mark.asyncio
async def test_without_an_override_the_agent_model_is_used(monkeypatch):
    request = await _config_request(monkeypatch, {"topic": "x"})

    assert request.override_model is None
