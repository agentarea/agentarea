"""Runs of an agent on a client's runner, on a real Temporal server (ADR-0051).

Each turn is an activity on the client's own task queue; here a stub runner
takes it, reports what its CLI did as signals and finishes it. The server runs
with a low continue-as-new threshold, so a short conversation crosses the
boundaries a long one does.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.testing.temporal import temporal_download_dir
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.models import (
    RUNNER_CLIENT_METADATA_KEY,
    AgentExecutionRequest,
    DeliverToRunnerRequest,
    RunnerApprovalAsk,
    RunnerTurnEvent,
    RunnerTurnRequest,
    RunnerTurnResult,
    RunnerTurnUpdate,
    UpdateTaskStatusRequest,
    runner_task_queue,
)
from agentarea_execution.testing import EventCapture, make_record_activity, runtime_policy
from agentarea_execution.workflows.agent.runner_turn import RESUME_MESSAGE
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.constants import EventTypes
from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

_CONTINUE_AS_NEW_EVENTS = 150
CLIENT_ID = str(uuid.uuid4())

Turn = Callable[["Runner", RunnerTurnRequest], Awaitable[RunnerTurnResult]]


@dataclass
class Runner:
    """The stub runner: what it was asked, and what the run delivered to it."""

    client: Client
    turn: Turn
    messages: list[str] = field(default_factory=list)
    deliveries: list[DeliverToRunnerRequest] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    delivered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    capture: EventCapture = field(default_factory=EventCapture)

    async def report(self, request: RunnerTurnRequest, **fields: Any) -> None:
        workflow_id = activity.info().workflow_id
        assert workflow_id is not None
        await self.client.get_workflow_handle(workflow_id).signal(
            "runner_turn_update", RunnerTurnUpdate(turn_key=request.turn_key, **fields)
        )

    def activities(self) -> tuple[list[Any], list[Any]]:
        runner = self

        @activity.defn(name="run_runner_turn_activity")
        async def run_runner_turn(request: RunnerTurnRequest) -> RunnerTurnResult:
            runner.messages.append(request.message)
            return await runner.turn(runner, request)

        @activity.defn(name="deliver_to_runner_activity")
        async def deliver_to_runner(request: DeliverToRunnerRequest) -> None:
            runner.deliveries.append(request)
            runner.delivered.set()

        @activity.defn(name="update_task_status_activity")
        async def update_status(request: UpdateTaskStatusRequest) -> bool:
            runner.statuses.append(request.status)
            return True

        workflow_activities = [
            deliver_to_runner,
            update_status,
            self.capture.make_activity(),
            make_record_activity(publish=self.capture.make_activity(), update_status=update_status),
        ]
        return workflow_activities, [run_runner_turn]


@pytest.fixture
async def temporal():
    env = await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter,
        download_dest_dir=temporal_download_dir(),
        dev_server_extra_args=[
            "--dynamic-config-value",
            f"limit.historyCount.suggestContinueAsNew={_CONTINUE_AS_NEW_EVENTS}",
        ],
    )
    try:
        yield env
    finally:
        await env.shutdown()


class _Run:
    def __init__(self, runner: Runner):
        self.runner = runner
        self.task_queue = f"runner-run-{uuid.uuid4()}"
        workflow_activities, turn_activities = runner.activities()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self._workers = [
            Worker(
                runner.client,
                task_queue=self.task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=workflow_activities,
                activity_executor=self._executor,
                workflow_runner=create_workflow_runner(),
            ),
            Worker(
                runner.client,
                task_queue=runner_task_queue(CLIENT_ID),
                activities=turn_activities,
                max_heartbeat_throttle_interval=timedelta(milliseconds=200),
                default_heartbeat_throttle_interval=timedelta(milliseconds=200),
            ),
        ]

    async def __aenter__(self) -> _Run:
        for worker in self._workers:
            await worker.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for worker in reversed(self._workers):
            await worker.__aexit__(*exc)
        self._executor.shutdown(wait=False)

    async def start(self) -> WorkflowHandle:
        task_id = uuid.uuid4()
        return await self.runner.client.start_workflow(
            AgentExecutionWorkflow.run,
            AgentExecutionRequest(
                task_id=task_id,
                agent_id=uuid.uuid4(),
                user_id="maria",
                workspace_id="workspace-1",
                task_query="parse the proposal",
                effective_policy=runtime_policy(max_model_turns=50),
                workflow_metadata={RUNNER_CLIENT_METADATA_KEY: CLIENT_ID},
            ),
            id=f"runner-run-{task_id}",
            task_queue=self.task_queue,
            execution_timeout=timedelta(minutes=10),
        )

    async def run_count(self, handle: WorkflowHandle) -> int:
        count = 0
        async for _ in self.runner.client.list_workflows(f"WorkflowId = '{handle.id}'"):
            count += 1
        return count


async def _wait_until(predicate: Callable[[], bool], timeout: float = 60.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition was not reached in time")
        await asyncio.sleep(0.05)


async def _state(handle: WorkflowHandle) -> dict[str, Any]:
    return await handle.query(AgentExecutionWorkflow.get_current_state)


async def _failed_workflow_tasks(handle: WorkflowHandle) -> int:
    history = await handle.fetch_history()
    return sum(
        1
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED
    )


async def _send(handle: WorkflowHandle, message: str) -> None:
    await handle.signal(
        AgentExecutionWorkflow.workflow_command,
        args=["queue_message", {"message": message, "sender": {"type": "user", "id": "maria"}}],
    )


@pytest.mark.asyncio
async def test_a_conversation_on_a_runner_continues_as_new_between_turns(temporal):
    async def turn(runner: Runner, request: RunnerTurnRequest) -> RunnerTurnResult:
        # Every report is a signal and a record in the run's history.
        for seq in range(1, 16):
            await runner.report(
                request,
                events=[
                    RunnerTurnEvent(
                        seq=seq, kind="message", item_id=f"{request.turn_key}-{seq}", text="…"
                    )
                ],
            )
        return RunnerTurnResult(status="completed", response=f"answered {request.message}")

    runner = Runner(temporal.client, turn)
    async with _Run(runner) as run:
        handle = await run.start()
        follow_ups = [f"and part {part}" for part in range(1, 6)]
        for sent, message in enumerate(follow_ups, start=1):
            await _wait_until(lambda sent=sent: runner.statuses.count("completed") == sent)
            await _send(handle, message)
        await _wait_until(lambda: len(runner.messages) == len(follow_ups) + 1)
        await _wait_until(lambda: runner.statuses.count("completed") == len(follow_ups) + 1)

        assert runner.messages == ["parse the proposal", *follow_ups]
        assert await run.run_count(handle) >= 3
        assert (await _state(handle))["current_iteration"] == len(follow_ups) + 1
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()


@pytest.mark.asyncio
async def test_an_approval_answered_while_the_turn_pauses_waits_for_the_paused_turn(temporal):
    async def turn(runner: Runner, request: RunnerTurnRequest) -> RunnerTurnResult:
        if len(runner.messages) > 1:
            return RunnerTurnResult(status="completed", response="done")
        await runner.report(
            request,
            approvals=[RunnerApprovalAsk(request_id="r1", kind="command", tool_name="shell")],
        )
        await runner.release.wait()
        return RunnerTurnResult(status="interrupted")

    runner = Runner(temporal.client, turn)
    async with _Run(runner) as run:
        handle = await run.start()
        await _wait_until(lambda: runner.statuses[-1:] == ["waiting_for_approval"])
        (escalation_id,) = (await _state(handle))["pending_escalations"]

        await handle.signal(AgentExecutionWorkflow.pause_execution, "lunch")
        await _wait_until(lambda: runner.delivered.is_set())
        await handle.signal(
            AgentExecutionWorkflow.resolve_escalation,
            args=[escalation_id, True, "", "maria"],
        )
        # Answered while the CLI stops its turn: the run waits for the turn, it does not spin.
        await asyncio.sleep(3)
        assert await _failed_workflow_tasks(handle) == 0

        runner.release.set()
        await _wait_until(lambda: runner.statuses[-1:] == ["running"])
        await handle.signal(AgentExecutionWorkflow.resume_execution, "back")
        await _wait_until(lambda: "completed" in runner.statuses)

        assert [delivery.kind for delivery in runner.deliveries] == ["pause"]
        assert runner.messages == ["parse the proposal", RESUME_MESSAGE]
        assert await _failed_workflow_tasks(handle) == 0
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()


@pytest.mark.asyncio
async def test_a_stop_cancels_the_turn_and_closes_its_running_command(temporal):
    async def turn(runner: Runner, request: RunnerTurnRequest) -> RunnerTurnResult:
        await runner.report(
            request,
            events=[RunnerTurnEvent(seq=1, kind="tool.call", item_id="c1", name="shell")],
        )
        try:
            while True:
                activity.heartbeat()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            runner.release.set()
            raise

    runner = Runner(temporal.client, turn)
    async with _Run(runner) as run:
        handle = await run.start()
        await _wait_until(
            lambda: any(
                e["event_type"] == EventTypes.TOOL_CALL_STARTED for e in runner.capture.events
            )
        )
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()

    assert runner.release.is_set()
    (closed,) = [
        event["data"]
        for event in runner.capture.events
        if event["event_type"] == EventTypes.TOOL_CALL_COMPLETED
    ]
    assert (closed["tool_call_id"], closed["success"]) == ("c1", False)
    assert runner.statuses[-1] == "cancelled"
