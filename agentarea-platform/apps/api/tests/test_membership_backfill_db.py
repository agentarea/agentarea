"""Membership rows are backfilled against the real migrated schema.

The migration and the reconcile script's ``--backfill-memberships-from-graph``
write rows with hand-written SQL that relies on the unique (workspace, user)
constraint and on the invitation and outbox tables, none of which a mock has.

Set MEMBERSHIP_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from agentarea_common.events.outbox_orm import EventOutbox
from agentarea_common.workspaces.models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from agentarea_common.workspaces.repository import MEMBERSHIP_ENDED
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("MEMBERSHIP_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="MEMBERSHIP_TEST_DATABASE_URL not set"
)

_API = Path(__file__).resolve().parents[1]
_MIGRATION = _API / "alembic/versions/20260926_1000_backfill_workspace_memberships.py"
_SCRIPT = _API.parents[1] / "scripts" / "20260923_reconcile_resource_authz.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load("_membership_backfill_migration", _MIGRATION)
reconcile = _load("_reconcile_resource_authz_db", _SCRIPT)

CREATED = datetime(2026, 8, 1, 9, 0)
JOINED = datetime(2026, 9, 5, 12, 30)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


def _workspace(owner: str) -> Workspace:
    workspace_id = str(uuid4())
    return Workspace(
        id=workspace_id,
        slug=f"ws-{workspace_id}",
        name="aadocs",
        owner_user_id=owner,
        created_at=CREATED,
        updated_at=CREATED,
    )


def _invitation(
    workspace_id: str,
    *,
    status: str,
    accepted_by: str | None = None,
    accepted_at: datetime | None = None,
) -> WorkspaceInvitation:
    return WorkspaceInvitation(
        id=uuid4(),
        workspace_id=workspace_id,
        token_hash=uuid4().hex + uuid4().hex,
        invited_by="owner",
        status=status,
        expires_at=CREATED + timedelta(days=60),
        accepted_at=accepted_at,
        accepted_by_user_id=accepted_by,
        membership_granted_at=accepted_at,
        created_at=CREATED,
        updated_at=CREATED,
    )


async def _rows(session: AsyncSession, workspace_id: str) -> dict[str, WorkspaceMembership]:
    result = await session.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
    )
    return {row.user_id: row for row in result.scalars()}


async def _upgrade(session: AsyncSession) -> None:
    def run(connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    connection = await session.connection()
    await connection.run_sync(run)


async def test_every_accepted_invitation_gets_the_row_it_should_have_written(session):
    owner, member, removed, invited, recorded = (str(uuid4()) for _ in range(5))
    workspace = _workspace(owner)
    first = _invitation(
        workspace.id, status=INVITATION_STATUS_ACCEPTED, accepted_by=member, accepted_at=JOINED
    )
    session.add_all(
        [
            workspace,
            first,
            _invitation(
                workspace.id,
                status=INVITATION_STATUS_ACCEPTED,
                accepted_by=member,
                accepted_at=JOINED + timedelta(days=1),
            ),
            _invitation(
                workspace.id,
                status=INVITATION_STATUS_REVOKED,
                accepted_by=removed,
                accepted_at=JOINED,
            ),
            _invitation(workspace.id, status=INVITATION_STATUS_PENDING),
            _invitation(workspace.id, status=INVITATION_STATUS_ACCEPTED, accepted_by=invited),
            _invitation(
                workspace.id,
                status=INVITATION_STATUS_ACCEPTED,
                accepted_by=recorded,
                accepted_at=JOINED,
            ),
            WorkspaceMembership(
                workspace_id=workspace.id, user_id=recorded, created_at=CREATED, updated_at=CREATED
            ),
        ]
    )
    await session.flush()

    await _upgrade(session)
    await _upgrade(session)

    rows = await _rows(session, workspace.id)
    assert set(rows) == {member, invited, recorded}, "no owner, removed or pending rows"
    assert rows[member].created_at == JOINED
    assert rows[member].invitation_id == first.id
    assert rows[invited].created_at == CREATED, "no accepted_at: the workspace's creation"
    assert rows[recorded].created_at == CREATED, "an existing row is left as it was"


async def test_graph_backfill_writes_the_row_a_graph_member_is_missing(session):
    owner, member, invited = (str(uuid4()) for _ in range(3))
    workspace = _workspace(owner)
    invitation = _invitation(
        workspace.id, status=INVITATION_STATUS_ACCEPTED, accepted_by=invited, accepted_at=JOINED
    )
    session.add_all([workspace, invitation])
    await session.flush()

    assert await reconcile.record_membership(session, workspace.id, member, dry_run=False) == (
        "recorded"
    )
    assert await reconcile.record_membership(session, workspace.id, invited, dry_run=False) == (
        "recorded"
    )
    assert await reconcile.record_membership(session, workspace.id, member, dry_run=False) == (
        "present"
    )

    rows = await _rows(session, workspace.id)
    assert rows[member].created_at == CREATED
    assert rows[member].invitation_id is None
    assert rows[invited].created_at == JOINED
    assert rows[invited].invitation_id == invitation.id


async def test_graph_backfill_does_not_undo_a_removal_still_in_flight(session):
    owner, revoked, queued = (str(uuid4()) for _ in range(3))
    workspace = _workspace(owner)
    session.add_all(
        [
            workspace,
            _invitation(
                workspace.id,
                status=INVITATION_STATUS_REVOKED,
                accepted_by=revoked,
                accepted_at=JOINED,
            ),
            EventOutbox(
                event_id=uuid4(),
                event_type=MEMBERSHIP_ENDED,
                aggregate_id=queued,
                aggregate_type="workspace_membership",
                payload={"workspace_id": workspace.id, "user_id": queued},
                workspace_id=workspace.id,
                created_by=owner,
            ),
        ]
    )
    await session.flush()

    for user_id in (revoked, queued):
        assert (
            await reconcile.record_membership(session, workspace.id, user_id, dry_run=False)
            == "ended"
        )
    assert await _rows(session, workspace.id) == {}


async def test_a_dry_run_writes_nothing(session):
    workspace = _workspace(str(uuid4()))
    session.add(workspace)
    await session.flush()

    assert await reconcile.record_membership(session, workspace.id, "someone", dry_run=True) == (
        "recorded"
    )
    assert await _rows(session, workspace.id) == {}


async def test_the_owner_and_accepted_invitees_without_a_row_are_protected(session):
    owner, member, recorded = (str(uuid4()) for _ in range(3))
    workspace = _workspace(owner)
    session.add_all(
        [
            workspace,
            _invitation(
                workspace.id,
                status=INVITATION_STATUS_ACCEPTED,
                accepted_by=member,
                accepted_at=JOINED,
            ),
            _invitation(
                workspace.id,
                status=INVITATION_STATUS_ACCEPTED,
                accepted_by=recorded,
                accepted_at=JOINED,
            ),
            _invitation(
                workspace.id,
                status=INVITATION_STATUS_REVOKED,
                accepted_by="gone",
                accepted_at=JOINED,
            ),
            WorkspaceMembership(workspace_id=workspace.id, user_id=recorded),
        ]
    )
    await session.flush()

    assert await reconcile.load_protected(session, workspace.id) == {owner, member}
    personal = str(uuid4())
    assert await reconcile.load_protected(session, personal) == {personal}
