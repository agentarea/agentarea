"""Real migrated PostgreSQL coverage for tool-call approvals under concurrency.

An approval runs one call: two retries racing on it must not both run, and two
first calls racing must not leave two open requests. Only row locking on the
conditional UPDATE and the migrated partial unique index can prove that.

Set GOVERNANCE_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.application.tool_call_approvals import ToolCallApprovalService
from agentarea_governance.domain.tool_call_approvals import (
    ToolCallApprovalNotPendingError,
    ToolCallRequest,
    arguments_hash,
)
from agentarea_governance.infrastructure.tool_call_approval_repository import (
    ToolCallApprovalRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("GOVERNANCE_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="GOVERNANCE_TEST_DATABASE_URL not set"
)

INSTANCE_ID = str(uuid4())


@pytest.fixture
async def sessions():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _request() -> ToolCallRequest:
    return ToolCallRequest(
        mcp_instance_id=INSTANCE_ID,
        connector="Instantly",
        tool="create_campaign",
        policy_name="instantly__create_campaign",
        arguments={"name": "Q4"},
        reason="tool 'instantly__create_campaign' requires approval",
        approvers=[],
        client_id=None,
        client_name=None,
    )


async def _in_own_transaction(sessions, ctx: UserContext, work):
    async with sessions() as session:
        result = await work(ToolCallApprovalService(RepositoryFactory(session, ctx)), session)
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_two_concurrent_retries_run_an_approval_once(sessions):
    ctx = UserContext(user_id="alice", workspace_id=str(uuid4()))
    pending = await _in_own_transaction(sessions, ctx, lambda s, _: s.gate(_request()))
    await _in_own_transaction(
        sessions, ctx, lambda s, _: s.decide(pending.approval.id, approved=True)
    )

    async def consume(_service, session):
        return await ToolCallApprovalRepository(session, ctx).consume_approved(
            mcp_instance_id=INSTANCE_ID,
            tool="create_campaign",
            arguments_hash=arguments_hash({"name": "Q4"}),
            now=datetime.now(UTC),
        )

    results = await asyncio.gather(
        *(_in_own_transaction(sessions, ctx, consume) for _ in range(5))
    )

    assert sum(row is not None for row in results) == 1


@pytest.mark.asyncio
async def test_two_concurrent_first_calls_share_one_open_request(sessions):
    ctx = UserContext(user_id="alice", workspace_id=str(uuid4()))

    outcomes = await asyncio.gather(
        *(_in_own_transaction(sessions, ctx, lambda s, _: s.gate(_request())) for _ in range(5))
    )

    assert len({outcome.approval.id for outcome in outcomes}) == 1
    async with sessions() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM tool_call_approvals WHERE workspace_id = :ws"),
            {"ws": ctx.workspace_id},
        )
    assert count == 1


@pytest.mark.asyncio
async def test_two_concurrent_decisions_record_one(sessions):
    ctx = UserContext(user_id="alice", workspace_id=str(uuid4()))
    pending = await _in_own_transaction(sessions, ctx, lambda s, _: s.gate(_request()))

    async def decide(approved: bool):
        try:
            return await _in_own_transaction(
                sessions, ctx, lambda s, _: s.decide(pending.approval.id, approved=approved)
            )
        except ToolCallApprovalNotPendingError:
            return None

    results = await asyncio.gather(decide(True), decide(False), decide(True))

    assert sum(result is not None for result in results) == 1
