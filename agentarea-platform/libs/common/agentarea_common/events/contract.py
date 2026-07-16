"""Canonical event contract: dotted taxonomy and supersede-by-id parts.

Pure, side-effect-free. No broker, redis, or db imports. Both the backend
read-path decoder and the frontend reducer mirror this contract.

The source emits the canonical dotted names directly (see EventTypes in
agentarea_execution.workflows.constants); there is no legacy vocabulary and no
alias-on-read bridge.

Core idea — supersede-by-id: every non-lifecycle event maps to a Part with a
stable ``part_id``; a later event with the same ``part_id`` replaces that part
in place. Lifecycle/terminal ``task.*`` events are append-only and derive no
Part.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Canonical (dotted) types — the one vocabulary the source emits and the wire
# carries.
LLM_STARTED = "llm.call.started"
LLM_COMPLETED = "llm.call.completed"
LLM_FAILED = "llm.call.failed"
LLM_CHUNK = "llm.call.chunk"
TOOL_CALL = "tool.call"
TOOL_RESULT = "tool.result"
INPUT_REQUEST = "input.request"
INPUT_RESPONSE = "input.response"
APPROVAL_REQUEST = "approval.request"
APPROVAL_RESPONSE = "approval.response"
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

# Canonical terminal types: append-only lifecycle events that end a task feed.
_TERMINAL_TYPES: frozenset[str] = frozenset({TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED})


def canonical_type(event_type: str) -> str:
    """Return the canonical dotted event type (identity for canonical inputs).

    The source already emits canonical names, so this only strips a leading
    ``workflow.`` prefix defensively. Kept as the call-site seam so read-path
    comparison sites stay uniform.
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
    APPROVAL_REQUEST: "form",
    APPROVAL_RESPONSE: "form",
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
        return f"{execution_id}:{iteration}"
    if kind == "form":
        if canonical in (APPROVAL_REQUEST, APPROVAL_RESPONSE):
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
