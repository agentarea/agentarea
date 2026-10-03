"""Continuing a completed conversation after its workflow closed.

A run that completes stores where its conversation stands; a later follow-up
starts a new run of the same workflow id that adopts it, sees the whole prior
conversation and carries the spend on. Logs without a snapshot are rebuilt.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from agentarea_common.testing.flows import MainFlow
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.activities.agent.conversation import pending_entries
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    AgentExecutionResume,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent.patches import CONVERSATION_RESUME_SNAPSHOT_PATCH
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_tasks.conversation_resume import reconstruct_conversation
from agentarea_tasks.domain.models import ConversationEntry
from temporalio import activity, workflow
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

_log: dict[int, ConversationEntry] = {}
_model_windows: list[list[dict[str, Any]]] = []
_status_requests: list[UpdateTaskStatusRequest] = []

_POLICY = {
    "budget": {"run_budget_usd": "10.00"},
    "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
    "execution": {
        "max_model_turns": 5,
        "max_tool_calls_per_turn": 10,
        "max_tool_calls_total": 100,
    },
}


def _write(next_seq: int, messages: list[dict[str, Any]]) -> None:
    _log.update((entry.seq, entry) for entry in pending_entries(next_seq, messages))


@activity.defn(name="build_agent_config_activity")
async def _build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Resume Agent",
        "model_id": "gpt-4o-mini",
        "description": "Resume test agent",
        "instruction": "Retain prior context.",
        "tools_config": {"mcp_servers": []},
        "context_window": 128000,
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _discover_tools(_request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def _resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id or "gpt-4o-mini",
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "api_key_secret": None,
        "endpoint_url": None,
        "context_window": 128000,
        "display_name": "GPT-4o Mini",
        "provider_display_name": "OpenAI",
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


@activity.defn(name="call_llm_activity")
async def _call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """Write the pending entries and answer from the window the log holds, as the real one."""
    window = request.conversation
    assert window is not None
    _write(window.next_seq, request.messages)
    end_seq = window.next_seq + len(request.messages)
    head = [_log[seq] for seq in window.head_seqs]
    tail = [
        _log[seq]
        for seq in sorted(_log)
        if window.tail_start <= seq < end_seq and seq not in window.head_seqs
    ]
    _model_windows.append([entry.as_message() for entry in (*head, *tail)])
    turn = len(_model_windows)
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"complete-{turn}",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({"result": f"Answer {turn}", "artifacts": []}),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": "0.01",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


@activity.defn(name="publish_workflow_events_activity")
async def _publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _update_task_status(request: UpdateTaskStatusRequest) -> dict[str, bool]:
    _status_requests.append(request)
    if request.conversation is not None:
        _write(request.conversation.next_seq, request.conversation_pending)
    return {"success": True}


@activity.defn(name="validate_artifacts_activity")
async def _validate_artifacts(_request: ArtifactValidationRequest) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


_ACTIVITIES = [
    _build_config,
    _discover_tools,
    _resolve_model,
    _call_llm,
    _publish_events,
    _update_task_status,
    _validate_artifacts,
]


@pytest.fixture(autouse=True)
def _reset() -> None:
    _log.clear()
    _model_windows.clear()
    _status_requests.clear()


def _request(task_id: uuid.UUID, resume: AgentExecutionResume | None = None):
    return AgentExecutionRequest(
        task_id=task_id,
        agent_id=uuid.UUID(int=7),
        user_id="resume-user",
        workspace_id="resume-workspace",
        task_query="Remember the number 42",
        effective_policy=_POLICY,
        resume=resume,
    )


async def _start(env, task_queue: str, request: AgentExecutionRequest, message: str | None = None):
    """Start like the API does: the task's workflow id, the follow-up as the start signal."""
    signal: dict[str, Any] = (
        {
            "start_signal": "workflow_command",
            "start_signal_args": ["queue_message", {"message": message}],
        }
        if message is not None
        else {}
    )
    return await env.client.start_workflow(
        AgentExecutionWorkflow.run,
        request,
        id=f"task-{request.task_id}",
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        task_queue=task_queue,
        execution_timeout=timedelta(days=1),
        **signal,
    )


def _worker(env, task_queue: str, executor, runner=None) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[AgentExecutionWorkflow],
        activities=_ACTIVITIES,
        activity_executor=executor,
        workflow_runner=runner or create_workflow_runner(),
    )


async def _replay(history, runner=None) -> None:
    await Replayer(
        workflows=[AgentExecutionWorkflow],
        data_converter=pydantic_data_converter,
        workflow_runner=runner or create_workflow_runner(),
    ).replay_workflow(history)


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_follow_up_after_close_continues_the_same_conversation():
    task_id = uuid.uuid4()
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"resume-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                first = await _start(env, task_queue, _request(task_id))
                assert (await first.result()).success is True
                first_history = await first.fetch_history()

                # The follow-up window timed out; the final turn is in the log and
                # the task records where the conversation stands.
                closing = _status_requests[-1]
                assert closing.status == "completed"
                snapshot = closing.conversation_resume
                assert snapshot is not None
                assert closing.total_cost is not None
                assert [_log[seq].role for seq in sorted(_log)] == [
                    "system",
                    "user",
                    "assistant",
                    "tool",
                ]
                assert snapshot.next_seq == len(_log)
                assert snapshot.current_iteration == 1

                resumed = await _start(
                    env,
                    task_queue,
                    _request(
                        task_id,
                        AgentExecutionResume(
                            snapshot=snapshot,
                            total_cost=closing.total_cost,
                            own_cost=closing.own_cost,
                        ),
                    ),
                    message="What was the number?",
                )
                result = await resumed.result()
                resumed_history = await resumed.fetch_history()

    assert resumed.result_run_id != first.result_run_id
    assert result.success is True
    assert result.final_response == "Answer 2"
    first_window, resumed_window = _model_windows
    assert resumed_window == [
        *first_window,
        _log[2].as_message(),
        _log[3].as_message(),
        {"role": "user", "content": "What was the number?"},
    ]
    assert resumed_window[2]["tool_calls"][0]["id"] == resumed_window[3]["tool_call_id"]
    assert result.reasoning_iterations_used == 2
    assert _status_requests[-1].total_cost == Decimal("0.02")
    assert _status_requests[-1].conversation_resume is not None
    assert _status_requests[-1].conversation_resume.next_seq == len(_log)
    await _replay(first_history)
    await _replay(resumed_history)


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_follow_up_racing_a_running_conversation_is_signalled_not_restarted():
    task_id = uuid.uuid4()
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"resume-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                first = await _start(env, task_queue, _request(task_id))
                for _ in range(400):
                    state = await first.query(AgentExecutionWorkflow.get_current_state)
                    if state["success"]:
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise AssertionError("first turn never completed")

                stale_resume = AgentExecutionResume.model_validate(
                    {
                        "snapshot": {
                            "head_seqs": [0],
                            "tail_start": 1,
                            "next_seq": 99,
                            "current_iteration": 50,
                        }
                    }
                )
                again = await _start(
                    env, task_queue, _request(task_id, stale_resume), message="One more thing"
                )
                result = await again.result()

    assert again.result_run_id == first.result_run_id
    assert result.reasoning_iterations_used == 2
    assert _model_windows[1][-1] == {"role": "user", "content": "One more thing"}
    assert len(_model_windows[1]) == 5


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_task_older_than_the_log_resumes_with_a_fresh_system_prompt():
    task_id = uuid.uuid4()
    rebuilt = reconstruct_conversation([], query="Remember the number 42", response="Noted: 42.")
    _log.update((entry.seq, entry) for entry in rebuilt.appended)

    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"resume-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                handle = await _start(
                    env,
                    task_queue,
                    _request(
                        task_id,
                        AgentExecutionResume(
                            snapshot=rebuilt.snapshot,
                            system_prompt_missing=rebuilt.system_prompt_missing,
                        ),
                    ),
                    message="What was the number?",
                )
                result = await handle.result()

    assert result.success is True
    [window] = _model_windows
    assert [message["role"] for message in window] == ["system", "user", "assistant", "user"]
    assert "Retain prior context." in window[0]["content"]
    assert window[1:] == [
        {"role": "user", "content": "Remember the number 42"},
        {"role": "assistant", "content": "Noted: 42."},
        {"role": "user", "content": "What was the number?"},
    ]
    # The logged system prompt stays at the head of the stored window.
    snapshot = _status_requests[-1].conversation_resume
    assert snapshot is not None
    assert _log[snapshot.head_seqs[0]].role == "system"


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_run_recorded_before_the_snapshot_replays(monkeypatch: pytest.MonkeyPatch):
    """A history from before the snapshot existed has no patch marker and no snapshot."""
    patched = workflow.patched
    with monkeypatch.context() as before_the_patch:
        before_the_patch.setattr(
            workflow,
            "patched",
            lambda patch_id: patch_id != CONVERSATION_RESUME_SNAPSHOT_PATCH and patched(patch_id),
        )
        env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
        async with env:
            task_queue = f"resume-{uuid.uuid4()}"
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                async with _worker(env, task_queue, executor, UnsandboxedWorkflowRunner()):
                    handle = await _start(env, task_queue, _request(uuid.uuid4()))
                    assert (await handle.result()).success is True
                    history = await handle.fetch_history()

    assert _status_requests[-1].status == "completed"
    assert _status_requests[-1].conversation_resume is None
    await _replay(history)
