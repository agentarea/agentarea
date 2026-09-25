"""One settled payment per idempotency key, against a real schema.

The rule is a partial unique index on ``payment_records``: a retried tool activity
may leave any number of failed attempts under a key, but at most one completed
payment. Mocked repositories have no indexes, so only a migrated database can
show it holds.

Needs a PostgreSQL migrated to head; skips without one:

    WALLET_TEST_DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/agentarea_test
"""

import os
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_common.auth import UserContext
from agentarea_wallet.application.wallet_service import WalletService
from agentarea_wallet.domain.models import AgentWallet
from agentarea_wallet.infrastructure.repository import PaymentRecordRepository, WalletRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("WALLET_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="WALLET_TEST_DATABASE_URL not set; skipping schema-backed payment idempotency tests",
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def wallet_setup(session: AsyncSession):
    workspace_id = f"wallet-idem-{uuid.uuid4().hex[:8]}"
    user_context = UserContext(user_id="wallet-idem-user", workspace_id=workspace_id)
    agent = Agent(
        workspace_id=workspace_id,
        created_by=user_context.user_id,
        name="Paid researcher",
        slug=f"paid-researcher-{uuid.uuid4().hex[:8]}",
    )
    session.add(agent)
    await session.flush()
    wallet = AgentWallet(
        workspace_id=workspace_id,
        created_by=user_context.user_id,
        agent_id=agent.id,
        wallet_type="x402",
    )
    session.add(wallet)
    await session.commit()
    service = WalletService(
        wallet_repository=WalletRepository(session, user_context),
        payment_repository=PaymentRecordRepository(session, user_context),
        secret_manager=AsyncMock(),
    )
    # Ids rather than instances: the rejected insert rolls the session back, which
    # expires every loaded object, and the async driver cannot lazily refresh one.
    return service, wallet.id, str(agent.id)


async def _record(service: WalletService, wallet_id, agent_id: str, key: str, status: str):
    return await service.record_payment(
        wallet_id=wallet_id,
        agent_id=agent_id,
        execution_id="exec-1",
        protocol="x402",
        amount_usd=0.25,
        recipient="0xrecipient",
        tx_hash="0xsettled" if status == "completed" else None,
        tool_name="paid_search",
        tool_call_id="call_1",
        idempotency_key=key,
        status=status,
    )


@pytest.mark.asyncio
async def test_failed_attempts_then_one_settlement_per_key(wallet_setup):
    service, wallet_id, agent_id = wallet_setup
    key = uuid.uuid4().hex

    await _record(service, wallet_id, agent_id, key, "failed")
    await _record(service, wallet_id, agent_id, key, "failed")
    assert await service.find_settled_payment(key) is None

    settled = await _record(service, wallet_id, agent_id, key, "completed")
    found = await service.find_settled_payment(key)
    assert found is not None
    assert found.id == settled.id
    assert found.tx_hash == "0xsettled"


@pytest.mark.asyncio
async def test_second_settlement_under_the_same_key_is_rejected(wallet_setup):
    service, wallet_id, agent_id = wallet_setup
    key = uuid.uuid4().hex
    await _record(service, wallet_id, agent_id, key, "completed")

    with pytest.raises(IntegrityError, match="uq_payment_records_settled_idempotency_key"):
        await _record(service, wallet_id, agent_id, key, "completed")

    await _record(service, wallet_id, agent_id, uuid.uuid4().hex, "completed")
