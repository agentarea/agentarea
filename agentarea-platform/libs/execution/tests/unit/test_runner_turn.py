"""A turn on a client's runner: one activity per turn, reassigned on a lost runner (ADR-0051).

The CLI's events reach the run as signals and are recorded once each; its
approval requests are the run's escalations; a command the turn left running is
closed when the turn ends.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from agentarea_execution.interaction import resolve_interaction_capabilities
from agentarea_execution.models import (
    RunnerActor,
    RunnerApprovalAsk,
    RunnerTurnEvent,
    RunnerTurnResult,
    RunnerTurnUpdate,
)
from agentarea_execution.workflows.agent.runner_turn import RESUME_MESSAGE, RUNNER_LOST
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.constants import Activities, EventTypes
from agentarea_execution.workflows.helpers import EventManager
from agentarea_execution.workflows.models import AgentGoal
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

CLIENT_ID = "f9e7328e-4d39-43a7-aa65-0116330ca9d5"
MODULE = "agentarea_execution.workflows.agent.runner_turn.workflow"


@pytest.fixture
def instance():
    workflow = AgentExecutionWorkflow()
    workflow.state.task_id = str(uuid4())
    workflow.state.agent_id = str(uuid4())
    workflow.state.workspace_id = "workspace-1"
    workflow.state.user_id = "user-1"
    workflow.state.execution_id = "task-1"
    workflow.state.current_iteration = 1
    workflow.state.user_context_data = {"user_id": "user-1", "workspace_id": "workspace-1"}
    workflow.state.goal = AgentGoal(
        id="goal",
        description="parse the proposal",
        success_criteria=[],
        max_iterations=5,
        requires_human_approval=False,
        context={},
    )
    workflow.state.effective_policy = {}
    workflow.state.interaction_capabilities = resolve_interaction_capabilities({}, {}, True)
    workflow.event_manager = EventManager(
        task_id=workflow.state.task_id,
        agent_id=workflow.state.agent_id,
        execution_id=workflow.state.execution_id,
    )
    workflow._runner_client_id = CLIENT_ID
    workflow._publish_events_immediately = AsyncMock()
    workflow._persist_task_status = AsyncMock()
    workflow._deliver_to_runner = AsyncMock()
    with (
        patch("temporalio.workflow.logger", new=Mock()),
        patch("temporalio.workflow.uuid4", side_effect=uuid4),
        patch("temporalio.workflow.patched", return_value=True),
    ):
        yield workflow


def _events(instance, event_type: str) -> list[dict]:
    return [
        event["data"]
        for event in instance._events.get_pending_events()
        if event["event_type"] == event_type
    ]


def _finished(result: RunnerTurnResult | BaseException) -> asyncio.Future:
    future = asyncio.get_running_loop().create_future()
    if isinstance(result, BaseException):
        future.set_exception(result)
    else:
        future.set_result(result)
    return future


def _runner_lost() -> ActivityError:
    error = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="api",
        activity_type=Activities.RUN_RUNNER_TURN,
        activity_id="1",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )
    error.__cause__ = ApplicationError("the runner went away", type=RUNNER_LOST)
    return error


def _workflow_module(handles: list[asyncio.Future]):
    module = Mock()
    module.start_activity = Mock(side_effect=handles)
    module.wait_condition = AsyncMock()
    module.sleep = AsyncMock()
    module.uuid4 = uuid4
    module.ActivityCancellationType = Mock()
    return module


@pytest.mark.asyncio
async def test_a_turn_runs_on_the_clients_queue_and_acts_for_the_sender(instance):
    instance._message_queue.append(
        {"id": "m1", "content": "and the totals", "sender": {"type": "user", "id": "maria"}}
    )
    instance._conversation_seeded = True
    module = _workflow_module([_finished(RunnerTurnResult(status="completed", response="ok"))])
    with patch(MODULE, module):
        await instance._execute_runner_turn()

    (call,) = module.start_activity.call_args_list
    request = call.args[1]
    assert call.args[0] == Activities.RUN_RUNNER_TURN
    assert call.kwargs["task_queue"] == f"runner-turns-{CLIENT_ID}"
    assert request.message == "and the totals"
    assert request.actor == RunnerActor(type="user", id="maria")
    assert instance.state.final_response == "ok"


@pytest.mark.asyncio
async def test_the_first_turn_sends_the_task_and_names_no_actor(instance):
    module = _workflow_module([_finished(RunnerTurnResult(status="completed", response="ok"))])
    with patch(MODULE, module):
        await instance._execute_runner_turn()

    request = module.start_activity.call_args.args[1]
    assert request.message == "parse the proposal"
    assert request.actor is None


@pytest.mark.asyncio
async def test_a_lost_runner_assigns_the_turn_again_and_closes_what_it_left_running(instance):
    attempts: list[str] = []

    def start(_activity, request, **_kwargs):
        attempts.append(request.turn_key)
        if len(attempts) == 1:
            instance._runner_updates.append(
                RunnerTurnUpdate(
                    turn_key=request.turn_key,
                    events=[RunnerTurnEvent(seq=1, kind="tool.call", item_id="c1", name="shell")],
                )
            )
            return _finished(_runner_lost())
        return _finished(RunnerTurnResult(status="completed", response="done"))

    module = _workflow_module([])
    module.start_activity.side_effect = start
    with patch(MODULE, module):
        result = await instance._run_runner_turn("go", None)

    assert result.response == "done"
    assert attempts == ["1.1", "1.2"]
    module.sleep.assert_awaited_once()
    (closed,) = _events(instance, EventTypes.TOOL_CALL_COMPLETED)
    assert closed["tool_call_id"] == "c1"
    assert closed["success"] is False


@pytest.mark.asyncio
async def test_reported_events_are_recorded_once_each(instance):
    instance._runner_turn_key = "1.1"
    update = RunnerTurnUpdate(
        turn_key="1.1",
        actor=RunnerActor(type="agent", id="agent-1"),
        events=[
            RunnerTurnEvent(seq=1, kind="tool.call", item_id="c1", name="shell"),
            RunnerTurnEvent(seq=2, kind="tool.result", item_id="c1", name="shell", output="x"),
            RunnerTurnEvent(seq=3, kind="message", item_id="m1", text="hi"),
        ],
    )
    await instance.runner_turn_update(update)
    await instance.runner_turn_update(update)
    await instance.runner_turn_update(RunnerTurnUpdate(turn_key="0.9", events=update.events))
    await instance._serve_runner_turn(deliver=False)

    (call,) = _events(instance, EventTypes.TOOL_CALL_STARTED)
    assert call["actor"] == {"type": "agent", "id": "agent-1"}
    assert len(_events(instance, EventTypes.TOOL_CALL_COMPLETED)) == 1
    assert [m["content"] for m in _events(instance, EventTypes.LLM_CALL_COMPLETED)] == ["hi"]
    await instance._close_open_runner_tools("Stopped before it finished.")
    assert len(_events(instance, EventTypes.TOOL_CALL_COMPLETED)) == 1


@pytest.mark.asyncio
async def test_a_stopped_turn_closes_its_running_command(instance):
    instance._runner_turn_key = "1.1"
    await instance.runner_turn_update(
        RunnerTurnUpdate(
            turn_key="1.1",
            events=[RunnerTurnEvent(seq=1, kind="tool.call", item_id="c1", name="shell")],
        )
    )
    await instance._serve_runner_turn(deliver=False)
    await instance._close_open_runner_tools("Stopped before it finished.")

    (closed,) = _events(instance, EventTypes.TOOL_CALL_COMPLETED)
    assert (closed["tool_name"], closed["tool_call_id"], closed["success"]) == (
        "shell",
        "c1",
        False,
    )


@pytest.mark.asyncio
async def test_an_approval_request_is_an_escalation_answered_to_the_runner(instance):
    instance._runner_turn_key = "1.1"
    await instance.runner_turn_update(
        RunnerTurnUpdate(
            turn_key="1.1",
            approvals=[
                RunnerApprovalAsk(request_id="r1", item_id="c1", kind="command", tool_name="shell")
            ],
        )
    )
    with patch(MODULE, _workflow_module([])):
        await instance._serve_runner_turn(deliver=True)
        (escalation_id,) = instance._pending_escalations
        assert instance.state.status == "waiting_for_approval"
        assert _events(instance, EventTypes.HUMAN_APPROVAL_REQUESTED)

        await instance.resolve_escalation(escalation_id, True, None, resolved_by="maria")
        await instance._serve_runner_turn(deliver=True)

    instance._deliver_to_runner.assert_awaited_once_with(
        kind="decision", request_id="r1", approved=True
    )
    assert instance._pending_escalations == {}
    assert _events(instance, EventTypes.HUMAN_APPROVAL_RECEIVED)


@pytest.mark.asyncio
async def test_a_message_during_a_turn_is_steered_into_it(instance):
    instance._runner_turn_key = "1.1"
    instance._message_queue.append({"id": "m2", "content": "answer БАНАН"})
    with patch(MODULE, _workflow_module([])):
        await instance._serve_runner_turn(deliver=True)

    instance._deliver_to_runner.assert_awaited_once_with(
        kind="steer", message_id="m2", text="answer БАНАН"
    )
    assert instance._message_queue == []
    assert "m2" in instance._runner_steering


@pytest.mark.asyncio
async def test_a_pause_stops_the_clis_turn_and_the_resume_continues_the_session(instance):
    running = asyncio.get_running_loop().create_future()
    requests = []

    def start(_activity, request, **_kwargs):
        requests.append(request)
        if len(requests) == 1:
            instance._runner_updates.append(
                RunnerTurnUpdate(
                    turn_key=request.turn_key,
                    events=[RunnerTurnEvent(seq=1, kind="tool.call", item_id="c1", name="shell")],
                )
            )
            return running
        return _finished(RunnerTurnResult(status="completed", response="done"))

    async def deliver(**fields):
        assert fields == {"kind": "pause"}
        running.set_result(RunnerTurnResult(status="interrupted"))
        await instance.resume_execution()

    instance._deliver_to_runner.side_effect = deliver
    instance._message_queue.append({"id": "m1", "content": "and the totals"})
    await instance.pause_execution()
    module = _workflow_module([])
    module.start_activity.side_effect = start
    with patch(MODULE, module):
        result = await instance._run_runner_turn("go", None)

    assert result.response == "done"
    assert [request.turn_key for request in requests] == ["1.1", "1.2"]
    assert requests[1].message == "and the totals"
    (closed,) = _events(instance, EventTypes.TOOL_CALL_COMPLETED)
    assert (closed["tool_call_id"], closed["success"]) == ("c1", False)
    assert instance._runner_pausing is False


@pytest.mark.asyncio
async def test_a_resume_with_no_message_tells_the_cli_to_continue(instance):
    instance._runner_turn_key = "1.1"
    assert instance._runner_resumed_turn(None) == (RESUME_MESSAGE, None)
