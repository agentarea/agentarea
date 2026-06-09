"""The workspace override is the authorization boundary for cross-workspace
access: a request may select any workspace the user is a member of, and
nothing else. Transport (header id vs slug) is irrelevant to this gate —
these tests pin the gate itself.
"""

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import _apply_workspace_override
from fastapi import HTTPException


def _ctx() -> UserContext:
    return UserContext(
        user_id="u1",
        workspace_id="u1",
        accessible_workspaces=["u1", "ws-shared"],
    )


def test_override_to_member_workspace_is_applied():
    ctx = _ctx()
    _apply_workspace_override(ctx, "ws-shared")
    assert ctx.workspace_id == "ws-shared"


def test_override_to_non_member_workspace_is_rejected():
    ctx = _ctx()
    with pytest.raises(HTTPException) as exc:
        _apply_workspace_override(ctx, "ws-foreign")
    assert exc.value.status_code == 403
    assert ctx.workspace_id == "u1"  # left untouched on rejection


def test_no_override_is_a_noop():
    ctx = _ctx()
    _apply_workspace_override(ctx, None)
    assert ctx.workspace_id == "u1"
