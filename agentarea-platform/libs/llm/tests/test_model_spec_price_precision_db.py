"""Per-token prices survive the database exactly, against a real schema.

A price is a fraction of a cent per token and a run bills it by the million, so
a column that rounds it to the nearest binary float bills a different amount
than the one configured.

Needs a PostgreSQL migrated to head; skips without one:

    LLM_TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:55441/agentarea_test
"""

import os
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from agentarea_llm.domain.models import ModelSpec, ProviderSpec
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("LLM_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="LLM_TEST_DATABASE_URL not set; skipping schema-backed model price tests",
)

WORKSPACE = "model-price-precision-test-ws"


@pytest.fixture
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM provider_specs WHERE workspace_id = :w"), {"w": WORKSPACE}
        )
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest.mark.asyncio
async def test_price_columns_are_numeric(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT column_name, data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns WHERE table_name = 'model_specs' "
                "AND column_name IN ('input_cost_per_token', 'output_cost_per_token')"
            )
        )
    ).all()

    assert sorted(tuple(r) for r in rows) == [
        ("input_cost_per_token", "numeric", 20, 12),
        ("output_cost_per_token", "numeric", 20, 12),
    ]


@pytest.mark.asyncio
async def test_a_nano_dollar_price_bills_a_million_tokens_exactly(engine, session) -> None:
    provider = ProviderSpec(
        id=uuid.uuid4(),
        provider_key=f"k-{uuid.uuid4().hex[:8]}",
        name="Precise provider",
        provider_type="openai",
        is_builtin=False,
        workspace_id=WORKSPACE,
        created_by="tester",
    )
    session.add(provider)
    await session.flush()
    spec = ModelSpec(
        provider_spec_id=provider.id,
        model_name="nano-priced",
        display_name="Nano priced",
        context_window=8192,
        input_cost_per_token=Decimal("0.000000001"),
        output_cost_per_token=Decimal("0.000000123456"),
        workspace_id=WORKSPACE,
        created_by="tester",
    )
    session.add(spec)
    await session.commit()

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as fresh:
        stored = (
            await fresh.execute(select(ModelSpec).where(ModelSpec.id == spec.id))
        ).scalar_one()

    assert isinstance(stored.input_cost_per_token, Decimal)
    assert stored.input_cost_per_token * 1_000_000 == Decimal("0.001")
    assert stored.output_cost_per_token * 1_000_000 == Decimal("0.123456")
