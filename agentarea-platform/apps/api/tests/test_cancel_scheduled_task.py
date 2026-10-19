"""Cancelling a run booked for later must settle the stored task.

A delayed Temporal workflow that has not started runs none of its own code, so
nothing but the cancel route can record the cancellation; left alone the row
stays "scheduled" and the run keeps showing in the dashboard schedule.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import cancel_agent_task
from agentarea_common.auth.context import UserContext
from fastapi import HTTPException


def _services(status: str, *, cancelled: bool = True):
    agent_id = uuid4()
    task_id = uuid4()
    agent_service = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=agent_id)))
    task_service = SimpleNamespace(
        get_task=AsyncMock(
            return_value=SimpleNamespace(
                id=task_id, agent_id=agent_id, status=status, execution_id=None
            )
        ),
        cancel_task=AsyncMock(return_value=cancelled),
    )
    workflow_service = SimpleNamespace(cancel_task=AsyncMock(return_value=cancelled))
    return agent_id, task_id, agent_service, task_service, workflow_service


async def _cancel(agent_id, task_id, agent_service, task_service, workflow_service):
    return await cancel_agent_task(
        agent_id=agent_id,
        task_id=task_id,
        user_context=UserContext(user_id="u", workspace_id="w"),
        agent_service=agent_service,
        task_service=task_service,
        workflow_task_service=workflow_service,
    )


async def test_a_scheduled_task_is_cancelled_through_the_task_manager():
    agent_id, task_id, agents, tasks, workflows = _services("scheduled")
    result = await _cancel(agent_id, task_id, agents, tasks, workflows)
    assert result["status"] == "cancelled"
    tasks.cancel_task.assert_awaited_once_with(task_id)
    workflows.cancel_task.assert_not_awaited()


async def test_a_running_task_is_left_to_its_workflow():
    agent_id, task_id, agents, tasks, workflows = _services("running")
    await _cancel(agent_id, task_id, agents, tasks, workflows)
    workflows.cancel_task.assert_awaited_once_with(f"task-{task_id}")
    tasks.cancel_task.assert_not_awaited()


async def test_a_scheduled_task_that_could_not_be_cancelled_is_not_found():
    agent_id, task_id, agents, tasks, workflows = _services("scheduled", cancelled=False)
    with pytest.raises(HTTPException) as raised:
        await _cancel(agent_id, task_id, agents, tasks, workflows)
    assert raised.value.status_code == 404
