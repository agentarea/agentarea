"""A built-in model from the catalog can be added to a workspace, against a real schema.

Built-in model specs live in the registry catalog (ADR-003) and the model-spec
list offers them under their registry-item id. ``model_instances.model_spec_id``
references ``model_specs``, so an instance cannot point at a catalog item: adding
one used to answer 404 (or 409 from the foreign key before that), and every
built-in model was un-addable. Adding one now copies the catalog values into the
workspace's own spec row and points the instance at it.

Needs a PostgreSQL migrated to head (``LLM_TEST_DATABASE_URL``); skips without one.
``make check-db`` wires it.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_common.auth import UserContext
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_common.exceptions.errors import NotFoundError
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import (
    ModelPricingNotConfiguredError,
    ModelSpecRepository,
)
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("LLM_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="LLM_TEST_DATABASE_URL not set; skipping schema-backed catalog model tests",
)

TENANT = "catalog-instance-test-ws"
PROVIDER_KEY = "catalog-instance-test-openai"
MODEL_NAME = "catalog-test-model"
REGISTRY_NAMES = (
    "catalog-instance-test-a",
    "catalog-instance-test-b",
    "catalog-instance-test-c",
)
CATALOG_SPEC = {
    "provider_key": PROVIDER_KEY,
    "model_name": MODEL_NAME,
    "context_window": 128000,
    "max_output_tokens": 16384,
    "input_cost_per_token": "0.0000025",
    "output_cost_per_token": "0.00001",
    "supports_function_calling": True,
}


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await _cleanup(s)
    yield factory
    async with factory() as s:
        await _cleanup(s)
    await engine.dispose()


async def _cleanup(s: AsyncSession) -> None:
    for table in ("model_instances", "model_specs", "provider_configs"):
        await s.execute(text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": TENANT})
    await s.execute(text("DELETE FROM registries WHERE name = ANY(:n)"), {"n": list(REGISTRY_NAMES)})
    await s.execute(text("DELETE FROM provider_specs WHERE provider_key = :k"), {"k": PROVIDER_KEY})
    await s.commit()


async def _add_catalog_item(
    s: AsyncSession,
    registry_name: str,
    *,
    name: str = "Catalog Test Model",
    priority: int = 100,
    active: bool = True,
    spec: dict | None = None,
) -> uuid.UUID:
    registry_id, item_id = uuid.uuid4(), uuid.uuid4()
    await s.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "recommendation_priority, is_active) "
            "VALUES (:id, :name, 'llm_models', 'git', 'https://example.invalid/catalog', "
            ":priority, :active)"
        ),
        {"id": registry_id, "name": registry_name, "priority": priority, "active": active},
    )
    item_spec = spec or CATALOG_SPEC
    await s.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, spec, "
            "registry_type, registry_priority, registry_active) "
            "VALUES (:id, :rid, :ext, :name, CAST(:spec AS jsonb), "
            "'llm_models', :priority, :active)"
        ),
        {
            "id": item_id,
            "rid": registry_id,
            "ext": f"{PROVIDER_KEY}/{item_spec['model_name']}",
            "name": name,
            "spec": json.dumps(item_spec),
            "priority": priority,
            "active": active,
        },
    )
    await s.commit()
    return item_id


@pytest.fixture
async def rows(session_factory) -> dict[str, uuid.UUID]:
    provider_spec_id, config_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as s:
        s.add(
            ProviderSpec(
                id=provider_spec_id,
                provider_key=PROVIDER_KEY,
                name="Catalog Test Provider",
                provider_type="openai",
                workspace_id=PLATFORM_WORKSPACE_ID,
                created_by="test",
            )
        )
        await s.flush()
        s.add(
            ProviderConfig(
                id=config_id,
                provider_spec_id=provider_spec_id,
                name="tenant key",
                workspace_id=TENANT,
                created_by="test",
            )
        )
        await s.commit()
        item_id = await _add_catalog_item(s, REGISTRY_NAMES[0])
    return {"provider_spec": provider_spec_id, "config": config_id, "item": item_id}


def _service(session: AsyncSession) -> ProviderService:
    context = UserContext(user_id="member", workspace_id=TENANT)
    return ProviderService(
        provider_spec_repo=ProviderSpecRepository(session, context),
        provider_config_repo=ProviderConfigRepository(session, context),
        model_spec_repo=ModelSpecRepository(session, context),
        model_instance_repo=ModelInstanceRepository(session, context),
        event_broker=AsyncMock(),
        secret_manager=MagicMock(),
    )


async def _create(session_factory, config_id: uuid.UUID, model_spec_id: uuid.UUID):
    async with session_factory() as s:
        return await _service(s).create_model_instance(
            provider_config_id=config_id, model_spec_id=model_spec_id, name="instance"
        )


async def _tenant_specs(session_factory) -> list[ModelSpec]:
    async with session_factory() as s:
        result = await s.execute(select(ModelSpec).where(ModelSpec.workspace_id == TENANT))
        return list(result.scalars().all())


async def _listed(session_factory, provider_spec_id: uuid.UUID) -> list[ModelSpec]:
    async with session_factory() as s:
        return await _service(s).model_spec_repo.list_specs(provider_spec_id=provider_spec_id)


async def test_a_catalog_spec_becomes_the_workspaces_own_spec(session_factory, rows):
    instance = await _create(session_factory, rows["config"], rows["item"])

    [spec] = await _tenant_specs(session_factory)
    assert str(instance.model_spec_id) == str(spec.id)
    assert spec.id != rows["item"]
    assert str(spec.provider_spec_id) == str(rows["provider_spec"])
    assert spec.model_name == MODEL_NAME
    assert spec.context_window == 128000
    assert spec.max_output_tokens == 16384
    assert spec.input_cost_per_token == Decimal("0.0000025")
    assert spec.output_cost_per_token == Decimal("0.00001")
    assert spec.supports_function_calling is True


async def test_a_second_instance_reuses_the_workspace_spec(session_factory, rows):
    first = await _create(session_factory, rows["config"], rows["item"])
    second = await _create(session_factory, rows["config"], rows["item"])

    assert first.id != second.id
    assert str(first.model_spec_id) == str(second.model_spec_id)
    assert len(await _tenant_specs(session_factory)) == 1


async def _add_own_spec(session_factory, provider_spec_id: uuid.UUID) -> ModelSpec:
    async with session_factory() as s:
        own = ModelSpec(
            id=uuid.uuid4(),
            provider_spec_id=provider_spec_id,
            model_name=MODEL_NAME,
            display_name="Negotiated",
            context_window=64000,
            input_cost_per_token=Decimal("0.000001"),
            output_cost_per_token=Decimal("0.000002"),
            workspace_id=TENANT,
            created_by="admin",
        )
        s.add(own)
        await s.commit()
    return own


async def test_a_workspace_price_is_kept_not_reset_to_the_catalogs(session_factory, rows):
    own = await _add_own_spec(session_factory, rows["provider_spec"])

    instance = await _create(session_factory, rows["config"], rows["item"])

    [spec] = await _tenant_specs(session_factory)
    assert str(instance.model_spec_id) == str(own.id)
    assert spec.input_cost_per_token == Decimal("0.000001")
    assert spec.display_name == "Negotiated"


async def test_the_workspace_spec_hides_the_catalog_entry_for_its_model(session_factory, rows):
    before = await _listed(session_factory, rows["provider_spec"])
    assert [str(s.id) for s in before] == [str(rows["item"])]
    assert getattr(before[0], "is_catalog", False) is True

    own = await _add_own_spec(session_factory, rows["provider_spec"])

    after = await _listed(session_factory, rows["provider_spec"])
    assert [str(s.id) for s in after] == [str(own.id)]


async def test_a_model_in_two_catalog_registries_is_listed_once(session_factory, rows):
    async with session_factory() as s:
        await _add_catalog_item(s, REGISTRY_NAMES[1])

    listed = await _listed(session_factory, rows["provider_spec"])
    assert [s.model_name for s in listed] == [MODEL_NAME]


async def test_an_unknown_spec_id_is_not_found(session_factory, rows):
    with pytest.raises(NotFoundError):
        await _create(session_factory, rows["config"], uuid.uuid4())

    assert await _tenant_specs(session_factory) == []
    async with session_factory() as s:
        count = await s.execute(select(ModelInstance).where(ModelInstance.workspace_id == TENANT))
        assert count.scalars().all() == []


PREFERRED_SPEC = {
    **CATALOG_SPEC,
    "input_cost_per_token": "0.000003",
    "output_cost_per_token": "0.000015",
}


async def test_the_preferred_registrys_copy_of_a_model_is_the_one_listed(session_factory, rows):
    async with session_factory() as s:
        preferred = await _add_catalog_item(
            s, REGISTRY_NAMES[1], name="Zz Preferred", priority=10, spec=PREFERRED_SPEC
        )

    listed = await _listed(session_factory, rows["provider_spec"])

    assert [str(s.id) for s in listed] == [str(preferred)]
    assert listed[0].input_cost_per_token == Decimal("0.000003")


async def test_a_hidden_duplicates_id_adds_the_preferred_registrys_price(session_factory, rows):
    async with session_factory() as s:
        await _add_catalog_item(
            s, REGISTRY_NAMES[1], name="Zz Preferred", priority=10, spec=PREFERRED_SPEC
        )

    await _create(session_factory, rows["config"], rows["item"])

    [spec] = await _tenant_specs(session_factory)
    assert spec.input_cost_per_token == Decimal("0.000003")
    assert spec.output_cost_per_token == Decimal("0.000015")
    assert spec.display_name == "Zz Preferred"


async def test_an_inactive_registrys_model_is_neither_listed_nor_addable(session_factory, rows):
    async with session_factory() as s:
        hidden = await _add_catalog_item(
            s,
            REGISTRY_NAMES[1],
            active=False,
            spec={**CATALOG_SPEC, "model_name": "catalog-test-inactive"},
        )

    listed = await _listed(session_factory, rows["provider_spec"])
    assert str(hidden) not in {str(s.id) for s in listed}

    with pytest.raises(NotFoundError):
        await _create(session_factory, rows["config"], hidden)
    assert await _tenant_specs(session_factory) == []


async def test_a_model_without_a_price_is_neither_listed_nor_addable(session_factory, rows):
    unpriced_spec = {**CATALOG_SPEC, "model_name": "catalog-test-unpriced"}
    del unpriced_spec["output_cost_per_token"]
    async with session_factory() as s:
        unpriced = await _add_catalog_item(s, REGISTRY_NAMES[1], spec=unpriced_spec)

    listed = await _listed(session_factory, rows["provider_spec"])
    assert [str(s.id) for s in listed] == [str(rows["item"])]

    with pytest.raises(ModelPricingNotConfiguredError) as raised:
        await _create(session_factory, rows["config"], unpriced)
    assert raised.value.status_code == 422
    assert await _tenant_specs(session_factory) == []


async def _wait_until_blocked_on_a_lock(session_factory) -> None:
    for _ in range(100):
        async with session_factory() as s:
            waiting = await s.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            )
            if waiting.scalar():
                return
        await asyncio.sleep(0.05)
    raise AssertionError("the concurrent add never reached the insert")


async def test_a_concurrent_first_add_reuses_the_row_the_other_add_committed(
    session_factory, rows
):
    async with session_factory() as winner:
        own = ModelSpec(
            id=uuid.uuid4(),
            provider_spec_id=rows["provider_spec"],
            model_name=MODEL_NAME,
            display_name="Won the race",
            context_window=128000,
            input_cost_per_token=Decimal("0.0000025"),
            output_cost_per_token=Decimal("0.00001"),
            workspace_id=TENANT,
            created_by="admin",
        )
        winner.add(own)
        await winner.flush()

        loser = asyncio.create_task(_create(session_factory, rows["config"], rows["item"]))
        await _wait_until_blocked_on_a_lock(session_factory)
        await winner.commit()
        instance = await loser

    [spec] = await _tenant_specs(session_factory)
    assert str(spec.id) == str(own.id)
    assert str(instance.model_spec_id) == str(own.id)
