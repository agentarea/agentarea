"""The spend ledger: one row per paid line, totals are sums of rows.

Spend is kept as the lines it is made of, never as a single number, so every
amount can be traced to the call that incurred it and the evidence the price was
computed from. Run budgets, spend caps and task breakdowns are all sums over these
rows. Most lines belong to a task; a tool call a Registered Client made over /mcp
belongs to that client and no task.

A tool call's line names the connection and tool, who paid (``payer``), how much was
used and what the vendor charged. A ``platform`` line is also the usage log billing
meters: billing prices its vendor cost; ``amount`` is the display and caps figure.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from agentarea_common.tool_cost import Payer

if TYPE_CHECKING:
    from agentarea_governance.tool_calls import ToolUsage

_TOOL_CALL_EVENTS = UUID("6f1d3c52-9a47-5e0b-8c21-4b7a9e2f1d08")


class CostCategory(StrEnum):
    """What kind of spend a line is.

    ``model`` is inference: an agent's LLM turn, a compaction, or a platform
    model a tool ran (image, video, decision). ``service`` is a tool call that
    cost something: on the customer's key, on the platform's, or paid from the
    agent's wallet (x402/MPP).
    """

    MODEL = "model"
    SERVICE = "service"


class CostSource(StrEnum):
    """How the amount of a line was established.

    ``x402`` and ``mpp`` name wallet payments recorded before the tool-call layer
    metered them; such a payment is now ``reported`` with the protocol in evidence.
    """

    TOKEN_PRICING = "token_pricing"  # noqa: S105 - enum value, not a credential
    TOOL_REPORTED = "tool_reported"
    RATE = "rate"
    REPORTED = "reported"
    SETTLED = "settled"
    X402 = "x402"
    MPP = "mpp"


class CostSubjectType(StrEnum):
    """What was bought."""

    MODEL_INSTANCE = "model_instance"
    TOOL = "tool"


@dataclass(frozen=True)
class CostEntry:
    """One paid line.

    ``currency`` is the ISO 4217 code ``amount`` is in. ``supersedes_id`` names
    an earlier line this one replaces, so an estimate settled later keeps both
    numbers and only the newest counts towards a sum. For a tool line,
    ``subject_id`` is the connection and ``subject_name`` the tool.
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
    payer: Payer = Payer.WORKSPACE
    quantity: Decimal | None = None
    unit: str | None = None
    vendor_cost: Decimal | None = None
    vendor_currency: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    supersedes_id: UUID | None = None
    client_id: UUID | None = None


def tool_call_event_id(line_key: str) -> UUID:
    """The ledger key of one tool call's line: the same call retried is the same line."""
    return uuid5(_TOOL_CALL_EVENTS, line_key)


def tool_call_entry(usage: "ToolUsage") -> CostEntry:
    """The line a metered tool call is, from a run or from /mcp."""
    return CostEntry(
        workspace_id=usage.workspace_id,
        created_by=usage.user_id,
        event_id=tool_call_event_id(usage.line_key),
        category=CostCategory.SERVICE,
        task_id=UUID(usage.task_id) if usage.task_id else None,
        agent_id=usage.agent_id,
        subject_type=CostSubjectType.TOOL,
        subject_id=usage.connection_id,
        subject_name=(usage.tool or usage.tool_name)[:255],
        call_ref=usage.call_id[:255],
        amount=usage.amount,
        currency=usage.currency,
        source=CostSource(usage.source.value),
        occurred_at=usage.occurred_at,
        payer=usage.payer,
        quantity=usage.quantity,
        unit=usage.unit[:32],
        vendor_cost=usage.vendor_cost,
        vendor_currency=usage.vendor_currency,
        evidence={
            key: value
            for key, value in {
                "connector": usage.connector,
                "tool_name": usage.tool_name,
                **usage.evidence,
            }.items()
            if value is not None
        },
        client_id=UUID(usage.client_id) if usage.client_id else None,
    )
