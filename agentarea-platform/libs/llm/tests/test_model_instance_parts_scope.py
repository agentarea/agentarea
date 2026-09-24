"""A model instance may only combine parts its own workspace can use.

The price a run is billed at is read from the instance's model spec. A member
who administers a second workspace can write a zero-price spec there, and
creating an instance was member-level with ``model_spec_id`` stored unchecked,
so an instance in the first workspace could point at that spec and run for $0.
The spec must be the workspace's own or the platform's; the provider config
must be the workspace's own or platform-managed.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.constants import MANAGED_BY_PLATFORM, PLATFORM_WORKSPACE_ID
from agentarea_common.exceptions.errors import NotFoundError
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

WORKSPACE = "ws-billed"
OTHER = "ws-attacker-owned"


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[
                    ProviderSpec.__table__,
                    ProviderConfig.__table__,
                    ModelSpec.__table__,
                    ModelInstance.__table__,
                ],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


@pytest.fixture
async def rows(session_factory):
    provider_spec_id = uuid4()
    ids = {
        "own_config": uuid4(),
        "other_config": uuid4(),
        "platform_config": uuid4(),
        "own_spec": uuid4(),
        "other_spec": uuid4(),
        "platform_spec": uuid4(),
    }
    async with session_factory() as session:
        session.add(
            ProviderSpec(
                id=provider_spec_id,
                provider_key="openai",
                name="OpenAI",
                provider_type="openai",
                workspace_id=PLATFORM_WORKSPACE_ID,
                created_by="test",
            )
        )
        for key, workspace_id, managed_by in (
            ("own_config", WORKSPACE, None),
            ("other_config", OTHER, None),
            ("platform_config", PLATFORM_WORKSPACE_ID, MANAGED_BY_PLATFORM),
        ):
            session.add(
                ProviderConfig(
                    id=ids[key],
                    provider_spec_id=provider_spec_id,
                    name=key,
                    managed_by=managed_by,
                    workspace_id=workspace_id,
                    created_by="test",
                )
            )
        for key, workspace_id, price in (
            ("own_spec", WORKSPACE, 1e-5),
            ("other_spec", OTHER, 0.0),
            ("platform_spec", PLATFORM_WORKSPACE_ID, 2e-5),
        ):
            session.add(
                ModelSpec(
                    id=ids[key],
                    provider_spec_id=provider_spec_id,
                    model_name=f"gpt-{key}",
                    display_name=key,
                    context_window=8192,
                    input_cost_per_token=price,
                    output_cost_per_token=price,
                    workspace_id=workspace_id,
                    created_by="test",
                )
            )
        await session.commit()
    return ids


async def _create(session_factory, provider_config_id: UUID, model_spec_id: UUID):
    context = UserContext(user_id="member", workspace_id=WORKSPACE)
    async with session_factory() as session:
        service = ProviderService(
            provider_spec_repo=ProviderSpecRepository(session, context),
            provider_config_repo=ProviderConfigRepository(session, context),
            model_spec_repo=ModelSpecRepository(session, context),
            model_instance_repo=ModelInstanceRepository(session, context),
            event_broker=AsyncMock(),
            secret_manager=MagicMock(),
        )
        return await service.create_model_instance(
            provider_config_id=provider_config_id,
            model_spec_id=model_spec_id,
            name="instance",
        )


async def _instance_count(session_factory) -> int:
    async with session_factory() as session:
        return len((await session.execute(select(ModelInstance))).scalars().all())


@pytest.mark.asyncio
async def test_a_spec_from_another_workspace_is_not_found(session_factory, rows):
    with pytest.raises(NotFoundError):
        await _create(session_factory, rows["own_config"], rows["other_spec"])
    assert await _instance_count(session_factory) == 0


@pytest.mark.asyncio
async def test_a_config_from_another_workspace_is_not_found(session_factory, rows):
    with pytest.raises(NotFoundError):
        await _create(session_factory, rows["other_config"], rows["own_spec"])
    assert await _instance_count(session_factory) == 0


@pytest.mark.asyncio
async def test_own_config_and_own_spec_are_accepted(session_factory, rows):
    instance = await _create(session_factory, rows["own_config"], rows["own_spec"])
    assert instance.workspace_id == WORKSPACE
    assert str(instance.model_spec_id) == str(rows["own_spec"])


@pytest.mark.asyncio
async def test_platform_spec_and_platform_config_are_accepted(session_factory, rows):
    instance = await _create(session_factory, rows["platform_config"], rows["platform_spec"])
    assert str(instance.model_spec_id) == str(rows["platform_spec"])
    assert str(instance.provider_config_id) == str(rows["platform_config"])


def test_runtime_names_a_part_the_instance_workspace_cannot_use():
    own_config = ProviderConfig(workspace_id=WORKSPACE, managed_by=None)
    platform_config = ProviderConfig(
        workspace_id=PLATFORM_WORKSPACE_ID, managed_by=MANAGED_BY_PLATFORM
    )
    other_config = ProviderConfig(workspace_id=OTHER, managed_by=None)
    own_spec = ModelSpec(workspace_id=WORKSPACE)
    platform_spec = ModelSpec(workspace_id=PLATFORM_WORKSPACE_ID)
    other_spec = ModelSpec(workspace_id=OTHER)

    def instance(config, spec):
        return ModelInstance(workspace_id=WORKSPACE, provider_config=config, model_spec=spec)

    assert instance(own_config, own_spec).foreign_part() is None
    assert instance(platform_config, platform_spec).foreign_part() is None
    assert instance(own_config, other_spec).foreign_part() == "model_spec"
    assert instance(other_config, own_spec).foreign_part() == "provider_config"
