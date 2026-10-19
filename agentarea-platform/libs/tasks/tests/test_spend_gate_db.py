"""The tool-call layer's spend gate, against the migrated ledger.

A cap counts only the current lines of its scope (agent, client, connection, tool)
this month, nothing is converted, and a call whose known cost would take a cap past
its amount is refused before it runs.
Only the query on the migrated table proves which lines a scope reaches.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.tool_authorization import ToolAuthorizationRequest
from agentarea_common.extensions import tool_billing
from agentarea_common.tool_cost import Payer, parse_cost_model
from agentarea_governance.domain.policies import BudgetPolicy
from agentarea_governance.tool_calls import GovernedToolCall, ToolConnection
from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository
from agentarea_tasks.spend_gate import monthly_llm_cap_reached, spend_cap_refusal
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
USD_RATE = {"source": "rate", "rate": {"amount": "0.40", "currency": "USD"}}
RUB_RATE = {"source": "rate", "rate": {"amount": "0.488", "currency": "RUB"}}


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def oss_usd(monkeypatch):
    monkeypatch.setattr(tool_billing, "deployment_currency", lambda: "USD")


def _line(
    workspace_id,
    *,
    amount,
    agent_id=None,
    client_id=None,
    connection="conn-1",
    tool="search",
    currency="USD",
    occurred_at=NOW,
    task_id=None,
    category=CostCategory.SERVICE,
):
    return CostEntry(
        workspace_id=workspace_id,
        created_by="runner",
        event_id=uuid4(),
        category=category,
        task_id=task_id or (None if client_id else uuid4()),
        agent_id=agent_id,
        subject_type=(
            CostSubjectType.TOOL
            if category is CostCategory.SERVICE
            else CostSubjectType.MODEL_INSTANCE
        ),
        subject_id=connection,
        subject_name=tool,
        call_ref="call",
        amount=Decimal(amount),
        currency=currency,
        source=CostSource.RATE,
        occurred_at=occurred_at,
        payer=Payer.WORKSPACE,
        client_id=client_id,
    )


def _call(
    workspace_id,
    policy,
    *,
    agent_id=None,
    client_id=None,
    cost=USD_RATE,
    connection="conn-1",
    tool="search",
    task_id=None,
):
    return GovernedToolCall(
        authorization=ToolAuthorizationRequest(
            tool_name=f"x__{tool}",
            tool_args={},
            user_id="runner",
            workspace_id=workspace_id,
            effective_policy=policy,
        ),
        call_id="call",
        agent_id=agent_id,
        task_id=str(task_id) if task_id else None,
        client_id=str(client_id) if client_id else None,
        connection=ToolConnection(
            connection, "vendor/api", tool, Payer.WORKSPACE, parse_cost_model(cost)
        ),
    )


async def _seed(session, workspace_id, lines):
    repo = CostEntryRepository(session, UserContext(user_id="r", workspace_id=workspace_id))
    await repo.record(lines)
    return repo


async def test_an_agent_cap_counts_customer_key_tool_spend_and_stops_the_agent(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="0.60", agent_id=agent_id),
            _line(workspace_id, amount="5.00", agent_id=uuid4()),
            _line(
                workspace_id,
                amount="9.00",
                agent_id=agent_id,
                occurred_at=datetime(2026, 9, 30, tzinfo=UTC),
            ),
        ],
    )
    policy = {"budget": {"agent_monthly_spend_cap_usd": "1.00"}}

    assert (
        await spend_cap_refusal(repo, _call(workspace_id, policy, agent_id=agent_id), now=NOW)
        is None
    )

    await repo.record([_line(workspace_id, amount="0.40", agent_id=agent_id)])
    refusal = await spend_cap_refusal(repo, _call(workspace_id, policy, agent_id=agent_id), now=NOW)

    assert refusal == "agent monthly spend cap of 1 USD reached: 1 USD spent this month"


async def test_connection_tool_and_client_caps_count_only_their_lines(session):
    workspace_id, client_id = str(uuid4()), uuid4()
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="2", tool="search"),
            _line(workspace_id, amount="3", tool="wordstat"),
            _line(workspace_id, amount="4", connection="conn-2"),
            _line(workspace_id, amount="1", client_id=client_id, connection="conn-3"),
        ],
    )

    def cap(**scope):
        return {"budget": {"spend_caps": [{"amount_usd": "3", **scope}]}}

    tool_cap = cap(connection_id="conn-1", tool="search")
    assert await spend_cap_refusal(repo, _call(workspace_id, tool_cap), now=NOW) is None
    refused = await spend_cap_refusal(
        repo, _call(workspace_id, cap(connection_id="conn-1")), now=NOW
    )
    assert refused.startswith("connection spend cap of 3 USD reached: 5 USD")
    other_tool = _call(workspace_id, cap(connection_id="conn-1", tool="wordstat"), tool="wordstat")
    assert (await spend_cap_refusal(repo, other_tool, now=NOW)).startswith("tool spend cap")
    client_call = _call(workspace_id, cap(client_id=str(client_id)), client_id=client_id)
    assert await spend_cap_refusal(repo, client_call, now=NOW) is None
    elsewhere = _call(workspace_id, cap(connection_id="conn-2"))
    assert await spend_cap_refusal(repo, elsewhere, now=NOW) is None


async def test_a_cap_counts_only_lines_in_its_own_currency(session):
    """Nothing is converted: RUB spend is not covered by a USD cap, and never blocked by it."""
    workspace_id = str(uuid4())
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="500", currency="RUB"),
            _line(workspace_id, amount="0.50", currency="USD"),
        ],
    )
    usd_cap = {"budget": {"monthly_spend_cap_usd": "1"}}
    rub_cap = {"budget": {"spend_caps": [{"amount_usd": "300", "currency": "RUB"}]}}

    assert (
        await spend_cap_refusal(repo, _call(workspace_id, usd_cap, cost=RUB_RATE), now=NOW) is None
    )
    refused = await spend_cap_refusal(repo, _call(workspace_id, rub_cap, cost=RUB_RATE), now=NOW)
    assert refused == "workspace monthly spend cap of 300 RUB reached: 500 RUB spent this month"
    totals = await repo.sum_by_currency_since(datetime(2026, 10, 1, tzinfo=UTC))
    assert totals == {"RUB": Decimal("500"), "USD": Decimal("0.50")}


async def test_no_cap_asks_nothing(session):
    workspace_id = str(uuid4())
    repo = await _seed(session, workspace_id, [_line(workspace_id, amount="0.488", currency="RUB")])

    assert await spend_cap_refusal(repo, _call(workspace_id, None, cost=RUB_RATE), now=NOW) is None


async def test_a_tools_cap_counts_tool_lines_only_and_an_llm_cap_never_refuses_a_tool(session):
    workspace_id = str(uuid4())
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="5", category=CostCategory.MODEL),
            _line(workspace_id, amount="0.50"),
        ],
    )

    def cap(category):
        return {"budget": {"spend_caps": [{"amount_usd": "1", "category": category}]}}

    assert await spend_cap_refusal(repo, _call(workspace_id, cap("tools")), now=NOW) is None
    assert await spend_cap_refusal(repo, _call(workspace_id, cap("llm")), now=NOW) is None

    await repo.record([_line(workspace_id, amount="0.50")])
    refused = await spend_cap_refusal(repo, _call(workspace_id, cap("tools")), now=NOW)

    assert refused == "monthly tools spend cap of 1 USD reached: 1 USD spent this month"


async def test_a_run_cap_counts_the_runs_own_lines_whenever_they_were_spent(session):
    workspace_id, task_id = str(uuid4()), uuid4()
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="0.60", task_id=task_id),
            _line(
                workspace_id,
                amount="0.30",
                task_id=task_id,
                occurred_at=datetime(2026, 9, 30, tzinfo=UTC),
            ),
            _line(workspace_id, amount="9", task_id=task_id, category=CostCategory.MODEL),
            _line(workspace_id, amount="9"),
        ],
    )

    def cap(amount, **scope):
        return {"budget": {"spend_caps": [{"amount_usd": amount, "period": "run", **scope}]}}

    tools = cap("1", category="tools")
    assert await spend_cap_refusal(repo, _call(workspace_id, tools, task_id=task_id), now=NOW) is None
    # A call outside a run (a Registered Client's) has no run to count.
    assert await spend_cap_refusal(repo, _call(workspace_id, cap("0.10")), now=NOW) is None

    refused = await spend_cap_refusal(
        repo, _call(workspace_id, cap("0.90", connection_id="conn-1"), task_id=task_id), now=NOW
    )

    assert refused == "run connection spend cap of 0.9 USD reached: 0.9 USD spent in this run"


async def test_a_monthly_llm_cap_counts_model_lines_only(session):
    workspace_id, agent_id = str(uuid4()), uuid4()
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="9", agent_id=agent_id),
            _line(workspace_id, amount="0.70", agent_id=agent_id, category=CostCategory.MODEL),
            _line(workspace_id, amount="0.50", category=CostCategory.MODEL),
        ],
    )

    def budget(**cap):
        return BudgetPolicy(spend_caps=[{"amount_usd": "1", "category": "llm", **cap}])

    agent_cap = budget(own_agent=True)
    assert await monthly_llm_cap_reached(repo, agent_cap, agent_id, "USD", now=NOW) is None
    assert await monthly_llm_cap_reached(repo, budget(category="tools"), None, "USD", now=NOW) is None
    assert await monthly_llm_cap_reached(repo, budget(period="run"), None, "USD", now=NOW) is None

    reached = await monthly_llm_cap_reached(repo, budget(), agent_id, "USD", now=NOW)

    assert (reached.spent, reached.cap, reached.agent_id) == (Decimal("1.2"), Decimal(1), None)


async def test_a_call_whose_known_cost_would_exceed_what_a_cap_has_left_is_refused(session):
    workspace_id = str(uuid4())
    repo = await _seed(session, workspace_id, [_line(workspace_id, amount="0.90")])
    policy = {"budget": {"monthly_spend_cap_usd": "1"}}
    call = _call(workspace_id, policy)

    refused = await spend_cap_refusal(repo, call, (Decimal("0.20"), "USD"), now=NOW)

    assert refused == (
        "workspace monthly spend cap of 1 USD would be exceeded: 0.9 USD spent this month, "
        "this call costs 0.2 USD"
    )
    assert await spend_cap_refusal(repo, call, (Decimal("0.10"), "USD"), now=NOW) is None
    # A cost in another currency is not covered by the cap, so it cannot exceed it.
    assert await spend_cap_refusal(repo, call, (Decimal("50"), "RUB"), now=NOW) is None


async def test_an_agent_may_spend_one_dollar_a_run_of_which_tools_twenty_cents(session):
    """The owner's example (ADR-0038 §2.6): a per-run cap and a per-run cap on tools."""
    workspace_id, task_id = str(uuid4()), uuid4()
    policy = {
        "budget": {
            "spend_caps": [
                {"amount_usd": "1", "period": "run"},
                {"amount_usd": "0.20", "period": "run", "category": "tools"},
            ]
        }
    }
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="0.70", task_id=task_id, category=CostCategory.MODEL),
            _line(workspace_id, amount="0.15", task_id=task_id),
        ],
    )
    call = _call(workspace_id, policy, task_id=task_id)

    tools = await spend_cap_refusal(repo, call, (Decimal("0.10"), "USD"), now=NOW)
    assert tools is not None and tools.startswith("run tools spend cap of 0.2 USD would be")
    assert await spend_cap_refusal(repo, call, (Decimal("0.05"), "USD"), now=NOW) is None

    await repo.record(
        [_line(workspace_id, amount="0.12", task_id=task_id, category=CostCategory.MODEL)]
    )
    total = await spend_cap_refusal(repo, call, (Decimal("0.05"), "USD"), now=NOW)
    assert total is not None and total.startswith("run spend cap of 1 USD would be exceeded")


async def test_the_runs_budget_refuses_a_tool_call_that_would_take_the_run_past_it(session):
    """A per-run cap with no narrowing compiles to the run budget, which the gate also reads."""
    workspace_id, task_id = str(uuid4()), uuid4()
    repo = await _seed(
        session,
        workspace_id,
        [
            _line(workspace_id, amount="0.10", task_id=task_id, category=CostCategory.MODEL),
            _line(workspace_id, amount="0.64", task_id=task_id),
        ],
    )
    call = _call(workspace_id, {"budget": {"run_budget_usd": "0.80"}}, task_id=task_id)

    refused = await spend_cap_refusal(repo, call, (Decimal("0.64"), "USD"), now=NOW)

    assert refused == (
        "run spend cap of 0.8 USD would be exceeded: 0.74 USD spent in this run, "
        "this call costs 0.64 USD"
    )
    assert await spend_cap_refusal(repo, call, (Decimal("0.05"), "USD"), now=NOW) is None


def _builtin_call(workspace_id, policy):
    return GovernedToolCall(
        authorization=ToolAuthorizationRequest(
            tool_name="shell",
            tool_args={},
            user_id="runner",
            workspace_id=workspace_id,
            effective_policy=policy,
        ),
        call_id="call",
        agent_id=None,
        task_id=None,
    )


async def test_a_reached_tools_cap_leaves_free_built_in_tools_alone(session):
    workspace_id = str(uuid4())
    repo = await _seed(session, workspace_id, [_line(workspace_id, amount="1")])
    tools_cap = {"budget": {"spend_caps": [{"amount_usd": "0", "category": "tools"}]}}
    workspace_cap = {"budget": {"monthly_spend_cap_usd": "1"}}

    assert await spend_cap_refusal(repo, _builtin_call(workspace_id, tools_cap), now=NOW) is None
    assert (await spend_cap_refusal(repo, _call(workspace_id, tools_cap), now=NOW)).startswith(
        "monthly tools spend cap"
    )
    assert (
        await spend_cap_refusal(repo, _builtin_call(workspace_id, workspace_cap), now=NOW)
    ).startswith("workspace monthly spend cap")


async def test_the_caps_passed_in_replace_the_ones_the_call_froze(session):
    workspace_id = str(uuid4())
    repo = await _seed(session, workspace_id, [_line(workspace_id, amount="1")])
    frozen = {"budget": {"monthly_spend_cap_usd": "500"}}

    refused = await spend_cap_refusal(
        repo,
        _call(workspace_id, frozen),
        budget=BudgetPolicy(monthly_spend_cap_usd=Decimal("0.01")),
        now=NOW,
    )

    assert refused == (
        "workspace monthly spend cap of 0.01 USD reached: 1 USD spent this month"
    )
