"""A model call is refused at a monthly spend cap, against the migrated ledger.

The workspace cap counts every current line of the workspace this month, the agent
cap only its agent's; neither counts last month or another currency.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.tool_cost import Payer
from agentarea_governance.domain.policies import BudgetPolicy
from agentarea_tasks import model_spend_caps
from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository
from agentarea_tasks.model_spend_caps import SpendCapReachedError, refuse_model_call_at_spend_cap
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def usd_billing(monkeypatch):
    class _Pricing:
        def currency(self):
            return "USD"

    monkeypatch.setattr(model_spend_caps, "get_customer_pricing", _Pricing)


def _line(workspace_id, *, amount, agent_id=None, currency="USD", occurred_at=NOW, model=True):
    return CostEntry(
        workspace_id=workspace_id,
        created_by="runner",
        event_id=uuid4(),
        category=CostCategory.MODEL if model else CostCategory.SERVICE,
        task_id=uuid4(),
        agent_id=agent_id,
        subject_type=CostSubjectType.MODEL_INSTANCE if model else CostSubjectType.TOOL,
        subject_id="subject",
        subject_name="name",
        call_ref="call",
        amount=Decimal(amount),
        currency=currency,
        source=CostSource.RATE,
        occurred_at=occurred_at,
        payer=Payer.WORKSPACE,
    )


async def _seeded(session, lines) -> UserContext:
    user_context = UserContext(user_id="runner", workspace_id=lines[0].workspace_id)
    await CostEntryRepository(session, user_context).record(lines)
    return user_context


async def test_the_workspace_cap_counts_every_line_of_the_month_in_its_currency(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    user_context = await _seeded(
        session,
        [
            _line(workspace_id, amount="0.60", agent_id=agent_id),
            _line(workspace_id, amount="0.30", model=False),
            _line(workspace_id, amount="50", currency="EUR"),
            _line(workspace_id, amount="9", occurred_at=datetime(2026, 9, 30, tzinfo=UTC)),
        ],
    )

    async def refuse(cap: str) -> None:
        await refuse_model_call_at_spend_cap(
            session,
            user_context,
            BudgetPolicy(monthly_spend_cap_usd=Decimal(cap)),
            agent_id,
            now=NOW,
        )

    await refuse("0.91")
    with pytest.raises(SpendCapReachedError) as raised:
        await refuse("0.90")

    assert raised.value.reason.startswith("Workspace monthly spend cap reached (0.9")


async def test_the_agent_cap_counts_only_its_agents_lines(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    user_context = await _seeded(
        session,
        [
            _line(workspace_id, amount="0.40", agent_id=agent_id),
            _line(workspace_id, amount="0.20", agent_id=agent_id, model=False),
            _line(workspace_id, amount="5", agent_id=uuid4()),
        ],
    )

    async def refuse(cap: str, agent=agent_id) -> None:
        await refuse_model_call_at_spend_cap(
            session,
            user_context,
            BudgetPolicy(agent_monthly_spend_cap_usd=Decimal(cap)),
            agent,
            now=NOW,
        )

    await refuse("0.61")
    await refuse("0.10", agent=uuid4())
    with pytest.raises(SpendCapReachedError) as raised:
        await refuse("0.60")

    assert raised.value.reason.startswith("Agent monthly spend cap reached (0.6")
