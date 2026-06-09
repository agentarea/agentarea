"""Tests for the reified Workspace entity (Step 1: workspace as a table).

These cover the foundation that the workspace switcher (Step 2) builds on:
- personal workspaces are real rows, provisioned idempotently, with
  ``id == user_id`` so existing data needs no backfill;
- shared workspaces get a generated id plus an owner membership;
- listing returns a user's personal workspace and every workspace they
  joined via membership.

The fixtures here intentionally create *only* the workspace tables on an
in-memory SQLite engine rather than the shared ``db_session`` fixture,
which calls ``BaseModel.metadata.create_all`` and currently fails on
SQLite because unrelated models use ``JSONB``.
"""

import pytest
import pytest_asyncio
from agentarea_common.workspaces.models import (
    WORKSPACE_TYPE_PERSONAL,
    WORKSPACE_TYPE_SHARED,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from agentarea_common.workspaces.repository import (
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from agentarea_common.workspaces.service import WorkspaceService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        for table in (
            Workspace.__table__,
            WorkspaceMembership.__table__,
            WorkspaceInvitation.__table__,
        ):
            await conn.run_sync(table.create)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def workspace_service(db_session):
    return WorkspaceService(
        workspace_repo=WorkspaceRepository(db_session),
        membership_repo=WorkspaceMembershipRepository(db_session),
    )


@pytest.mark.asyncio
async def test_ensure_personal_creates_real_row_with_id_equal_to_user_id(workspace_service):
    ws = await workspace_service.ensure_personal("user-1")

    assert ws.id == "user-1"
    assert ws.type == WORKSPACE_TYPE_PERSONAL
    assert ws.owner_user_id == "user-1"
    assert ws.slug == "user"  # no email -> fallback handle


@pytest.mark.asyncio
async def test_personal_slug_is_derived_from_email_handle(workspace_service):
    ws = await workspace_service.ensure_personal("user-1", email="Jane.Doe@example.com")

    assert ws.slug == "jane-doe"


@pytest.mark.asyncio
async def test_slugs_are_unique_with_numeric_suffix(workspace_service):
    # Two different users with the same email handle collide on the base slug.
    a = await workspace_service.ensure_personal("user-1", email="sam@a.com")
    b = await workspace_service.ensure_personal("user-2", email="sam@b.com")

    assert a.slug == "sam"
    assert b.slug == "sam-2"


@pytest.mark.asyncio
async def test_create_shared_slug_is_derived_from_name(workspace_service):
    ws = await workspace_service.create_shared(owner_user_id="user-1", name="Team Rocket!")

    assert ws.slug == "team-rocket"


@pytest.mark.asyncio
async def test_get_by_slug_resolves_to_workspace(workspace_service):
    created = await workspace_service.create_shared(owner_user_id="user-1", name="Acme")

    found = await workspace_service.get_by_slug("acme")
    assert found is not None
    assert found.id == created.id


@pytest.mark.asyncio
async def test_ensure_personal_is_idempotent(workspace_service):
    first = await workspace_service.ensure_personal("user-1")
    second = await workspace_service.ensure_personal("user-1")

    assert first.id == second.id == "user-1"


@pytest.mark.asyncio
async def test_create_shared_creates_workspace_and_owner_membership(workspace_service, db_session):
    ws = await workspace_service.create_shared(owner_user_id="user-1", name="Team A")

    assert ws.type == WORKSPACE_TYPE_SHARED
    assert ws.id != "user-1"
    assert ws.name == "Team A"
    assert ws.owner_user_id == "user-1"

    membership_repo = WorkspaceMembershipRepository(db_session)
    assert await membership_repo.get(ws.id, "user-1") is not None


@pytest.mark.asyncio
async def test_list_for_user_returns_personal_and_member_workspaces(workspace_service, db_session):
    # user-1 owns a shared workspace; user-2 is added to it as a member.
    shared = await workspace_service.create_shared(owner_user_id="user-1", name="Team A")
    membership_repo = WorkspaceMembershipRepository(db_session)
    await membership_repo.add(
        WorkspaceMembership(workspace_id=shared.id, user_id="user-2", invitation_id=None)
    )

    user2_workspaces = await workspace_service.list_for_user("user-2")
    ids = {w.id for w in user2_workspaces}

    assert "user-2" in ids  # personal, auto-provisioned by list_for_user
    assert shared.id in ids  # shared, via membership
