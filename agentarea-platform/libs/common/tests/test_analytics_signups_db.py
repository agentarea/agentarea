"""Sign-up attributions, against the migrated schema.

Kratos may deliver a registration's hook more than once; only the primary key on
identity_id decides that the first delivery's row stands, which a mocked session
cannot show. It runs under the ENFORCE tenant scope with no workspace bound, as the
hook's request does.

Needs a PostgreSQL migrated to head; skips without one:

    ANALYTICS_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/agentarea_test  # pragma: allowlist secret
"""

import os
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from agentarea_common.analytics.attribution import Attribution
from agentarea_common.analytics.signup_repository import upsert_signup_attribution
from agentarea_common.base.tenant_scope import tenant_scoped_session_class
from agentarea_common.config.database import TenantScopeMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("ANALYTICS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ANALYTICS_TEST_DATABASE_URL not set; skipping schema-backed sign-up tests",
)

CREATED = datetime(2030, 6, 15, 12, 0, 0)


@pytest.fixture
async def maker() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    await _clear(factory)
    yield factory
    await _clear(factory)
    await engine.dispose()


async def _clear(factory) -> None:
    async with factory() as session:
        await session.execute(text("DELETE FROM signup_attributions"))
        await session.commit()


async def _upsert(factory, attribution: Attribution, method: str | None = "password") -> bool:
    async with factory() as session:
        inserted = await upsert_signup_attribution(
            session,
            identity_id="identity-1",
            created_at=CREATED,
            method=method,
            attribution=attribution,
        )
        await session.commit()
        return inserted


async def _rows(factory) -> list[dict]:
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT identity_id, created_at, method, channel, referrer_host, landing_host, "
                "landing_path, utm_source, utm_medium, utm_campaign FROM signup_attributions"
            )
        )
        return [dict(row) for row in result.mappings()]


async def test_the_first_delivery_stores_the_channel(maker):
    attribution = Attribution(
        channel="search",
        referrer_host="www.google.com",
        landing_host="agentarea.ai",
        landing_path="/skills/*",
    )

    assert await _upsert(maker, attribution) is True

    assert await _rows(maker) == [
        {
            "identity_id": "identity-1",
            "created_at": CREATED,
            "method": "password",
            "channel": "search",
            "referrer_host": "www.google.com",
            "landing_host": "agentarea.ai",
            "landing_path": "/skills/*",
            "utm_source": None,
            "utm_medium": None,
            "utm_campaign": None,
        }
    ]


async def test_a_replay_leaves_the_first_row_unchanged(maker):
    await _upsert(maker, Attribution(channel="campaign", utm_source="newsletter"))

    assert await _upsert(maker, Attribution(channel="direct"), method="oidc") is False

    rows = await _rows(maker)
    assert len(rows) == 1
    assert rows[0]["channel"] == "campaign"
    assert rows[0]["utm_source"] == "newsletter"
    assert rows[0]["method"] == "password"
