"""A catalog cache price reaches every workspace's copy of the model, against a real schema.

A workspace copies a catalog model's prices when it first adds it, so a cached-read or
cache-write price the catalog gained later never reached the copy, and every cached
prompt token on it was priced as a fresh one. Reconciling the catalog carries the
price into each copy whose price is unset or still the catalog's previous one; a
price a workspace set itself stays.

Needs a PostgreSQL migrated to head (``LLM_TEST_DATABASE_URL``); skips without one.
``make check-db`` wires it.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from agentarea_common.auth import UserContext
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_llm.domain.models import ModelSpec, ProviderSpec
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("LLM_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="LLM_TEST_DATABASE_URL not set; skipping schema-backed cache price tests",
)

PROVIDER_KEY = "cache-resync-test-provider"
MODEL = "cache-resync-model"
WORKSPACES = ("cache-resync-a", "cache-resync-b", "cache-resync-c")


@pytest.fixture
async def factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    made = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with made() as s:
        await _cleanup(s)
    yield made
    async with made() as s:
        await _cleanup(s)
    await engine.dispose()


async def _cleanup(s: AsyncSession) -> None:
    await s.execute(
        text("DELETE FROM model_specs WHERE workspace_id = ANY(:w)"), {"w": list(WORKSPACES)}
    )
    await s.execute(text("DELETE FROM provider_specs WHERE provider_key = :k"), {"k": PROVIDER_KEY})
    await s.commit()


async def _seed(s: AsyncSession, cached: dict[str, Decimal | None]) -> uuid.UUID:
    provider_id = uuid.uuid4()
    s.add(
        ProviderSpec(
            id=provider_id,
            provider_key=PROVIDER_KEY,
            name="Cache Resync Provider",
            provider_type="anthropic",
            workspace_id=PLATFORM_WORKSPACE_ID,
            created_by="test",
        )
    )
    await s.flush()
    for workspace, price in cached.items():
        s.add(
            ModelSpec(
                provider_spec_id=provider_id,
                model_name=MODEL,
                display_name=MODEL,
                context_window=200000,
                input_cost_per_token=Decimal("0.000003"),
                output_cost_per_token=Decimal("0.000015"),
                cached_input_cost_per_token=price,
                workspace_id=workspace,
                created_by="test",
            )
        )
    await s.commit()
    return provider_id


async def test_the_catalogs_cache_prices_reach_copies_that_never_set_their_own(factory):
    unset, stale, own = WORKSPACES
    async with factory() as s:
        provider_id = await _seed(
            s, {unset: None, stale: Decimal("0.0000004"), own: Decimal("0.0000001")}
        )
        repo = ModelSpecRepository(s, UserContext(user_id="sync", workspace_id=unset))

        changed = await repo.resync_cache_prices(
            provider_spec_id=provider_id,
            model_name=MODEL,
            previous={"cached_input_cost_per_token": "0.0000004"},
            current={
                "cached_input_cost_per_token": "0.0000003",
                "cache_creation_input_cost_per_token": "0.00000375",
            },
        )
        await s.commit()

    async with factory() as fresh:
        rows = {
            row.workspace_id: row
            for row in (
                await fresh.execute(select(ModelSpec).where(ModelSpec.model_name == MODEL))
            ).scalars()
        }

    assert rows[unset].cached_input_cost_per_token == Decimal("0.0000003")
    assert rows[stale].cached_input_cost_per_token == Decimal("0.0000003")
    assert rows[own].cached_input_cost_per_token == Decimal("0.0000001")
    assert {row.cache_creation_input_cost_per_token for row in rows.values()} == {
        Decimal("0.00000375")
    }
    assert changed == 5
