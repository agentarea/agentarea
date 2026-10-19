"""Reusable mock activities and helpers for workflow integration tests."""

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.infrastructure.task_log import model_window
from temporalio import activity

from agentarea_execution.models import (
    AgentConfigRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    LogRow,
    MCPToolRequest,
    RecordRequest,
    RecordResult,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)

# ---------------------------------------------------------------------------
# LLM response builders
# ---------------------------------------------------------------------------


def llm_response_text(content: str = "Hello!", cost: float = 0.001) -> dict[str, Any]:
    """Plain text response, no tool calls."""
    return {
        "content": content,
        "role": "assistant",
        "tool_calls": [],
        "finish_reason": "stop",
        "cost": cost,
        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
    }


def llm_response_completion(
    result: str = "Task completed", artifacts: list[str] | None = None
) -> dict[str, Any]:
    """LLM calls the completion tool -> triggers task_complete."""
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"call_{uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({"result": result, "artifacts": artifacts or []}),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def llm_response_tool_call(tool_name: str = "search", args: dict | None = None) -> dict[str, Any]:
    """LLM calls a regular tool -> triggers another iteration."""
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"call_{uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args or {"query": "test"}),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
    }


# ---------------------------------------------------------------------------
# Sequenced LLM mock activity
# ---------------------------------------------------------------------------


def make_sequenced_llm_activity(responses: list[dict[str, Any]]):
    """Create a call_llm_activity that returns responses in sequence.

    After exhausting the list, repeats the last response.
    """
    call_count = {"n": 0}

    @activity.defn(name="call_llm_activity")
    async def sequenced_call_llm(request: LLMCallRequest) -> dict[str, Any]:
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    return sequenced_call_llm


# ---------------------------------------------------------------------------
# Event capture
# ---------------------------------------------------------------------------


class EventCapture:
    """Captures published events in order for assertions."""

    def __init__(self):
        self.events: list[dict[str, Any]] = []

    @property
    def event_types(self) -> list[str]:
        return [e["event_type"] for e in self.events]

    def make_activity(self):
        """Create a publish_workflow_events_activity that captures events."""
        capture = self

        @activity.defn(name="publish_workflow_events_activity")
        async def mock_publish_events(
            request: WorkflowEventsRequest,
        ) -> WorkflowEventsResult:
            for ej in request.events_json:
                if not ej or not ej.strip():
                    continue
                data = json.loads(ej)
                capture.events.append(data)
            return WorkflowEventsResult(success=True, events_published=len(request.events_json))

        return mock_publish_events

    def make_record_activity(self):
        """Create a record_activity that captures the events it records."""
        return make_record_activity(publish=self.make_activity())


# ---------------------------------------------------------------------------
# Run policy
# ---------------------------------------------------------------------------


def runtime_policy(max_model_turns: int = 5, run_budget_usd: str = "1.00") -> dict[str, Any]:
    """An effective policy carrying every runtime limit the workflow requires."""
    return {
        "budget": {"run_budget_usd": run_budget_usd},
        "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 4_000},
        "execution": {
            "max_model_turns": max_model_turns,
            "max_tool_calls_per_turn": 10,
            "max_tool_calls_total": 100,
        },
    }


# ---------------------------------------------------------------------------
# Standard boilerplate mock activities
# ---------------------------------------------------------------------------


@activity.defn(name="build_agent_config_activity")
async def mock_build_agent_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Test Agent",
        "model_id": "gpt-4o-mini",
        "instruction": "You are a helpful assistant.",
        "context_window": 128000,
        "tools_config": {"mcp_servers": []},
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def mock_resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id,
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "api_key_secret": None,
        "endpoint_url": None,
        "context_window": 128000,
        "display_name": "GPT-4o Mini",
        "provider_display_name": "OpenAI",
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


@activity.defn(name="execute_mcp_tool_activity")
async def mock_execute_mcp_tool(request: MCPToolRequest) -> dict[str, Any]:
    return {"success": True, "result": "Mock result", "tool_name": request.tool_name}


@activity.defn(name="update_task_status_activity")
async def mock_update_task_status(request: UpdateTaskStatusRequest) -> bool:
    return True


@activity.defn(name="validate_artifacts_activity")
async def mock_validate_artifacts(
    request: ArtifactValidationRequest,
) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


# ---------------------------------------------------------------------------
# Task log
# ---------------------------------------------------------------------------


class TaskLogFake:
    """An in-memory task log: the record activity writes it, model calls read it.

    Rows are kept once per task and position, as the real append keeps them once
    per id.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[int, LogRow]] = {}
        self.statuses: list[UpdateTaskStatusRequest] = []
        self.requests: list[RecordRequest] = []

    def append(self, request: RecordRequest) -> None:
        self.requests.append(request)
        rows = self.rows.setdefault(request.task_id, {})
        for row in request.rows:
            rows.setdefault(row.seq, row)
        if request.status is not None:
            self.statuses.append(request.status)

    def entries(self, task_id: str | None = None) -> list[ConversationEntry]:
        """One task's rows in order; without ``task_id``, the only task's."""
        if task_id is None:
            [task_id] = self.rows
        rows = self.rows.get(task_id, {})
        return [_entry(rows[seq]) for seq in sorted(rows)]

    def window(self, conversation: Any, pending: list[dict[str, Any]]) -> list[ConversationEntry]:
        """What a model call or compaction on ``conversation`` reads.

        The log's window, then the pending messages it carries.
        """
        logged = [
            entry
            for entry in self.entries(conversation.task_id)
            if entry.seq < conversation.next_seq
        ]
        unwritten = [
            ConversationEntry(seq=conversation.next_seq + offset, **message)
            for offset, message in enumerate(pending)
        ]
        return [*model_window(logged), *(e for e in unwritten if e.kind != "event")]

    def messages(self, request: LLMCallRequest) -> list[dict[str, Any]]:
        """The messages the model call of ``request`` sends; a call without a log its own."""
        if request.conversation is None:
            return request.messages
        return [entry.as_message() for entry in self.window(request.conversation, request.messages)]


def _entry(row: LogRow) -> ConversationEntry:
    return ConversationEntry(**row.model_dump(exclude={"event_id"}), event_id=UUID(row.event_id))


def make_record_activity(
    *,
    publish: Callable[[WorkflowEventsRequest], Awaitable[Any]] | None = None,
    update_status: Callable[[UpdateTaskStatusRequest], Awaitable[Any]] | None = None,
    log: TaskLogFake | None = None,
):
    """A record_activity that keeps the rows in ``log``.

    It hands the status and the events to a test's own status and publish mocks,
    in the order the real one writes them. The events are the event rows and the
    live-only signals the run sent beside them, in the order they happened.
    """

    @activity.defn(name="record_activity")
    async def record(request: RecordRequest) -> RecordResult:
        if log is not None:
            log.append(request)
        if request.status is not None and update_status is not None:
            await update_status(request.status)
        events = [
            {
                "event_id": row.event_id,
                "event_type": row.name,
                "timestamp": row.timestamp,
                "data": row.meta or {},
            }
            for row in request.rows
            if row.kind == "event" and row.timestamp is not None
        ] + [json.loads(event) for event in request.events_json]
        events.sort(key=lambda event: event["timestamp"])
        if events and publish is not None:
            await publish(
                WorkflowEventsRequest(
                    events_json=[json.dumps(event) for event in events],
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                )
            )
        return RecordResult(rows=len(request.rows), events=len(request.events_json))

    return record
