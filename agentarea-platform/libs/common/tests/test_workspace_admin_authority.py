"""Administering a workspace is not the same authority as writing in it.

``assert_workspace_admin`` gates policy rules, wallet credentials and the
authorization graph. Its docstring has always said that plain membership is not
enough -- "any member could otherwise loosen their own spend cap, delete a deny
rule, or drain another agent's wallet" -- but it resolved that question through
``can_write_workspace``, whose open-core implementation is
``workspace_id == user_context.workspace_id``. For a caller already acting in
that workspace it is a tautology, so every admin-gated endpoint was open to
every member.

The two questions are now separate predicates. Writing entities stays with
membership; administering requires ownership.
"""

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService


@pytest.fixture
def authz():
    return WorkspaceScopedAuthorizationService()


def _member(**kwargs) -> UserContext:
    return UserContext(user_id="user-member", workspace_id="ws-acme", **kwargs)


@pytest.mark.asyncio
async def test_a_member_may_write_in_their_workspace(authz):
    assert await authz.can_write_workspace(_member(), "ws-acme") is True


@pytest.mark.asyncio
async def test_a_member_may_not_administer_their_workspace(authz):
    """The regression this whole change exists for."""
    assert await authz.can_administer_workspace(_member(), "ws-acme") is False


@pytest.mark.asyncio
async def test_an_owner_may_administer_the_workspace_they_own(authz):
    owner = _member(admin_workspaces=["ws-acme"])
    assert await authz.can_administer_workspace(owner, "ws-acme") is True


@pytest.mark.asyncio
async def test_ownership_does_not_carry_to_another_workspace(authz):
    owner = UserContext(
        user_id="user-owner",
        workspace_id="ws-other",
        accessible_workspaces=["ws-other", "ws-acme"],
        admin_workspaces=["ws-acme"],
    )
    assert await authz.can_administer_workspace(owner, "ws-other") is False


@pytest.mark.asyncio
async def test_a_personal_workspace_is_administered_by_its_user(authz):
    """The personal workspace is keyed by the user id and has no owner row."""
    solo = UserContext(user_id="user-solo", workspace_id="user-solo")
    assert await authz.can_administer_workspace(solo, "user-solo") is True


@pytest.mark.asyncio
async def test_unresolved_admin_workspaces_deny(authz):
    """A context built without the request dependency must not administer."""
    assert await authz.can_administer_workspace(_member(admin_workspaces=None), "ws-acme") is False
