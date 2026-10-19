"""Stopping, pausing and resuming a run reach the workflow it is, in the state it is in.

A delegated child is acted on under the workflow id its row records: the parent
starts it as ``delegation-<parent>-<call>``, not ``task-<id>``, and addressing it
by the task id found no workflow. A resume reaches only a run that is paused.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import (
    cancel_agent_task,
    pause_agent_task,
    resume_agent_task,
    task_execution_id,
)
from agentarea_common.auth.context import UserContext
from fastapi import HTTPException

CHILD_WORKFLOW = "delegation-task-parent-call_1"


def _child(agent_id, task_id):
    return SimpleNamespace(
        id=task_id, agent_id=agent_id, status="running", execution_id=CHILD_WORKFLOW
    )


def test_a_task_without_a_recorded_workflow_uses_the_id_its_start_uses():
    task_id = uuid4()
    assert task_execution_id(SimpleNamespace(id=task_id, execution_id=None)) == f"task-{task_id}"


async def test_cancelling_a_delegated_child_cancels_its_own_workflow():
    agent_id, task_id = uuid4(), uuid4()
    workflows = SimpleNamespace(cancel_task=AsyncMock(return_value=True))
    result = await cancel_agent_task(
        agent_id=agent_id,
        task_id=task_id,
        user_context=UserContext(user_id="u", workspace_id="w"),
        agent_service=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=agent_id))),
        task_service=SimpleNamespace(get_task=AsyncMock(return_value=_child(agent_id, task_id))),
        workflow_task_service=workflows,
    )
    workflows.cancel_task.assert_awaited_once_with(CHILD_WORKFLOW)
    assert result["execution_id"] == CHILD_WORKFLOW


async def test_pausing_a_delegated_child_signals_its_own_workflow():
    agent_id, task_id = uuid4(), uuid4()
    workflows = SimpleNamespace(
        get_workflow_status=AsyncMock(return_value={"status": "running"}),
        get_live_state=AsyncMock(return_value=None),
        pause_task=AsyncMock(return_value=True),
    )
    await pause_agent_task(
        agent_id=agent_id,
        task_id=task_id,
        user_context=UserContext(user_id="u", workspace_id="w"),
        agent_service=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=agent_id))),
        task_service=SimpleNamespace(get_task=AsyncMock(return_value=_child(agent_id, task_id))),
        workflow_task_service=workflows,
    )
    workflows.get_workflow_status.assert_awaited_once_with(CHILD_WORKFLOW)
    workflows.pause_task.assert_awaited_once_with(CHILD_WORKFLOW)


async def test_resuming_a_run_that_is_not_paused_is_refused():
    agent_id, task_id = uuid4(), uuid4()
    workflows = SimpleNamespace(
        get_workflow_status=AsyncMock(return_value={"status": "running"}),
        get_live_state=AsyncMock(return_value={"paused": False}),
        resume_task=AsyncMock(return_value=True),
    )
    with pytest.raises(HTTPException) as refused:
        await resume_agent_task(
            agent_id=agent_id,
            task_id=task_id,
            user_context=UserContext(user_id="u", workspace_id="w"),
            agent_service=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=agent_id))
            ),
            task_service=SimpleNamespace(
                get_task=AsyncMock(return_value=_child(agent_id, task_id))
            ),
            workflow_task_service=workflows,
        )
    assert refused.value.status_code == 400
    workflows.resume_task.assert_not_awaited()
