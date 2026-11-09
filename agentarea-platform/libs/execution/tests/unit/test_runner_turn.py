"""A turn on a client's runner: one activity per turn, reassigned on a lost runner (ADR-0051).

The CLI's events reach the run as signals and are recorded once each; its
approval requests are the run's escalations; a command the turn left running is
closed when the turn ends.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from agentarea_common.money import to_money
from agentarea_execution.interaction import resolve_interaction_capabilities
from agentarea_execution.models import (
    AgentExecutionResume,
    ConversationResumeSnapshot,
    RunnerActor,
    RunnerApprovalAsk,
    RunnerTurnEvent,
    RunnerTurnResult,
    RunnerTurnUpdate,
)
from agentarea_execution.workflows.agent.runner_turn import (
    RESUME_MESSAGE,
    RETRY_MESSAGE,
    RUNNER_LOST,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.constants import (
    RUNNER_TURN_MAX_ATTEMPTS,
    Activities,
    EventTypes,
)
from agentarea_execution.workflows.helpers import BudgetTracker, EventManager
from agentarea_execution.workflows.models import AgentGoal
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    CancelledError,
    RetryState,
    TimeoutError,
    TimeoutType,
)

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


def _activity_error(cause: BaseException, activity_type: str = Activities.RUN_RUNNER_TURN):
    error = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="api",
        activity_type=activity_type,
        activity_id="1",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )
    error.__cause__ = cause
    return error


def _runner_lost() -> ActivityError:
    return _activity_error(ApplicationError("the runner went away", type=RUNNER_LOST))


class _RunningTurn(asyncio.Future):
    """A turn activity still running, which ends cancelled when the run cancels it."""

    cancel_requested = False

    def cancel(self, msg=None) -> bool:
        self.cancel_requested = True
        if not self.done():
            self.set_exception(_activity_error(CancelledError()))
        return True


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


@pytest.mark.asyncio
async def test_a_turn_its_runners_keep_losing_fails_after_a_bounded_number_of_attempts(instance):
    module = _workflow_module([_finished(_runner_lost()) for _ in range(RUNNER_TURN_MAX_ATTEMPTS)])
    with patch(MODULE, module), pytest.raises(ApplicationError) as failed:
        await instance._run_runner_turn("go", None)

    assert failed.value.type == "RunnerTurnLost"
    assert module.start_activity.call_count == RUNNER_TURN_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_a_turn_no_runner_takes_fails_as_the_runner_being_offline(instance):
    offline = _activity_error(
        TimeoutError(
            "activity timed out", type=TimeoutType.SCHEDULE_TO_START, last_heartbeat_details=[]
        )
    )
    module = _workflow_module([_finished(offline)])
    with patch(MODULE, module), pytest.raises(ApplicationError) as failed:
        await instance._run_runner_turn("go", None)

    assert failed.value.type == "RunnerOffline"
    assert module.start_activity.call_count == 1
    assert module.start_activity.call_args.kwargs["schedule_to_start_timeout"]


@pytest.mark.asyncio
async def test_a_failed_delivery_stops_the_clis_turn_before_the_run_fails(instance):
    handle = _RunningTurn()
    outage = _activity_error(ApplicationError("redis is down"), Activities.DELIVER_TO_RUNNER)
    instance._deliver_to_runner.side_effect = outage
    instance._message_queue.append({"id": "m2", "content": "and the totals"})
    with patch(MODULE, _workflow_module([handle])), pytest.raises(ActivityError) as failed:
        await instance._run_runner_turn("go", None)

    assert failed.value is outage
    assert handle.cancel_requested
    assert instance._runner_turn_key is None
    await instance.runner_turn_update(RunnerTurnUpdate(turn_key="1.1"))
    assert instance._runner_updates == []


@pytest.mark.asyncio
async def test_an_answer_while_the_turn_pauses_waits_for_the_paused_turn(instance):
    instance._runner_turn_key = "1.1"
    await instance.runner_turn_update(
        RunnerTurnUpdate(
            turn_key="1.1",
            approvals=[RunnerApprovalAsk(request_id="r1", kind="command", tool_name="shell")],
        )
    )
    with patch(MODULE, _workflow_module([])):
        await instance._serve_runner_turn(deliver=True)
    (escalation_id,) = instance._pending_escalations
    instance._runner_pausing = True
    await instance.resolve_escalation(escalation_id, True, None, resolved_by="maria")

    assert instance._runner_has_work() is False
    instance._message_queue.append({"id": "m2", "content": "later"})
    assert instance._runner_has_work() is False


@pytest.mark.asyncio
async def test_an_approval_reported_again_after_its_answer_opens_no_second_escalation(instance):
    instance._runner_turn_key = "1.1"
    ask = RunnerApprovalAsk(request_id="r1", kind="command", tool_name="shell")
    with patch(MODULE, _workflow_module([])):
        await instance.runner_turn_update(RunnerTurnUpdate(turn_key="1.1", approvals=[ask]))
        await instance._serve_runner_turn(deliver=True)
        (escalation_id,) = instance._pending_escalations
        await instance.resolve_escalation(escalation_id, True, None, resolved_by="maria")
        await instance._serve_runner_turn(deliver=True)
        await instance.runner_turn_update(RunnerTurnUpdate(turn_key="1.1", approvals=[ask]))
        await instance._serve_runner_turn(deliver=True)

    assert instance._pending_escalations == {}
    assert len(_events(instance, EventTypes.HUMAN_APPROVAL_REQUESTED)) == 1


def _resume(current_iteration: int) -> AgentExecutionResume:
    return AgentExecutionResume(
        snapshot=ConversationResumeSnapshot(
            head_seqs=[], tail_start=0, next_seq=3, current_iteration=current_iteration
        ),
        retry=True,
    )


@pytest.mark.asyncio
async def test_a_retry_after_a_failed_first_turn_sends_the_task_again(instance):
    instance.budget_tracker = BudgetTracker(to_money("1"))
    instance._adopt_resume(_resume(1))
    instance._conversation_seeded = True
    module = _workflow_module([_finished(RunnerTurnResult(status="completed", response="ok"))])
    with patch(MODULE, module):
        await instance._execute_runner_turn()

    assert module.start_activity.call_args.args[1].message == "parse the proposal"


@pytest.mark.asyncio
async def test_a_retry_after_a_later_turn_tells_the_cli_to_do_it_again(instance):
    instance.budget_tracker = BudgetTracker(to_money("1"))
    instance._adopt_resume(_resume(3))
    instance._conversation_seeded = True
    module = _workflow_module([_finished(RunnerTurnResult(status="completed", response="ok"))])
    with patch(MODULE, module):
        await instance._execute_runner_turn()

    assert module.start_activity.call_args.args[1].message == RETRY_MESSAGE


@pytest.mark.asyncio
async def test_a_message_with_a_malformed_sender_is_rejected_not_raised(instance):
    await instance.workflow_command("queue_message", {"message": "hi", "sender": {"type": "robot"}})
    await instance.workflow_command("queue_message", {"message": "hi", "sender": {"type": "user"}})

    assert instance._message_queue == []
    assert len(_events(instance, EventTypes.COMMAND_REJECTED)) == 2
