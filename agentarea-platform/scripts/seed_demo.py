"""Unified demo seed: dashboard data, agents, automations, Telegram bot.

Replaces ``seed_dashboard.py`` with a one-shot end-to-end fixture for showing
off the platform: workspace settings → LLM provider/model → diverse agents
with personas → tasks (with spend) covering 30 days → blockers (HITL, failed,
exhausted-wallet) → cron automations → a Telegram webhook trigger wired to a
real bot token.

Usage::

    cd agentarea-platform
    uv run python scripts/seed_demo.py <workspace_id> \
        [--user UID] \
        [--agents 5] [--tasks 120] [--cap 50] [--reset] \
        [--openrouter-key sk-or-...] \
        [--openrouter-model "minimax/minimax-m2.7"] \
        [--telegram-token 8156330210:AAH...] \
        [--no-telegram] [--no-automations] [--no-blockers]

Idempotent for upserts (workspace_settings, provider/model, telegram secret).
Tasks are *appended* — pass ``--reset`` to wipe seed-tagged rows first.

Skip flags let you re-seed pieces independently. The script prints a summary
and the public webhook URL Telegram should target via ``setWebhook``.

Notes:
- Direct SQLAlchemy ORM, no event broker / Temporal wiring.
- Costs go in ``task.result.total_cost`` so dashboard spend aggregator picks
  them up.
- Telegram bot token is encrypted with Fernet using
  ``SECRET_MANAGER_ENCRYPTION_KEY`` and stored in ``encrypted_secrets``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import secrets as _secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from agentarea_agents.domain.models import Agent
from agentarea_common.infrastructure.database import db
from agentarea_llm.domain.models import (
    ModelInstance,
    ModelSpec,
    ProviderConfig,
    ProviderSpec,
)
from agentarea_secrets.database_secret_manager import EncryptedSecret
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_triggers.infrastructure.orm import TriggerORM
from agentarea_wallet.domain.models import AgentWallet, PaymentRecord
from agentarea_workspaces.domain.models import WorkspaceSettings
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# ── Fixtures ────────────────────────────────────────────────────────

# Each agent has a real persona so the dashboard isn't a wall of "researcher-a1b2c3".
AGENT_PERSONAS: list[dict[str, str]] = [
    {
        "name": "Aurora",
        "role": "operations-lead",
        "description": "Coordinates the rest of the fleet, escalates blockers.",
        "instruction": (
            "You orchestrate a small team of agents. Plan work, delegate, and surface "
            "anything humans need to approve. Be terse."
        ),
    },
    {
        "name": "Atlas",
        "role": "researcher",
        "description": "Investigates topics, summarizes sources, drafts briefs.",
        "instruction": (
            "You research questions thoroughly. Cite sources, distinguish facts from "
            "speculation, and end with a one-paragraph executive summary."
        ),
    },
    {
        "name": "Echo",
        "role": "writer",
        "description": "Turns rough notes into polished customer-facing copy.",
        "instruction": (
            "You write clearly for non-technical readers. Lead with the benefit, keep "
            "sentences short, avoid jargon."
        ),
    },
    {
        "name": "Quill",
        "role": "data-analyst",
        "description": "Pulls metrics, builds charts, flags anomalies.",
        "instruction": (
            "You analyze numbers. State the period, the metric, and the delta. If "
            "something looks off, say so explicitly."
        ),
    },
    {
        "name": "Pulse",
        "role": "support-bot",
        "description": "Triages incoming tickets and Telegram messages.",
        "instruction": (
            "You handle inbound messages. Be friendly, ask clarifying questions, and "
            "escalate anything involving refunds or complaints."
        ),
    },
    {
        "name": "Forge",
        "role": "engineer",
        "description": "Reviews PRs, runs tests, files build issues.",
        "instruction": (
            "You review code changes. Flag obvious bugs, missing tests, and security "
            "concerns. Be concrete — point at lines, not abstractions."
        ),
    },
    {
        "name": "Beacon",
        "role": "scheduler",
        "description": "Owns recurring jobs and reminders.",
        "instruction": (
            "You run scheduled tasks. Confirm each job's status, summarize results, "
            "and post to the team channel."
        ),
    },
    {
        "name": "Sage",
        "role": "qa",
        "description": "Validates output quality before release.",
        "instruction": (
            "You verify deliverables before they go out. Check facts, links, tone, "
            "and formatting. Report pass/fail with specific evidence."
        ),
    },
]

TASK_TITLES = [
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
    "Build weekly KPI digest",
    "Scan PRs for regressions",
    "Sync Notion roadmap to Linear",
    "Refresh customer health scores",
    "Compose Telegram broadcast",
]

ERROR_POOL = [
    "ToolExecutionError: tool 'fetch_invoice' timed out after 30s",
    "LLMRateLimitError: 429 from upstream",
    "ValidationError: missing required field 'customer_id'",
    "MCPConnectionError: server returned 503",
    "BudgetCapExceededError: workspace cap reached mid-execution",
]

HITL_PROMPTS = [
    "Approve refund of $148 to customer C-2842?",
    "Confirm sending email blast to 14k recipients?",
    "Merge conflicting calendar events into one?",
    "Reset password for shared account?",
    "Authorize Telegram broadcast to 320 chats?",
]

# (cron_expr, name, description, persona role hint)
CRON_AUTOMATIONS = [
    ("0 9 * * *", "Daily morning brief", "Pulls yesterday's metrics and posts to Slack.", "scheduler"),
    ("*/30 * * * *", "Inbox triage", "Sweeps support inbox and routes urgent tickets.", "support-bot"),
    ("0 17 * * 5", "Weekly review", "Compiles last 7 days into a leadership digest.", "operations-lead"),
    ("0 * * * *", "Hourly metric sync", "Refreshes KPI dashboards from source systems.", "data-analyst"),
]

DEFAULT_TELEGRAM_TOKEN = os.environ.get("SEED_TELEGRAM_BOT_TOKEN", "")
DEFAULT_OPENROUTER_KEY = ""
DEFAULT_OPENROUTER_MODEL = "minimax/minimax-m2.7"
WEBHOOK_BASE_URL_DEFAULT = "http://localhost:8000/webhooks"


# ── Helpers ─────────────────────────────────────────────────────────


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _random_cost() -> float:
    return round(random.uniform(0.0008, 0.012), 5)


def _within_today() -> datetime:
    now = _utc_now_naive()
    today_start = datetime(now.year, now.month, now.day)
    span = max(1, int((now - today_start).total_seconds()))
    return today_start + timedelta(seconds=random.randint(0, span))


def _within_last_n_days(n: int) -> datetime:
    now = _utc_now_naive()
    earliest = now - timedelta(days=n)
    span = int((now - earliest).total_seconds())
    return earliest + timedelta(seconds=random.randint(0, span))


def _within_mtd() -> datetime:
    now = _utc_now_naive()
    month_start = datetime(now.year, now.month, 1)
    span = max(1, int((now - month_start).total_seconds()))
    return month_start + timedelta(seconds=random.randint(0, span))


# ── 1. Workspace settings ───────────────────────────────────────────


async def upsert_settings(session: AsyncSession, workspace_id: str, cap: float | None) -> None:
    stmt = (
        pg_insert(WorkspaceSettings)
        .values(workspace_id=workspace_id, monthly_cap_usd=cap)
        .on_conflict_do_update(
            index_elements=["workspace_id"],
            set_={"monthly_cap_usd": cap},
        )
    )
    await session.execute(stmt)
    print(f"  workspace_settings.monthly_cap_usd = {cap}")


# ── 2. LLM: OpenRouter provider + model ─────────────────────────────


async def upsert_provider_and_model(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
    api_key: str,
    model_name: str,
) -> ModelInstance:
    """Ensure an OpenRouter ProviderSpec / Config / ModelSpec / ModelInstance
    chain exists. provider_key is globally unique, so we look it up first."""
    spec = (
        await session.execute(select(ProviderSpec).where(ProviderSpec.provider_key == "openrouter"))
    ).scalar_one_or_none()
    if spec is None:
        spec = ProviderSpec(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            provider_key="openrouter",
            name="OpenRouter",
            description="Aggregator for many LLM providers.",
            provider_type="openrouter",
            icon=None,
            is_builtin=True,
        )
        session.add(spec)
        await session.flush()
        print(f"  created ProviderSpec openrouter [{spec.id}]")

    config = (
        await session.execute(
            select(ProviderConfig)
            .where(ProviderConfig.workspace_id == workspace_id)
            .where(ProviderConfig.provider_spec_id == spec.id)
        )
    ).scalar_one_or_none()
    if config is None:
        config = ProviderConfig(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            provider_spec_id=spec.id,
            name="OpenRouter (demo)",
            api_key=api_key,
            endpoint_url="https://openrouter.ai/api/v1",
            is_active=True,
        )
        session.add(config)
        await session.flush()
        print(f"  created ProviderConfig [{config.id}]")
    elif config.api_key != api_key:
        config.api_key = api_key
        await session.flush()
        print(f"  refreshed ProviderConfig.api_key [{config.id}]")

    spec_row = (
        await session.execute(
            select(ModelSpec)
            .where(ModelSpec.provider_spec_id == spec.id)
            .where(ModelSpec.model_name == model_name)
        )
    ).scalar_one_or_none()
    if spec_row is None:
        spec_row = ModelSpec(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            provider_spec_id=spec.id,
            model_name=model_name,
            display_name=model_name,
            description="Demo seeded model",
            context_window=128000,
            max_output_tokens=4096,
            supports_function_calling=True,
            is_active=True,
        )
        session.add(spec_row)
        await session.flush()
        print(f"  created ModelSpec {model_name} [{spec_row.id}]")

    instance = (
        await session.execute(
            select(ModelInstance)
            .where(ModelInstance.workspace_id == workspace_id)
            .where(ModelInstance.provider_config_id == config.id)
            .where(ModelInstance.model_spec_id == spec_row.id)
        )
    ).scalar_one_or_none()
    if instance is None:
        instance = ModelInstance(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            provider_config_id=config.id,
            model_spec_id=spec_row.id,
            name=f"OpenRouter · {model_name}",
            description="Default demo model for seeded agents.",
            is_active=True,
        )
        session.add(instance)
        await session.flush()
        print(f"  created ModelInstance [{instance.id}]")
    return instance


# ── 3. Agents ───────────────────────────────────────────────────────


async def get_or_create_agents(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
    model_instance_id: UUID,
    count: int,
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
        # Backfill model_id on existing agents that have none.
        for a in existing[:count]:
            if not a.model_id:
                a.model_id = str(model_instance_id)
        await session.flush()
        return list(existing[:count])

    needed = count - len(existing)
    used_names = {a.name for a in existing}
    pool = [p for p in AGENT_PERSONAS if p["name"] not in used_names]
    print(f"  workspace has {len(existing)} agents, creating {needed} more")
    created: list[Agent] = []
    for i in range(needed):
        persona = pool[i % len(pool)] if pool else AGENT_PERSONAS[i % len(AGENT_PERSONAS)]
        suffix = "" if persona in pool else "-" + uuid4().hex[:4]
        agent = Agent(
            id=uuid4(),
            name=persona["name"] + suffix,
            description=persona["description"],
            instruction=persona["instruction"],
            workspace_id=workspace_id,
            created_by=user_id,
            model_id=str(model_instance_id),
            agent_type="stateless",
        )
        session.add(agent)
        created.append(agent)
    await session.flush()
    return list(existing) + created


def _persona_role(agent: Agent) -> str | None:
    base = agent.name.split("-")[0]
    for p in AGENT_PERSONAS:
        if p["name"] == base:
            return p["role"]
    return None


# ── 4. Tasks (dashboard data) ───────────────────────────────────────


async def reset_seeded(session: AsyncSession, workspace_id: str) -> None:
    stmt = delete(TaskORM).where(
        TaskORM.workspace_id == workspace_id,
        TaskORM.task_metadata.op("->>")("seed") == "demo",
    )
    res = await session.execute(stmt)
    print(f"  removed {res.rowcount} previously seeded tasks")


async def seed_tasks(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
    agents: list[Agent],
    n_tasks: int,
    with_blockers: bool,
) -> tuple[int, int, int]:
    """Insert n_tasks across 30-day window. Returns (completed, failed, hitl)."""
    completed = failed = hitl = 0
    now = _utc_now_naive()

    for _ in range(n_tasks):
        agent = random.choice(agents)
        roll = random.random()
        title = random.choice(TASK_TITLES)
        common = dict(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            agent_id=agent.id,
            description=title,
            parameters={},
            task_metadata={"seed": "demo"},
        )
        # Bias ~40% of completed tasks to today/yesterday so dashboard "today"
        # numbers are non-zero on a fresh seed.
        if roll < 0.70:
            if random.random() < 0.4:
                started = _within_today() if random.random() < 0.5 else now - timedelta(
                    hours=random.randint(1, 30)
                )
            else:
                started = _within_last_n_days(30)
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


# ── 5. Exhausted wallet ─────────────────────────────────────────────


async def exhaust_one_wallet(
    session: AsyncSession, workspace_id: str, user_id: str, agent: Agent
) -> None:
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
    print(f"  wallet for '{agent.name}' marked exhausted (1.05 / 1.0 USD monthly)")


# ── 6. Cron triggers (automations) ──────────────────────────────────


async def seed_cron_triggers(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
    agents: list[Agent],
) -> int:
    """Create one cron trigger per CRON_AUTOMATIONS entry, mapped to the agent
    whose persona role matches (falling back to round-robin)."""
    by_role: dict[str, Agent] = {}
    for a in agents:
        r = _persona_role(a)
        if r and r not in by_role:
            by_role[r] = a

    created = 0
    for i, (cron, name, desc, role_hint) in enumerate(CRON_AUTOMATIONS):
        agent = by_role.get(role_hint) or agents[i % len(agents)]

        # Idempotency: skip if a seeded trigger with this name already exists for the agent.
        existing = (
            await session.execute(
                select(TriggerORM)
                .where(TriggerORM.workspace_id == workspace_id)
                .where(TriggerORM.agent_id == agent.id)
                .where(TriggerORM.name == name)
            )
        ).scalar_one_or_none()
        if existing:
            continue

        session.add(
            TriggerORM(
                id=uuid4(),
                workspace_id=workspace_id,
                created_by=user_id,
                name=name,
                description=desc,
                agent_id=agent.id,
                trigger_type="cron",
                cron_expression=cron,
                timezone="UTC",
                is_active=True,
                task_parameters={"prompt": f"Run scheduled job: {name}"},
                conditions={},
                validation_rules={},
            )
        )
        created += 1
    await session.flush()
    if created:
        print(f"  created {created} cron triggers")
    else:
        print("  cron triggers already present, skipped")
    return created


# ── 7. Telegram webhook trigger + encrypted secret ──────────────────


def _encrypt(value: str, encryption_key: str) -> str:
    return Fernet(encryption_key.encode("utf-8")).encrypt(value.encode("utf-8")).decode("utf-8")


async def upsert_secret(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
    secret_name: str,
    value: str,
    encryption_key: str,
) -> None:
    enc = _encrypt(value, encryption_key)
    existing = (
        await session.execute(
            select(EncryptedSecret)
            .where(EncryptedSecret.workspace_id == workspace_id)
            .where(EncryptedSecret.secret_name == secret_name)
        )
    ).scalar_one_or_none()
    if existing:
        existing.encrypted_value = enc
        existing.updated_by = user_id
    else:
        session.add(
            EncryptedSecret(
                id=uuid4(),
                workspace_id=workspace_id,
                secret_name=secret_name,
                encrypted_value=enc,
                created_by=user_id,
            )
        )
    await session.flush()


async def seed_telegram_trigger(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
    agent: Agent,
    bot_token: str,
    encryption_key: str,
    webhook_base_url: str,
) -> tuple[str, str]:
    """Create or refresh a Telegram webhook trigger for ``agent`` and store
    the bot token as an encrypted secret. Returns (webhook_id, public_url)."""
    existing = (
        await session.execute(
            select(TriggerORM)
            .where(TriggerORM.workspace_id == workspace_id)
            .where(TriggerORM.agent_id == agent.id)
            .where(TriggerORM.webhook_type == "telegram")
        )
    ).scalar_one_or_none()

    if existing:
        webhook_id = existing.webhook_id or _secrets.token_urlsafe(16)
        existing.webhook_id = webhook_id
        existing.is_active = True
        existing.allowed_methods = ["POST"]
        secret_name = (existing.webhook_config or {}).get("secret_key") or f"telegram_bot_token__{webhook_id}"
        existing.webhook_config = {**(existing.webhook_config or {}), "secret_key": secret_name}
        await session.flush()
        await upsert_secret(session, workspace_id, user_id, secret_name, bot_token, encryption_key)
        print(f"  refreshed Telegram trigger [{existing.id}]")
    else:
        webhook_id = _secrets.token_urlsafe(16)
        secret_name = f"telegram_bot_token__{webhook_id}"
        trigger = TriggerORM(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=user_id,
            name=f"{agent.name} · Telegram inbox",
            description="Inbound Telegram messages → tasks.",
            agent_id=agent.id,
            trigger_type="webhook",
            webhook_type="telegram",
            webhook_id=webhook_id,
            allowed_methods=["POST"],
            webhook_config={"secret_key": secret_name},
            event_types=[],
            is_active=True,
            task_parameters={"prompt": "Handle incoming Telegram message: {{ message_text }}"},
            conditions={},
            validation_rules={},
        )
        session.add(trigger)
        await session.flush()
        await upsert_secret(session, workspace_id, user_id, secret_name, bot_token, encryption_key)
        print(f"  created Telegram trigger [{trigger.id}]")

    public_url = f"{webhook_base_url.rstrip('/')}/{webhook_id}"
    return webhook_id, public_url


# ── Main ────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id", help="Target workspace id")
    parser.add_argument("--user", default="seed-script", help="created_by attribution")
    parser.add_argument("--agents", type=int, default=5, help="agents to use/create")
    parser.add_argument("--tasks", type=int, default=120, help="tasks to insert")
    parser.add_argument("--cap", type=float, default=50.0, help="monthly cap USD (0 to clear)")
    parser.add_argument("--reset", action="store_true", help="delete prior seed-tagged tasks first")
    parser.add_argument("--no-blockers", dest="with_blockers", action="store_false")
    parser.set_defaults(with_blockers=True)
    parser.add_argument("--no-automations", dest="with_automations", action="store_false")
    parser.set_defaults(with_automations=True)
    parser.add_argument("--no-telegram", dest="with_telegram", action="store_false")
    parser.set_defaults(with_telegram=True)
    parser.add_argument("--openrouter-key", default=os.environ.get("OPENROUTER_API_KEY", DEFAULT_OPENROUTER_KEY))
    parser.add_argument("--openrouter-model", default=DEFAULT_OPENROUTER_MODEL)
    parser.add_argument("--telegram-token", default=DEFAULT_TELEGRAM_TOKEN)
    parser.add_argument(
        "--webhook-base-url",
        default=os.environ.get("TRIGGERS_WEBHOOK_BASE_URL", WEBHOOK_BASE_URL_DEFAULT),
        help="Public base URL for Telegram setWebhook (e.g., https://api.example.com/webhooks)",
    )
    args = parser.parse_args()

    random.seed()
    encryption_key = os.environ.get("SECRET_MANAGER_ENCRYPTION_KEY")
    if args.with_telegram and not encryption_key:
        raise SystemExit(
            "SECRET_MANAGER_ENCRYPTION_KEY env var is required for --telegram seeding "
            "(or pass --no-telegram)."
        )
    if not args.openrouter_key:
        raise SystemExit(
            "OpenRouter API key is required. Pass --openrouter-key or export OPENROUTER_API_KEY."
        )
    if args.with_telegram and not args.telegram_token:
        raise SystemExit(
            "Telegram bot token is required for --telegram seeding. "
            "Pass --telegram-token or export SEED_TELEGRAM_BOT_TOKEN (or pass --no-telegram)."
        )

    cap = args.cap if args.cap and args.cap > 0 else None

    async with db.session() as session:
        if args.reset:
            print("→ Reset:")
            await reset_seeded(session, args.workspace_id)

        print("→ Workspace settings:")
        await upsert_settings(session, args.workspace_id, cap)

        print("→ LLM provider/model (OpenRouter):")
        model_instance = await upsert_provider_and_model(
            session, args.workspace_id, args.user, args.openrouter_key, args.openrouter_model
        )

        print("→ Agents:")
        agents = await get_or_create_agents(
            session, args.workspace_id, args.user, model_instance.id, args.agents
        )
        print(f"  using {len(agents)} agents: {[a.name for a in agents]}")

        print("→ Tasks:")
        completed, failed, hitl = await seed_tasks(
            session, args.workspace_id, args.user, agents, args.tasks, args.with_blockers
        )
        print(f"  +{completed} completed, +{failed} failed, +{hitl} input_required")

        if args.with_blockers and agents:
            print("→ Exhausted wallet:")
            await exhaust_one_wallet(session, args.workspace_id, args.user, agents[0])

        if args.with_automations:
            print("→ Cron automations:")
            await seed_cron_triggers(session, args.workspace_id, args.user, agents)

        webhook_url: str | None = None
        if args.with_telegram and agents:
            print("→ Telegram trigger:")
            inbox_agent = next((a for a in agents if _persona_role(a) == "support-bot"), agents[0])
            _, webhook_url = await seed_telegram_trigger(
                session,
                args.workspace_id,
                args.user,
                inbox_agent,
                args.telegram_token,
                encryption_key,
                args.webhook_base_url,
            )

        await session.commit()

    print("\n✔ Seed complete.")
    print(f"  Open /dashboard")
    if webhook_url:
        print("\n  Telegram bot wiring (run once on a public host):")
        print(
            f"    curl -X POST 'https://api.telegram.org/bot{args.telegram_token}/setWebhook' "
            f"-d 'url={webhook_url}'"
        )


if __name__ == "__main__":
    asyncio.run(main())
