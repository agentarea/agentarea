"""A workspace reference cannot be hijacked by a look-alike slug.

Workspace ids are UUIDs, and a personal workspace's id is its owner's user id.
If a slug could take the shape of a UUID, anyone could name a new workspace
after someone else's id, and every surface that resolves "slug first, then id"
would hand them the attacker's workspace instead. So a UUID-shaped reference
resolves by id only, and slugs are never minted in that shape.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import enter_workspace, get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.workspaces.slug import is_uuid_shaped, slugify
from fastapi import HTTPException, Request

VICTIM_ID = "5b1edbaf-8480-4885-a003-78adc92ab513"
VICTIM = SimpleNamespace(id=VICTIM_ID, slug="victim", owner_user_id=VICTIM_ID)
IMPOSTOR = SimpleNamespace(id="ws-attacker", slug=VICTIM_ID, owner_user_id="attacker")


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _request(workspace: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/v1/workspaces/{workspace}/agents/",
            "query_string": b"",
            "headers": [],
            "path_params": {"workspace": workspace},
        }
    )


@pytest.mark.asyncio
async def test_mcp_reference_shaped_like_an_id_resolves_by_id_only():
    async def load(*, workspace_id=None, slug=None):
        if slug == VICTIM_ID:
            return IMPOSTOR
        return VICTIM if workspace_id == VICTIM_ID else None

    principal = UserPrincipal(user_id=VICTIM_ID, accessible_workspaces=[VICTIM_ID, "ws-attacker"])
    with patch("agentarea_common.workspaces.lookup.load_workspace", new=load):
        context = await enter_workspace(principal, VICTIM_ID)

    assert context.workspace_id == VICTIM_ID


@pytest.mark.asyncio
async def test_rest_path_shaped_like_an_id_resolves_by_id_only():
    calls: list[dict] = []

    async def owned_and_named(user_id, *, slug=None, workspace_id=None):
        calls.append({"slug": slug, "workspace_id": workspace_id})
        if slug == VICTIM_ID:
            return [VICTIM], IMPOSTOR
        return [VICTIM], VICTIM if workspace_id == VICTIM_ID else None

    with (
        patch(
            "agentarea_common.auth.dependencies._owned_and_named_workspaces",
            new=owned_and_named,
        ),
        patch(
            "agentarea_common.auth.dependencies._member_workspace_ids",
            new=AsyncMock(return_value=["ws-attacker"]),
        ),
    ):
        context = await get_user_context(_request(VICTIM_ID), UserPrincipal(user_id=VICTIM_ID))

    assert context.workspace_id == VICTIM_ID
    assert calls == [{"slug": None, "workspace_id": VICTIM_ID}]


@pytest.mark.parametrize(
    "name",
    [VICTIM_ID, VICTIM_ID.upper(), f" {VICTIM_ID} ", VICTIM_ID.replace("-", " ")],
)
def test_a_slug_is_never_minted_in_the_shape_of_an_id(name):
    slug = slugify(name)

    assert not is_uuid_shaped(slug)
    assert slug.startswith(VICTIM_ID)


@pytest.mark.parametrize("workspace", ["Bad_Slug", "-leading", "a" * 121, "x%20y"])
@pytest.mark.asyncio
async def test_a_malformed_slug_is_rejected_before_any_lookup(workspace):
    lookup = AsyncMock()
    with (
        patch("agentarea_common.auth.dependencies._owned_and_named_workspaces", new=lookup),
        pytest.raises(HTTPException) as refused,
    ):
        await get_user_context(_request(workspace), UserPrincipal(user_id="alice"))

    assert refused.value.status_code == 422
    lookup.assert_not_awaited()
