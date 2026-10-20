"""The workspace's ``platform`` stream: what a task's outcome becomes there (ADR-0040 §1, §5).

One stream per workspace, written only by the ``platform`` group from
``tasks.events``. An event says what happened to a task in a few fields; a
reader who wants more opens the task. Tool output, tool arguments and error
details stay in the task log.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agentarea_common.events.contract import (
    APPROVAL_REQUESTED,
    INPUT_REQUEST,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
)
from agentarea_common.events.redaction import mask_inline_secrets

PLATFORM_STREAM_NAME = "platform"
#: The catalog entry of the platform stream's one source.
PLATFORM_SOURCE_TYPE = "platform"
SUMMARY_CHARS = 500

#: The task events the stream carries, with the status each reports.
PLATFORM_STATUSES: dict[str, str] = {
    TASK_COMPLETED: "completed",
    TASK_FAILED: "failed",
    TASK_CANCELLED: "cancelled",
    APPROVAL_REQUESTED: "waiting_for_approval",
    INPUT_REQUEST: "waiting_for_input",
}


@dataclass(frozen=True)
class PlatformTask:
    """The task an event is about, as the platform stream names it."""

    id: UUID
    agent_id: UUID
    owner: str
    correlation_id: str | None
    #: The causation depth of the event that started the task; 0 for one nothing caused.
    depth: int

    @property
    def event_depth(self) -> int:
        return self.depth + 1


def projects(kind: str) -> bool:
    return kind in PLATFORM_STATUSES


def _summary(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    text = mask_inline_secrets(text)
    return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS] + "…"


def platform_event_data(kind: str, task: PlatformTask, data: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "task_id": str(task.id),
        "agent_id": str(task.agent_id),
        "kind": kind,
        "status": PLATFORM_STATUSES[kind],
    }
    if kind == TASK_COMPLETED:
        # A stateless run reports final_response; a conversational turn, result.
        summary["result"] = _summary(data.get("final_response") or data.get("result"))
    elif kind in (TASK_FAILED, TASK_CANCELLED):
        summary["error"] = _summary(data.get("error"))
        summary["failure_reason"] = _summary(data.get("failure_reason"))
    elif kind == APPROVAL_REQUESTED:
        summary["tool_name"] = _summary(data.get("tool_name"))
        summary["reason"] = _summary(data.get("reason") or data.get("message"))
    elif kind == INPUT_REQUEST:
        summary["question"] = _summary(data.get("question"))
    summary["cost"] = data.get("total_cost")
    return {key: value for key, value in summary.items() if value is not None}


def platform_event_key(kind: str, event_id: UUID, data: Mapping[str, Any]) -> str:
    """The task event's id; a request the run records twice is keyed by the request."""
    if kind == APPROVAL_REQUESTED and data.get("escalation_id"):
        return f"approval:{data['escalation_id']}"
    if kind == INPUT_REQUEST and data.get("input_request_id"):
        return f"input:{data['input_request_id']}"
    return str(event_id)
