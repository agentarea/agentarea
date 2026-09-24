"""Issuing, listing and revoking invitations takes admin of the target workspace.

The REST routes gated these on the router, and ``members_invite`` over MCP
called the same ``WorkspaceInvitationService`` without it: any member could mint
a join link for a stranger by asking an agent to. The service now takes the
acting principal and decides itself, so no door can skip it.
"""

from uuid import uuid4

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_common.workspaces import WorkspaceInvitationService
from fastapi import HTTPException

WORKSPACE = "workspace-1"
MEMBER = UserContext(user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[])
OWNER = UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])


class _Invitations:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def add(self, invitation):
        self.calls.append("add")
        return invitation

    async def list_pending(self, workspace_id):
        self.calls.append("list_pending")
        return []

    async def get_by_id(self, invitation_id):
        self.calls.append("get_by_id")
        return None


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


CALLS = {
    "create_invitation": lambda s, actor: s.create_invitation(
        actor=actor, workspace_id=WORKSPACE, email="stranger@example.com"
    ),
    "list_pending": lambda s, actor: s.list_pending(actor=actor, workspace_id=WORKSPACE),
    "revoke": lambda s, actor: s.revoke(actor=actor, workspace_id=WORKSPACE, invitation_id=uuid4()),
}


@pytest.mark.parametrize("call", CALLS.values(), ids=CALLS.keys())
async def test_a_member_cannot_manage_invitations(call) -> None:
    repo = _Invitations()

    with pytest.raises(HTTPException) as refused:
        await call(WorkspaceInvitationService(repo), MEMBER)  # type: ignore[arg-type]

    assert refused.value.status_code == 403
    assert repo.calls == []


async def test_a_member_cannot_act_on_a_workspace_they_do_not_administer() -> None:
    """Administering one workspace grants nothing over another."""
    repo = _Invitations()

    with pytest.raises(HTTPException):
        await WorkspaceInvitationService(repo).create_invitation(  # type: ignore[arg-type]
            actor=OWNER, workspace_id="workspace-2"
        )

    assert repo.calls == []


async def test_the_admin_issues_the_invitation_as_themselves() -> None:
    repo = _Invitations()

    invitation, token = await WorkspaceInvitationService(repo).create_invitation(  # type: ignore[arg-type]
        actor=OWNER, workspace_id=WORKSPACE, email="new@example.com"
    )

    assert token
    assert invitation.invited_by == OWNER.user_id
    assert repo.calls == ["add"]
