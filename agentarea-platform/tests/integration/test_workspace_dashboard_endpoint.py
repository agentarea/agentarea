"""Integration tests for GET /v1/workspaces/acme/dashboard.

Calls get_dashboard() directly against an in-memory SQLite seeded with Agent,
TaskORM, TriggerORM, and PolicyRuleORM rows. The PostgreSQL-only operators
(JSON ->> and the Date-cast CTE) are sidestepped: sum_spend_today,
sum_spend_mtd, and list_budget_exhausted are patched, and a small session
proxy intercepts the daily_spend CTE. All other queries (HITL, failed-24h,
agent name lookup, active and recent tasks, cron triggers) run against real
SQLite rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1.dashboard import get_dashboard, project_month_end
from agentarea_common.auth.context import UserContext
from agentarea_common.extensions.workspace_usage import WorkspaceUsage
from agentarea_common.base.models import BaseModel
from agentarea_common.money import to_money
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_mcp.domain.auth_models import MCPAuthConfig
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_tasks.infrastructure.orm import CostEntryORM, TaskORM
from agentarea_triggers.infrastructure.orm import TriggerORM
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
    return UserContext(user_id=USER_ID, workspace_id=WORKSPACE_ID)


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
        CostEntryORM.__table__,
        PolicyRuleORM.__table__,
        TriggerORM.__table__,
        MCPAuthConfig.__table__,
        MCPServerInstance.__table__,
    ]

    async with _engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(sync_conn, tables=target_tables)
        )
    yield _engine
    await _engine.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(scope="module")
async def seeded(session_factory):
    """Seed tasks across dashboard activity and blocker statuses.

    t1 completed today      cost=10  → spend.today, mtd, tasks_done_today
    t2 completed yesterday  cost=5   → spend.mtd only
    t3 failed now-1h        cost=0   → blockers.failed_24h, tasks_failed_today
    t4 failed now-30h       cost=0   → outside 24h window
    t5 waiting_for_input today       → blockers.hitl
    t6 waiting_for_approval today    → blockers.hitl
    t7 waiting_for_input elsewhere   → excluded by workspace
    t8 running now, t9 pending       → active_tasks
    t10 preparing, t11 working       → active_tasks
    t12 waiting_for_continuation     → blockers.awaiting_continuation
    t13 blocked now-3m               → blockers.blocked_24h and recent_tasks
    t14 blocked now-30h              → recent_tasks only, outside 24h window
    t15 completed, unreadable cost   → recent_tasks with cost_usd None
    t16 scheduled in 2 days          → schedule.runs, by task
    t17 scheduled past the horizon, t19 scheduled in another workspace → none
    t18 scheduled then cancelled     → recent_tasks only, never a run

    Cron triggers: daily 09:00 UTC → schedule.runs; every 5 minutes →
    schedule.frequent; inactive, unparseable, and other-workspace ones → none.

    Health: a connection that failed verification and one whose last call
    failed are broken, a verified one and another workspace's are not. A
    trigger failing in a row, one stopped at its failure threshold and one
    left without an owner are broken; one paused by hand is not.
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
    t6_id = uuid.uuid4()
    t8_id = uuid.uuid4()
    t9_id = uuid.uuid4()
    t10_id = uuid.uuid4()
    t11_id = uuid.uuid4()
    t12_id = uuid.uuid4()
    t13_id = uuid.uuid4()
    t14_id = uuid.uuid4()
    t15_id = uuid.uuid4()
    daily_trigger_id = uuid.uuid4()
    frequent_trigger_id = uuid.uuid4()
    t16_id = uuid.uuid4()
    t16_fires_at = (now + timedelta(days=2)).replace(microsecond=0)
    t18_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                name="Dashboard Test Agent",
                slug="dashboard-test-agent",
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
                slug="other-workspace-agent",
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
                # Never in the future: today + 2h is ahead of now until 02:00 UTC,
                # which put t1 at the head of recent_tasks.
                started_at=today,
                completed_at=max(
                    today, min(today + timedelta(hours=2), now - timedelta(minutes=5))
                ),
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
                # Midnight, not "now - 2h": between 00:00 and 02:00 UTC that
                # landed on yesterday and the "today" assertion failed.
                started_at=today,
                completed_at=now,
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
                status="waiting_for_input",
                started_at=today,
                completed_at=None,
                result=None,
            )
        )
        session.add(
            TaskORM(
                id=t6_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Waiting for tool approval",
                status="waiting_for_approval",
                started_at=today,
            )
        )
        session.add(
            TaskORM(
                id=t12_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Waiting for continuation",
                status="waiting_for_continuation",
                started_at=now,
            )
        )
        session.add(
            TaskORM(
                id=uuid.uuid4(),
                agent_id=other_workspace_agent_id,
                workspace_id="other-workspace-999",
                created_by="other-user",
                description="Other workspace input",
                status="waiting_for_input",
                started_at=today,
            )
        )

        session.add(
            TaskORM(
                id=t8_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Running right now",
                status="running",
                started_at=now - timedelta(minutes=3),
            )
        )
        session.add(
            TaskORM(
                id=t9_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Queued next",
                status="pending",
            )
        )
        session.add(
            TaskORM(
                id=t10_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Preparing task",
                status="preparing",
                started_at=now,
            )
        )
        session.add(
            TaskORM(
                id=t11_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Working task",
                status="working",
                started_at=now,
            )
        )
        session.add(
            TaskORM(
                id=t13_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Blocked by provider quota",
                status="blocked",
                started_at=now - timedelta(minutes=5),
                completed_at=now - timedelta(minutes=3),
                error="Provider quota exceeded",
            )
        )
        session.add(
            TaskORM(
                id=t14_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Blocked long ago",
                status="blocked",
                started_at=now - timedelta(hours=31),
                completed_at=now - timedelta(hours=30),
                error="Budget exhausted",
            )
        )
        session.add(
            TaskORM(
                id=t15_id,
                agent_id=agent_id,
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                description="Completed with a garbled cost",
                status="completed",
                started_at=now - timedelta(hours=3),
                completed_at=now - timedelta(hours=2),
                result={"total_cost": "not-a-number", "output": "done"},
            )
        )

        def scheduled_task(
            task_id: uuid.UUID,
            description: str,
            scheduled_at: datetime,
            *,
            status: str = "scheduled",
            task_agent_id: uuid.UUID = agent_id,
            workspace_id: str = WORKSPACE_ID,
        ) -> TaskORM:
            return TaskORM(
                id=task_id,
                agent_id=task_agent_id,
                workspace_id=workspace_id,
                created_by=USER_ID,
                description=description,
                status=status,
                scheduled_at=scheduled_at,
                updated_at=now - timedelta(hours=40),
            )

        session.add(scheduled_task(t16_id, "Monthly accounting report", t16_fires_at))
        session.add(scheduled_task(uuid.uuid4(), "Next quarter review", now + timedelta(days=60)))
        session.add(
            scheduled_task(t18_id, "Called off", now + timedelta(days=1), status="cancelled")
        )
        session.add(
            scheduled_task(
                uuid.uuid4(),
                "Scheduled elsewhere",
                now + timedelta(days=1),
                task_agent_id=other_workspace_agent_id,
                workspace_id="other-workspace-999",
            )
        )

        def cron_trigger(
            name: str,
            cron: str,
            *,
            trigger_id: uuid.UUID | None = None,
            active: bool = True,
            workspace_id: str = WORKSPACE_ID,
        ) -> TriggerORM:
            return TriggerORM(
                id=trigger_id or uuid.uuid4(),
                name=name,
                agent_id=agent_id,
                trigger_type="cron",
                cron_expression=cron,
                timezone="UTC",
                is_active=active,
                workspace_id=workspace_id,
                created_by=USER_ID,
            )

        session.add(cron_trigger("Morning report", "0 9 * * *", trigger_id=daily_trigger_id))
        session.add(cron_trigger("Inbox sweep", "*/5 * * * *", trigger_id=frequent_trigger_id))
        session.add(cron_trigger("Paused digest", "0 10 * * *", active=False))
        session.add(cron_trigger("Broken schedule", "not a cron"))
        session.add(cron_trigger("Elsewhere", "0 11 * * *", workspace_id="other-workspace-999"))

        def stream_trigger(name: str, *, active: bool = True, failures: int = 0, **extra):
            return TriggerORM(
                id=uuid.uuid4(),
                name=name,
                agent_id=agent_id,
                trigger_type="stream",
                is_active=active,
                failure_threshold=5,
                consecutive_failures=failures,
                last_execution_at=now - timedelta(minutes=20),
                workspace_id=extra.pop("workspace_id", WORKSPACE_ID),
                created_by=USER_ID,
                **extra,
            )

        failing_trigger = stream_trigger("Lead intake", failures=2)
        stopped_trigger = stream_trigger("Invoice sync", active=False, failures=5)
        orphan_trigger = stream_trigger("Weekly digest", needs_new_owner_at=now)
        session.add_all(
            [
                failing_trigger,
                stopped_trigger,
                orphan_trigger,
                stream_trigger("Paused by hand", active=False),
                stream_trigger("Healthy", failures=0),
                stream_trigger("Elsewhere failing", failures=3, workspace_id="other-workspace-999"),
            ]
        )

        def connection(name: str, *, workspace_id: str = WORKSPACE_ID, **state):
            instance = MCPServerInstance(
                name=name,
                server_spec_id="io.example/server",
                transport="url",
                verification=state.get("verification"),
                workspace_id=workspace_id,
                created_by=USER_ID,
            )
            instance.last_dispatch = state.get("last_dispatch")
            return instance

        unverified = connection(
            "Google Analytics",
            verification={
                "schema_version": 1,
                "status": "failed",
                "at": now.isoformat(),
                "error": {"code": "auth", "message": "refresh token missing", "detail": None},
            },
        )
        failing_calls = connection(
            "Notion",
            verification={"schema_version": 1, "status": "succeeded", "at": None, "error": None},
            last_dispatch={
                "schema_version": 1,
                "status": "failed",
                "at": now.isoformat(),
                "error": "401 Unauthorized",
            },
        )
        session.add_all(
            [
                unverified,
                failing_calls,
                connection(
                    "Healthy MCP",
                    verification={
                        "schema_version": 1,
                        "status": "succeeded",
                        "at": None,
                        "error": None,
                    },
                ),
                connection(
                    "Elsewhere MCP",
                    workspace_id="other-workspace-999",
                    verification={
                        "schema_version": 1,
                        "status": "failed",
                        "at": None,
                        "error": None,
                    },
                ),
            ]
        )

        session.add(
            PolicyRuleORM(
                workspace_id=WORKSPACE_ID,
                created_by=USER_ID,
                subject_type="workspace",
                subject_id=WORKSPACE_ID,
                target="spend",
                effect="cap",
                params={"amount_usd": str(to_money(MONTHLY_CAP_USD)), "period": "month"},
                enabled=True,
            )
        )
        await session.commit()

    return {
        "failing_trigger_id": failing_trigger.id,
        "stopped_trigger_id": stopped_trigger.id,
        "orphan_trigger_id": orphan_trigger.id,
        "unverified_connection_id": unverified.id,
        "failing_calls_connection_id": failing_calls.id,
        "agent_id": agent_id,
        "other_workspace_agent_id": other_workspace_agent_id,
        "t1_id": t1_id,
        "t2_id": t2_id,
        "t3_id": t3_id,
        "t4_id": t4_id,
        "t5_id": t5_id,
        "t6_id": t6_id,
        "t10_id": t10_id,
        "t11_id": t11_id,
        "t12_id": t12_id,
        "t13_id": t13_id,
        "t14_id": t14_id,
        "t15_id": t15_id,
        "t8_id": t8_id,
        "t9_id": t9_id,
        "daily_trigger_id": daily_trigger_id,
        "frequent_trigger_id": frequent_trigger_id,
        "t16_id": t16_id,
        "t16_fires_at": t16_fires_at,
        "t18_id": t18_id,
    }


class _SafeSession:
    """Session proxy that returns empty results for the daily spend CTE.

    The dashboard's daily_spend query uses cast(activity_at, Date) which
    SQLite's Date result-processor cannot handle when the column is NULL — it
    raises TypeError on date.fromisoformat(None). The CTE aliases the cast
    column "day" and its sum "usd"; we detect both and short-circuit to an
    empty result so the rest of the dashboard runs normally against SQLite.
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

        if "AS day" in sql_text and "AS usd" in sql_text:
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
                "agentarea_tasks.infrastructure.repository.TaskRepository.sum_spend_by_day",
                new_callable=AsyncMock,
                return_value={},
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


class TestSpendCard:
    async def test_today_usd_comes_from_spend_today(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context, today_usd=10.0, mtd_usd=15.0)
        assert result.spend.today_usd == Decimal("10")

    async def test_mtd_usd_comes_from_sum_spend_mtd(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context, today_usd=10.0, mtd_usd=15.0)
        assert result.spend.mtd_usd == Decimal("15")

    async def test_cap_usd_populated_when_governance_policy_exists(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context, mtd_usd=15.0)
        assert result.spend.cap_usd == Decimal("500")

    async def test_empty_governance_policy_yields_no_cap(self, session_factory, seeded):
        policy_workspace_id = "workspace-policy-clear-dashboard-001"
        policy_context = UserContext(
            user_id="policy-user-dashboard-002",
            workspace_id=policy_workspace_id,
        )

        async with session_factory() as session:
            session.add(
                PolicyRuleORM(
                    workspace_id=policy_workspace_id,
                    created_by=policy_context.user_id,
                    subject_type="workspace",
                    subject_id=policy_workspace_id,
                    target="spend",
                    effect="cap",
                    params={},
                    enabled=True,
                )
            )
            await session.commit()

        result = await _call_dashboard(session_factory, policy_context, mtd_usd=50.0)
        assert result.spend.cap_usd is None
        assert result.spend.pct_of_cap is None

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
        assert result.spend.projected_eom_usd >= 0

    async def test_cap_fields_are_none_when_no_policy_row(self, session_factory, seeded):
        other_context = UserContext(
            user_id="no-policy-user",
            workspace_id="workspace-without-policy",
        )
        result = await _call_dashboard(session_factory, other_context, mtd_usd=50.0)
        assert result.spend.cap_usd is None
        assert result.spend.pct_of_cap is None

    async def test_month_end_is_projected_without_a_cap(self, session_factory, seeded):
        other_context = UserContext(user_id="no-policy-user", workspace_id="workspace-no-cap")
        result = await _call_dashboard(session_factory, other_context, mtd_usd=50.0)
        assert result.spend.projected_eom_usd is not None
        assert result.spend.projection_method == "trailing-7d"


class TestBlockersHitl:
    async def test_hitl_selects_input_and_approval_waiters_in_workspace(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        hitl_ids = {b.task_id for b in result.blockers.hitl}
        assert hitl_ids == {seeded["t5_id"], seeded["t6_id"]}

    async def test_a_waiter_says_whether_it_wants_an_answer_or_an_approval(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        statuses = {b.task_id: b.status for b in result.blockers.hitl}
        assert statuses == {
            seeded["t5_id"]: "waiting_for_input",
            seeded["t6_id"]: "waiting_for_approval",
        }

    async def test_runs_waiting_to_continue_are_blockers(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        assert [b.task_id for b in result.blockers.awaiting_continuation] == [seeded["t12_id"]]

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
    async def test_schedule_excludes_other_workspace_triggers(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        titles = {r.title for r in result.schedule.runs}
        assert "Elsewhere" not in titles

    async def test_hitl_is_empty_for_workspace_with_no_tasks(self, session_factory, seeded):
        empty_context = UserContext(
            user_id="user-empty",
            workspace_id="workspace-empty-000",
        )
        result = await _call_dashboard(session_factory, empty_context, today_usd=0.0, mtd_usd=0.0)
        assert result.blockers.hitl == []
        assert result.blockers.failed_24h == []
        assert result.active_tasks == []
        assert result.recent_tasks == []
        assert result.schedule.runs == []
        assert result.schedule.frequent == []


class TestTasks:
    async def test_active_tasks_include_preparing_and_working_statuses(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        assert {t.task_id for t in result.active_tasks} == {
            seeded["t8_id"],
            seeded["t9_id"],
            seeded["t10_id"],
            seeded["t11_id"],
        }

    async def test_active_task_carries_agent_name_and_title(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        running = next(t for t in result.active_tasks if t.task_id == seeded["t8_id"])
        assert running.agent_name == "Dashboard Test Agent"
        assert running.title == "Running right now"
        assert running.status == "running"

    async def test_recent_tasks_leave_out_what_blockers_already_show(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        ids = [t.task_id for t in result.recent_tasks]
        # t3 (failed) and t13 (blocked) ended in the last 24h: they are blockers.
        # t4 and t14 ended earlier, so they are only history.
        assert set(ids) == {
            seeded["t1_id"],
            seeded["t2_id"],
            seeded["t4_id"],
            seeded["t14_id"],
            seeded["t15_id"],
            seeded["t18_id"],
        }

    async def test_blocked_in_the_last_24h_are_blockers(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        blocked = result.blockers.blocked_24h
        assert [b.task_id for b in blocked] == [seeded["t13_id"]]
        assert blocked[0].description == "Blocked by provider quota"
        assert blocked[0].error == "Provider quota exceeded"

    async def test_recent_task_reports_its_cost(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        done = next(t for t in result.recent_tasks if t.task_id == seeded["t1_id"])
        assert done.cost_usd == Decimal("10")
        failed = next(t for t in result.recent_tasks if t.task_id == seeded["t4_id"])
        assert failed.cost_usd is None

    async def test_an_unreadable_cost_is_unknown_not_a_failed_dashboard(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        garbled = next(t for t in result.recent_tasks if t.task_id == seeded["t15_id"])
        assert garbled.cost_usd is None

    async def test_money_reaches_the_client_as_decimal_strings(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context, mtd_usd=15.0)
        body = result.model_dump(mode="json")
        done = next(t for t in body["recent_tasks"] if t["task_id"] == str(seeded["t1_id"]))
        amounts = [body["spend"]["mtd_usd"], body["spend"]["cap_usd"], done["cost_usd"]]
        assert all(isinstance(amount, str) for amount in amounts)
        assert [Decimal(amount) for amount in amounts] == [15, 500, 10]


class TestSchedule:
    async def test_daily_trigger_lists_one_run_per_day_over_the_horizon(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        runs = [r for r in result.schedule.runs if r.trigger_id == seeded["daily_trigger_id"]]
        assert len(runs) in (result.schedule.horizon_days, result.schedule.horizon_days + 1)
        assert all(r.fires_at.hour == 9 and r.fires_at.minute == 0 for r in runs)
        assert runs[0].title == "Morning report"
        assert runs[0].agent_name == "Dashboard Test Agent"

    async def test_frequent_trigger_is_summarised_not_listed(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        assert all(r.trigger_id != seeded["frequent_trigger_id"] for r in result.schedule.runs)
        frequent = next(
            f for f in result.schedule.frequent if f.trigger_id == seeded["frequent_trigger_id"]
        )
        assert frequent.runs_per_day == 288
        assert frequent.title == "Inbox sweep"

    async def test_inactive_and_unparseable_triggers_are_left_out(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        titles = {r.title for r in result.schedule.runs if r.trigger_id is not None} | {
            f.title for f in result.schedule.frequent
        }
        assert titles == {"Morning report", "Inbox sweep"}

    async def test_runs_are_in_time_order(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        times = [r.fires_at for r in result.schedule.runs]
        assert times == sorted(times)

    async def test_a_task_scheduled_inside_the_horizon_is_a_run(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        run = next(r for r in result.schedule.runs if r.task_id == seeded["t16_id"])
        assert run.trigger_id is None
        assert run.title == "Monthly accounting report"
        assert run.agent_name == "Dashboard Test Agent"
        assert run.fires_at.replace(tzinfo=None) == seeded["t16_fires_at"]

    async def test_only_pending_scheduled_tasks_in_the_horizon_are_runs(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        task_runs = [r.task_id for r in result.schedule.runs if r.task_id is not None]
        assert task_runs == [seeded["t16_id"]]


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
        assert exhausted.budget_usd == Decimal("100")
        assert exhausted.period == "monthly"


class TestProjection:
    NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)

    def test_the_rest_of_the_month_runs_at_the_last_seven_full_days_pace(self):
        days = {
            (self.NOW.date() - timedelta(days=i)).isoformat(): Decimal("1") for i in range(1, 8)
        }
        days[self.NOW.date().isoformat()] = Decimal("100")

        # 1 a day for the half of today left and the 31st; today's own spend is
        # already in month-to-date and does not set the pace.
        assert project_month_end(Decimal("40"), days, self.NOW) == Decimal("41.50")

    def test_nothing_spent_lately_projects_what_is_spent(self):
        assert project_month_end(Decimal("40"), {}, self.NOW) == Decimal("40.00")


class TestHealth:
    async def test_a_connection_that_failed_verification_or_its_last_call_is_broken(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        broken = {c.instance_id: c for c in result.health.connections}
        assert set(broken) == {
            seeded["unverified_connection_id"],
            seeded["failing_calls_connection_id"],
        }
        unverified = broken[seeded["unverified_connection_id"]]
        assert unverified.reason == "verification_failed"
        assert unverified.error == "refresh token missing"
        failing = broken[seeded["failing_calls_connection_id"]]
        assert failing.reason == "last_call_failed"
        assert failing.error == "401 Unauthorized"

    async def test_failing_stopped_and_ownerless_triggers_are_broken(
        self, session_factory, user_context, seeded
    ):
        result = await _call_dashboard(session_factory, user_context)
        reasons = {t.trigger_id: t.reason for t in result.health.triggers}
        assert reasons == {
            seeded["failing_trigger_id"]: "failing",
            seeded["stopped_trigger_id"]: "stopped_after_failures",
            seeded["orphan_trigger_id"]: "needs_owner",
        }
        failing = next(t for t in result.health.triggers if t.reason == "failing")
        assert (failing.consecutive_failures, failing.failure_threshold) == (2, 5)
        assert failing.agent_name is not None


class TestRuntimeUsage:
    async def test_no_metering_reads_as_no_usage(self, session_factory, user_context, seeded):
        result = await _call_dashboard(session_factory, user_context)
        assert result.usage is None

    async def test_a_tenth_of_a_mebibyte_stored_is_not_rounded_away(
        self, session_factory, user_context, seeded
    ):
        source = MagicMock()
        source.usage_since = AsyncMock(
            return_value=WorkspaceUsage(
                cpu_core_hours=Decimal("21.84321"),
                memory_gib_hours=Decimal("27.1"),
                storage_gib=Decimal("0.1") / 1024,
            )
        )
        with patch(
            "agentarea_api.api.v1.dashboard.get_workspace_usage_source", return_value=source
        ):
            result = await _call_dashboard(session_factory, user_context)
        assert result.usage is not None
        assert result.usage.cpu_core_hours == Decimal("21.84")
        assert result.usage.storage_gib == Decimal("0.000098")
