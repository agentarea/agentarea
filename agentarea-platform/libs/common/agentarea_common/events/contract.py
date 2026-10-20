"""Canonical event contract: the closed task-event vocabulary and supersede-by-id parts.

Pure, side-effect-free. No broker, redis, or db imports. Both the backend
read-path decoder and the frontend reducer mirror this contract.

``EVENT_TYPES`` is the one closed, versioned list of dotted task-event types
(ADR-0043 §9). Every producer emits only these names (see EventTypes in
agentarea_execution.workflows.constants) and every place that creates an event
calls ``require_known_type``, so a name outside the list fails loud. Adding,
renaming or removing a type bumps ``VOCABULARY_VERSION``.

Core idea — supersede-by-id: every non-lifecycle event maps to a Part with a
stable ``part_id``; a later event with the same ``part_id`` replaces that part
in place. Lifecycle/terminal ``task.*`` events are append-only and derive no
Part.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

VOCABULARY_VERSION = 5

LLM_STARTED = "llm.call.started"
LLM_COMPLETED = "llm.call.completed"
LLM_FAILED = "llm.call.failed"
LLM_CHUNK = "llm.call.chunk"
TOOL_CALL = "tool.call"
TOOL_RESULT = "tool.result"
# An MCP server's progress on a running call. Not a part: the tool part of the
# same tool_call_id stays as tool.call / tool.result left it.
TOOL_PROGRESS = "tool.progress"
INPUT_REQUEST = "input.request"
INPUT_RESPONSE = "input.response"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_DECIDED = "approval.decided"
ARTIFACT_CREATED = "artifact.created"
ARTIFACT_UPDATED = "artifact.updated"
A2UI_CREATE = "a2ui.create"
A2UI_UPDATE_COMPONENTS = "a2ui.update.components"
A2UI_UPDATE_DATA = "a2ui.update.data"
A2UI_DELETE = "a2ui.delete"
TASK_STARTED = "task.started"
TASK_COMPLETED = "task.completed"
TASK_FAILED = "task.failed"
TASK_CANCELLED = "task.cancelled"
TASK_AWAITING_FOLLOW_UP = "task.awaiting_follow_up"
TASK_AWAITING_CONTINUATION = "task.awaiting_continuation"
TASK_CONTINUED = "task.continued"
TASK_AWAITING_INFRASTRUCTURE = "task.awaiting_infrastructure"
TASK_INFRASTRUCTURE_RECOVERED = "task.infrastructure_recovered"
TASK_RETRIED = "task.retried"
EXECUTION_FINISHED = "execution.finished"
EXECUTION_CONTINUED_AS_NEW = "execution.continued_as_new"
EXECUTION_PAUSED = "execution.paused"
EXECUTION_RESUMED = "execution.resumed"
ARTIFACT_VALIDATION_STARTED = "artifact.validation.started"
ARTIFACT_VALIDATION_COMPLETED = "artifact.validation.completed"
TURN_STARTED = "turn.started"
TURN_COMPLETED = "turn.completed"
TURN_ABORTED = "turn.aborted"
BUDGET_WARNING = "budget.warning"
BUDGET_EXCEEDED = "budget.exceeded"
BUDGET_UPDATED = "budget.updated"
SERVICE_PAYMENT = "service.payment"
SERVICE_BUDGET_WARNING = "service.budget_warning"
SERVICE_BUDGET_EXCEEDED = "service.budget_exceeded"
CONTEXT_COMPACTED = "context.compacted"
CONTEXT_WARNING = "context.warning"
ANSWER_CHECKED = "answer.checked"
MODEL_CHANGED = "model.changed"
MODEL_FALLBACK = "model.fallback"
MODEL_UNAVAILABLE = "model.unavailable"
RUNTIME_DISCOVERED = "runtime.discovered"
COMMAND_RECEIVED = "command.received"
COMMAND_REJECTED = "command.rejected"
MESSAGE_QUEUED = "message.queued"
MESSAGE_RECEIVED = "message.received"
MESSAGE_REMOVED = "message.removed"
INPUT_SUBMITTED = "input.submitted"
DELEGATION_STARTED = "delegation.started"
DELEGATION_COMPLETED = "delegation.completed"
DELEGATION_FAILED = "delegation.failed"

# The closed vocabulary, one line per type.
EVENT_DESCRIPTIONS: dict[str, str] = {
    TASK_STARTED: "The run started for the first time.",
    TASK_COMPLETED: "The run (or a conversational turn's reply) finished with a result.",
    TASK_FAILED: "The run ended with an error.",
    TASK_CANCELLED: "The run was cancelled.",
    TASK_AWAITING_FOLLOW_UP: "A conversational run replied and waits for the next message.",
    TASK_AWAITING_CONTINUATION: "The run hit a limit and waits for a decision to continue.",
    TASK_CONTINUED: "A run waiting for continuation was allowed to go on.",
    TASK_AWAITING_INFRASTRUCTURE: (
        "A service the run needs is unreachable; the run waits and retries on its own."
    ),
    TASK_INFRASTRUCTURE_RECOVERED: "The service the run waited for answered; the run went on.",
    TASK_RETRIED: "A failed run was started again from its last state.",
    EXECUTION_FINISHED: "The workflow execution ended, whatever the outcome.",
    EXECUTION_CONTINUED_AS_NEW: "The workflow rolled its history over into a fresh execution.",
    EXECUTION_PAUSED: "Someone paused the run.",
    EXECUTION_RESUMED: "Someone resumed a paused run.",
    TURN_STARTED: "A turn (one model call and the tool calls it asks for) began.",
    TURN_COMPLETED: "A turn ended normally.",
    TURN_ABORTED: "A turn ended early: failure, cancellation, a limit or a block.",
    LLM_STARTED: "A model call began.",
    LLM_CHUNK: "A snapshot of a model call's streamed reply so far (live only).",
    LLM_COMPLETED: "A model call ended with its reply, usage and cost.",
    LLM_FAILED: "A model call failed.",
    TOOL_CALL: "The agent called a tool.",
    TOOL_RESULT: "A tool call ended, with its output or its error.",
    TOOL_PROGRESS: "A running tool call reported progress.",
    APPROVAL_REQUESTED: "A tool call waits for a person to approve it.",
    APPROVAL_DECIDED: "A person approved or denied a tool call.",
    INPUT_REQUEST: "The agent asked a person for structured input.",
    INPUT_SUBMITTED: "A person's answer to an input request reached the run.",
    INPUT_RESPONSE: "The run took the answer to an input request.",
    MESSAGE_QUEUED: "A message was queued for the agent's next turn.",
    MESSAGE_RECEIVED: "A person's message entered the conversation: the run's input or a follow-up.",
    MESSAGE_REMOVED: "A queued message was removed before the agent saw it.",
    COMMAND_RECEIVED: "The run accepted a control command.",
    COMMAND_REJECTED: "The run refused a malformed control command.",
    BUDGET_WARNING: "The run's spend crossed the warning share of its budget.",
    BUDGET_EXCEEDED: "The run's spend reached its budget.",
    BUDGET_UPDATED: "The run's budget was lowered while it ran.",
    SERVICE_PAYMENT: "The agent paid a paid service.",
    SERVICE_BUDGET_WARNING: "Service payments crossed the warning share of their budget.",
    SERVICE_BUDGET_EXCEEDED: "Service payments reached their budget.",
    CONTEXT_WARNING: "The conversation filled the warning share of the model's window.",
    CONTEXT_COMPACTED: "Older conversation was summarised to make room.",
    ANSWER_CHECKED: "The final answer's check found leaks; data says which and the rewrite.",
    MODEL_CHANGED: "The run switched to another model.",
    MODEL_FALLBACK: "The requested model could not be resolved and another was used.",
    MODEL_UNAVAILABLE: "The run's model could not be resolved.",
    RUNTIME_DISCOVERED: "The run's runtime manifest (tools, skills, sandbox) was resolved.",
    DELEGATION_STARTED: "The agent handed a sub-task to another agent.",
    DELEGATION_COMPLETED: "A delegated sub-task returned its result.",
    DELEGATION_FAILED: "A delegated sub-task failed.",
    ARTIFACT_VALIDATION_STARTED: "The run's output artifacts are being validated.",
    ARTIFACT_VALIDATION_COMPLETED: "Artifact validation finished with its verdict.",
    ARTIFACT_CREATED: "The run produced an artifact.",
    ARTIFACT_UPDATED: "The run changed an artifact it produced.",
    A2UI_CREATE: "The agent opened an interactive UI surface.",
    A2UI_UPDATE_COMPONENTS: "The agent changed a UI surface's components.",
    A2UI_UPDATE_DATA: "The agent changed a UI surface's data.",
    A2UI_DELETE: "The agent closed a UI surface.",
}

EVENT_TYPES: frozenset[str] = frozenset(EVENT_DESCRIPTIONS)

# Signals that matter only while the run is live: broadcast, never stored
# (ADR-0043 §9). The completed call supersedes them.
LIVE_ONLY_TYPES: frozenset[str] = frozenset({LLM_STARTED, LLM_CHUNK, TOOL_PROGRESS})


class UnknownEventTypeError(ValueError):
    """An event type outside the closed vocabulary."""


def require_known_type(event_type: str) -> str:
    """Return ``event_type`` when it is in the vocabulary; raise otherwise."""
    if event_type not in EVENT_TYPES:
        raise UnknownEventTypeError(
            f"Unknown event type {event_type!r}: not in the task-event vocabulary "
            f"v{VOCABULARY_VERSION} (agentarea_common.events.contract.EVENT_TYPES)"
        )
    return event_type


# Canonical terminal types: append-only lifecycle events that end a task feed.
_TERMINAL_TYPES: frozenset[str] = frozenset({TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED})


def canonical_type(event_type: str) -> str:
    """Return the canonical dotted event type (identity for canonical inputs).

    The vocabulary is already canonical at the source; the only transform is
    stripping the ``workflow.`` namespace prefix that the activity publisher
    adds when it puts an event on the wire (see event_publisher). Kept as the
    call-site seam so read-path comparison sites stay uniform.
    """
    return event_type[len("workflow.") :] if event_type.startswith("workflow.") else event_type


# Canonical type -> part kind. Absence means "no part" (lifecycle/terminal).
_KIND_BY_TYPE: dict[str, str] = {
    LLM_STARTED: "llm",
    LLM_COMPLETED: "llm",
    LLM_FAILED: "llm",
    LLM_CHUNK: "llm",
    TOOL_CALL: "tool",
    TOOL_RESULT: "tool",
    INPUT_REQUEST: "form",
    INPUT_RESPONSE: "form",
    APPROVAL_REQUESTED: "form",
    APPROVAL_DECIDED: "form",
    ARTIFACT_CREATED: "artifact",
    ARTIFACT_UPDATED: "artifact",
    A2UI_CREATE: "a2ui",
    A2UI_UPDATE_COMPONENTS: "a2ui",
    A2UI_UPDATE_DATA: "a2ui",
    A2UI_DELETE: "a2ui",
}


@dataclass(frozen=True)
class Part:
    part_id: str
    kind: str
    event_type: str
    data: dict[str, Any]


def _part_id_for(kind: str, canonical: str, data: dict[str, Any]) -> str | None:
    if kind == "tool":
        return _as_str(data.get("tool_call_id"))
    if kind == "llm":
        execution_id = data.get("execution_id")
        iteration = data.get("iteration")
        if execution_id is None or iteration is None:
            return None
        # A compaction call is metered like a turn but is not the turn's reply;
        # its own id keeps it from superseding (or being superseded by) that part.
        if data.get("purpose") == "compaction":
            return f"{execution_id}:{iteration}:compaction"
        return f"{execution_id}:{iteration}"
    if kind == "form":
        if canonical in (APPROVAL_REQUESTED, APPROVAL_DECIDED):
            return _as_str(data.get("escalation_id") or data.get("request_id"))
        return _as_str(data.get("input_request_id") or data.get("request_id"))
    if kind == "a2ui":
        return _as_str(data.get("surface_id"))
    if kind == "artifact":
        return _as_str(data.get("artifact_id"))
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def derive_part(event_type: str, data: dict[str, Any]) -> Part | None:
    """Derive the superseding Part for an event, or None for lifecycle events."""
    canonical = canonical_type(event_type)
    kind = _KIND_BY_TYPE.get(canonical)
    if kind is None:
        return None
    part_id = _part_id_for(kind, canonical, data)
    if part_id is None:
        return None
    return Part(part_id=part_id, kind=kind, event_type=canonical, data=data)


def ensure_terminal_message(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Return terminal event data with a user-facing ``message`` (additive).

    A client attaching AFTER a task finishes renders the final state from the
    catch-up snapshot alone, so terminal events must carry a human-readable
    ``message`` (and ``reason`` for failed/cancelled). Non-terminal events pass
    through unchanged, and an existing ``message`` is never overwritten.

    Returns the same dict instance mutated in place; the caller may pass a copy
    if the source must stay untouched.
    """
    canonical = canonical_type(event_type)
    if canonical not in _TERMINAL_TYPES:
        return data

    if canonical == TASK_COMPLETED:
        if not data.get("message"):
            final = _as_str(data.get("final_response") or data.get("result"))
            data["message"] = final or "Task completed."
        return data

    # Failed / cancelled: carry a reason too.
    reason = _as_str(
        data.get("reason")
        or data.get("error")
        or data.get("blocked_reason")
        or data.get("error_type")
    )
    if canonical == TASK_FAILED:
        reason = reason or "Task failed."
        data.setdefault("reason", reason)
        if not data.get("message"):
            data["message"] = reason
    else:  # TASK_CANCELLED
        reason = reason or "Task cancelled."
        data.setdefault("reason", reason)
        if not data.get("message"):
            data["message"] = reason
    return data


def reduce_parts(events: Iterable[tuple[str, dict[str, Any]]]) -> list[Part]:
    """Fold an event stream into ordered parts via supersede-by-id.

    Non-part events are skipped. A later part with an existing ``part_id``
    replaces the earlier one at its original position.
    """
    order: list[str] = []
    by_id: dict[str, Part] = {}
    for event_type, data in events:
        part = derive_part(event_type, data)
        if part is None:
            continue
        if part.part_id not in by_id:
            order.append(part.part_id)
        by_id[part.part_id] = part
    return [by_id[pid] for pid in order]
