"""Approval links: a person's yes to one exact tool call a client could not wait on.

A client's call is a stateless request, so a call the policy holds for approval
cannot block until someone answers. The gate records the exact call instead, the
person decides on a page, and the client's retry with the same arguments runs
it — once.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.application.tool_call_approvals import ToolCallApprovalService
from agentarea_governance.domain.tool_call_approvals import (
    GateVerdict,
    NotAnApproverError,
    ToolCallApprovalNotFoundError,
    ToolCallApprovalNotPendingError,
    ToolCallApprovalStatus,
    ToolCallRequest,
    arguments_hash,
)
from agentarea_governance.infrastructure.orm import ToolCallApprovalORM
from agentarea_governance.infrastructure.tool_call_approval_repository import (
    ToolCallApprovalRepository,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

WORKSPACE = "ws-acme"
INSTANCE_ID = "4f1c2a9e-7b3d-4c5e-9a8b-1d2e3f4a5b6c"
ALICE = UserContext(user_id="alice", workspace_id=WORKSPACE)
BOB = UserContext(user_id="bob", workspace_id=WORKSPACE)


async def _engine(url: str = "sqlite+aiosqlite:///:memory:"):
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[ToolCallApprovalORM.__table__, AuditEventORM.__table__]
            )
        )
    return engine


@pytest.fixture
async def session():
    engine = await _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as s:
            yield s
    finally:
        await engine.dispose()


def _service(session: AsyncSession, ctx: UserContext = ALICE) -> ToolCallApprovalService:
    return ToolCallApprovalService(RepositoryFactory(session, ctx))


def _request(arguments: dict | None = None, *, approvers: list[str] | None = None):
    return ToolCallRequest(
        mcp_instance_id=INSTANCE_ID,
        connector="Instantly",
        tool="create_campaign",
        policy_name="instantly__create_campaign",
        arguments={"name": "Q4"} if arguments is None else arguments,
        reason="tool 'instantly__create_campaign' requires approval",
        approvers=approvers or [],
        client_id="client-1",
        client_name="Claude Code",
    )


async def _expire(session: AsyncSession, approval_id) -> None:
    await session.execute(
        update(ToolCallApprovalORM)
        .where(ToolCallApprovalORM.id == UUID(approval_id))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )


def test_the_arguments_hash_ignores_key_order_and_whitespace():
    assert arguments_hash({"b": 1, "a": [1, {"y": 2, "x": 1}]}) == arguments_hash(
        {"a": [1, {"x": 1, "y": 2}], "b": 1}
    )
    assert arguments_hash({"a": 1}) != arguments_hash({"a": 2})


@pytest.mark.asyncio
async def test_a_held_call_records_one_pending_approval_with_the_exact_call(session):
    outcome = await _service(session).gate(_request({"name": "Q4", "daily_limit": 50}))

    assert outcome.verdict is GateVerdict.PENDING
    approval = outcome.approval
    assert approval.status is ToolCallApprovalStatus.PENDING
    assert approval.requested_by == "alice"
    assert approval.workspace_id == WORKSPACE
    assert approval.client_id == "client-1"
    assert approval.client_name == "Claude Code"
    assert approval.mcp_instance_id == INSTANCE_ID
    assert (approval.connector, approval.tool) == ("Instantly", "create_campaign")
    assert approval.policy_name == "instantly__create_campaign"
    assert approval.arguments == {"name": "Q4", "daily_limit": 50}
    assert approval.arguments_hash == arguments_hash({"daily_limit": 50, "name": "Q4"})
    assert approval.reason == "tool 'instantly__create_campaign' requires approval"
    remaining = approval.expires_at - datetime.now(UTC)
    assert timedelta(hours=23, minutes=59) < remaining <= timedelta(hours=24)


@pytest.mark.asyncio
async def test_a_retry_while_pending_returns_the_same_approval(session):
    first = await _service(session).gate(_request())
    second = await _service(session).gate(_request())

    assert second.verdict is GateVerdict.PENDING
    assert second.approval.id == first.approval.id
    rows = (await session.scalars(select(ToolCallApprovalORM))).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_an_approved_call_runs_once_and_the_next_needs_a_new_approval(session):
    pending = (await _service(session).gate(_request())).approval
    decided = await _service(session, BOB).decide(pending.id, approved=True, comment="ok")
    assert decided.status is ToolCallApprovalStatus.APPROVED
    assert decided.decided_by == "bob"
    remaining = decided.expires_at - datetime.now(UTC)
    assert timedelta(minutes=59) < remaining <= timedelta(hours=1)

    ran = await _service(session).gate(_request())
    assert ran.verdict is GateVerdict.RUN
    assert ran.approval.id == pending.id
    assert ran.approval.status is ToolCallApprovalStatus.CONSUMED

    again = await _service(session).gate(_request())
    assert again.verdict is GateVerdict.PENDING
    assert again.approval.id != pending.id


@pytest.mark.asyncio
async def test_changed_arguments_do_not_match_an_approval(session):
    pending = (await _service(session).gate(_request({"name": "Q4"}))).approval
    await _service(session, BOB).decide(pending.id, approved=True)

    other = await _service(session).gate(_request({"name": "Q5"}))

    assert other.verdict is GateVerdict.PENDING
    assert other.approval.id != pending.id


@pytest.mark.asyncio
async def test_another_user_does_not_match_an_approval(session):
    pending = (await _service(session).gate(_request())).approval
    await _service(session, BOB).decide(pending.id, approved=True)

    bobs = await _service(session, BOB).gate(_request())

    assert bobs.verdict is GateVerdict.PENDING
    assert bobs.approval.id != pending.id
    assert bobs.approval.requested_by == "bob"


@pytest.mark.asyncio
async def test_an_expired_approval_does_not_run(session):
    pending = (await _service(session).gate(_request())).approval
    await _service(session, BOB).decide(pending.id, approved=True)
    await _expire(session, pending.id)

    retry = await _service(session).gate(_request())

    assert retry.verdict is GateVerdict.PENDING
    assert retry.approval.id != pending.id
    lapsed = await _service(session).get(pending.id)
    assert lapsed is not None
    assert lapsed.status is ToolCallApprovalStatus.EXPIRED


@pytest.mark.asyncio
async def test_an_expired_pending_approval_is_replaced(session):
    pending = (await _service(session).gate(_request())).approval
    await _expire(session, pending.id)

    retry = await _service(session).gate(_request())

    assert retry.verdict is GateVerdict.PENDING
    assert retry.approval.id != pending.id


@pytest.mark.asyncio
async def test_a_rejected_call_stays_rejected_until_the_arguments_change(session):
    pending = (await _service(session).gate(_request())).approval
    await _service(session, BOB).decide(pending.id, approved=False, comment="wrong list")

    retry = await _service(session).gate(_request())
    assert retry.verdict is GateVerdict.REJECTED
    assert retry.approval.id == pending.id
    assert retry.approval.comment == "wrong list"
    assert len((await session.scalars(select(ToolCallApprovalORM))).all()) == 1

    changed = await _service(session).gate(_request({"name": "Q4 fixed"}))
    assert changed.verdict is GateVerdict.PENDING


@pytest.mark.asyncio
async def test_only_a_named_approver_may_decide(session):
    pending = (await _service(session).gate(_request(approvers=["user:carol"]))).approval

    with pytest.raises(NotAnApproverError):
        await _service(session, BOB).decide(pending.id, approved=True)

    carol = UserContext(user_id="carol", workspace_id=WORKSPACE)
    decided = await _service(session, carol).decide(pending.id, approved=True)
    assert decided.status is ToolCallApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_with_no_approvers_named_the_requester_may_approve_their_own_call(session):
    pending = (await _service(session).gate(_request())).approval

    decided = await _service(session).decide(pending.id, approved=True)

    assert decided.decided_by == "alice"
    assert _service(session).may_decide(decided, "anyone")


@pytest.mark.asyncio
async def test_only_a_pending_unexpired_approval_can_be_decided(session):
    pending = (await _service(session).gate(_request())).approval
    await _service(session).decide(pending.id, approved=True)
    with pytest.raises(ToolCallApprovalNotPendingError):
        await _service(session).decide(pending.id, approved=False)

    stale = (await _service(session).gate(_request({"name": "other"}))).approval
    await _expire(session, stale.id)
    with pytest.raises(ToolCallApprovalNotPendingError):
        await _service(session).decide(stale.id, approved=True)

    with pytest.raises(ToolCallApprovalNotFoundError):
        await _service(session).decide("00000000-0000-0000-0000-000000000000", approved=True)


@pytest.mark.asyncio
async def test_a_decision_is_audited(session):
    pending = (await _service(session).gate(_request())).approval
    await _service(session, BOB).decide(pending.id, approved=False, comment="no")

    [event] = (
        await session.scalars(
            select(AuditEventORM).where(AuditEventORM.resource_type == "tool_call_approval")
        )
    ).all()
    assert event.action == "tool_call_approval.rejected"
    assert event.resource_id == str(pending.id)
    assert event.actor_id == "bob"
    assert event.event_metadata["tool"] == "create_campaign"
    assert event.event_metadata["requested_by"] == "alice"


@pytest.mark.asyncio
async def test_approvals_are_listed_by_status_within_the_workspace(session):
    first = (await _service(session).gate(_request({"n": 1}))).approval
    await _service(session).gate(_request({"n": 2}))
    await _service(session).decide(first.id, approved=False)
    other_ws = UserContext(user_id="alice", workspace_id="ws-other")
    await _service(session, other_ws).gate(_request({"n": 3}))

    pending, total = await _service(session).list(status=ToolCallApprovalStatus.PENDING)

    assert total == 1
    assert [a.arguments for a in pending] == [{"n": 2}]
    _, total_all = await _service(session).list()
    assert total_all == 2
    assert await _service(session, other_ws).get(first.id) is None


@pytest.mark.asyncio
async def test_two_concurrent_retries_consume_an_approval_once(tmp_path):
    engine = await _engine(f"sqlite+aiosqlite:///{tmp_path / 'approvals.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with sessions() as s:
            pending = (await _service(s).gate(_request())).approval
            await _service(s).decide(pending.id, approved=True)
            await s.commit()

        async def consume():
            async with sessions() as s:
                row = await ToolCallApprovalRepository(s, ALICE).consume_approved(
                    mcp_instance_id=INSTANCE_ID,
                    tool="create_campaign",
                    arguments_hash=arguments_hash({"name": "Q4"}),
                    now=datetime.now(UTC),
                )
                await s.commit()
                return row

        results = await asyncio.gather(consume(), consume())
        assert sum(row is not None for row in results) == 1
    finally:
        await engine.dispose()
