"""Tool-call approvals: a person's yes to one exact call a client could not wait on.

An agent run that hits an approval rule suspends until someone answers. A
client's call is a stateless request, so the call is recorded instead, a person
decides on a page, and the client's retry with identical arguments runs it once.
The arguments hash is the match: no approval id travels back through the model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

PENDING_TTL = timedelta(hours=24)
APPROVED_TTL = timedelta(hours=1)


class ToolCallApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"
    EXPIRED = "expired"


# A stored status that lapses once ``expires_at`` passes.
LAPSING_STATUSES = (ToolCallApprovalStatus.PENDING, ToolCallApprovalStatus.APPROVED)


class GateVerdict(StrEnum):
    RUN = "run"
    PENDING = "pending"
    REJECTED = "rejected"


class ToolCallApprovalNotFoundError(LookupError):
    """No approval with that id in the workspace."""


class ToolCallApprovalNotPendingError(Exception):
    """The approval was already decided, used, or has expired."""


class NotAnApproverError(PermissionError):
    """The caller is not among the approvers the policy named."""


def arguments_hash(arguments: dict[str, Any]) -> str:
    """sha256 of the arguments as canonical JSON: sorted keys, no whitespace."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def as_utc(value: datetime) -> datetime:
    """A stored timestamp as an aware UTC datetime; a naive one is UTC already."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class ToolCallRequest:
    """One call the policy holds for approval, as the client made it."""

    # None for a platform tool, which belongs to no connection.
    mcp_instance_id: str | None
    connector: str
    # The tool's own name on its server, and the name the policy judged.
    tool: str
    policy_name: str
    arguments: dict[str, Any]
    reason: str
    # Subject refs the policy names as approvers; empty = any workspace member.
    approvers: list[str]
    client_id: str | None
    client_name: str | None


@dataclass(frozen=True)
class ToolCallApproval:
    id: str
    workspace_id: str
    requested_by: str
    client_id: str | None
    client_name: str | None
    mcp_instance_id: str | None
    connector: str
    tool: str
    policy_name: str
    arguments: dict[str, Any]
    arguments_hash: str
    # Effective: a pending or approved row past ``expires_at`` reads as expired.
    status: ToolCallApprovalStatus
    reason: str
    approvers: list[str]
    decided_by: str | None
    decided_at: datetime | None
    comment: str | None
    # Pending: the deadline to decide. Approved: the deadline to use it.
    # Rejected: until when the same call is answered with the rejection.
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class GateOutcome:
    verdict: GateVerdict
    approval: ToolCallApproval
