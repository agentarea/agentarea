"""Authenticating with an API key does not write to the database on every request.

The usage stamp used to be an UPDATE and a COMMIT in front of every API-key
request. It is now written once per interval, and the uses in between are
carried into that write so the count stays exact.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from agentarea_common.auth.dependencies import _validate_api_key
from agentarea_common.base.models import BaseModel
from agentarea_common.workspaces import Workspace
from agentarea_mcp.application.access_token_service import hash_token
from agentarea_mcp.domain.auth_models import APIKey
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

OWNER = "key-owner"
KEY = "aat_throttle-probe-key"  # pragma: allowlist secret


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[Workspace.__table__, APIKey.__table__]
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(Workspace(id=OWNER, slug="owner", name="Personal", owner_user_id=OWNER))
        session.add(
            APIKey(
                name="probe",
                token_hash=hash_token(KEY),
                token_prefix=KEY[:12],
                workspace_id=OWNER,
                created_by=OWNER,
            )
        )
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _wiring(session_factory):
    database = SimpleNamespace(async_session_factory=session_factory)
    with patch("agentarea_common.config.get_database", return_value=database):
        yield


async def _stored(factory) -> tuple[int, datetime | None]:
    async with factory() as session:
        key = (await session.execute(select(APIKey))).scalar_one()
        return key.access_count, key.last_accessed_at


async def _use_key() -> None:
    assert await _validate_api_key(KEY, MagicMock()) is not None


async def test_uses_within_the_interval_are_not_written(session_factory):
    await _use_key()
    first = await _stored(session_factory)

    await _use_key()
    await _use_key()

    assert first[0] == 1
    assert first[1] is not None
    assert await _stored(session_factory) == first


async def test_the_next_write_carries_the_uses_it_skipped(session_factory):
    await _use_key()
    await _use_key()
    await _use_key()
    async with session_factory() as session:
        await session.execute(
            update(APIKey).values(last_accessed_at=datetime.utcnow() - timedelta(minutes=5))
        )
        await session.commit()

    await _use_key()

    count, last_accessed_at = await _stored(session_factory)
    assert count == 4
    assert last_accessed_at is not None
    assert datetime.utcnow() - last_accessed_at < timedelta(minutes=1)
