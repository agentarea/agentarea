"""A workspace's model specs, and so its prices, are its own.

``(provider_spec_id, model_name)`` used to be unique across all workspaces, so
the first workspace to discover a model owned the only row for it. Every later
workspace's discovery was handed that row back, its model instances pointed at
it, and whoever administered the first workspace set the price the others were
billed and budgeted against. Each workspace now writes its own row.
"""

from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_secrets.models import EncryptedSecret
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROVIDER_SPEC_ID = uuid4()


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # CI's SQLite enforces foreign keys; enforce them here too.
    event.listen(
        engine.sync_engine,
        "connect",
        lambda dbapi_connection, _record: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[
                    EncryptedSecret.__table__,
                    ProviderSpec.__table__,
                    ProviderConfig.__table__,
                    ModelSpec.__table__,
                    ModelInstance.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(
            ProviderSpec(
                id=PROVIDER_SPEC_ID,
                provider_key="openai",
                name="OpenAI",
                provider_type="openai",
                workspace_id="platform",
                created_by="test",
            )
        )
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


async def _discover(session_factory, workspace_id: str, price: float) -> ModelSpec:
    context = UserContext(user_id=f"admin-{workspace_id}", workspace_id=workspace_id)
    async with session_factory() as session:
        return await ModelSpecRepository(session, context).upsert_by_provider_and_model_kwargs(
            provider_spec_id=PROVIDER_SPEC_ID,
            model_name="gpt-5",
            display_name="GPT-5",
            context_window=8192,
            input_cost_per_token=price,
            output_cost_per_token=price,
        )


@pytest.mark.asyncio
async def test_a_second_workspace_gets_its_own_spec_not_the_first_ones(session_factory):
    first = await _discover(session_factory, "ws-a", 1e-6)
    second = await _discover(session_factory, "ws-b", 0.0)

    assert second.id != first.id
    assert second.workspace_id == "ws-b"
    assert second.input_cost_per_token == 0.0
    async with session_factory() as session:
        rows = {
            row.workspace_id: row.input_cost_per_token
            for row in (await session.execute(select(ModelSpec))).scalars()
        }
    assert rows == {"ws-a": 1e-6, "ws-b": 0.0}


@pytest.mark.asyncio
async def test_rediscovery_updates_the_workspaces_own_row(session_factory):
    first = await _discover(session_factory, "ws-a", 1e-6)
    again = await _discover(session_factory, "ws-a", 2e-6)

    assert again.id == first.id
    assert again.input_cost_per_token == 2e-6
