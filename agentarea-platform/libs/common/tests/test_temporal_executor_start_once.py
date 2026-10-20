"""A start that may run only once finds any earlier execution of its id and reports it started."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.workflow.executor import WorkflowConfig
from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError


def _args() -> dict:
    return {
        "task_id": str(uuid4()),
        "agent_id": str(uuid4()),
        "user_id": "u",
        "workspace_id": "w",
        "task_query": "go",
        "effective_policy": {},
    }


def _executor(start: AsyncMock) -> TemporalWorkflowExecutor:
    client = MagicMock()
    client.start_workflow = start
    return TemporalWorkflowExecutor(client=client)


@pytest.mark.parametrize(
    ("start_once", "policy"),
    [
        (True, WorkflowIDReusePolicy.REJECT_DUPLICATE),
        (False, WorkflowIDReusePolicy.ALLOW_DUPLICATE),
    ],
)
async def test_the_reuse_policy_follows_start_once(start_once, policy):
    start = AsyncMock(return_value=MagicMock(id="task-1"))
    await _executor(start).start_workflow(
        "AgentExecutionWorkflow",
        "task-1",
        _args(),
        WorkflowConfig(task_queue="q", start_once=start_once),
    )
    assert start.await_args.kwargs["id_reuse_policy"] is policy


async def test_an_execution_already_there_is_reported_started():
    start = AsyncMock(side_effect=WorkflowAlreadyStartedError("task-1", "AgentExecutionWorkflow"))
    workflow_id = await _executor(start).start_workflow(
        "AgentExecutionWorkflow",
        "task-1",
        _args(),
        WorkflowConfig(task_queue="q", start_once=True),
    )
    assert workflow_id == "task-1"
