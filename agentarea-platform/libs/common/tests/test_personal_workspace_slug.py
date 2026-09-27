"""A personal workspace is named after its owner, never after a placeholder.

An API key or a Hydra OAuth token carries no email. Provisioning from one used
to mint the slug ``user``, which is how an owner ended up at ``/w/user``. The
email now comes from the identity provider, and when nobody can supply it the
workspace is not created.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.identity_directory import (
    IdentityDirectoryUnavailableError,
    IdentityRecord,
)
from agentarea_common.workspaces import Workspace
from agentarea_common.workspaces.service import (
    PersonalWorkspaceIdentityError,
    WorkspaceService,
)


class _Repo:
    def __init__(self, existing: Workspace | None = None, joined: list[Workspace] = ()) -> None:
        self._existing = existing
        self._joined = list(joined)
        self.added: list[Workspace] = []
        self.session = AsyncMock()

    async def list_for_user(self, user_id: str, *, member_workspace_ids: list[str]):
        return [*self.added, *(w for w in self._joined if w.id in member_workspace_ids)]

    async def get(self, workspace_id: str) -> Workspace | None:
        return self._existing

    async def get_by_slug(self, slug: str) -> Workspace | None:
        return None

    async def add(self, workspace: Workspace) -> Workspace:
        self.added.append(workspace)
        return workspace


class _Directory:
    def __init__(self, emails: dict[str, str], *, down: bool = False) -> None:
        self.emails = emails
        self.down = down
        self.asked: list[str] = []

    async def resolve(self, user_ids):
        raise AssertionError("provisioning must use lookup, which tells an outage apart")

    async def lookup(self, user_id):
        self.asked.append(user_id)
        if self.down:
            raise IdentityDirectoryUnavailableError("kratos is down")
        if user_id not in self.emails:
            return None
        return IdentityRecord(user_id=user_id, email=self.emails[user_id], display_name=None)


@pytest.mark.asyncio
async def test_without_an_email_the_slug_comes_from_the_identity_provider():
    repo = _Repo()
    service = WorkspaceService(repo, identities=_Directory({"u1": "jane@example.com"}))

    workspace = await service.ensure_personal("u1")

    assert workspace.slug == "jane"


@pytest.mark.asyncio
async def test_an_email_on_the_token_needs_no_lookup():
    directory = _Directory({})
    service = WorkspaceService(_Repo(), identities=directory)

    workspace = await service.ensure_personal("u1", email="sam@example.com")

    assert workspace.slug == "sam"
    assert directory.asked == []


@pytest.mark.asyncio
async def test_an_identity_the_provider_cannot_name_creates_nothing():
    repo = _Repo()
    service = WorkspaceService(repo, identities=_Directory({}))

    with pytest.raises(PersonalWorkspaceIdentityError):
        await service.ensure_personal("u1")
    assert repo.added == []


@pytest.mark.asyncio
async def test_without_an_identity_provider_nothing_is_created():
    repo = _Repo()
    service = WorkspaceService(repo, identities=None)

    with pytest.raises(PersonalWorkspaceIdentityError):
        await service.ensure_personal("u1")
    assert repo.added == []


@pytest.mark.asyncio
async def test_an_existing_personal_workspace_needs_no_name():
    existing = Workspace(id="u1", slug="jane", name="Personal", owner_user_id="u1")
    directory = _Directory({})
    service = WorkspaceService(_Repo(existing), identities=directory)

    assert await service.ensure_personal("u1") is existing
    assert directory.asked == []


@pytest.mark.asyncio
async def test_an_identity_provider_outage_is_not_read_as_a_missing_email():
    repo = _Repo()
    service = WorkspaceService(repo, identities=_Directory({}, down=True))

    with pytest.raises(PersonalWorkspaceIdentityError, match="unavailable") as raised:
        await service.ensure_personal("u1")
    assert isinstance(raised.value.__cause__, IdentityDirectoryUnavailableError)
    assert repo.added == []


@pytest.mark.asyncio
async def test_joined_workspaces_are_listed_when_the_personal_one_cannot_be_named():
    team = Workspace(id="team-1", slug="team", name="Team", owner_user_id="someone")
    service = WorkspaceService(_Repo(joined=[team]), identities=_Directory({}, down=True))

    workspaces = await service.list_for_user("u1", member_workspace_ids=["team-1"])

    assert workspaces == [team]
