"""A run writes its task log through one door and reads its window from it.

The record activity appends the log rows with the task's status after each model
call and tool result; no other activity writes the conversation or the status.
The model's window is the system prompt (row 0), the latest compaction and every
message after it; a compaction summarizes everything before it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.activities.agent.conversation import compaction_input
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    CompactMessagesRequest,
    CompactMessagesResult,
    LLMCallRequest,
    LLMUsage,
    MCPToolRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.testing import (
    TaskLogFake,
    make_record_activity,
    mock_build_agent_config,
    mock_validate_artifacts,
    runtime_policy,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

_TOOL = {
    "type": "function",
    "function": {
        "name": "run_report",
        "description": "Runs the report.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _reply(*calls: dict[str, Any], prompt_tokens: int = 100) -> dict[str, Any]:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": list(calls),
        "cost": "0.001",
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 10,
            "total_tokens": prompt_tokens + 10,
        },
    }


class _Run:
    """The stubbed activities of one run and what they saw."""

    def __init__(
        self,
        *,
        context_window: int = 128_000,
        prompt_tokens: int = 100,
        tool_time: float | None = 1.5,
    ) -> None:
        self.tool_time = tool_time
        self.log = TaskLogFake()
        self.windows: list[list[dict[str, Any]]] = []
        self.requests: list[LLMCallRequest] = []
        self.status_calls: list[UpdateTaskStatusRequest] = []
        self.publish_calls: list[WorkflowEventsRequest] = []
        self.compactions: list[CompactMessagesRequest] = []
        self.first_call_started = asyncio.Event()
        self.release_first_call = asyncio.Event()
        self.release_first_call.set()
        self.context_window = context_window
        self.prompt_tokens = prompt_tokens

    def activities(self) -> list[Any]:
        run = self

        @activity.defn(name="build_agent_config_activity")
        async def build_config(request: AgentConfigRequest) -> dict[str, Any]:
            return {
                **(await mock_build_agent_config(request)),
                "context_window": run.context_window,
            }

        @activity.defn(name="discover_available_tools_activity")
        async def discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
            return {"tools": [_TOOL], "context_strategy": "STATIC"}

        @activity.defn(name="resolve_model_activity")
        async def resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
            return {
                "model_id": request.model_id,
                "provider_type": "openai",
                "model_name": f"name-of-{request.model_id}",
                "context_window": run.context_window,
                "resolved_at": "2026-01-01T00:00:00+00:00",
            }

        @activity.defn(name="call_llm_activity")
        async def call_llm(request: LLMCallRequest) -> dict[str, Any]:
            run.requests.append(request)
            run.windows.append(run.log.messages(request))
            if len(run.requests) == 1:
                run.first_call_started.set()
                await run.release_first_call.wait()
                return _reply(_call("report-1", "run_report", {}), prompt_tokens=run.prompt_tokens)
            return _reply(
                _call("done-1", "completion", {"result": "Report ready", "artifacts": []})
            )

        @activity.defn(name="execute_mcp_tool_activity")
        async def execute_tool(request: MCPToolRequest) -> dict[str, Any]:
            return {
                "success": True,
                "result": "42 rows",
                "exit_code": 0,
                **({"execution_time": run.tool_time} if run.tool_time is not None else {}),
                "server_name": "reports",
                "artifact_paths": ["out/report.csv"],
            }

        @activity.defn(name="compact_messages_activity")
        async def compact(request: CompactMessagesRequest) -> CompactMessagesResult:
            run.compactions.append(request)
            entries = run.log.window(request.conversation, request.pending)
            _, skills, replaced = compaction_input(entries)
            return CompactMessagesResult(
                summary=f"{len(replaced)} entries summarized",
                skills=skills,
                original_message_count=len(replaced),
                estimated_tokens_saved=100,
                context_tokens=50,
                cost="0.001",
                usage=LLMUsage(prompt_tokens=100, completion_tokens=10, total_tokens=110),
            )

        @activity.defn(name="update_task_status_activity")
        async def update_status(request: UpdateTaskStatusRequest) -> bool:
            run.status_calls.append(request)
            return True

        @activity.defn(name="publish_workflow_events_activity")
        async def publish(request: WorkflowEventsRequest) -> WorkflowEventsResult:
            run.publish_calls.append(request)
            return WorkflowEventsResult(success=True, events_published=len(request.events_json))

        return [
            build_config,
            discover_tools,
            resolve_model,
            call_llm,
            execute_tool,
            compact,
            update_status,
            publish,
            make_record_activity(log=run.log),
            mock_validate_artifacts,
        ]


async def _drive(run: _Run, during=None):
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"task-log-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=run.activities(),
                activity_executor=executor,
                workflow_runner=create_workflow_runner(),
            ):
                policy = runtime_policy()
                policy["tools"] = {"allowed": ["*"]}
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="log-user",
                        workspace_id="log-workspace",
                        task_query="Build the monthly report",
                        effective_policy=policy,
                        workflow_metadata={"source": "agent_delegation"},
                    ),
                    id=f"task-log-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(minutes=10),
                )
                if during is not None:
                    await during(handle)
                return await handle.result()


@pytest.mark.asyncio
async def test_a_run_records_its_log_and_status_through_the_record_activity():
    run = _Run()

    result = await _drive(run)

    assert result.success is True
    assert run.status_calls == []
    assert run.publish_calls == []
    rows = run.log.entries()
    assert [row.seq for row in rows] == list(range(len(rows)))
    messages = [row for row in rows if row.kind != "event"]
    assert (messages[0].role, messages[1].role, messages[1].content) == (
        "system",
        "user",
        "Build the monthly report",
    )
    [assistant, *_] = [row for row in rows if row.role == "assistant"]
    assert assistant.meta == {"model_id": "gpt-4o-mini", "model_name": "name-of-gpt-4o-mini"}
    [tool] = [row for row in rows if row.name == "run_report"]
    assert tool.content == "42 rows"
    assert tool.meta is not None
    assert {key: tool.meta[key] for key in ("exit_code", "duration", "server")} == {
        "exit_code": 0,
        "duration": 1.5,
        "server": "reports",
    }
    assert tool.meta["artifact_paths"] == ["out/report.csv"]
    assert tool.meta["started_at"]
    assert all(row.iteration for row in messages)
    assert all(request.conversation.head_seqs is None for request in run.requests)
    assert any(m.get("content") == "42 rows" for m in run.windows[1])
    assert run.log.statuses[-1].status == "completed"


@pytest.mark.asyncio
async def test_the_runs_events_are_event_rows_and_live_signals_are_not_kept():
    run = _Run()

    await _drive(run)

    rows = run.log.entries()
    events = [row.name for row in rows if row.kind == "event"]
    assert "task.started" in events
    assert "tool.result" in events
    assert "task.completed" in events
    assert not {"llm.call.started", "llm.call.chunk", "tool.progress"} & set(events)
    assert all(row.meta and row.meta.get("task_id") for row in rows if row.kind == "event")
    sent = [
        json.loads(event)["event_type"]
        for request in run.log.requests
        for event in request.events_json
    ]
    assert set(sent) <= {"llm.call.started", "llm.call.chunk", "tool.progress"}


@pytest.mark.asyncio
async def test_a_tool_that_reports_no_time_gets_the_duration_the_workflow_measured():
    run = _Run(tool_time=None)

    await _drive(run)

    [tool] = [row for row in run.log.entries() if row.name == "run_report"]
    assert tool.meta is not None
    assert isinstance(tool.meta["duration"], float)
    assert tool.meta["duration"] >= 0


@pytest.mark.asyncio
async def test_a_model_change_is_an_event_row_and_the_next_answer_names_the_new_model():
    run = _Run()
    run.release_first_call.clear()

    async def change_model(handle):
        await asyncio.wait_for(run.first_call_started.wait(), timeout=30)
        await handle.signal(
            AgentExecutionWorkflow.workflow_command,
            args=[
                "change_model",
                {
                    "model_id": "model-b",
                    "provider_type": "openai",
                    "model_name": "name-of-model-b",
                    "context_window": 128000,
                    "changed_by": "user-7",
                },
            ],
        )
        run.release_first_call.set()

    result = await _drive(run, during=change_model)

    assert result.success is True
    rows = run.log.entries()
    [changed] = [row for row in rows if row.kind == "event" and row.name == "model.changed"]
    assert {key: changed.meta[key] for key in ("from", "to", "by")} == {
        "from": {"model_id": "gpt-4o-mini", "model_name": "name-of-gpt-4o-mini"},
        "to": {"model_id": "model-b", "model_name": "name-of-model-b"},
        "by": "user-7",
    }
    answers = [row.meta for row in rows if row.role == "assistant"]
    assert answers[-1] == {"model_id": "model-b", "model_name": "name-of-model-b"}
    assert all(m["role"] != "event" for window in run.windows for m in window)


@pytest.mark.asyncio
async def test_a_compaction_row_replaces_everything_before_it_in_the_window():
    run = _Run(context_window=4_000, prompt_tokens=3_500)

    result = await _drive(run)

    assert result.success is True
    assert len(run.compactions) == 1
    assert run.compactions[0].conversation.head_seqs is None
    rows = run.log.entries()
    [compaction] = [row for row in rows if row.kind == "compaction"]
    assert compaction.content.startswith("[Previous conversation summary]\n")
    assert compaction.seq > max(row.seq for row in rows if row.name == "run_report")
    after = run.windows[1]
    assert [m["role"] for m in after] == ["system", "user"]
    assert after[1]["content"].startswith("[Previous conversation summary]")
