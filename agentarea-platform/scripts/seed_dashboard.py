"""Seed dashboard demo data: tasks with cost, HITL blockers, failed tasks,
exhausted wallets, and a workspace monthly cap.

Lets the operator dashboard at ``/dashboard`` render meaningful widgets
without waiting for real workflow runs.

Usage::

    cd agentarea-platform
    uv run python scripts/seed_dashboard.py <workspace_id> \
        [--user <user_id>] [--agents 3] [--tasks 50] [--cap 25] \
        [--with-blockers] [--reset]

Idempotent for the workspace cap policy (governance upsert) and
``agent_wallets`` (updated when matching). Tasks are always *appended* —
pass ``--reset`` to wipe seeded rows first
(matched by ``task_metadata->>'seed'='dashboard'``).

Notes:
- Inserts directly through SQLAlchemy ORM. No event broker / Temporal wiring.
- Costs are stored under ``task.result.total_cost`` so the dashboard
  spend aggregator picks them up.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agentarea_agents.domain.models import Agent
from agentarea_common.infrastructure.database import db
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_wallet.domain.models import AgentWallet, PaymentRecord
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

AGENT_NAME_POOL = [
    "orchestrator",
    "researcher",
    "writer",
    "data-analyst",
    "scheduler",
    "qa",
    "translator",
    "support-bot",
]

TASK_TITLE_POOL = [
    "Summarize daily metrics",
    "Triage incoming tickets",
    "Draft Q3 board update",
    "Reconcile invoices vs Stripe",
    "Pull vendor onboarding docs",
    "Translate FAQ to Spanish",
    "Audit feature flags drift",
    "Generate release notes",
    "Backfill missing avatars",
    "Lint and rotate API keys",
]

ERROR_POOL = [
    "ToolExecutionError: tool 'fetch_invoice' timed out after 30s",
    "LLMRateLimitError: 429 from upstream",
    "ValidationError: missing required field 'customer_id'",
    "MCPConnectionError: server returned 503",
]

HITL_PROMPTS = [
    "Approve refund of $148 to customer C-2842?",
    "Confirm sending email blast to 14k recipients?",
    "Merge conflicting calendar events into one?",
    "Reset password for shared account?",
]


async def get_or_create_agents(
    session, workspace_id: str, user_id: str, count: int
) -> list[Agent]:
    existing = (
        (
            await session.execute(
                select(Agent).where(Agent.workspace_id == workspace_id).limit(count)
            )
        )
        .scalars()
        .all()
    )
    if len(existing) >= count:
        return existing[:count]

    print(f"workspace has {len(existing)} agents, creating {count - len(existing)} more")
    for _ in range(count - len(existing)):
        name_base = random.choice(AGENT_NAME_POOL)
        suffix = uuid4().hex[:6]
        agent = Agent(
            id=uuid4(),
            name=f"{name_base}-{suffix}",
            description=f"Demo {name_base}",
            instruction="You are a demo agent.",
            workspace_id=workspace_id,
            created_by=user_id,
        )
        session.add(agent)
    await session.flush()
    return (
        (
            await session.execute(
                select(Agent).where(Agent.workspace_id == workspace_id).limit(count)
            )
        )
        .scalars()
        .all()
    )


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _random_cost() -> float:
    # ~$0.0008..$0.012 per task — mimics cheap chinese model spend
    return round(random.uniform(0.0008, 0.012), 5)


def _within_today() -> datetime:
    now = _utc_now_naive()
    today_start = datetime(now.year, now.month, now.day)
    return today_start + timedelta(seconds=random.randint(0, max(1, int((now - today_start).total_seconds()))))


def _within_mtd() -> datetime:
    now = _utc_now_naive()
    month_start = datetime(now.year, now.month, 1)
    return month_start + timedelta(
        seconds=random.randint(0, max(1, int((now - month_start).total_seconds())))
    )


async def reset_seeded(session, workspace_id: str) -> None:
    stmt = delete(TaskORM).where(
        TaskORM.workspace_id == workspace_id,
        TaskORM.task_metadata.op("->>")("seed") == "dashboard",
    )
    res = await session.execute(stmt)
    print(f"removed {res.rowcount} previously seeded tasks")


async def seed_tasks(
    session,
    workspace_id: str,
    user_id: str,
    agents: list[Agent],
    n_tasks: int,
    with_blockers: bool,
) -> tuple[int, int, int]:
    """Insert n_tasks demo tasks across statuses. Returns (completed, failed, hitl)."""
    completed = failed = hitl = 0
    now = _utc_now_naive()

    for _ in range(n_tasks):
        agent = random.choice(agents)
        # 70% completed, 12% failed (recent), 8% input_required, 10% running/cancelled
        roll = random.random()
        title = random.choice(TASK_TITLE_POOL)
        common = dict(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            agent_id=agent.id,
            description=title,
            parameters={},
            task_metadata={"seed": "dashboard"},
        )
        if roll < 0.70:
            started = _within_mtd()
            duration = timedelta(seconds=random.randint(5, 600))
            completed_at = min(started + duration, now)
            session.add(
                TaskORM(
                    **common,
                    status="completed",
                    started_at=started,
                    completed_at=completed_at,
                    result={"total_cost": _random_cost(), "summary": "ok"},
                )
            )
            completed += 1
        elif with_blockers and roll < 0.82:
            occurred = now - timedelta(minutes=random.randint(5, 23 * 60))
            session.add(
                TaskORM(
                    **common,
                    status="failed",
                    started_at=occurred - timedelta(seconds=30),
                    completed_at=occurred,
                    error=random.choice(ERROR_POOL),
                    result={"total_cost": round(_random_cost() * 0.3, 5)},
                )
            )
            failed += 1
        elif with_blockers and roll < 0.90:
            started = now - timedelta(minutes=random.randint(2, 240))
            session.add(
                TaskORM(
                    **{**common, "description": random.choice(HITL_PROMPTS)},
                    status="input_required",
                    started_at=started,
                )
            )
            hitl += 1
        else:
            started = _within_today()
            session.add(
                TaskORM(
                    **common,
                    status="running" if random.random() < 0.5 else "cancelled",
                    started_at=started,
                )
            )

    await session.flush()
    return completed, failed, hitl


async def upsert_settings(
    session, workspace_id: str, user_id: str, cap: float | None
) -> None:
    """Upsert the workspace cap as a unified policy rule row."""
    if cap is None:
        print("workspace cap policy = (none)")
        return

    params = {"amount_usd": str(cap), "period": "month"}
    stmt = pg_insert(PolicyRuleORM).values(
        workspace_id=workspace_id,
        created_by=user_id,
        subject_type="workspace",
        subject_id=workspace_id,
        target="spend",
        effect="cap",
        params=params,
        enabled=True,
        priority=0,
    )
    await session.execute(stmt)
    print(f"policies workspace cap = ${cap}")


async def exhaust_one_wallet(
    session, workspace_id: str, user_id: str, agent: Agent
) -> bool:
    """Force one wallet into 'exhausted' state by setting a tiny budget and
    inserting a completed payment that meets/exceeds it."""
    wallet = (
        await session.execute(
            select(AgentWallet)
            .where(AgentWallet.agent_id == agent.id)
            .where(AgentWallet.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()

    if wallet is None:
        wallet = AgentWallet(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            agent_id=agent.id,
            wallet_type="x402",
            x402_config={"chain": "demo"},
            service_budget_usd=1.0,
            service_budget_period="monthly",
            status="active",
        )
        session.add(wallet)
        await session.flush()
    else:
        wallet.service_budget_usd = 1.0
        wallet.service_budget_period = "monthly"
        wallet.status = "active"

    # Insert payment that hits the cap
    session.add(
        PaymentRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            wallet_id=wallet.id,
            agent_id=str(agent.id),
            execution_id=f"seed-{uuid4().hex[:8]}",
            protocol="x402",
            amount_usd=1.05,
            recipient="0x000seed",
            tool_name="seed-tool",
            tool_call_id=f"call-{uuid4().hex[:8]}",
            status="completed",
        )
    )
    await session.flush()
    print(f"wallet for agent '{agent.name}' marked exhausted (1.05 / 1.0 USD monthly)")
    return True


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id", help="Target workspace id")
    parser.add_argument("--user", default="seed-script", help="created_by attribution")
    parser.add_argument("--agents", type=int, default=3, help="agents to use/create")
    parser.add_argument("--tasks", type=int, default=80, help="tasks to insert")
    parser.add_argument(
        "--cap",
        type=float,
        default=25.0,
        help="monthly cap in USD (use 0 or negative to clear)",
    )
    parser.add_argument(
        "--with-blockers",
        action="store_true",
        default=True,
        help="include HITL / failed / exhausted-wallet entries",
    )
    parser.add_argument(
        "--no-blockers", dest="with_blockers", action="store_false"
    )
    parser.add_argument(
        "--reset", action="store_true", help="delete prior seed-tagged tasks first"
    )
    args = parser.parse_args()

    random.seed()

    async with db.session() as session:
        if args.reset:
            await reset_seeded(session, args.workspace_id)

        cap = args.cap if args.cap and args.cap > 0 else None
        await upsert_settings(session, args.workspace_id, args.user, cap)

        agents = await get_or_create_agents(
            session, args.workspace_id, args.user, args.agents
        )
        print(f"using {len(agents)} agents: {[a.name for a in agents]}")

        completed, failed, hitl = await seed_tasks(
            session,
            args.workspace_id,
            args.user,
            agents,
            args.tasks,
            args.with_blockers,
        )

        if args.with_blockers and agents:
            await exhaust_one_wallet(session, args.workspace_id, args.user, agents[0])

        await session.commit()

    print(
        f"\nseeded: {completed} completed, {failed} failed (24h-ish), "
        f"{hitl} input_required tasks. cap=${cap}. open /dashboard."
    )


if __name__ == "__main__":
    asyncio.run(main())
