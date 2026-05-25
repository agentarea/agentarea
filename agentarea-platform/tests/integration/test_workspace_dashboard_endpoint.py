"""Integration tests for GET /v1/workspace/dashboard.

Calls get_dashboard() directly against an in-memory SQLite seeded with Agent,
TaskORM, and GovernancePolicyORM rows. The PostgreSQL-only operators
(JSON ->> and the Date-cast CTEs) are sidestepped: sum_spend_today,
sum_spend_mtd, and list_budget_exhausted are patched, and a small session
proxy intercepts the daily_spend / daily_tasks CTEs. All other queries
(HITL, failed-24h, agent name lookup, per-agent counts, recent task names)
run against real SQLite rows.

Cost assertions on the per-agent rows are relaxed to "non-negative float" —
SQLite returns NULL for the ->> expression and COALESCE gives 0.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1.dashboard import get_dashboard
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_governance.domain.policies import monthly_cap_policy
from agentarea_governance.infrastructure.orm import GovernancePolicyORM
from agentarea_tasks.infrastructure.orm import TaskORM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

WORKSPACE_ID = "test-workspace-dashboard-001"
USER_ID = "test-user-dashboard-001"
MONTHLY_CAP_USD = 500.0


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _today_start() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day)


def _month_start() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, 1)


@pytest.fixture(scope="module")
def user_context() -> UserContext:
    return UserContext(user_id=USER_ID, workspace_id=WORKSPACE_ID, roles=["user"])


@pytest.fixture(scope="module")
async def engine():
    """In-memory SQLite engine with only the tables needed by the dashboard.

    BaseModel.metadata contains every imported ORM (incl. TaskEventORM with
    JSONB and AgentWallet with FK chains). Restricting create_all to the three
    tables we actually seed avoids unrelated FK resolution.
    """
    _engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    target_tables = [
        Agent.__table__,
        TaskORM.__table__,
        GovernancePolicyORM.__table__,
    ]

    async with _engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=target_tables
            )
        )
    yield _engine
    await _engine.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(scope="module")
async def seeded(session_factory):
    """Seed Agent + 5 Tasks + workspace cap governance policy.

    t1 completed today      cost=10  → spend.today, mtd, tasks_done_today
    t2 completed yesterday  cost=5   → spend.mtd only
    t3 failed now-1h        cost=0   → blockers.failed_24h, tasks_failed_today
    t4 failed now-30h       cost=0   → outside 24h window
    t5 input_required today          → blockers.hitl
    """
    agent_id = uuid.uuid4()
    other_workspace_agent_id = uuid.uuid4()

    now = _now_utc()
    today = _today_start().replace(tzinfo=None)

    t1_id = uuid.uuid4()
    t2_id = uuid.uuid4()
    t3_id = uuid.uuid4()
    t4_id = uuid.uuid4()
    t5_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                name="Dashboard Test Agent",
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                status="active",
                description="agent for dashboard tests",
                model_id="test-model",
                planning=False,
            )
        )
        session.add(
            Agent(
                id=other_workspace_agent_id,
                name="Other Workspace Agent",
                workspace_id="other-workspace-999",
                created_by="other-user",
                status="active",
                model_id="test-model",
                planning=False,
            )
        )

        session.add(
            TaskORM(
                id=t1_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Completed task today",
                status="completed",
                started_at=today + timedelta(hours=1),
                completed_at=today + timedelta(hours=2),
                result={"total_cost": 10.0, "output": "done"},
            )
        )

        yesterday = today - timedelta(days=1)
        session.add(
            TaskORM(
                id=t2_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Completed task yesterday",
                status="completed",
                started_at=yesterday,
                completed_at=yesterday + timedelta(hours=1),
                result={"total_cost": 5.0, "output": "done yesterday"},
            )
        )

        session.add(
            TaskORM(
                id=t3_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Failed task within 24h",
                status="failed",
                started_at=now - timedelta(hours=2),
                completed_at=now - timedelta(hours=1),
                error="Something went wrong",
                result=None,
            )
        )

        session.add(
            TaskORM(
                id=t4_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Old failed task",
                status="failed",
                started_at=now - timedelta(hours=31),
                completed_at=now - timedelta(hours=30),
                error="Old error",
                result=None,
            )
        )

        session.add(
            TaskORM(
                id=t5_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Waiting for human input",
                status="input_required",
                started_at=today,
                completed_at=None,
                result=None,
            )
        )

        session.add(
            GovernancePolicyORM(
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                scope_type="workspace",
                scope_id=WORKSPACE_ID,
                document=monthly_cap_policy(MONTHLY_CAP_USD).to_json_dict(),
            )
        )
        await session.commit()

    return {
        "agent_id": agent_id,
        "other_workspace_agent_id": other_workspace_agent_id,
        "t1_id": t1_id,
        "t2_id": t2_id,
        "t3_id": t3_id,
        "t4_id": t4_id,
        "t5_id": t5_id,
    }


class _SafeSession:
    """Session proxy that returns empty results for the daily CTEs.

    The dashboard's daily_spend and daily_tasks queries use cast(activity_at,
    Date) which SQLite's Date result-processor cannot handle when the column
    is NULL — it raises TypeError on date.fromisoformat(None). Both CTEs alias
    the cast column "day"; we detect that combined with their cost/count
    aliases and short-circuit to empty results so the rest of the dashboard
    runs normally against SQLite.
    """

    def __init__(self, real_session: AsyncSession):
        self._s = real_session

    def __getattr__(self, name: str):
        return getattr(self._s, name)

    async def execute(self, statement, *args, **kwargs):
        try:
            from sqlalchemy.dialects import sqlite as _sqlite_dialect

            sql_text = str(
                statement.compile(
                    dialect=_sqlite_dialect.dialect(),
                    compile_kwargs={"literal_binds": False},
                )
            )
        except Exception:
            sql_text = ""

        if "day" in sql_text and ("usd" in sql_text or "completed" in sql_text):
            mock_result = MagicMock()
            mock_result.all.return_value = []
            return mock_result

        return await self._s.execute(statement, *args, **kwargs)


async def _call_dashboard(
    session_factory,
    user_context: UserContext,
    *,
    today_usd: float = 10.0,
    mtd_usd: float = 15.0,
    exhausted_wallets: list | None = None,
):
    if exhausted_wallets is None:
        exhausted_wallets = []

    async with session_factory() as session:
        safe_session = _SafeSession(session)
        with (
            patch(
                "agentarea_tasks.infrastructure.repository.TaskRepository.sum_spend_today",
                new_callable=AsyncMock,
                return_value=today_usd,
            ),
            patch(
                "agentarea_tasks.infrastructure.repository.TaskRepository.sum_spend_mtd",
                new_callable=AsyncMock,
                return_value=mtd_usd,
            ),
            patch(
                "agentarea_wallet.infrastructure.repository.WalletRepository.list_budget_exhausted",
                new_callable=AsyncMock,
                return_value=exhausted_wallets,
            ),
        ):
            return await get_dashboard(user_context=user_context, db_session=safe_session)


class TestDashboardResponseShape:
    async def test_daily_spend_has_30_entries(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        assert len(result.daily_spend) == 30

    async def test_daily_tasks_has_14_entries(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        assert len(result.daily_tasks) == 14


class TestSpendCard:
    async def test_today_usd_comes_from_spend_today(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context, today_usd=10.0, mtd_usd=15.0)
        assert result.spend.today_usd == pytest.approx(10.0, abs=0.01)

    async def test_mtd_usd_comes_from_sum_spend_mtd(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context, today_usd=10.0, mtd_usd=15.0)
        assert result.spend.mtd_usd == pytest.approx(15.0, abs=0.01)

    async def test_cap_usd_populated_when_governance_policy_exists(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context, mtd_usd=15.0)
        assert result.spend.cap_usd == pytest.approx(MONTHLY_CAP_USD, abs=0.01)

    async def test_empty_governance_policy_yields_no_cap(self, session_factory, seeded):
        policy_workspace_id = "workspace-policy-clear-dashboard-001"
        policy_context = UserContext(
            user_id="policy-user-dashboard-002",
            workspace_id=policy_workspace_id,
            roles=["user"],
        )

        async with session_factory() as session:
            session.add(
                GovernancePolicyORM(
                    workspace_id=policy_workspace_id,
                    created_by=policy_context.user_id,
                    scope_type="workspace",
                    scope_id=policy_workspace_id,
                    document={},
                )
            )
            await session.commit()

        result = await _call_dashboard(session_factory, policy_context, mtd_usd=50.0)
        assert result.spend.cap_usd is None
        assert result.spend.pct_of_cap is None
        assert result.spend.projected_eom_usd is None

    async def test_pct_of_cap_is_computed_correctly(self, session_factory, user_context, seeded):
        mtd = 100.0
        expected_pct = round(mtd / MONTHLY_CAP_USD * 100, 2)
        result = await _call_dashboard(session_factory, user_context, mtd_usd=mtd)
        assert result.spend.pct_of_cap == pytest.approx(expected_pct, abs=0.01)

    async def test_projected_eom_is_positive_when_cap_is_set(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context, mtd_usd=50.0)
        assert result.spend.projected_eom_usd is not None
        assert result.spend.projected_eom_usd >= 0.0

    async def test_cap_fields_are_none_when_no_policy_row(self, session_factory, seeded):
        other_context = UserContext(
            user_id="no-policy-user",
            workspace_id="workspace-without-policy",
            roles=["user"],
        )
        result = await _call_dashboard(session_factory, other_context, mtd_usd=50.0)
        assert result.spend.cap_usd is None
        assert result.spend.pct_of_cap is None
        assert result.spend.projected_eom_usd is None


class TestBlockersHitl:
    async def test_hitl_contains_the_input_required_task(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        hitl_ids = {b.task_id for b in result.blockers.hitl}
        assert seeded["t5_id"] in hitl_ids

    async def test_hitl_does_not_contain_completed_tasks(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        hitl_ids = {b.task_id for b in result.blockers.hitl}
        assert seeded["t1_id"] not in hitl_ids
        assert seeded["t2_id"] not in hitl_ids

    async def test_hitl_does_not_contain_failed_tasks(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        hitl_ids = {b.task_id for b in result.blockers.hitl}
        assert seeded["t3_id"] not in hitl_ids

    async def test_hitl_blocker_has_correct_agent_name(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        hitl_task = next(b for b in result.blockers.hitl if b.task_id == seeded["t5_id"])
        assert hitl_task.agent_name == "Dashboard Test Agent"

    async def test_hitl_blocker_has_correct_description(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        hitl_task = next(b for b in result.blockers.hitl if b.task_id == seeded["t5_id"])
        assert hitl_task.description == "Waiting for human input"


class TestBlockersFailed24h:
    async def test_failed_24h_contains_recent_failed_task(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        failed_ids = {b.task_id for b in result.blockers.failed_24h}
        assert seeded["t3_id"] in failed_ids

    async def test_failed_24h_excludes_task_older_than_24h(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        failed_ids = {b.task_id for b in result.blockers.failed_24h}
        assert seeded["t4_id"] not in failed_ids

    async def test_failed_24h_does_not_include_completed_tasks(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        failed_ids = {b.task_id for b in result.blockers.failed_24h}
        assert seeded["t1_id"] not in failed_ids

    async def test_failed_24h_does_not_include_hitl_tasks(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        failed_ids = {b.task_id for b in result.blockers.failed_24h}
        assert seeded["t5_id"] not in failed_ids

    async def test_failed_24h_blocker_has_agent_name(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        failed_task = next(b for b in result.blockers.failed_24h if b.task_id == seeded["t3_id"])
        assert failed_task.agent_name == "Dashboard Test Agent"

    async def test_failed_24h_blocker_has_error_message(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        failed_task = next(b for b in result.blockers.failed_24h if b.task_id == seeded["t3_id"])
        assert failed_task.error == "Something went wrong"


class TestWorkspaceIsolation:
    async def test_agents_list_excludes_other_workspace_agents(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        agent_ids = {a.agent_id for a in result.agents}
        assert seeded["other_workspace_agent_id"] not in agent_ids

    async def test_hitl_is_empty_for_workspace_with_no_tasks(self, session_factory, seeded):
        empty_context = UserContext(
            user_id="user-empty",
            workspace_id="workspace-empty-000",
            roles=["user"],
        )
        result = await _call_dashboard(session_factory, empty_context, today_usd=0.0, mtd_usd=0.0)
        assert result.blockers.hitl == []
        assert result.blockers.failed_24h == []
        assert result.agents == []


class TestAgentRows:
    async def test_agents_list_contains_seeded_agent(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        agent_ids = {a.agent_id for a in result.agents}
        assert seeded["agent_id"] in agent_ids

    async def test_tasks_done_today_counts_completed_tasks_with_started_at_today(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        agent_row = next(a for a in result.agents if a.agent_id == seeded["agent_id"])
        # t1 completed and started today; t2 completed but started yesterday
        assert agent_row.tasks_done_today == 1

    async def test_tasks_failed_today_counts_failed_tasks_started_today(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        agent_row = next(a for a in result.agents if a.agent_id == seeded["agent_id"])
        # t3 within today's window; t4 started >24h ago
        assert agent_row.tasks_failed_today >= 1

    async def test_tasks_failed_today_excludes_old_failed_tasks(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        agent_row = next(a for a in result.agents if a.agent_id == seeded["agent_id"])
        # t4 started 31h ago — must not count
        assert agent_row.tasks_failed_today < 2

    async def test_agent_row_has_name_populated(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        agent_row = next(a for a in result.agents if a.agent_id == seeded["agent_id"])
        assert agent_row.name == "Dashboard Test Agent"

    async def test_agent_row_cost_fields_are_non_negative_floats(
        self, session_factory, user_context, seeded
    ):
        # SQLite returns NULL for the ->> cost expression; COALESCE → 0
        result = await _call_dashboard(session_factory, user_context)
        agent_row = next(a for a in result.agents if a.agent_id == seeded["agent_id"])
        assert isinstance(agent_row.cost_today_usd, float)
        assert isinstance(agent_row.cost_mtd_usd, float)
        assert agent_row.cost_today_usd >= 0.0
        assert agent_row.cost_mtd_usd >= 0.0

    async def test_recent_task_names_are_seeded_descriptions(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        agent_row = next(a for a in result.agents if a.agent_id == seeded["agent_id"])

        assert isinstance(agent_row.recent_task_names, list)
        assert len(agent_row.recent_task_names) <= 3
        assert all(isinstance(n, str) for n in agent_row.recent_task_names)

        seeded_descriptions = {
            "Completed task today",
            "Completed task yesterday",
            "Failed task within 24h",
            "Old failed task",
            "Waiting for human input",
        }
        assert len(seeded_descriptions & set(agent_row.recent_task_names)) > 0

    async def test_agents_sorted_most_active_first(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        activities = [a.last_activity_at for a in result.agents if a.last_activity_at is not None]
        assert activities == sorted(activities, reverse=True)


class TestWalletExhaustedBlockers:
    async def test_wallet_exhausted_contains_agent_info_from_mocked_wallet(
        self, session_factory, user_context, seeded
    ):
        fake_wallet = MagicMock()
        fake_wallet.agent_id = seeded["agent_id"]
        fake_wallet.service_budget_usd = 100.0
        fake_wallet.service_budget_period = "monthly"

        result = await _call_dashboard(
            session_factory, user_context, exhausted_wallets=[fake_wallet]
        )
        assert len(result.blockers.wallet_exhausted) == 1
        exhausted = result.blockers.wallet_exhausted[0]
        assert exhausted.agent_id == seeded["agent_id"]
        assert exhausted.agent_name == "Dashboard Test Agent"
        assert exhausted.budget_usd == pytest.approx(100.0)
        assert exhausted.period == "monthly"
