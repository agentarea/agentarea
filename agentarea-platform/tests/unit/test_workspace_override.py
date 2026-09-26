"""Entering a workspace is the authorization boundary for cross-workspace
access: a principal may act in any workspace it is a member of, and nothing
else. How the request named the workspace (path slug, bound entity) is
irrelevant to this gate — these tests pin the gate itself.
"""

import pytest
from agentarea_common.auth.context import UserPrincipal, WorkspaceUnreachableError


def _principal() -> UserPrincipal:
    return UserPrincipal(user_id="u1", accessible_workspaces=["u1", "ws-shared"])


def test_entering_a_member_workspace_yields_its_context():
    context = _principal().enter("ws-shared", "shared")

    assert context.workspace_id == "ws-shared"
    assert context.workspace_slug == "shared"
    assert context.accessible_workspaces == ["u1", "ws-shared"]


def test_entering_a_non_member_workspace_is_rejected():
    with pytest.raises(WorkspaceUnreachableError):
        _principal().enter("ws-foreign", "foreign")


def test_an_unresolved_principal_reaches_nothing():
    with pytest.raises(WorkspaceUnreachableError):
        UserPrincipal(user_id="u1").enter("u1", "personal")
