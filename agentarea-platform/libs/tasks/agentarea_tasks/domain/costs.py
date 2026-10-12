"""The spend ledger: one row per paid line, totals are sums of rows.

Spend is kept as the lines it is made of, never as a single number, so every
amount can be traced to the call that incurred it and the evidence the price was
computed from. Run budgets, agent and workspace caps, and task breakdowns are all
sums over these rows. Most lines belong to a task; a platform-funded tool call a
Registered Client made over /mcp belongs to that client and no task.

It is also the usage log billing meters: a line with ``managed_by`` platform is
something the platform paid a vendor for, and billing rates its evidence.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from agentarea_common.constants import MANAGED_BY_PLATFORM

if TYPE_CHECKING:
    from agentarea_governance.tool_calls import PlatformToolUsage

_TOOL_CALL_EVENTS = UUID("6f1d3c52-9a47-5e0b-8c21-4b7a9e2f1d08")
TOOL_CALL_UNIT = "call"


class CostCategory(StrEnum):
    """What kind of spend a line is.

    ``model`` is inference: an agent's LLM turn, a compaction, or a platform
    model a tool ran (image, video, decision). ``service`` is a paid external
    service a tool called, such as an HTTP 402 payment from the agent's wallet,
    or a search API the platform pays for and charges on (``managed_by`` platform).
    """

    MODEL = "model"
    SERVICE = "service"


class CostSource(StrEnum):
    """How the amount of a line was established."""

    TOKEN_PRICING = "token_pricing"  # noqa: S105 - enum value, not a credential
    TOOL_REPORTED = "tool_reported"
    X402 = "x402"
    MPP = "mpp"


class CostSubjectType(StrEnum):
    """What was bought."""

    MODEL_INSTANCE = "model_instance"
    TOOL = "tool"


@dataclass(frozen=True)
class CostEntry:
    """One paid line, derived from the workflow event that reported it.

    ``currency`` is the ISO 4217 code ``amount`` is in. ``supersedes_id`` names
    an earlier line this one replaces, so an estimate settled later keeps both
    numbers and only the newest counts towards a sum.
    """

    workspace_id: str
    created_by: str
    event_id: UUID
    category: CostCategory
    task_id: UUID | None
    agent_id: UUID | None
    subject_type: CostSubjectType
    subject_id: str | None
    subject_name: str | None
    call_ref: str | None
    amount: Decimal
    currency: str
    source: CostSource
    occurred_at: datetime
    provider_cost_usd: Decimal | None = None
    managed_by: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    supersedes_id: UUID | None = None
    client_id: UUID | None = None


def tool_call_event_id(call_id: str) -> UUID:
    """The ledger key of one tool call: the same call retried is the same line."""
    return uuid5(_TOOL_CALL_EVENTS, call_id)


def platform_tool_call_entry(usage: "PlatformToolUsage") -> CostEntry:
    """The one line a platform-funded tool call that ran is, from a run or from /mcp."""
    return CostEntry(
        workspace_id=usage.workspace_id,
        created_by=usage.user_id,
        event_id=tool_call_event_id(usage.call_id),
        category=CostCategory.SERVICE,
        task_id=UUID(usage.task_id) if usage.task_id else None,
        agent_id=usage.agent_id,
        subject_type=CostSubjectType.TOOL,
        subject_id=usage.resource_ref,
        subject_name=usage.tool_name[:255],
        call_ref=usage.call_id[:255],
        amount=usage.amount,
        currency=usage.currency,
        source=CostSource.TOOL_REPORTED,
        occurred_at=usage.occurred_at,
        managed_by=MANAGED_BY_PLATFORM,
        evidence={
            "quantity": usage.quantity,
            "unit": TOOL_CALL_UNIT,
            "resource_ref": usage.resource_ref,
        },
        client_id=UUID(usage.client_id) if usage.client_id else None,
    )
