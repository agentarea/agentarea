"""Acting on a run over MCP needs the same authority as over REST.

Every ``runs.*`` control tool reaches a run by id inside the caller's workspace.
Being in the workspace is not enough to steer, stop or approve somebody else's
run: the caller must have started it or administer the workspace.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RunsToolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton

RUN_ID = str(uuid4())
WORKSPACE = "ws-1"
STARTER = "user-who-started-it"
OTHER_MEMBER = "user-invited-yesterday"


class Recorder:
    def __init__(self):
        self.calls: list[str] = []

    def record(self, name: str, result):
        self.calls.append(name)
        return result


class FakeTaskService:
    def __init__(self, recorder: Recorder):
        self.recorder = recorder

    async def get_task(self, task_id):
        return SimpleNamespace(id=task_id, user_id=STARTER, status="running")

    async def cancel_task(self, task_id):
        return self.recorder.record("cancel_task", True)

    async def continue_execution(self, task_id, **kwargs):
        return self.recorder.record("continue_execution", {"continued": True})


class FakeWorkflowService:
    def __init__(self, recorder: Recorder):
        self.recorder = recorder

    async def pause_task(self, execution_id):
        return self.recorder.record("pause_task", True)

    async def resume_task(self, execution_id):
        return self.recorder.record("resume_task", True)

    async def send_workflow_command(self, execution_id, command, body):
        return self.recorder.record(command, True)

    async def resolve_escalation(self, execution_id, *args, **kwargs):
        return self.recorder.record("resolve_escalation", True)


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _harness(monkeypatch, caller: str) -> Recorder:
    recorder = Recorder()
    tasks = FakeTaskService(recorder)
    workflow = FakeWorkflowService(recorder)

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
    return recorder


ACTIONS = {
    "cancel": lambda t: t.cancel(run_id=RUN_ID),
    "pause": lambda t: t.pause(run_id=RUN_ID),
    "resume": lambda t: t.resume(run_id=RUN_ID),
    "send_input": lambda t: t.send_input(run_id=RUN_ID, input_request_id="req-1", answers={}),
    "send_command": lambda t: t.send_command(
        run_id=RUN_ID, command="queue_message", message="stop that"
    ),
    "resolve_escalation": lambda t: t.resolve_escalation(
        run_id=RUN_ID, escalation_id="esc-1", approved=True
    ),
    "continue_run": lambda t: t.continue_run(run_id=RUN_ID, additional_iterations=5),
}


@pytest.mark.parametrize("action", ACTIONS)
async def test_a_member_who_did_not_start_the_run_cannot_act_on_it(monkeypatch, action):
    recorder = _harness(monkeypatch, OTHER_MEMBER)

    result = json.loads(await ACTIONS[action](RunsToolset()))

    assert "error" in result
    assert recorder.calls == []


@pytest.mark.parametrize("action", ACTIONS)
async def test_the_member_who_started_the_run_can_act_on_it(monkeypatch, action):
    recorder = _harness(monkeypatch, STARTER)

    result = json.loads(await ACTIONS[action](RunsToolset()))

    assert "error" not in result
    assert len(recorder.calls) == 1
