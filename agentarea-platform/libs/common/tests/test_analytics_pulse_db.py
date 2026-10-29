"""The daily pulse, against the migrated schema.

The pulse names other libraries' tables by hand, so only the real schema shows that
every table and column it reads exists. The aggregates run on a seeded installation
whose rows are rolled back afterwards; the send-once rules run on the installation
row and a real advisory lock. Everything runs under the ENFORCE tenant scope, as the
worker does.

Needs a PostgreSQL migrated to head; skips without one:

    ANALYTICS_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/agentarea_test  # pragma: allowlist secret
"""

import json
import os
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from agentarea_common.analytics import InstallationPulse
from agentarea_common.analytics.pulse_repository import PULSE_LOCK_KEY, collect_pulse
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, unscoped
from agentarea_common.config.database import TenantScopeMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("ANALYTICS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ANALYTICS_TEST_DATABASE_URL not set; skipping schema-backed pulse tests",
)

NOW = datetime(2030, 6, 15, 12, 0, 0)

_SEEDED_TABLES = (
    "workspaces",
    "workspace_memberships",
    "tasks",
    "agents",
    "mcp_server_instances",
    "mcp_servers",
    "openapi_connections",
    "mcp_auth_configs",
    "registry_items",
    "registries",
    "triggers",
    "skills",
    "installed_bundles",
    "policies",
    "clients",
    "provider_configs",
    "provider_specs",
)

# What the seeded tenants named their own resources; none of it may leave.
_PRIVATE = (
    "acme",
    "Acme Secret",
    "Bob Private",
    "secret.internal",
    "internal-crm",
    "secret-skill",
    "acme-private-pack",
    "bobs-secret-bundle",
    "My Private Skill",
    "Some free text",
    "u-alice",
    "team-1",
)


@pytest.fixture
async def maker() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    await engine.dispose()


async def _insert(session: AsyncSession, table: str, **values: Any) -> str:
    row = {"id": str(uuid4()), "created_at": NOW, "updated_at": NOW, **values}
    row = {k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in row.items()}
    columns, params = ", ".join(row), ", ".join(f":{k}" for k in row)
    await session.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), row)  # noqa: S608
    return str(row["id"])


def _ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


async def _seed(session: AsyncSession) -> None:
    async def workspace(ws_id: str, owner: str, created: datetime, *members: str) -> None:
        await _insert(
            session,
            "workspaces",
            id=ws_id,
            name=f"{ws_id} name",
            slug=ws_id,
            owner_user_id=owner,
            created_at=created,
        )
        for user in members:
            await _insert(session, "workspace_memberships", workspace_id=ws_id, user_id=user)

    await workspace("platform", "platform", _ago(days=400), "platform")
    await workspace("u-alice", "u-alice", _ago(days=2), "u-alice")
    await workspace("u-bob", "u-bob", _ago(days=3), "u-bob")
    await workspace("u-carol", "u-carol", _ago(days=40), "u-carol")
    await workspace("team-1", "u-carol", _ago(days=40), "u-carol", "u-dave", "u-erin")
    await workspace("big-1", "u-m1", _ago(days=100), *(f"u-m{n}" for n in range(1, 7)))

    def scoped(ws_id: str) -> dict[str, str]:
        return {"workspace_id": ws_id, "created_by": "u-carol"}

    async def agent(ws_id: str, created: datetime) -> None:
        await _insert(
            session,
            "agents",
            name="Acme Secret Agent",
            slug=str(uuid4()),
            status="active",
            created_at=created,
            **scoped(ws_id),
        )

    await agent("u-alice", _ago(hours=1))
    await agent("team-1", _ago(days=30))
    await agent("team-1", _ago(days=30))
    await agent("platform", _ago(hours=1))

    async def task(ws_id: str, by: str, status: str, created: datetime, **more: Any) -> None:
        await _insert(
            session,
            "tasks",
            agent_id=str(uuid4()),
            description="Some free text the user typed",
            status=status,
            workspace_id=ws_id,
            created_by=by,
            created_at=created,
            **more,
        )

    created = _ago(days=2) + timedelta(hours=4)
    await task(
        "u-alice",
        "u-alice",
        "completed",
        created,
        origin_type="user",
        started_at=created,
        completed_at=created + timedelta(hours=1),
    )
    await task(
        "u-bob",
        "u-bob",
        "completed",
        _ago(hours=26),
        origin_type="trigger",
        started_at=_ago(hours=25),
        completed_at=_ago(hours=23),
    )
    await task(
        "team-1",
        "u-dave",
        "completed",
        _ago(hours=2),
        origin_type="api",
        started_at=_ago(hours=2),
        completed_at=_ago(hours=1),
    )
    await task(
        "team-1",
        "u-erin",
        "failed",
        _ago(hours=3),
        origin_type="agent",
        result={"failure_reason": "no_credits"},
        started_at=_ago(hours=3),
        completed_at=_ago(hours=3) + timedelta(seconds=60),
    )
    await task(
        "team-1",
        "u-dave",
        "failed",
        _ago(hours=4),
        result={"failure_reason": "Some free text with Names"},
    )
    await task("team-1", "u-dave", "failed", _ago(hours=5), origin_type="user")
    await task("u-carol", "u-carol", "completed", _ago(days=20), origin_type="user")
    await task("platform", "platform", "completed", _ago(hours=1), origin_type="user")

    async def registry(name: str, source_url: str) -> str:
        return await _insert(
            session,
            "registries",
            name=name,
            registry_type="mcp_servers",
            source_type="url",
            source_url=source_url,
        )

    official = await registry(
        "system-mcp-servers",
        "https://agentarea-mcp-registry.s3.amazonaws.com/registry/system/mcp-servers.json",
    )
    private = await registry("acme-catalog", "https://catalog.acme.internal/registry.json")

    async def item(external_id: str, registry_type: str, registry_id: str = official) -> str:
        return await _insert(
            session,
            "registry_items",
            registry_id=registry_id,
            external_id=external_id,
            name=f"{external_id} title",
            registry_type=registry_type,
            registry_priority=100,
            registry_active=True,
        )

    github = await item("io.github/github-mcp", "mcp_servers")
    stripe = await item("stripe-api", "mcp_servers")
    pdf = await item("anthropics/pdf", "skills")
    await item("sales-pack", "bundles")
    private_mcp = await item("acme/internal-crm", "mcp_servers", private)
    private_skill = await item("acme/secret-skill", "skills", private)
    await item("acme-private-pack", "bundles", private)

    async def spec(ws_id: str, registry_item_id: str | None) -> str:
        return await _insert(
            session,
            "mcp_servers",
            name="Acme Secret Spec",
            slug=str(uuid4()),
            description="",
            version="1",
            tags=[],
            status="active",
            is_public=False,
            registry_item_id=registry_item_id,
            **scoped(ws_id),
        )

    github_spec = await spec("platform", github)
    custom_spec = await spec("team-1", None)
    private_spec = await spec("u-alice", private_mcp)

    async def auth(ws_id: str, auth_type: str) -> str:
        return await _insert(
            session,
            "mcp_auth_configs",
            name="Acme Secret Auth",
            auth_type=auth_type,
            **scoped(ws_id),
        )

    oauth = await auth("team-1", "oauth2")
    api_key = await auth("u-alice", "api_key")
    bearer = await auth("team-1", "bearer")

    async def instance(ws_id: str, spec_id: str, auth_id: str | None, **more: Any) -> None:
        await _insert(
            session,
            "mcp_server_instances",
            name="Acme Secret Internal MCP",
            server_spec_id=spec_id,
            transport="url",
            auth_config_id=auth_id,
            **scoped(ws_id),
            **more,
        )

    await instance("team-1", github_spec, oauth, verification={"status": "succeeded"})
    await instance("team-1", custom_spec, None, verification={"status": "failed"})
    await instance("u-alice", private_spec, api_key)
    await instance("platform", github_spec, None, verification={"status": "succeeded"})

    async def openapi(ws_id: str, item_id: str | None, auth_id: str | None) -> None:
        await _insert(
            session,
            "openapi_connections",
            name="Bob Private API",
            base_url="https://secret.internal.example",
            registry_item_id=item_id,
            auth_config_id=auth_id,
            **scoped(ws_id),
        )

    await openapi("team-1", stripe, bearer)
    await openapi("u-bob", None, None)

    async def trigger(ws_id: str, trigger_type: str, active: bool) -> None:
        await _insert(
            session,
            "triggers",
            name="Acme Secret Trigger",
            description="",
            agent_id=str(uuid4()),
            trigger_type=trigger_type,
            is_active=active,
            task_parameters={},
            conditions={},
            failure_threshold=5,
            consecutive_failures=0,
            **scoped(ws_id),
        )

    await trigger("team-1", "cron", True)
    await trigger("team-1", "stream", True)
    await trigger("team-1", "cron", False)
    await trigger("platform", "cron", True)

    await _insert(
        session, "skills", name="pdf", slug="pdf", registry_item_id=pdf, **scoped("team-1")
    )
    await _insert(session, "skills", name="My Private Skill", slug="mine", **scoped("u-alice"))
    await _insert(
        session,
        "skills",
        name="secret",
        slug="secret",
        registry_item_id=private_skill,
        **scoped("u-bob"),
    )

    for ws_id, name in (
        ("team-1", "sales-pack"),
        ("u-bob", "bobs-secret-bundle"),
        ("team-1", "acme-private-pack"),
    ):
        await _insert(
            session,
            "installed_bundles",
            name=name,
            schema_version="1",
            canonical={"name": name},
            **scoped(ws_id),
        )

    for ws_id in ("team-1", "team-1", "platform"):
        await _insert(
            session,
            "policies",
            subject_type="workspace",
            subject_id=ws_id,
            target="*",
            effect="allow",
            **scoped(ws_id),
        )

    for ws_id in ("team-1", "u-alice"):
        await _insert(session, "clients", name="Acme Secret Harness", **scoped(ws_id))

    async def provider(provider_type: str) -> str:
        return await _insert(
            session,
            "provider_specs",
            provider_key=provider_type,
            name=provider_type,
            provider_type=provider_type,
            is_builtin=True,
            **scoped("platform"),
        )

    openai = await provider("openai")
    anthropic = await provider("anthropic")
    for ws_id, spec_id in (
        ("team-1", openai),
        ("u-alice", openai),
        ("u-bob", anthropic),
        ("platform", openai),
    ):
        await _insert(
            session,
            "provider_configs",
            provider_spec_id=spec_id,
            name="Acme Secret Key",
            is_active=True,
            is_public=False,
            **scoped(ws_id),
        )


async def test_the_pulse_counts_the_seeded_installation_and_names_nothing(maker):
    async with maker() as session:
        await session.execute(text(f"TRUNCATE {', '.join(_SEEDED_TABLES)} CASCADE"))
        await _seed(session)
        try:
            with unscoped("the test reads the pulse the way the worker does"):
                pulse = await collect_pulse(session, NOW)
        finally:
            await session.rollback()

    assert pulse == {
        "workspaces": {"total": 5, "active_7d": 3, "active_30d": 4},
        "users": {"total": 11, "active_7d": 4, "active_30d": 5},
        "agents": {"total": 3, "created_24h": 1},
        "runs_24h": {
            "by_status": {"completed": 1, "failed": 3},
            "by_origin": {"api": 1, "agent": 1, "user": 1, "unknown": 1},
            "failed_by_reason": {"no_credits": 1, "other": 1, "unknown": 1},
            "median_duration_seconds": 3600.0,
        },
        "connectors": {
            "by_kind": {"mcp": 3, "openapi": 2},
            "by_catalog": {"io.github/github-mcp": 1, "stripe-api": 1, "custom": 3},
            "by_auth_type": {"oauth2": 1, "api_key": 1, "bearer": 1, "none": 2},
            "by_verification_status": {"succeeded": 1, "failed": 1, "never_attempted": 1},
        },
        "triggers_active": {"cron": 1, "stream": 1},
        "skills": {"anthropics/pdf": 1, "custom": 2},
        "bundles": {"sales-pack": 1, "custom": 2},
        "policies": 2,
        "clients": {"harness": 2},
        "llm_providers": {"openai": 2, "anthropic": 1},
        "workspace_sizes": {"1": 3, "2-5": 1, "6+": 1},
        "activation_7d": {
            "personal_workspaces": 2,
            "with_agent": 1,
            "succeeded_within_1d": 1,
            "succeeded_within_7d": 2,
        },
    }
    sent = json.dumps(pulse)
    assert not [private for private in _PRIVATE if private in sent]


class _Sender:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushes = 0

    def enqueue(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def flush(self) -> int:
        self.flushes += 1
        return len(self.events)


async def _clear_installation(factory) -> None:
    async with factory() as session:
        await session.execute(text("DELETE FROM installation"))
        await session.commit()


async def test_the_pulse_is_sent_once_a_day_and_recorded(maker):
    await _clear_installation(maker)
    sender = _Sender()
    clock = [NOW]
    pulse = InstallationPulse(session_factory=maker, sender=sender, clock=lambda: clock[0])  # type: ignore[arg-type]

    try:
        assert await pulse.run_once() is True
        clock[0] = NOW + timedelta(hours=23)
        assert await pulse.run_once() is False
        clock[0] = NOW + timedelta(hours=24)
        assert await pulse.run_once() is True

        assert [event["event"] for event in sender.events] == ["installation_pulse"] * 2
        assert sender.flushes == 2
        async with maker() as session:
            last = (
                await session.execute(text("SELECT last_pulse_at FROM installation"))
            ).scalar_one()
        assert last == NOW + timedelta(hours=24)
    finally:
        await _clear_installation(maker)


async def test_a_replica_without_the_lock_sends_nothing(maker):
    await _clear_installation(maker)
    sender = _Sender()
    pulse = InstallationPulse(session_factory=maker, sender=sender, clock=lambda: NOW)  # type: ignore[arg-type]

    try:
        async with maker() as holder:
            await holder.execute(text(f"SELECT pg_advisory_xact_lock({PULSE_LOCK_KEY})"))
            assert await pulse.run_once() is False
            await holder.rollback()

        assert sender.events == []
        assert await pulse.run_once() is True
    finally:
        await _clear_installation(maker)
