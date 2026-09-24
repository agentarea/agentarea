"""A workspace and its governance baseline are admitted together or not at all.

``provision_default_policies`` runs from the creation hook. Had the row been
committed before it, a provisioning failure would leave a workspace that exists
and has no runtime baseline -- it looks finished, so nothing retries it, and it
executes under weaker implicit settings.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from agentarea_api.api.v1 import workspaces as workspaces_api
from agentarea_common.auth.context import UserContext
from agentarea_common.workspaces import Workspace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

OWNER = "user-owner"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Workspace.__table__.create)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "create",
    [
        pytest.param(lambda s: s.create_shared(owner_user_id=OWNER, name="Acme"), id="shared"),
        pytest.param(lambda s: s.ensure_personal(OWNER), id="personal"),
    ],
)
async def test_a_failed_policy_baseline_leaves_no_workspace_row(
    monkeypatch, session_factory, create
) -> None:
    monkeypatch.setattr(workspaces_api, "seed_workspace", AsyncMock())
    monkeypatch.setattr(
        workspaces_api,
        "provision_default_policies",
        AsyncMock(side_effect=RuntimeError("policy store down")),
    )
    user = UserContext(user_id=OWNER, workspace_id=OWNER)

    async with session_factory() as session:
        service = workspaces_api.get_workspace_service(session, user)
        with pytest.raises(RuntimeError, match="policy store down"):
            await create(service)

    async with session_factory() as fresh:
        assert (await fresh.execute(select(Workspace.id))).scalars().all() == []
