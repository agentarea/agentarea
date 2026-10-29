"""How an AgentArea task and its workflow events look on the A2A wire.

Wire types are the SDK's ``a2a.types`` protobuf messages. Nothing here touches a
service: these are the pure translations the request handler composes, kept
apart so they can be tested without a server.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from a2a.server.events.event_queue import Event
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.proto_utils import make_dict_serializable
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_common.events.contract import (
    APPROVAL_REQUESTED,
    CONTEXT_COMPACTED,
    DELEGATION_COMPLETED,
    DELEGATION_FAILED,
    DELEGATION_STARTED,
    INPUT_REQUEST,
    LLM_CHUNK,
    TASK_AWAITING_CONTINUATION,
    TASK_AWAITING_INFRASTRUCTURE,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TOOL_CALL,
    TOOL_PROGRESS,
    TOOL_RESULT,
    TURN_STARTED,
    canonical_type,
)
from agentarea_tasks.domain.models import AgentTask
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp

logger = logging.getLogger(__name__)

RESPONSE_ARTIFACT_NAME = "agent-response"

# Every status a task row can hold (see ``BaseTaskService._validate_task``).
_TASK_STATES: dict[str, TaskState] = {
    "submitted": TaskState.TASK_STATE_SUBMITTED,
    "pending": TaskState.TASK_STATE_SUBMITTED,
    "preparing": TaskState.TASK_STATE_SUBMITTED,
    "scheduled": TaskState.TASK_STATE_SUBMITTED,
    "running": TaskState.TASK_STATE_WORKING,
    "working": TaskState.TASK_STATE_WORKING,
    "waiting_for_input": TaskState.TASK_STATE_INPUT_REQUIRED,
    "waiting_for_approval": TaskState.TASK_STATE_INPUT_REQUIRED,
    "waiting_for_continuation": TaskState.TASK_STATE_INPUT_REQUIRED,
    "waiting_for_infrastructure": TaskState.TASK_STATE_WORKING,
    "completed": TaskState.TASK_STATE_COMPLETED,
    "failed": TaskState.TASK_STATE_FAILED,
    "blocked": TaskState.TASK_STATE_FAILED,
    "cancelled": TaskState.TASK_STATE_CANCELED,
    "canceled": TaskState.TASK_STATE_CANCELED,
}

TERMINAL_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
    }
)

_TERMINAL_EVENT_STATES = {
    TASK_COMPLETED: TaskState.TASK_STATE_COMPLETED,
    TASK_FAILED: TaskState.TASK_STATE_FAILED,
    TASK_CANCELLED: TaskState.TASK_STATE_CANCELED,
}
# Terminal task event types that end an A2A stream.
TERMINAL_EVENT_TYPES = frozenset(_TERMINAL_EVENT_STATES)


def task_state(status: str) -> TaskState:
    state = _TASK_STATES.get(status)
    if state is None:
        # A row with a status this map does not know must still read; it is
        # reported, not guessed into a state a client would act on.
        logger.warning("Task status %r has no A2A task state", status)
        return TaskState.TASK_STATE_UNSPECIFIED
    return state


def context_id_for(task: AgentTask) -> str:
    """The task's A2A ``contextId``: the one the client sent, else the task id."""
    return str((task.metadata or {}).get("a2a_context_id") or task.id)


def final_text(task: AgentTask) -> str | None:
    """The agent's final answer: ``task.result["response"]`` (ADR 2026-06-20)."""
    result = task.result
    if isinstance(result, dict):
        for key in ("response", "final_response", "result", "text"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _struct(values: dict[str, Any]) -> Struct:
    struct = Struct()
    struct.update(make_dict_serializable(values))
    return struct


def _timestamp(value: datetime | None) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(value or datetime.now(UTC))
    return ts


def _agent_message(message_id: str, text: str) -> Message:
    return Message(message_id=message_id, role=Role.ROLE_AGENT, parts=[Part(text=text)])


def to_a2a_task(task: AgentTask) -> Task:
    """The A2A ``Task`` for a task row.

    On success the final text is surfaced both as an artifact and as
    ``status.message``, so a client reading only the status still gets it.
    """
    state = task_state(task.status)
    a2a_task = Task(
        id=str(task.id),
        context_id=context_id_for(task),
        status=TaskStatus(state=state, timestamp=_timestamp(task.updated_at)),
    )

    text: str | None = None
    if state == TaskState.TASK_STATE_COMPLETED:
        text = final_text(task)
        if text:
            a2a_task.artifacts.append(
                Artifact(
                    artifact_id=str(task.id),
                    name=RESPONSE_ARTIFACT_NAME,
                    parts=[Part(text=text)],
                )
            )
    elif state in (TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_REJECTED):
        text = task.error_message or final_text(task)
    if text:
        a2a_task.status.message.CopyFrom(_agent_message(f"{task.id}-status", text))

    if task.metadata:
        a2a_task.metadata.CopyFrom(_struct(task.metadata))
    return a2a_task


def message_text(message: Message) -> str:
    return "".join(part.text for part in message.parts if part.WhichOneof("content") == "text")


# The agent key a task was started with; only that key may read or act on it.
AGENT_KEY_METADATA = "a2a_agent_key_id"


def build_agent_task(
    *,
    message: Message,
    metadata: dict[str, Any],
    agent_id: UUID,
    auth: A2AAuthContext,
    user_id: str,
    workspace_id: str,
    method: str,
    request_id: str | int | None,
) -> AgentTask:
    """The task an inbound A2A message becomes.

    Client-supplied ``metadata`` is merged first, so it can carry options such
    as ``requires_human_approval`` but cannot overwrite the provenance and
    security context recorded here.
    """
    text = message_text(message)
    now = datetime.now(UTC).isoformat()
    a2a_metadata: dict[str, Any] = {
        **metadata,
        "source": "a2a",
        "a2a_method": method,
        "a2a_request_id": request_id,
        "auth_method": auth.auth_method,
        "authenticated": auth.authenticated,
        "created_via": "a2a_protocol",
        "created_timestamp": now,
        "security_context": {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "permissions": auth.permissions,
            "auth_timestamp": now,
        },
        "monitoring": {
            "task_source": "a2a_protocol",
            "protocol_version": "1.0",
            "message_length": len(text),
            "has_message_parts": bool(message.parts),
            "message_parts_count": len(message.parts),
            "is_streaming": method == "SendStreamingMessage",
            "agent_target": str(agent_id),
        },
    }
    a2a_metadata.pop(AGENT_KEY_METADATA, None)
    if auth.agent_key_id:
        a2a_metadata[AGENT_KEY_METADATA] = auth.agent_key_id
    if message.context_id:
        a2a_metadata["a2a_context_id"] = message.context_id
    if "agent_name" in auth.metadata:
        a2a_metadata["target_agent_name"] = auth.metadata["agent_name"]
    client_metadata = {
        key: auth.metadata[key]
        for key in ("user_agent", "client_ip", "forwarded_for")
        if auth.metadata.get(key)
    }
    if client_metadata:
        a2a_metadata["client_metadata"] = client_metadata

    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return AgentTask(
        id=uuid4(),
        title=first_line[:80] or "A2A Message Task",
        description=text.strip() or "Task created from A2A message",
        query=text,
        user_id=user_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        status="submitted",
        task_parameters={},
        metadata=a2a_metadata,
    )


def _payload(event_data: dict[str, Any]) -> dict[str, Any]:
    """The workflow payload, nested under ``original_data`` on the live channel."""
    payload = event_data.get("original_data")
    return payload if isinstance(payload, dict) else event_data


def event_text(event_data: dict[str, Any]) -> str:
    """Text carried by a streamed workflow event.

    Final answers live in ``result``/``final_response``; an ``llm.call.chunk``
    carries the call's whole reply so far in ``chunk``.
    """
    payload = _payload(event_data)
    for key in ("chunk", "content", "text", "result", "final_response", "delta"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _name(payload: dict[str, Any], key: str, fallback: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) and value else fallback


def _step(canonical: str, payload: dict[str, Any]) -> str | None:
    """What the agent is doing, in a line a person can read, for a working status.

    Names only: a tool's arguments and results stay out, since the caller may be
    another party's agent.
    """
    tool = _name(payload, "tool_name", "a tool")
    if canonical == TURN_STARTED:
        iteration = payload.get("iteration")
        return f"Step {iteration}" if isinstance(iteration, int) else "Thinking"
    if canonical == TOOL_CALL:
        return f"Calling {tool}"
    if canonical == TOOL_RESULT:
        failed = payload.get("error") or payload.get("success") is False
        return f"{tool} failed" if failed else f"{tool} finished"
    if canonical == TOOL_PROGRESS:
        message = payload.get("message")
        return f"{tool}: {message}" if isinstance(message, str) and message else None
    if canonical == DELEGATION_STARTED:
        return f"Asking {_name(payload, 'target_agent_name', 'another agent')}"
    if canonical == DELEGATION_COMPLETED:
        return f"{_name(payload, 'target_agent_name', 'The other agent')} answered"
    if canonical == DELEGATION_FAILED:
        return f"{_name(payload, 'target_agent_name', 'The other agent')} could not answer"
    if canonical == CONTEXT_COMPACTED:
        return "Summarising the earlier conversation"
    if canonical == TASK_AWAITING_INFRASTRUCTURE:
        return "Waiting for a service to come back"
    return None


def _interruption(canonical: str, payload: dict[str, Any]) -> str | None:
    """Why the run stopped to wait on its caller, or None when it did not."""
    if canonical == INPUT_REQUEST:
        return _name(payload, "question", "The agent needs more information")
    if canonical == APPROVAL_REQUESTED:
        return f"Waiting for approval to run {_name(payload, 'tool_name', 'a tool')}"
    if canonical == TASK_AWAITING_CONTINUATION:
        return _name(payload, "message", "The run reached a limit and waits for a decision")
    return None


def _status_update(
    state: TaskState,
    *,
    task_id: str,
    context_id: str,
    text: str | None = None,
    event: str | None = None,
) -> TaskStatusUpdateEvent:
    status = TaskStatus(state=state, timestamp=_timestamp(None))
    if text:
        status.message.CopyFrom(_agent_message(uuid4().hex, text))
    update = TaskStatusUpdateEvent(task_id=task_id, context_id=context_id, status=status)
    if event:
        update.metadata.CopyFrom(_struct({"agentarea_event": event}))
    return update


def workflow_event_to_a2a(
    event_type: str, event_data: dict[str, Any], *, task_id: str, context_id: str
) -> tuple[list[Event], bool]:
    """Map one task event to A2A stream events; the bool says the stream is over.

    A terminal event yields the full answer as a last-chunk artifact (on
    success) and then the terminal status. A run that stops to wait on its
    caller (a question, an approval, a limit) reports input-required and ends
    the stream too. LLM chunks replace the response artifact: each carries the
    call's reply so far. A step the agent takes is a working status whose
    message says what it does, with the event type in ``metadata``; anything
    else is a bare working status.
    """
    canonical = canonical_type(event_type)
    payload = _payload(event_data)
    state = _TERMINAL_EVENT_STATES.get(canonical)
    if state is not None:
        events: list[Event] = []
        text = event_text(event_data) if state == TaskState.TASK_STATE_COMPLETED else ""
        if text:
            events.append(
                TaskArtifactUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    artifact=Artifact(
                        artifact_id=task_id,
                        name=RESPONSE_ARTIFACT_NAME,
                        parts=[Part(text=text)],
                    ),
                    append=False,
                    last_chunk=True,
                )
            )
        events.append(_status_update(state, task_id=task_id, context_id=context_id))
        return events, True

    reason = _interruption(canonical, payload)
    if reason is not None:
        return [
            _status_update(
                TaskState.TASK_STATE_INPUT_REQUIRED,
                task_id=task_id,
                context_id=context_id,
                text=reason,
                event=canonical,
            )
        ], True

    if canonical == LLM_CHUNK:
        text = event_text(event_data)
        if not text:
            return [], False
        return [
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=task_id, name=RESPONSE_ARTIFACT_NAME, parts=[Part(text=text)]
                ),
                append=False,
                last_chunk=False,
            )
        ], False

    step = _step(canonical, payload)
    return [
        _status_update(
            TaskState.TASK_STATE_WORKING,
            task_id=task_id,
            context_id=context_id,
            text=step,
            event=canonical if step else None,
        )
    ], False
