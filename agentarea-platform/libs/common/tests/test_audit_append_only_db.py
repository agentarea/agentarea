"""The append-only rule on `audit_events`, against a real schema.

`AuditEventORM` has always documented itself as append-only and `AuditRepository`
only ever inserts, but neither statement binds anything: until the trigger added
in 20260915_1400 the application role could rewrite or erase its own audit trail,
which is the first property an auditor asks us to demonstrate.

The rule lives in a database trigger, so only a migrated database can check it.
A `REVOKE` would not substitute for it: production connects as the table's owner
and could re-grant itself the privilege, and this suite runs as `postgres`, a
superuser, which ignores grants altogether — so a grant-based rule would look
enforced here while binding nothing anywhere.

Needs a PostgreSQL migrated to head; skips without one:

    AUDIT_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agentarea_test
"""

import os
from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from agentarea_common.audit.models import AuditEventORM
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("AUDIT_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="AUDIT_TEST_DATABASE_URL not set; skipping schema-backed audit tests",
)

WORKSPACE = "audit-append-only-test-ws"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    # No pool_pre_ping: every test here deliberately provokes a database error,
    # and re-checking out the invalidated connection pings outside the greenlet
    # context the async driver needs.
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    # No teardown: deleting these rows is the very thing under test. They are
    # scoped to a test workspace and the gate's database is thrown away.
    await engine.dispose()


async def _insert_event(session: AsyncSession) -> UUID:
    """Insert one event and return its id.

    The id rather than the instance: ``rollback`` expires every object in the
    session, so reading an attribute afterwards would fire a synchronous
    refresh and fail on the async driver before the assertion is reached.
    """
    event_id = uuid4()
    event = AuditEventORM(
        id=event_id,
        actor_id="tester",
        actor_type="user",
        workspace_id=WORKSPACE,
        action="agent.create",
        resource_type="agent",
        resource_id=str(uuid4()),
        event_metadata={},
    )
    session.add(event)
    await session.commit()
    return event_id


async def _stored_action(session: AsyncSession, event_id) -> str | None:
    """Read the row back from the database.

    Deliberately not ``session.get``: the identity map would answer from the
    copy this test already holds, so a row the trigger failed to protect would
    still look untouched.
    """
    result = await session.execute(
        text("SELECT action FROM audit_events WHERE id = :id"), {"id": event_id}
    )
    return result.scalar_one_or_none()


async def test_insert_is_allowed(session: AsyncSession):
    event_id = await _insert_event(session)

    assert await _stored_action(session, event_id) == "agent.create"


async def test_update_is_refused(session: AsyncSession):
    event_id = await _insert_event(session)

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(
            text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"),
            {"id": event_id},
        )
    await session.rollback()

    assert await _stored_action(session, event_id) == "agent.create"


async def test_delete_is_refused(session: AsyncSession):
    event_id = await _insert_event(session)

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": event_id})
    await session.rollback()

    assert await _stored_action(session, event_id) == "agent.create"


async def test_mutation_matching_no_rows_is_still_refused(session: AsyncSession):
    """The trigger fires per statement, not per row.

    A row-level trigger would let `UPDATE audit_events SET ... WHERE false`
    report success, which reads as "the table accepts updates" to anyone
    probing it and leaves the guarantee resting on which rows happened to match.
    """
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(text("UPDATE audit_events SET action = 'x' WHERE false"))
    await session.rollback()
