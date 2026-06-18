"""The workspace-creation hook fires exactly once, on a genuine insert.

The composition layer relies on this to provision cross-domain baseline data
(e.g. governance policies) without WorkspaceService depending on those domains.
The hook must NOT fire on idempotent re-reads (``ensure_personal`` of an
already-provisioned workspace), or defaults would be re-seeded repeatedly.
"""

import pytest
from agentarea_common.workspaces import Workspace
from agentarea_common.workspaces.service import WorkspaceService


class _FakeWorkspaceRepo:
    def __init__(self, existing: Workspace | None = None):
        self._existing = existing
        self.added: list[Workspace] = []

    async def get(self, workspace_id: str) -> Workspace | None:
        return self._existing

    async def get_by_slug(self, slug: str) -> Workspace | None:
        return None

    async def add(self, workspace: Workspace) -> Workspace:
        self.added.append(workspace)
        return workspace


class _FakeMembershipRepo:
    async def get(self, *_args, **_kwargs):
        return object()  # already a member -> no insert path needed


@pytest.mark.asyncio
async def test_hook_fires_on_genuine_create():
    fired: list[str] = []

    async def on_created(ws: Workspace) -> None:
        fired.append(ws.id)

    service = WorkspaceService(
        _FakeWorkspaceRepo(existing=None),
        _FakeMembershipRepo(),
        on_created=on_created,
    )

    ws = await service.ensure_personal("u1", email="jane@example.com")
    assert fired == [ws.id]


@pytest.mark.asyncio
async def test_hook_does_not_fire_on_idempotent_reread():
    fired: list[str] = []

    async def on_created(ws: Workspace) -> None:
        fired.append(ws.id)

    existing = Workspace(
        id="u1", slug="jane", type="personal", name="Personal", owner_user_id="u1"
    )
    service = WorkspaceService(
        _FakeWorkspaceRepo(existing=existing),
        _FakeMembershipRepo(),
        on_created=on_created,
    )

    await service.ensure_personal("u1", email="jane@example.com")
    assert fired == []
