"""The settlement worker against the migrated ledger (wiki ADR-0038 §2.7).

A line marked for settlement that no line supersedes is claimed, finalised by a
superseding line, and never claimed again; sums count only the newest line of a
chain. Only the partial index and the anti-join on the migrated table prove which
lines are waiting.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.tool_cost import Payer
from agentarea_tasks.cost_settlement import CostSettlement
from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
from agentarea_tasks.infrastructure.cost_repository import (
    CostEntryRepository,
    CrossWorkspaceCostLines,
    SpendScope,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

NOW = datetime.now(UTC)


class Billing:
    def __init__(self):
        self.captures = []

    def currency(self):
        return "EUR"

    async def authorize(self, **request):
        raise AssertionError("settlement places no hold")

    async def capture(self, **request):
        self.captures.append(request)
        return SimpleNamespace(amount=Decimal("0.66"), currency="EUR")

    async def void(self, *, hold_id):
        raise AssertionError("settlement voids nothing")

    async def quote(self, lines):
        raise AssertionError("every line here is in EUR")


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def billing(monkeypatch):
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "EUR")
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    installed = Billing()
    ExtensionRegistry.register("tool_billing", lambda: installed)
    yield installed
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


def _line(workspace_id, *, evidence, occurred_at=NOW - timedelta(seconds=30), supersedes=None):
    return CostEntry(
        workspace_id=workspace_id,
        created_by="runner",
        event_id=uuid4(),
        category=CostCategory.SERVICE,
        task_id=uuid4(),
        agent_id=None,
        subject_type=CostSubjectType.TOOL,
        subject_id="conn-1",
        subject_name="web_search",
        call_ref="call",
        amount=Decimal("0.64"),
        currency="EUR",
        source=CostSource.RATE,
        occurred_at=occurred_at,
        payer=Payer.PLATFORM,
        quantity=Decimal(1),
        unit="request",
        vendor_cost=Decimal("0.488"),
        vendor_currency="EUR",
        evidence=evidence,
        supersedes_id=supersedes,
        estimate=True,
    )


async def _vendor_never(line):
    raise AssertionError("no vendor settlement expected")


async def test_a_held_line_is_captured_once_and_the_sum_counts_the_charge(maker, billing):
    workspace_id = str(uuid4())
    held = {"connector": "example.com/search-api", "hold_id": "hold-1", "settle": "capture"}
    waiting = _line(workspace_id, evidence=held)
    final = _line(workspace_id, evidence={"connector": "x"})
    async with maker() as session:
        repo = CostEntryRepository(session, UserContext(user_id="r", workspace_id=workspace_id))
        await repo.record([waiting, final])
        await session.commit()

    settlement = CostSettlement(session_factory=maker, vendor_settle=_vendor_never)
    assert await settlement.settle_batch(NOW) >= 1
    await settlement.settle_batch(NOW + timedelta(seconds=5))

    ours = [c["hold_id"] for c in billing.captures if c["workspace_id"] == workspace_id]
    assert ours == ["hold-1"]
    async with maker() as session:
        repo = CostEntryRepository(session, UserContext(user_id="r", workspace_id=workspace_id))
        total = await repo.sum_since(NOW - timedelta(days=1), currency="EUR", scope=SpendScope())
    assert total == Decimal("0.66") + Decimal("0.64")


async def test_old_lines_are_retried_less_often_and_past_the_horizon_not_at_all(maker):
    workspace_id = str(uuid4())
    held = {"connector": "c", "hold_id": "h", "settle": "capture"}
    hour_old = _line(workspace_id, evidence=held, occurred_at=NOW - timedelta(hours=1))
    ancient = _line(workspace_id, evidence=held, occurred_at=NOW - timedelta(days=30))
    async with maker() as session:
        repo = CostEntryRepository(session, UserContext(user_id="r", workspace_id=workspace_id))
        await repo.record([hour_old, ancient])
        await session.commit()

    tick = timedelta(seconds=5)
    seen = []
    async with maker() as session:
        lines = CrossWorkspaceCostLines(session)
        # An hour-old line is retried every six minutes: due in about one tick in 72.
        for step in range(72 * 2):
            now = NOW + step * tick
            claimed = await lines.claim_unsettled(
                now=now,
                since=now - timedelta(days=7),
                tick=tick,
                max_interval=timedelta(hours=1),
                limit=1000,
            )
            seen.extend(line.event_id for line in claimed if line.workspace_id == workspace_id)
        await session.rollback()

    assert ancient.event_id not in seen
    assert 1 <= seen.count(hour_old.event_id) <= 3
