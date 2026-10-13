"""Over MCP a failed run's turn is retried, and a message reaches a closed run's conversation.

``runs.retry`` and ``runs.send_command(queue_message)`` go through the task
service, as the REST routes do, so a stopped or failed run continues in a new
execution instead of a signal no workflow receives.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RunsToolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton

RUN_ID = uuid4()
WORKSPACE = "ws-1"
STARTER = "user-who-started-it"


class FakeTaskService:
    def __init__(self, *, retried: bool = True, delivered: bool = True):
        self.task = SimpleNamespace(id=RUN_ID, user_id=STARTER, status="failed")
        self.retried = retried
        self.delivered = delivered
        self.retries: list = []
        self.follow_ups: list = []

    async def get_task(self, task_id):
        return self.task

    async def retry_last_turn(self, task_id):
        self.retries.append(task_id)
        return self.retried

    async def queue_follow_up(self, task_id, message):
        self.follow_ups.append((task_id, message))
        return self.delivered


class FakeWorkflowService:
    def __init__(self):
        self.commands: list = []

    async def send_workflow_command(self, execution_id, command, payload):
        self.commands.append((execution_id, command, payload))
        return True


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _harness(monkeypatch, caller: str, tasks: FakeTaskService) -> FakeWorkflowService:
    workflow = FakeWorkflowService()

    @asynccontextmanager
    async def fake_context():
        user_ctx = UserContext(user_id=caller, workspace_id=WORKSPACE, admin_workspaces=[])
        yield None, user_ctx, SimpleNamespace(), None, None

    async def fake_build(_repo_factory, _broker):
        return tasks

    async def fake_workflow_service():
        return workflow

    monkeypatch.setattr(runs_toolset, "platform_context", fake_context)
    monkeypatch.setattr(runs_toolset, "_build_task_service", fake_build)
    monkeypatch.setattr(runs_toolset, "get_temporal_workflow_service", fake_workflow_service)
    return workflow


async def test_retry_reruns_the_failed_turn(monkeypatch):
    tasks = FakeTaskService()
    _harness(monkeypatch, STARTER, tasks)

    result = json.loads(await RunsToolset().retry(run_id=str(RUN_ID)))

    assert result == {"retried": True, "run_id": str(RUN_ID)}
    assert tasks.retries == [RUN_ID]


async def test_retry_of_a_run_that_did_not_fail_says_why(monkeypatch):
    tasks = FakeTaskService(retried=False)
    _harness(monkeypatch, STARTER, tasks)

    with pytest.raises(ToolError, match="failed run"):
        await RunsToolset().retry(run_id=str(RUN_ID))


async def test_retry_is_refused_to_a_member_who_cannot_act_on_the_run(monkeypatch):
    tasks = FakeTaskService()
    _harness(monkeypatch, "user-invited-yesterday", tasks)

    with pytest.raises(ToolError):
        await RunsToolset().retry(run_id=str(RUN_ID))

    assert tasks.retries == []


async def test_a_queued_message_reaches_the_conversation_through_the_task_service(monkeypatch):
    tasks = FakeTaskService()
    workflow = _harness(monkeypatch, STARTER, tasks)

    result = json.loads(
        await RunsToolset().send_command(
            run_id=str(RUN_ID), command="queue_message", message="Carry on"
        )
    )

    assert result == {"delivered": True, "command": "queue_message"}
    assert tasks.follow_ups == [(RUN_ID, "Carry on")]
    assert workflow.commands == []
