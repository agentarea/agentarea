"""The workspace's owner column and its ``Workspace#admin`` tuple say the same thing.

Administrative authority has two representations, and both are live on different
paths. ``workspaces.owner_user_id`` answers ``requires_workspace_admin()`` --
policy, secrets, money. ``Workspace#admin`` is what OpenFGA evaluates inside
``project.can_read: ... or admin from workspace``, the branch that lets an admin
reach an object they do not own once a route asks the PDP.

They agree by construction today: ``seed_workspace`` writes the tuple for the
same user the row records as owner, and nothing in the codebase ever changes
``owner_user_id`` afterwards. This pins that, because the failure it prevents is
a quiet one -- an admin who can rewrite policy and gets 403 opening an agent.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import _access_control_grants as grants
from agentarea_common.rebac.models import RelationTuple

WORKSPACE = "ws-acme"
OWNER = "user-owner"


@pytest.fixture
def written(monkeypatch) -> list[RelationTuple]:
    recorded: list[RelationTuple] = []
    client = AsyncMock()
    client.write_tuple.side_effect = lambda tuple_: recorded.append(tuple_)
    # The module binds the resolver at import, so patch it where it is used.
    monkeypatch.setattr(grants, "resolve_graph_client", lambda: (client, "OpenFGA"))
    return recorded


@pytest.mark.asyncio
async def test_seeding_records_the_owner_as_the_graph_admin(written) -> None:
    await grants.seed_workspace(workspace_id=WORKSPACE, creator_user_id=OWNER)

    admin = [t for t in written if t.namespace == "Workspace" and t.relation == "admin"]
    assert [(t.object, t.subject_id) for t in admin] == [(WORKSPACE, f"User:{OWNER}")]


@pytest.mark.asyncio
async def test_seeding_attaches_the_root_project_to_the_workspace(written) -> None:
    """Without this edge `admin from workspace` has nothing to traverse."""
    await grants.seed_workspace(workspace_id=WORKSPACE, creator_user_id=OWNER)

    assert (
        RelationTuple(
            namespace="project",
            object=f"{WORKSPACE}-root",
            relation="workspace",
            subject_id=f"Workspace:{WORKSPACE}",
        )
        in written
    )


def test_nothing_in_the_codebase_transfers_workspace_ownership() -> None:
    """The two representations can only diverge if ownership moves.

    If this fails, somebody added a transfer path: it must write the
    ``Workspace#admin`` tuple as well, or an ex-owner keeps reaching every
    resource through the root project.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in (root / "apps").rglob("*.py"):
        if "/tests/" in str(path):
            continue
        text = path.read_text()
        if "owner_user_id=" in text and "Workspace(" in text:
            offenders.append(path.relative_to(root))
    assert not offenders, f"ownership is assigned outside workspace creation: {offenders}"


def test_the_seed_is_the_only_writer_of_the_admin_relation() -> None:
    """One writer, so the projection has one place to go wrong."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    writers = []
    for path in list((root / "apps").rglob("*.py")) + list((root / "libs").rglob("*.py")):
        if "/tests/" in str(path):
            continue
        text = path.read_text()
        if 'relation="admin"' in text:
            writers.append(path.name)
    assert sorted(writers) == ["_access_control_grants.py"], writers


@pytest.mark.asyncio
async def test_the_owner_of_a_personal_workspace_needs_no_row() -> None:
    """A personal workspace is keyed by its user's id and has no owner row.

    ``can_administer_workspace`` short-circuits on that, which is why an empty
    ``admin_workspaces`` is not a hole there.
    """
    from agentarea_common.auth.workspace_authorization import (
        WorkspaceScopedAuthorizationService,
    )

    service = WorkspaceScopedAuthorizationService()
    solo = SimpleNamespace(user_id="user-solo", workspace_id="user-solo", admin_workspaces=[])
    guest = SimpleNamespace(user_id="user-guest", workspace_id="user-solo", admin_workspaces=[])

    assert await service.can_administer_workspace(solo, "user-solo") is True
    assert await service.can_administer_workspace(guest, "user-solo") is False


@pytest.mark.asyncio
async def test_a_failed_graph_seed_leaves_no_workspace_row() -> None:
    """Admission goes graph-first, so a failure means nothing was created.

    The graph cannot join Postgres' transaction, so one system goes first and
    the harmless order is the graph: tuples about a workspace id that was never
    inserted grant nobody anything, while a committed row with no tuples is a
    workspace whose own owner is refused on everything the PDP governs, with
    nothing to retry it. Previously the seed ran after the commit *and* had its
    failure swallowed, which is both halves of that wrong.
    """
    from agentarea_common.workspaces.repository import Workspace
    from agentarea_common.workspaces.service import WorkspaceService

    repo = AsyncMock()
    repo.get.return_value = None
    repo.get_by_slug.return_value = None

    async def _refuse(_workspace: Workspace) -> None:
        raise RuntimeError("graph unreachable")

    service = WorkspaceService(repo, before_insert=_refuse)

    with pytest.raises(RuntimeError, match="graph unreachable"):
        await service.create_shared(owner_user_id=OWNER, name="Acme")

    repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_graph_is_seeded_before_the_row_is_inserted() -> None:
    """Order is the whole point; assert it rather than trusting the wiring."""
    from agentarea_common.workspaces.repository import Workspace
    from agentarea_common.workspaces.service import WorkspaceService

    order: list[str] = []
    repo = AsyncMock()
    repo.get_by_slug.return_value = None
    repo.add.side_effect = lambda workspace: order.append("insert") or workspace

    async def _seed(_workspace: Workspace) -> None:
        order.append("graph")

    await WorkspaceService(repo, before_insert=_seed).create_shared(
        owner_user_id=OWNER, name="Acme"
    )

    assert order == ["graph", "insert"]
