"""The installation row, against the migrated schema.

Replicas starting together must end up with one row and one install_id; only the
single-row index decides that, which a mocked session cannot show. It runs under
the ENFORCE tenant scope with no workspace bound, as a pulse job or a request
that selects no workspace does.

Needs a PostgreSQL migrated to head; skips without one:

    ANALYTICS_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/agentarea_test  # pragma: allowlist secret
"""

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
from agentarea_common.analytics import get_or_create_installation
from agentarea_common.base.tenant_scope import tenant_scoped_session_class
from agentarea_common.config.database import TenantScopeMode
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("ANALYTICS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ANALYTICS_TEST_DATABASE_URL not set; skipping schema-backed installation tests",
)


@pytest.fixture
async def maker() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_size=10)
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
        await session.execute(text("DELETE FROM installation"))
        await session.commit()


async def _install_id(factory) -> str:
    async with factory() as session:
        installation = await get_or_create_installation(session)
        await session.commit()
        return installation.id


async def _rows(factory) -> int:
    async with factory() as session:
        return (await session.execute(text("SELECT count(*) FROM installation"))).scalar_one()


async def test_the_first_call_creates_the_row_and_later_calls_return_it(maker):
    first = await _install_id(maker)

    assert len(first) == 32
    assert await _install_id(maker) == first
    assert await _rows(maker) == 1


async def test_replicas_creating_it_at_once_share_one_row(maker):
    ids = await asyncio.gather(*(_install_id(maker) for _ in range(8)))

    assert len(set(ids)) == 1
    assert await _rows(maker) == 1


async def test_the_table_refuses_a_second_row(maker):
    await _install_id(maker)

    async with maker() as session:
        with pytest.raises(IntegrityError, match="uq_installation_single_row"):
            await session.execute(
                text(
                    "INSERT INTO installation (id, created_at, updated_at) "
                    "VALUES ('other', now(), now())"
                )
            )
