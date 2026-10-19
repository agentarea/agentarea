"""Real migrated PostgreSQL coverage for the spend ledger.

A retried event batch must not store a paid line twice, and caps read sums that
skip superseded lines and lines in another currency. Only the unique constraint
and the query on the migrated table can prove that.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository, SpendScope
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

MONTH_START = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _entry(workspace_id: str, agent_id, amount: str, **changes) -> CostEntry:
    entry = CostEntry(
        workspace_id=workspace_id,
        created_by="event-writer",
        event_id=uuid4(),
        category=CostCategory.MODEL,
        task_id=uuid4(),
        agent_id=agent_id,
        subject_type=CostSubjectType.MODEL_INSTANCE,
        subject_id="model-1",
        subject_name="gpt-luna-6",
        call_ref=None,
        amount=Decimal(amount),
        currency="USD",
        source=CostSource.TOKEN_PRICING,
        occurred_at=datetime(2026, 10, 7, 12, tzinfo=UTC),
    )
    return replace(entry, **changes)


def _repo(session: AsyncSession, workspace_id: str) -> CostEntryRepository:
    return CostEntryRepository(session, UserContext(user_id="reader", workspace_id=workspace_id))


async def test_a_retried_line_is_stored_once(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    line = _entry(workspace_id, agent_id, "0.25")
    repo = _repo(session, workspace_id)

    assert await repo.record([line]) == 1
    assert await repo.record([line]) == 0

    count = await session.scalar(
        text("SELECT count(*) FROM cost_entries WHERE event_id = :id"), {"id": line.event_id}
    )
    assert count == 1
    assert await repo.sum_since(MONTH_START, currency="USD") == Decimal("0.25")


async def test_one_event_keeps_its_model_and_service_lines_apart(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    model = _entry(workspace_id, agent_id, "0.10")
    service = replace(model, category=CostCategory.SERVICE, amount=Decimal("0.05"))
    repo = _repo(session, workspace_id)

    await repo.record([model, service])

    assert await repo.sum_since(MONTH_START, currency="USD") == Decimal("0.15")


async def test_agent_sum_counts_only_that_agents_current_lines(session):
    workspace_id, agent_id, other_agent = str(uuid4()), uuid4(), uuid4()
    estimate = _entry(workspace_id, agent_id, "1.00")
    repo = _repo(session, workspace_id)
    await repo.record(
        [
            estimate,
            _entry(workspace_id, agent_id, "0.50"),
            _entry(workspace_id, other_agent, "7.00"),
            _entry(workspace_id, agent_id, "9.00", occurred_at=datetime(2026, 9, 30, tzinfo=UTC)),
            _entry(workspace_id, agent_id, "3.00", currency="RUB"),
        ]
    )
    stored_estimate = await session.scalar(
        text("SELECT id FROM cost_entries WHERE event_id = :id"), {"id": estimate.event_id}
    )
    await repo.record([_entry(workspace_id, agent_id, "1.20", supersedes_id=stored_estimate)])

    assert await repo.sum_since(MONTH_START, currency="USD", agent_id=agent_id) == Decimal("1.70")
    assert await repo.sum_since(MONTH_START, currency="USD") == Decimal("8.70")


async def test_a_line_of_another_workspace_is_refused(session):
    repo = _repo(session, str(uuid4()))

    with pytest.raises(ValueError, match="belongs to workspace"):
        await repo.record([_entry(str(uuid4()), uuid4(), "0.10")])


async def test_daily_totals_group_current_lines_by_utc_day(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    repo = _repo(session, workspace_id)
    await repo.record(
        [
            _entry(
                workspace_id, agent_id, "0.10", occurred_at=datetime(2026, 10, 6, 23, tzinfo=UTC)
            ),
            _entry(
                workspace_id, agent_id, "0.20", occurred_at=datetime(2026, 10, 7, 1, tzinfo=UTC)
            ),
            _entry(
                workspace_id, agent_id, "0.30", occurred_at=datetime(2026, 10, 7, 22, tzinfo=UTC)
            ),
        ]
    )

    totals = await repo.sum_by_day(MONTH_START, currency="USD", agent_id=agent_id)

    assert totals == {date(2026, 10, 6): Decimal("0.10"), date(2026, 10, 7): Decimal("0.50")}


async def test_a_line_with_no_task_counts_for_its_workspace_and_no_agent(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    client_id = uuid4()
    client_line = _entry(
        workspace_id, None, "0.74", task_id=None, client_id=client_id, category=CostCategory.SERVICE
    )
    repo = _repo(session, workspace_id)

    await repo.record([client_line, _entry(workspace_id, agent_id, "0.26")])
    await repo.record([client_line])

    stored = (
        await session.execute(
            text("SELECT task_id, client_id FROM cost_entries WHERE event_id = :id"),
            {"id": client_line.event_id},
        )
    ).all()
    assert stored == [(None, client_id)]
    assert await repo.sum_since(MONTH_START, currency="USD") == Decimal("1.00")
    assert await repo.sum_since(MONTH_START, currency="USD", agent_id=agent_id) == Decimal("0.26")


async def test_the_estimated_part_of_spend_is_its_current_lines_not_yet_final(session):
    workspace_id = str(uuid4())
    repo = _repo(session, workspace_id)
    held = _entry(workspace_id, None, "0.64", estimate=True)
    await repo.record(
        [
            held,
            _entry(workspace_id, None, "1.00"),
            _entry(workspace_id, None, "0.30", estimate=True),
            _entry(workspace_id, None, "0.66", supersedes_id=None, estimate=False),
        ]
    )
    [held_id] = (
        await session.execute(
            text("SELECT id FROM cost_entries WHERE event_id = :e"), {"e": held.event_id}
        )
    ).scalars()
    await repo.record([_entry(workspace_id, None, "0.66", supersedes_id=held_id)])

    estimated = await repo.sum_since(MONTH_START, currency="USD", scope=SpendScope(estimate=True))
    exact = await repo.sum_since(MONTH_START, currency="USD", scope=SpendScope(estimate=False))

    assert estimated == Decimal("0.30")
    assert exact == Decimal("1.00") + Decimal("0.66") + Decimal("0.66")
