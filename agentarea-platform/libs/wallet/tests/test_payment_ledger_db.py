"""The wallet ledger counts every payment that settled, against a real schema.

A paid request can settle with the provider and still fail afterwards: the retry
returns an error, but the settlement receipt says the money left the wallet. That
payment must reduce the service budget and must stop a retry from paying again.

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
from agentarea_wallet.domain.enums import settlement_status
from agentarea_wallet.domain.models import AgentWallet
from agentarea_wallet.infrastructure.repository import PaymentRecordRepository, WalletRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("WALLET_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="WALLET_TEST_DATABASE_URL not set; skipping schema-backed wallet ledger tests",
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture(params=["execution", "monthly"])
async def wallet_setup(request, session: AsyncSession):
    workspace_id = f"wallet-ledger-{uuid.uuid4().hex[:8]}"
    user_context = UserContext(user_id="wallet-ledger-user", workspace_id=workspace_id)
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
        service_budget_usd=1.0,
        service_budget_period=request.param,
    )
    session.add(wallet)
    await session.commit()
    service = WalletService(
        wallet_repository=WalletRepository(session, user_context),
        payment_repository=PaymentRecordRepository(session, user_context),
        secret_manager=AsyncMock(),
    )
    return service, wallet.id, str(agent.id)


async def _record(
    service: WalletService,
    wallet_id,
    agent_id: str,
    key: str,
    *,
    request_succeeded: bool,
    tx_hash: str | None,
    error: str | None = None,
):
    return await service.record_payment(
        wallet_id=wallet_id,
        agent_id=agent_id,
        execution_id="exec-1",
        protocol="x402",
        amount_usd=0.25,
        recipient="0xrecipient",
        tx_hash=tx_hash,
        tool_name="paid_search",
        tool_call_id="call_1",
        idempotency_key=key,
        status=settlement_status(request_succeeded=request_succeeded, tx_hash=tx_hash),
        error_message=error,
    )


@pytest.mark.asyncio
async def test_settled_payment_whose_retry_failed_reduces_the_budget(wallet_setup):
    service, wallet_id, agent_id = wallet_setup
    key = uuid.uuid4().hex

    await _record(
        service,
        wallet_id,
        agent_id,
        key,
        request_succeeded=False,
        tx_hash="0xsettled",
        error="Payment retry failed: 500",
    )

    assert await service.get_service_budget_remaining(agent_id, "exec-1") == pytest.approx(0.75)
    assert await service.get_total_spent_current_period(agent_id) == pytest.approx(0.25)
    settled = await service.find_settled_payment(key)
    assert settled is not None
    assert settled.tx_hash == "0xsettled"


@pytest.mark.asyncio
async def test_payment_that_never_settled_leaves_the_budget(wallet_setup):
    service, wallet_id, agent_id = wallet_setup
    key = uuid.uuid4().hex

    await _record(
        service,
        wallet_id,
        agent_id,
        key,
        request_succeeded=False,
        tx_hash=None,
        error="Payment retry failed: 402",
    )

    assert await service.get_service_budget_remaining(agent_id, "exec-1") == pytest.approx(1.0)
    assert await service.find_settled_payment(key) is None

