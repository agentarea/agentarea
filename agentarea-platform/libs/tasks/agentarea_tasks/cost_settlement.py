"""The settlement worker: turns spend lines that are not final into final ones.

A line marked ``evidence["settle"]`` that no line supersedes yet still waits on
something (wiki ADR-0038 §2.7):

- ``capture``: billing holds what a platform-paid call costs; capturing the hold with
  the call's vendor cost returns what was charged.
- ``vendor``: the vendor says what a call cost only later; the connection's declared
  ``settled.fetch`` reads it with the connection's own credential. A vendor may still
  be adding to the figure for a moment after it reports the run done, so a figure is
  final only once a second fetch reads the same.
- ``convert``: billing could not convert a foreign-currency cost when it was recorded.

Each is finalised by a superseding line, so the ledger stays append-only and only the
newest line of a chain counts. The line is the work item: there is no queue table.
Lines are claimed across workspaces with ``FOR UPDATE SKIP LOCKED``, so any number of
workers share them. How often a line is retried follows from its age alone.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped, workspace_scope
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.tool_billing import KIND_MODEL, KIND_TOOL
from agentarea_common.model_charges import MODEL_CONNECTOR
from agentarea_common.money import to_money
from agentarea_common.tool_cost import CostSourceKind, MeteredCost, Payer
from agentarea_governance.tool_calls import (
    SETTLE_CAPTURE,
    SETTLE_CONVERT,
    SETTLE_VENDOR,
    convert_cost,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
from .infrastructure.cost_repository import CostEntryRepository, CrossWorkspaceCostLines
from .infrastructure.orm import CostEntryORM

logger = logging.getLogger(__name__)

_SETTLED_LINES = UUID("2b9e4a6c-7d31-5f08-9c4e-1a5d8b3f6e27")
_SETTLEMENT_KEYS = ("settle", "settle_params", "vendor_exact")

# What a vendor settlement fetch says a line cost; None while the vendor is not done.
VendorSettle = Callable[[CostEntryORM], Awaitable[MeteredCost | None]]


def _successor_event_id(line: CostEntryORM, kind: str) -> UUID:
    return uuid5(_SETTLED_LINES, f"{line.event_id}:{kind}")


def _successor(
    line: CostEntryORM,
    kind: str,
    *,
    amount: Decimal,
    currency: str,
    estimate: bool,
    vendor_cost: Decimal | None = None,
    vendor_currency: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> CostEntry:
    kept = {k: v for k, v in (line.evidence or {}).items() if k not in _SETTLEMENT_KEYS}
    return CostEntry(
        workspace_id=line.workspace_id,
        created_by=line.created_by,
        event_id=_successor_event_id(line, kind),
        category=CostCategory(line.category),
        task_id=line.task_id,
        agent_id=line.agent_id,
        subject_type=CostSubjectType(line.subject_type),
        subject_id=line.subject_id,
        subject_name=line.subject_name,
        call_ref=line.call_ref,
        amount=amount,
        currency=currency,
        source=(CostSource.SETTLED if kind.startswith(SETTLE_VENDOR) else CostSource(line.source)),
        # The spend happened when the call did: a settled line counts in that period.
        occurred_at=line.occurred_at,
        provider_cost_usd=line.provider_cost_usd,
        payer=Payer(line.payer),
        quantity=line.quantity,
        unit=line.unit,
        vendor_cost=line.vendor_cost if vendor_cost is None else vendor_cost,
        vendor_currency=line.vendor_currency if vendor_currency is None else vendor_currency,
        evidence={**kept, **(evidence or {})},
        supersedes_id=UUID(str(line.id)),
        client_id=line.client_id,
        estimate=estimate,
    )


def _cost(line: CostEntryORM, *, exact: bool) -> MeteredCost:
    """The vendor cost a line records, to convert; its source does not enter a conversion."""
    return MeteredCost(
        Decimal(line.quantity if line.quantity is not None else 1),
        line.unit or "call",
        Decimal(line.vendor_cost or 0),
        str(line.vendor_currency),
        CostSourceKind.REPORTED,
        exact=exact,
    )


async def _capture(line: CostEntryORM) -> CostEntry:
    billing = tool_billing.get_tool_billing()
    evidence = line.evidence or {}
    if billing is None:
        raise RuntimeError(
            f"line {line.id} holds {evidence.get('hold_id')} but no billing is installed"
        )
    model = line.subject_type == CostSubjectType.MODEL_INSTANCE.value
    capture = billing.capture(
        hold_id=str(evidence["hold_id"]),
        workspace_id=line.workspace_id,
        connector=MODEL_CONNECTOR if model else str(evidence.get("connector") or ""),
        tool=str(line.subject_id if model else line.subject_name or ""),
        vendor_cost=Decimal(line.vendor_cost or 0),
        vendor_currency=str(line.vendor_currency),
        quantity=Decimal(line.quantity if line.quantity is not None else 1),
        unit=line.unit or "call",
        idempotency_key=f"tool:{line.event_id}",
        metadata={
            "event_id": str(line.event_id),
            "call_ref": line.call_ref,
            "connection_id": line.subject_id,
            "tool_name": evidence.get("tool_name"),
            "task_id": str(line.task_id) if line.task_id else None,
            "agent_id": str(line.agent_id) if line.agent_id else None,
            "client_id": str(line.client_id) if line.client_id else None,
            "occurred_at": line.occurred_at.isoformat(),
        },
        kind=KIND_MODEL if model else KIND_TOOL,
    )
    charge = await tool_billing.billing_call("capture", capture)
    return _successor(
        line,
        SETTLE_CAPTURE,
        amount=to_money(charge.amount),
        currency=str(charge.currency),
        estimate=False,
    )


async def _vendor(line: CostEntryORM, vendor_settle: VendorSettle) -> CostEntry | None:
    cost = await vendor_settle(line)
    if cost is None:
        return None
    payer = Payer(line.payer)
    # A line that supersedes another already holds a figure read from the vendor.
    confirmed = (
        line.supersedes_id is not None
        and line.vendor_currency == cost.currency
        and Decimal(line.vendor_cost or 0) == cost.vendor_cost
    )
    if not confirmed:
        # Read once: kept waiting, with the figure as read, until a fetch agrees.
        return _successor(
            line,
            f"{SETTLE_VENDOR}:{cost.vendor_cost}",
            amount=Decimal(line.amount),
            currency=str(line.currency),
            estimate=True,
            vendor_cost=cost.vendor_cost,
            vendor_currency=cost.currency,
            evidence={
                key: (line.evidence or {})[key]
                for key in ("settle", "settle_params")
                if key in (line.evidence or {})
            },
        )
    if payer is Payer.PLATFORM and (line.evidence or {}).get("hold_id"):
        # Still held: billing charges the settled cost when the successor is captured.
        return _successor(
            line,
            SETTLE_VENDOR,
            amount=Decimal(line.amount),
            currency=str(line.currency),
            estimate=True,
            vendor_cost=cost.vendor_cost,
            vendor_currency=cost.currency,
            evidence={"settle": SETTLE_CAPTURE},
        )
    connector = str((line.evidence or {}).get("connector") or "")
    converted = await convert_cost(payer, connector, str(line.subject_name or ""), cost)
    evidence: dict[str, Any] = {}
    if converted.pending:
        evidence = {"settle": SETTLE_CONVERT, "vendor_exact": cost.exact}
    return _successor(
        line,
        SETTLE_VENDOR,
        amount=converted.amount,
        currency=converted.currency,
        estimate=not cost.exact or converted.pending,
        vendor_cost=cost.vendor_cost,
        vendor_currency=cost.currency,
        evidence=evidence,
    )


async def _convert(line: CostEntryORM) -> CostEntry | None:
    exact = bool((line.evidence or {}).get("vendor_exact"))
    connector = str((line.evidence or {}).get("connector") or "")
    converted = await convert_cost(
        Payer(line.payer), connector, str(line.subject_name or ""), _cost(line, exact=exact)
    )
    if converted.pending:
        return None
    return _successor(
        line,
        SETTLE_CONVERT,
        amount=converted.amount,
        currency=converted.currency,
        estimate=not exact,
    )


async def settle(line: CostEntryORM, vendor_settle: VendorSettle) -> CostEntry | None:
    """The line that finalises ``line``, or None while what it waits on is not there yet."""
    kind = (line.evidence or {}).get("settle")
    if kind == SETTLE_CAPTURE:
        return await _capture(line)
    if kind == SETTLE_VENDOR:
        return await _vendor(line, vendor_settle)
    if kind == SETTLE_CONVERT:
        return await _convert(line)
    raise ValueError(f"line {line.id} waits on an unknown settlement {kind!r}")


class CostSettlement:
    """Settles waiting lines on a fixed tick, inside the worker (no app of its own)."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        vendor_settle: VendorSettle,
        tick: timedelta = timedelta(seconds=5),
        batch_size: int = 20,
        horizon: timedelta = timedelta(days=7),
        max_interval: timedelta = timedelta(hours=1),
    ) -> None:
        self._session_factory = session_factory
        self._vendor_settle = vendor_settle
        self._tick = tick
        self._batch_size = batch_size
        self._horizon = horizon
        self._max_interval = max_interval
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="cost-settlement")
            logger.info("Cost settlement started (tick=%s)", self._tick)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.settle_batch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cost settlement batch failed")
            await asyncio.sleep(self._tick.total_seconds())

    async def settle_batch(self, now: datetime | None = None) -> int:
        """Settle the lines due now; returns how many were finalised or advanced."""
        now = now or datetime.now(UTC)
        settled = 0
        with unscoped("the settlement worker finalises spend lines of every workspace"):
            async with self._session_factory() as session:
                lines = await CrossWorkspaceCostLines(session).claim_unsettled(
                    now=now,
                    since=now - self._horizon,
                    tick=self._tick,
                    max_interval=self._max_interval,
                    limit=self._batch_size,
                )
                for line in lines:
                    with workspace_scope(line.workspace_id):
                        try:
                            successor = await settle(line, self._vendor_settle)
                        except Exception:
                            logger.error(
                                "Line %s (event %s, %s) could not be settled; retried later",
                                line.id,
                                line.event_id,
                                (line.evidence or {}).get("settle"),
                                exc_info=True,
                            )
                            continue
                        if successor is None:
                            continue
                        repo = CostEntryRepository(
                            session,
                            UserContext(user_id=line.created_by, workspace_id=line.workspace_id),
                        )
                        await repo.record([successor])
                        settled += 1
                await session.commit()
        return settled
