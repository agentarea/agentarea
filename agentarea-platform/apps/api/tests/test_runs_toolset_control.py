"""Unit tests for run-control tools (pause/resume/input/command/escalation).

Every control tool must resolve the run through the workspace-scoped
``TaskService`` before it signals Temporal: ``run_id`` arrives from the caller,
so the repository's workspace filter keeps a tenant out of someone else's
workflow. Run authority inside the workspace is covered in
``test_runs_toolset_task_authority.py``.
"""

import json
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents.application.execution_service import EscalationNotPendingError
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RUN_NOT_FOUND, RunsToolset

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
        self.follow_ups: list = []
        self.follow_up_delivered = True

    async def queue_follow_up(self, task_id, message):
        self.follow_ups.append((task_id, message))
        return self.follow_up_delivered

    async def get_task(self, task_id):
        return self.task

    async def continue_execution(
        self,
        task_id,
        *,
        additional_iterations,
        additional_budget_usd,
        additional_tokens,
        additional_tool_calls,
    ):
        self.continued.append(
            (
                task_id,
                additional_iterations,
                additional_budget_usd,
                additional_tokens,
                additional_tool_calls,
            )
        )
        return {"accepted": True}


@pytest.fixture
def harness(monkeypatch):
    workflow = FakeWorkflowService()
    task_service = FakeTaskService(
        SimpleNamespace(id=RUN_ID, user_id="user-1", status="running", execution_id=None)
    )

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
        lambda: RunsToolset().pause(run_id=str(RUN_ID)),
        lambda: RunsToolset().resume(run_id=str(RUN_ID)),
        lambda: RunsToolset().send_input(run_id=str(RUN_ID), input_request_id="req-1"),
        lambda: RunsToolset().send_command(
            run_id=str(RUN_ID), command="queue_message", message="hi"
        ),
        lambda: RunsToolset().resolve_escalation(
            run_id=str(RUN_ID), escalation_id="e-1", approved=True
        ),
    ):
        with pytest.raises(ToolError, match=re.escape(RUN_NOT_FOUND)):
            await call()

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
    with pytest.raises(ToolError, match=re.escape("message is required for queue_message")):
        await RunsToolset().send_command(run_id=str(RUN_ID), command="queue_message")

    assert harness.workflow.calls == []


async def test_send_command_rejects_an_unknown_command(harness):
    with pytest.raises(ToolError, match=re.escape("Unknown command: self_destruct")):
        await RunsToolset().send_command(run_id=str(RUN_ID), command="self_destruct")

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


async def test_resolve_escalation_that_is_not_pending_reports_an_error(harness, monkeypatch):
    async def not_pending(execution_id, escalation_id, *_args, **_kwargs):
        raise EscalationNotPendingError(execution_id, escalation_id)

    monkeypatch.setattr(harness.workflow, "resolve_escalation", not_pending)

    with pytest.raises(ToolError, match=re.escape("Escalation not found or no longer pending")):
        await RunsToolset().resolve_escalation(
            run_id=str(RUN_ID), escalation_id="None", approved=True
        )


async def test_continue_run_parses_budget_through_the_rest_dto(harness):
    await RunsToolset().continue_run(
        run_id=str(RUN_ID),
        additional_iterations=5,
        additional_budget_usd="2.50",
    )

    _task_id, iterations, budget, tokens, tool_calls = harness.tasks.continued[0]
    assert iterations == 5
    assert str(budget) == "2.50"
    assert tokens == 0
    assert tool_calls == 0


async def test_continue_run_forwards_token_and_tool_call_grants(harness):
    await RunsToolset().continue_run(
        run_id=str(RUN_ID),
        additional_tokens=40_000,
        additional_tool_calls=30,
    )

    _task_id, iterations, budget, tokens, tool_calls = harness.tasks.continued[0]
    assert (iterations, budget, tokens, tool_calls) == (0, None, 40_000, 30)


async def test_undelivered_command_is_reported_as_a_failure(harness, monkeypatch):
    async def undelivered(*_args, **_kwargs):
        return False

    monkeypatch.setattr(harness.workflow, "send_workflow_command", undelivered)

    result = json.loads(
        await RunsToolset().send_command(
            run_id=str(RUN_ID), command="remove_message", message_id="m-1"
        )
    )

    assert result["delivered"] is False


async def test_a_message_the_run_cannot_take_is_reported_as_a_failure(harness):
    harness.tasks.follow_up_delivered = False

    result = json.loads(
        await RunsToolset().send_command(run_id=str(RUN_ID), command="queue_message", message="hi")
    )

    assert result["delivered"] is False
    assert harness.tasks.follow_ups == [(RUN_ID, "hi")]
