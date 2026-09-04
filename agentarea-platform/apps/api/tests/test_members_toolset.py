"""Unit tests for the workspace members toolset.

Membership tools operate on the caller's own workspace only: the MCP mount is
workspace-scoped, so a ``workspace_id`` argument would be an invitation to try
someone else's. The signature test below keeps that property honest.
"""

import inspect
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.tools import members_toolset
from agentarea_api.tools.members_toolset import MembersToolset
from agentarea_common.workspaces import InvitationNotFound

INVITATION_ID = uuid4()
RETURNED_ONCE = "plaintext-token"


class FakeInvitationService:
    def __init__(self):
        self.created: list = []
        self.revoked: list = []
        self.raise_on_revoke = False

    async def create_invitation(self, **kwargs):
        self.created.append(kwargs)
        return (
            SimpleNamespace(
                id=INVITATION_ID,
                workspace_id=kwargs["workspace_id"],
                email=kwargs.get("email"),
                invited_by=kwargs["invited_by"],
                status="pending",
                expires_at="2026-09-01T00:00:00Z",
                accepted_at=None,
                accepted_by_user_id=None,
                created_at="2026-08-26T00:00:00Z",
            ),
            RETURNED_ONCE,
        )

    async def list_pending(self, workspace_id):
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

    async def revoke(self, *, workspace_id, invitation_id):
        if self.raise_on_revoke:
            raise InvitationNotFound(str(invitation_id))
        self.revoked.append((workspace_id, invitation_id))


@pytest.fixture
def harness(monkeypatch):
    service = FakeInvitationService()
    graph_calls: list = []

    @asynccontextmanager
    async def fake_context():
        user_ctx = SimpleNamespace(user_id="user-1", workspace_id="ws-1", email="me@example.com")
        yield SimpleNamespace(), user_ctx, SimpleNamespace(), None, None

    async def fake_list_member_ids(workspace_id):
        graph_calls.append(("list", workspace_id))
        return ["user-1", "user-2"]

    async def fake_revoke_member(workspace_id, user_id):
        graph_calls.append(("revoke", workspace_id, user_id))

    monkeypatch.setattr(members_toolset, "platform_context", fake_context)
    monkeypatch.setattr(members_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(members_toolset, "_build_service", lambda _session: service)
    monkeypatch.setattr(members_toolset, "_list_member_ids", fake_list_member_ids)
    monkeypatch.setattr(members_toolset, "_revoke_member", fake_revoke_member)
    return SimpleNamespace(service=service, graph=graph_calls)


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
    assert harness.graph == [("list", "ws-1")]


async def test_invite_returns_the_token_once(harness):
    result = json.loads(await MembersToolset().invite(email="new@example.com", expires_in_days=7))

    assert result["token"] == RETURNED_ONCE
    assert harness.service.created == [
        {
            "workspace_id": "ws-1",
            "invited_by": "user-1",
            "email": "new@example.com",
            "expires_in_days": 7,
        }
    ]


async def test_invite_omits_expiry_when_not_given(harness):
    await MembersToolset().invite()

    assert "expires_in_days" not in harness.service.created[0]
    assert harness.service.created[0]["email"] is None


async def test_remove_revokes_membership_in_the_callers_workspace(harness):
    await MembersToolset().remove(user_id="user-2")

    assert harness.graph == [("revoke", "ws-1", "user-2")]


async def test_revoke_invitation_reports_a_missing_invitation(harness):
    harness.service.raise_on_revoke = True

    result = json.loads(await MembersToolset().revoke_invitation(invitation_id=str(INVITATION_ID)))

    assert result == {"error": "Invitation not found"}


async def test_list_invitations_never_returns_tokens(harness):
    result = json.loads(await MembersToolset().list_invitations())

    assert result[0]["email"] == "new@example.com"
    assert "token" not in result[0]
