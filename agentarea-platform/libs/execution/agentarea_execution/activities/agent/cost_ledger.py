"""The spend ledger lines a batch of workflow events stands for.

Every paid line of a run is already on a persisted event: ``llm.call.completed``
carries an inference call's priced cost, and ``tool.result`` carries what a tool
paid an external service from the agent's wallet (``service_cost``) and what a
platform model it ran cost (``model_cost``). They are mapped onto ledger rows here,
in the activity that stores the events, so the ledger covers every path without the
workflow doing IO. A line is keyed by its event's id and category, which makes a
retried batch write nothing twice.

A tool call the tool-call layer metered is not among them: the layer writes its
lines (a connector's declared cost, a wallet payment) when the call runs, the same
way for a run and for /mcp, and marks the event ``cost_metered``. A wallet payment
on an event without that mark was made by a build before the layer metered
payments; it is still derived here, keyed by the event, so each payment is one line.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.money import ZERO, to_money, to_optional_money
from agentarea_common.tool_cost import Payer
from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType

from ...workflows.constants import EventTypes

SERVICE_COST_CURRENCY = "USD"
_PAYMENT_SOURCES = {"x402": CostSource.X402, "mpp": CostSource.MPP}
_PAYMENT_EVIDENCE_KEYS = ("protocol", "recipient", "tx_hash", "amount_usd")


def _label(value: Any, limit: int = 255) -> str | None:
    """A free-form name as the ledger column holds it; over-long names are cut."""
    return str(value)[:limit] if value else None


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def cost_entries(
    event: dict[str, Any],
    *,
    workspace_id: str,
    created_by: str,
    billing_currency: str,
) -> list[CostEntry]:
    """The ledger lines one stored workflow event stands for; empty if it is not paid."""
    event_type = event.get("event_type")
    data = event.get("data") or {}
    task_id = _uuid(data.get("task_id"))
    if task_id is None:
        return []

    def line(
        category: CostCategory,
        amount: Any,
        *,
        currency: str,
        source: CostSource,
        subject_type: CostSubjectType,
        subject_id: Any,
        subject_name: Any,
        call_ref: Any = None,
        provider_cost_usd: Any = None,
        payer: Payer = Payer.WORKSPACE,
        evidence: dict[str, Any],
        vendor_cost: Any = None,
        vendor_currency: str | None = None,
        estimate: bool = False,
    ) -> CostEntry:
        return CostEntry(
            workspace_id=workspace_id,
            created_by=created_by,
            event_id=UUID(event["event_id"]),
            category=category,
            task_id=task_id,
            agent_id=_uuid(data.get("agent_id")),
            subject_type=subject_type,
            subject_id=_label(subject_id),
            subject_name=_label(subject_name),
            call_ref=_label(call_ref),
            amount=to_money(amount),
            currency=currency,
            source=source,
            occurred_at=datetime.fromisoformat(event["timestamp"]),
            provider_cost_usd=to_optional_money(provider_cost_usd),
            payer=payer,
            evidence={key: value for key, value in evidence.items() if value is not None},
            vendor_cost=to_optional_money(vendor_cost),
            vendor_currency=vendor_currency,
            estimate=estimate,
        )

    if event_type == EventTypes.LLM_CALL_COMPLETED:
        usage = (data.get("usage") or {}).get("usage") or {}
        # What billing said the call comes to, and the hold still to capture; absent
        # on calls made before holds, whose cost is in the billing currency.
        raw_billing = usage.get("billing")
        billing: dict[str, Any] = raw_billing if isinstance(raw_billing, dict) else {}
        if to_money(billing.get("amount", data.get("cost"))) <= ZERO and not billing.get("hold_id"):
            return []
        return [
            line(
                CostCategory.MODEL,
                billing.get("amount", data.get("cost")),
                currency=str(billing.get("currency") or billing_currency),
                vendor_cost=billing.get("vendor_cost"),
                vendor_currency=billing.get("vendor_currency"),
                estimate=bool(billing.get("estimate")),
                source=CostSource.TOKEN_PRICING,
                subject_type=CostSubjectType.MODEL_INSTANCE,
                subject_id=data.get("model_id"),
                subject_name=data.get("model_name"),
                provider_cost_usd=data.get("provider_cost_usd"),
                payer=(
                    Payer.PLATFORM
                    if data.get("managed_by") == MANAGED_BY_PLATFORM
                    else Payer.WORKSPACE
                ),
                evidence={
                    "iteration": data.get("iteration"),
                    "purpose": data.get("purpose"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "cached_prompt_tokens": usage.get("cached_prompt_tokens"),
                    "cache_creation_tokens": usage.get("cache_creation_tokens"),
                    "hold_id": billing.get("hold_id"),
                    "settle": billing.get("settle"),
                },
            )
        ]

    if event_type != EventTypes.TOOL_CALL_COMPLETED:
        return []

    tool = {
        "subject_type": CostSubjectType.TOOL,
        "subject_id": data.get("server_instance_id"),
        "subject_name": data.get("tool_name"),
        "call_ref": data.get("tool_call_id"),
    }
    tool_evidence = {
        "source": data.get("source"),
        "server_name": data.get("server_name"),
        "iteration": data.get("iteration"),
    }
    entries: list[CostEntry] = []
    if to_money(data.get("model_cost")) > ZERO:
        entries.append(
            line(
                CostCategory.MODEL,
                data.get("model_cost"),
                currency=billing_currency,
                source=CostSource.TOOL_REPORTED,
                evidence=tool_evidence,
                **tool,
            )
        )
    if to_money(data.get("service_cost")) > ZERO and not data.get("cost_metered"):
        raw_payment = data.get("payment")
        payment: dict[str, Any] = raw_payment if isinstance(raw_payment, dict) else {}
        entries.append(
            line(
                CostCategory.SERVICE,
                data.get("service_cost"),
                currency=SERVICE_COST_CURRENCY,
                source=_PAYMENT_SOURCES.get(str(payment.get("protocol")), CostSource.TOOL_REPORTED),
                provider_cost_usd=data.get("service_cost"),
                payer=Payer.PER_CALL,
                evidence={
                    **tool_evidence,
                    "payment": {
                        key: payment[key] for key in _PAYMENT_EVIDENCE_KEYS if key in payment
                    }
                    or None,
                },
                **tool,
            )
        )
    return entries
