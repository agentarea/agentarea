"""Unit tests for the workspace members toolset.

Membership tools operate on the caller's own workspace only: the MCP mount is
workspace-scoped, so a ``workspace_id`` argument would be an invitation to try
someone else's. The signature test below keeps that property honest.
"""

import inspect
import json
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.tools import members_toolset
from agentarea_api.tools.members_toolset import MembersToolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.identity_directory import IdentityRecord
from agentarea_common.auth.permission import PermissionService
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_common.workspaces import (
    InvitationNotFound,
    OwnerRemovalRejected,
    WorkspaceMemberView,
)
from agentarea_common.workspaces.invitation_email import InvitationEmailDelivery

INVITATION_ID = uuid4()
RETURNED_ONCE = "plaintext-token"


class _AllowAll(PermissionService):
    async def check(self, user_id, permission, resource_type, resource_id) -> bool:
        return True


@pytest.fixture(autouse=True)
def caller():
    """The tools check the MCP caller first; this one administers the workspace."""
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    container.register_singleton(PermissionService, _AllowAll())
    owner = UserContext(user_id="user-1", workspace_id="ws-1", admin_workspaces=["ws-1"])
    with use_mcp_user_context(owner):
        yield
    container._singletons.clear()
    container._singletons.update(saved)


class FakeInvitationService:
    def __init__(self):
        self.created: list = []
        self.revoked: list = []
        self.raise_on_revoke = False

    async def create_invitation(self, **kwargs):
        self.created.append({**kwargs, "actor": kwargs["actor"].user_id})
        return (
            SimpleNamespace(
                id=INVITATION_ID,
                workspace_id=kwargs["workspace_id"],
                email=kwargs.get("email"),
                invited_by=kwargs["actor"].user_id,
                status="pending",
                expires_at="2026-09-01T00:00:00Z",
                accepted_at=None,
                accepted_by_user_id=None,
                created_at="2026-08-26T00:00:00Z",
            ),
            RETURNED_ONCE,
        )

    async def list_pending(self, *, actor, workspace_id):
        return [
            SimpleNamespace(
                id=INVITATION_ID,
                workspace_id=workspace_id,
                email="new@example.com",
                invited_by="user-1",
                status="pending",
                expires_at="2026-09-01T00:00:00Z",
                accepted_at=None,
                accepted_by_user_id=None,
                created_at="2026-08-26T00:00:00Z",
            )
        ]

    async def revoke(self, *, actor, workspace_id, invitation_id):
        if self.raise_on_revoke:
            raise InvitationNotFound(str(invitation_id))
        self.revoked.append((workspace_id, invitation_id))


JOINED_AT = datetime(2026, 3, 2, 9, 30)


class FakeMembershipService:
    def __init__(self):
        self.calls: list = []
        self.removal_error: Exception | None = None

    async def list_members(self, workspace_id):
        self.calls.append(("list", workspace_id))
        return [
            WorkspaceMemberView(user_id="user-1", joined_at=JOINED_AT, invitation_id=None),
            WorkspaceMemberView(user_id="user-2", joined_at=None, invitation_id=None),
        ]

    async def owner_user_id(self, _workspace_id):
        return "user-1"

    async def remove(self, *, workspace_id, target_user_id, actor_user_id):
        if self.removal_error is not None:
            raise self.removal_error
        self.calls.append(("remove", workspace_id, target_user_id, actor_user_id))


class FakeDirectory:
    def __init__(self, records: dict[str, IdentityRecord]):
        self.records = records

    async def resolve(self, user_ids):
        return {uid: self.records[uid] for uid in user_ids if uid in self.records}


class FakeInvitationMailer:
    """Stands in for the shared invitation-email delivery."""

    def __init__(self):
        self.calls: list[dict] = []
        self.outcome = InvitationEmailDelivery.SENT

    async def __call__(self, *, workspace_repo, workspace_id, recipient, token):
        self.calls.append({"workspace_id": workspace_id, "recipient": recipient, "token": token})
        return self.outcome


@pytest.fixture
def harness(monkeypatch):
    service = FakeInvitationService()
    memberships = FakeMembershipService()
    directory = FakeDirectory({})
    mailer = FakeInvitationMailer()
    monkeypatch.setattr(members_toolset, "deliver_invitation_for_workspace", mailer)

    @asynccontextmanager
    async def fake_context():
        user_ctx = SimpleNamespace(user_id="user-1", workspace_id="ws-1", email="me@example.com")
        yield SimpleNamespace(), user_ctx, SimpleNamespace(), None, None

    monkeypatch.setattr(members_toolset, "platform_context", fake_context)
    monkeypatch.setattr(members_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(members_toolset, "_build_service", lambda _session: service)
    monkeypatch.setattr(members_toolset, "_build_membership_service", lambda _session: memberships)
    monkeypatch.setattr(members_toolset, "get_identity_directory", lambda: directory)
    return SimpleNamespace(
        service=service, memberships=memberships, directory=directory, mailer=mailer
    )


async def test_no_membership_tool_takes_a_workspace_argument():
    for name, method in MembersToolset()._tool_methods.items():
        params = set(inspect.signature(method).parameters)
        assert "workspace_id" not in params, (
            f"members_{name} takes workspace_id; membership tools must act on "
            "the caller's workspace only"
        )


async def test_list_reads_members_of_the_callers_workspace(harness):
    result = json.loads(await MembersToolset().list())

    assert [m["user_id"] for m in result] == ["user-1", "user-2"]
    assert harness.memberships.calls == [("list", "ws-1")]


async def test_list_reports_the_real_join_date_and_owner(harness):
    result = json.loads(await MembersToolset().list())

    assert result[0]["joined_at"] == str(JOINED_AT)
    assert result[0]["is_owner"] is True
    assert result[0]["is_you"] is True
    assert result[1]["is_owner"] is False


async def test_list_resolves_other_members_through_the_directory(harness):
    harness.directory.records["user-2"] = IdentityRecord(
        user_id="user-2", email="teammate@example.com", display_name="Team Mate"
    )

    result = json.loads(await MembersToolset().list())

    assert result[1]["email"] == "teammate@example.com"
    assert result[1]["display_name"] == "Team Mate"


async def test_list_leaves_unresolvable_members_empty_rather_than_guessing(harness):
    result = json.loads(await MembersToolset().list())

    assert result[1]["email"] is None
    assert result[1]["display_name"] is None
    # The caller still resolves from their own verified token.
    assert result[0]["email"] == "me@example.com"


async def test_invite_returns_the_token_once(harness):
    result = json.loads(await MembersToolset().invite(email="new@example.com", expires_in_days=7))

    assert result["token"] == RETURNED_ONCE
    assert harness.service.created == [
        {
            "actor": "user-1",
            "workspace_id": "ws-1",
            "email": "new@example.com",
            "expires_in_days": 7,
        }
    ]


async def test_invite_omits_expiry_when_not_given(harness):
    await MembersToolset().invite()

    assert "expires_in_days" not in harness.service.created[0]
    assert harness.service.created[0]["email"] is None


async def test_invite_emails_the_link_and_reports_the_outcome(harness):
    result = json.loads(await MembersToolset().invite(email="new@example.com"))

    assert harness.mailer.calls == [
        {"workspace_id": "ws-1", "recipient": "new@example.com", "token": RETURNED_ONCE}
    ]
    assert result["email_delivery"] == "sent"


async def test_invite_says_so_when_the_email_did_not_go_out(harness):
    """A failed send must not read as success — the caller still has to share the link."""
    harness.mailer.outcome = InvitationEmailDelivery.NOT_CONFIGURED

    result = json.loads(await MembersToolset().invite(email="new@example.com"))

    assert result["email_delivery"] == "not_configured"
    assert result["token"] == RETURNED_ONCE


async def test_remove_revokes_membership_in_the_callers_workspace(harness):
    await MembersToolset().remove(user_id="user-2")

    assert harness.memberships.calls == [("remove", "ws-1", "user-2", "user-1")]


async def test_remove_reports_a_refused_removal_instead_of_claiming_success(harness):
    harness.memberships.removal_error = OwnerRemovalRejected("owner cannot be removed")

    result = json.loads(await MembersToolset().remove(user_id="user-1"))

    assert result == {"error": "owner cannot be removed"}
    assert harness.memberships.calls == []


async def test_revoke_invitation_reports_a_missing_invitation(harness):
    harness.service.raise_on_revoke = True

    result = json.loads(await MembersToolset().revoke_invitation(invitation_id=str(INVITATION_ID)))

    assert result == {"error": "Invitation not found"}


async def test_list_invitations_never_returns_tokens(harness):
    result = json.loads(await MembersToolset().list_invitations())

    assert result[0]["email"] == "new@example.com"
    assert "token" not in result[0]
