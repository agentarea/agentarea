"""The audit trail of what an agent's tools were allowed, denied and asked to do.

The workflow's persisted events already carry every policy outcome of a tool
call: ``tool.call`` once the gate let it run, a ``tool.result`` marked
``denied_by_policy`` when it refused, ``approval.request`` when it paused for a
human and ``approval.response`` with who decided. They are mapped onto audit
rows here, in the activity that stores them, so the trail covers every gate
without the workflow doing IO. Each row reuses its event's id, which makes a
retried batch write nothing twice.

Tool arguments never reach the audit trail, only their names: values are the
model's input and may carry anything the task saw, secrets included.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agentarea_common.audit import AuditService

from ...workflows.constants import EventTypes

TOOL_CALL_ALLOWED = "tool.call.allowed"
TOOL_CALL_DENIED = "tool.call.denied"
TOOL_CALL_APPROVAL_REQUIRED = "tool.call.approval_required"
APPROVAL_APPROVED = "approval.approved"
APPROVAL_DENIED = "approval.denied"


@dataclass(frozen=True)
class ToolAuditEntry:
    """One audit row derived from a workflow event."""

    action: str
    actor_type: str
    actor_id: str | None
    task_id: str
    metadata: dict[str, Any]


def argument_keys(arguments: Any) -> list[str]:
    """The names of a tool call's arguments, never their values."""
    return sorted(str(key) for key in arguments) if isinstance(arguments, dict) else []


def tool_audit_entry(event: dict[str, Any]) -> ToolAuditEntry | None:
    """The audit row a stored workflow event stands for, or None if it is not one."""
    event_type = event.get("event_type")
    data = event.get("data") or {}
    task_id = str(data.get("task_id") or "")
    agent_id = data.get("agent_id")
    base = {
        "tool": data.get("tool_name"),
        "task_id": task_id,
        "agent_id": agent_id,
        "tool_call_id": data.get("tool_call_id"),
    }

    def as_agent(action: str, **extra: Any) -> ToolAuditEntry:
        return ToolAuditEntry(
            action=action,
            actor_type="agent",
            actor_id=str(agent_id) if agent_id else None,
            task_id=task_id,
            metadata={**base, **extra},
        )

    if event_type == EventTypes.TOOL_CALL_STARTED:
        return as_agent(
            TOOL_CALL_ALLOWED,
            decision="allowed",
            argument_keys=argument_keys(data.get("arguments")),
        )
    if event_type == EventTypes.AGENT_DELEGATION_STARTED:
        return as_agent(
            TOOL_CALL_ALLOWED,
            decision="allowed",
            delegate_agent_id=data.get("target_agent_id"),
        )
    if event_type == EventTypes.TOOL_CALL_COMPLETED and data.get("denied_by_policy"):
        return as_agent(TOOL_CALL_DENIED, decision="denied", reason=data.get("error"))
    if event_type == EventTypes.HUMAN_APPROVAL_REQUESTED:
        return as_agent(
            TOOL_CALL_APPROVAL_REQUIRED,
            decision="approval_required",
            reason=data.get("message"),
            escalation_id=data.get("escalation_id"),
            approvers=data.get("approvers"),
            argument_keys=argument_keys(data.get("arguments")),
        )
    # Only the response that carries the decision: before the one-response
    # patch a denial also emitted a second, decision-less approval.response.
    if event_type == EventTypes.HUMAN_APPROVAL_RECEIVED and "approved" in data:
        approved = bool(data["approved"])
        approver = data.get("approved_by")
        return ToolAuditEntry(
            action=APPROVAL_APPROVED if approved else APPROVAL_DENIED,
            actor_type="user" if approver else "system",
            actor_id=str(approver) if approver else None,
            task_id=task_id,
            metadata={
                **base,
                "decision": "approved" if approved else "denied",
                "comment": data.get("comment"),
                "escalation_id": data.get("escalation_id"),
            },
        )
    return None


async def record_tool_audit(
    audit: AuditService, event_id: UUID, entry: ToolAuditEntry, *, requested_by: str
) -> None:
    """Write ``entry`` once under its event's id.

    ``requested_by`` is the user the task runs for; it stands in as the actor
    only when the event names none.
    """
    await audit.record_once(
        event_id,
        entry.action,
        "task",
        entry.task_id or None,
        actor_type=entry.actor_type,
        actor_id=entry.actor_id or requested_by,
        event_metadata={
            **{k: v for k, v in entry.metadata.items() if v is not None},
            "requested_by": requested_by,
        },
    )
