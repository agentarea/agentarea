"""Tests for the reified Workspace entity (Step 1: workspace as a table).

These cover the foundation that the workspace switcher (Step 2) builds on:
- personal workspaces are real rows, provisioned idempotently, with
  ``id == user_id`` so existing data needs no backfill;
- shared workspaces get a generated id;
- listing returns a user's personal workspace and workspace ids supplied by
  the membership graph.

The fixtures here intentionally create *only* the workspace tables on an
in-memory SQLite engine rather than the shared ``db_session`` fixture,
which calls ``BaseModel.metadata.create_all`` and currently fails on
SQLite because unrelated models use ``JSONB``.
"""

import pytest
import pytest_asyncio
from agentarea_common.workspaces.models import (
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from agentarea_common.workspaces.repository import (
    WorkspaceRepository,
)
from agentarea_common.workspaces.service import WorkspaceService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def session_factory():
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

    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def workspace_service(db_session):
    return WorkspaceService(
        workspace_repo=WorkspaceRepository(db_session),
    )


@pytest.mark.asyncio
async def test_ensure_personal_creates_real_row_with_id_equal_to_user_id(workspace_service):
    ws = await workspace_service.ensure_personal("user-1", email="jane@example.com")

    assert ws.id == "user-1"
    assert ws.owner_user_id == "user-1"
    assert ws.slug == "jane"


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
    first = await workspace_service.ensure_personal("user-1", email="jane@example.com")
    second = await workspace_service.ensure_personal("user-1")

    assert first.id == second.id == "user-1"


@pytest.mark.asyncio
async def test_create_shared_creates_workspace_row(workspace_service):
    ws = await workspace_service.create_shared(owner_user_id="user-1", name="Team A")

    assert ws.id != "user-1"
    assert ws.name == "Team A"
    assert ws.owner_user_id == "user-1"


@pytest.mark.asyncio
async def test_personal_is_derived_from_the_id_not_a_stored_flag(workspace_service):
    """``id == owner_user_id`` is the only marker of a personal workspace.

    There is no ``type`` column: a stored flag could disagree with the id it
    describes, and the id already carries the fact (``ensure_personal`` reuses
    the user id, ``create_shared`` mints a fresh uuid).
    """
    personal = await workspace_service.ensure_personal("user-1", email="jane@example.com")
    shared = await workspace_service.create_shared(owner_user_id="user-1", name="Team A")

    assert personal.id == personal.owner_user_id
    assert shared.id != shared.owner_user_id
    assert not hasattr(shared, "type")


@pytest.mark.asyncio
async def test_list_for_user_returns_personal_and_granted_workspaces(workspace_service):
    # user-1 owns a shared workspace; user-2 receives membership from graph.
    shared = await workspace_service.create_shared(owner_user_id="user-1", name="Team A")

    user2_workspaces = await workspace_service.list_for_user(
        "user-2",
        email="sam@example.com",
        member_workspace_ids=[shared.id],
    )
    ids = {w.id for w in user2_workspaces}

    assert "user-2" in ids  # personal, auto-provisioned by list_for_user
    assert shared.id in ids  # shared, via membership


async def _committed_workspace_ids(session_factory) -> set[str]:
    async with session_factory() as fresh:
        return set((await fresh.execute(select(Workspace.id))).scalars().all())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "create",
    [
        pytest.param(lambda s: s.create_shared(owner_user_id="user-1", name="Acme"), id="shared"),
        pytest.param(
            lambda s: s.ensure_personal("user-1", email="jane@example.com"), id="personal"
        ),
    ],
)
async def test_a_failed_creation_hook_leaves_no_workspace_row(db_session, session_factory, create):
    """The row and what ``on_created`` provisions for it land together or not at all.

    ``on_created`` is where the composition layer seeds the governance baseline.
    If the row were committed before it ran, a provisioning failure would leave
    a workspace that exists with no runtime baseline and nothing to retry it.
    """

    async def refuse(_workspace: Workspace) -> None:
        raise RuntimeError("baseline unavailable")

    service = WorkspaceService(WorkspaceRepository(db_session), on_created=refuse)

    with pytest.raises(RuntimeError, match="baseline unavailable"):
        await create(service)

    assert await _committed_workspace_ids(session_factory) == set()


@pytest.mark.asyncio
async def test_creation_hook_writes_commit_with_the_row(db_session, session_factory):
    """The hook writes through the caller's session and the service commits both."""

    async def provision(workspace: Workspace) -> None:
        db_session.add(
            WorkspaceMembership(workspace_id=workspace.id, user_id="user-1", invitation_id=None)
        )

    service = WorkspaceService(WorkspaceRepository(db_session), on_created=provision)
    ws = await service.create_shared(owner_user_id="user-1", name="Acme")

    assert await _committed_workspace_ids(session_factory) == {ws.id}
    async with session_factory() as fresh:
        members = (
            (
                await fresh.execute(
                    select(WorkspaceMembership.user_id).where(
                        WorkspaceMembership.workspace_id == ws.id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert members == ["user-1"]
