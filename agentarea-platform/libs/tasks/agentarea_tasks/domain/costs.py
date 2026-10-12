"""The spend ledger: one row per paid line of a task, totals are sums of rows.

A task's spend is kept as the lines it is made of, never as a single number,
so every amount can be traced to the call that incurred it and the evidence
the price was computed from. Run budgets, agent and workspace caps, and task
breakdowns are all sums over these rows.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID


class CostCategory(StrEnum):
    """What kind of spend a line is.

    ``model`` is inference: an agent's LLM turn, a compaction, or a platform
    model a tool ran (image, video, decision). ``service`` is a paid external
    service a tool called, such as an HTTP 402 payment from the agent's wallet.
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
    task_id: UUID
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
