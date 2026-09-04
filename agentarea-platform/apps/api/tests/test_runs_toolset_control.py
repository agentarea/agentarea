"""Unit tests for run-control tools (pause/resume/input/command/escalation).

Every control tool must resolve the run through the workspace-scoped
``TaskService`` before it signals Temporal: ``run_id`` arrives from the caller,
so the repository's workspace filter is the only thing standing between a
tenant and someone else's workflow.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RunsToolset

RUN_ID = uuid4()


class FakeWorkflowService:
    def __init__(self):
        self.calls: list = []

    async def pause_task(self, execution_id):
        self.calls.append(("pause", execution_id))
        return True

    async def resume_task(self, execution_id):
        self.calls.append(("resume", execution_id))
        return True

    async def send_workflow_command(self, execution_id, command, payload):
        self.calls.append(("command", execution_id, command, payload))
        return True

    async def resolve_escalation(self, execution_id, escalation_id, approved, comment, resolved_by):
        self.calls.append(
            ("escalation", execution_id, escalation_id, approved, comment, resolved_by)
        )
        return True


class FakeTaskService:
    def __init__(self, task):
        self.task = task
        self.continued: list = []

    async def get_task(self, task_id):
        return self.task

    async def continue_execution(self, task_id, *, additional_iterations, additional_budget_usd):
        self.continued.append((task_id, additional_iterations, additional_budget_usd))
        return {"accepted": True}


@pytest.fixture
def harness(monkeypatch):
    workflow = FakeWorkflowService()
    task_service = FakeTaskService(SimpleNamespace(id=RUN_ID, status="running"))

    @asynccontextmanager
    async def fake_context():
        user_ctx = SimpleNamespace(user_id="user-1", workspace_id="ws-1")
        yield None, user_ctx, SimpleNamespace(), None, None

    async def fake_build(_repo_factory, _broker):
        return task_service

    async def fake_workflow_service():
        return workflow

    monkeypatch.setattr(runs_toolset, "platform_context", fake_context)
    monkeypatch.setattr(runs_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(runs_toolset, "_build_task_service", fake_build)
    monkeypatch.setattr(runs_toolset, "get_temporal_workflow_service", fake_workflow_service)
    return SimpleNamespace(workflow=workflow, tasks=task_service)


async def test_pause_signals_the_runs_execution(harness):
    result = json.loads(await RunsToolset().pause(run_id=str(RUN_ID)))

    assert result == {"paused": True}
    assert harness.workflow.calls == [("pause", f"task-{RUN_ID}")]


async def test_resume_signals_the_runs_execution(harness):
    await RunsToolset().resume(run_id=str(RUN_ID))

    assert harness.workflow.calls == [("resume", f"task-{RUN_ID}")]


async def test_control_tools_never_signal_a_run_outside_the_workspace(harness):
    harness.tasks.task = None

    for call in (
        RunsToolset().pause(run_id=str(RUN_ID)),
        RunsToolset().resume(run_id=str(RUN_ID)),
        RunsToolset().send_input(run_id=str(RUN_ID), input_request_id="req-1"),
        RunsToolset().send_command(run_id=str(RUN_ID), command="queue_message", message="hi"),
        RunsToolset().resolve_escalation(run_id=str(RUN_ID), escalation_id="e-1", approved=True),
    ):
        assert json.loads(await call) == {"error": "Run not found"}

    assert harness.workflow.calls == []


async def test_send_input_forwards_answers_as_a_submit_user_input_command(harness):
    await RunsToolset().send_input(
        run_id=str(RUN_ID),
        input_request_id="req-1",
        answers={"city": "Berlin"},
    )

    _kind, execution_id, command, payload = harness.workflow.calls[0]
    assert execution_id == f"task-{RUN_ID}"
    assert command == "submit_user_input"
    assert payload["input_request_id"] == "req-1"
    assert payload["answers"] == {"city": "Berlin"}
    assert payload["submitted_by"] == "user-1"


async def test_send_command_rejects_a_queue_message_without_a_message(harness):
    result = json.loads(
        await RunsToolset().send_command(run_id=str(RUN_ID), command="queue_message")
    )

    assert "error" in result
    assert harness.workflow.calls == []


async def test_send_command_rejects_an_unknown_command(harness):
    result = json.loads(
        await RunsToolset().send_command(run_id=str(RUN_ID), command="self_destruct")
    )

    assert "error" in result
    assert harness.workflow.calls == []


async def test_resolve_escalation_records_who_resolved_it(harness):
    await RunsToolset().resolve_escalation(
        run_id=str(RUN_ID),
        escalation_id="esc-1",
        approved=False,
        comment="not now",
    )

    assert harness.workflow.calls == [
        ("escalation", f"task-{RUN_ID}", "esc-1", False, "not now", "user-1")
    ]


async def test_continue_run_parses_budget_through_the_rest_dto(harness):
    await RunsToolset().continue_run(
        run_id=str(RUN_ID),
        additional_iterations=5,
        additional_budget_usd="2.50",
    )

    _task_id, iterations, budget = harness.tasks.continued[0]
    assert iterations == 5
    assert str(budget) == "2.50"


async def test_undelivered_command_is_reported_as_a_failure(harness, monkeypatch):
    async def undelivered(*_args, **_kwargs):
        return False

    monkeypatch.setattr(harness.workflow, "send_workflow_command", undelivered)

    result = json.loads(
        await RunsToolset().send_command(run_id=str(RUN_ID), command="queue_message", message="hi")
    )

    assert result["delivered"] is False
