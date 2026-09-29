"""The URL path is the only workspace selector.

A request names its workspace as ``/v1/workspaces/{workspace}/...`` by slug.
Anything else a client sends -- the retired ``X-AgentArea-Workspace`` family of
headers included -- selects nothing, and there is no personal-workspace default
to fall back on. Unknown and foreign slugs are refused with the same 403 so the
response does not reveal which workspaces exist.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import (
    UserContextDep,
    WorkspaceNotSelectedError,
    authenticate_principal,
    bind_request_workspace,
    binds_workspace,
)
from agentarea_common.di.container import register_singleton
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

ALICE_WORKSPACE = SimpleNamespace(id="ws-alice", slug="alice")
SHARED_WORKSPACE = SimpleNamespace(id="ws-shared", slug="shared")
BOB_WORKSPACE = SimpleNamespace(id="ws-bob", slug="bob")
WORKSPACES = {w.slug: w for w in (ALICE_WORKSPACE, SHARED_WORKSPACE, BOB_WORKSPACE)}


class _NoStaticGrants(AuthorizationService):
    async def get_accessible_workspaces(self, principal):
        return []

    async def can_write_workspace(self, user_context, workspace_id):
        return workspace_id == user_context.workspace_id


@pytest.fixture(autouse=True)
def _alice_owns_one_workspace_and_joined_another():
    """Alice owns ``alice`` and is a member of ``shared``; ``bob`` is not hers."""
    register_singleton(AuthorizationService, _NoStaticGrants())

    async def owned_and_named(user_id, *, slug=None, workspace_id=None):
        return [ALICE_WORKSPACE], WORKSPACES.get(slug) if slug else None

    with (
        patch(
            "agentarea_common.auth.dependencies._owned_and_named_workspaces",
            new=owned_and_named,
        ),
        patch(
            "agentarea_common.auth.dependencies._member_workspace_ids",
            new=AsyncMock(return_value=[SHARED_WORKSPACE.id]),
        ),
    ):
        yield


def _app(principal: UserPrincipal) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/workspaces/{workspace}/whoami")
    async def whoami(ctx: UserContextDep) -> dict:
        return {"workspace_id": ctx.workspace_id, "workspace_slug": ctx.workspace_slug}

    @app.get("/v1/unscoped")
    async def unscoped(ctx: UserContextDep) -> dict:
        return {"workspace_id": ctx.workspace_id}

    @binds_workspace
    async def bind_to_shared(request: Request) -> None:
        bind_request_workspace(request, SHARED_WORKSPACE.id, SHARED_WORKSPACE.slug)

    @app.get("/v1/things/{thing_id}", dependencies=[Depends(bind_to_shared)])
    async def bound(thing_id: str, ctx: UserContextDep) -> dict:
        return {"workspace_id": ctx.workspace_id, "workspace_slug": ctx.workspace_slug}

    app.dependency_overrides[authenticate_principal] = lambda: principal
    return app


def _client(principal: UserPrincipal | None = None) -> TestClient:
    return TestClient(
        _app(principal or UserPrincipal(user_id="alice")), raise_server_exceptions=False
    )


def test_owned_workspace_is_selected_by_slug():
    response = _client().get("/v1/workspaces/alice/whoami")

    assert response.status_code == 200
    assert response.json() == {"workspace_id": "ws-alice", "workspace_slug": "alice"}


def test_member_workspace_is_selected_by_slug():
    response = _client().get("/v1/workspaces/shared/whoami")

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "ws-shared"


def test_foreign_slug_is_forbidden():
    response = _client().get("/v1/workspaces/bob/whoami")

    assert response.status_code == 403


def test_unknown_slug_is_refused_exactly_like_a_foreign_one():
    foreign = _client().get("/v1/workspaces/bob/whoami")
    unknown = _client().get("/v1/workspaces/no-such-workspace/whoami")

    assert unknown.status_code == 403
    assert unknown.json() == foreign.json()


@pytest.mark.parametrize("header", ["X-AgentArea-Workspace", "X-Workspace-ID", "X-Workspace-Slug"])
def test_a_workspace_header_selects_nothing(header):
    response = _client().get("/v1/workspaces/alice/whoami", headers={header: "shared"})

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "ws-alice"


def test_a_route_naming_no_workspace_fails_loudly_instead_of_defaulting():
    response = _client().get("/v1/unscoped", headers={"X-AgentArea-Workspace": "alice"})

    assert response.status_code == 500


def test_a_binding_dependency_selects_the_entity_workspace():
    response = _client().get("/v1/things/thing-1")

    assert response.status_code == 200
    assert response.json() == {"workspace_id": "ws-shared", "workspace_slug": "shared"}


def test_api_key_acts_only_in_the_workspace_it_was_issued_for():
    key = UserPrincipal(user_id="alice", bound_workspace_id=ALICE_WORKSPACE.id)

    assert _client(key).get("/v1/workspaces/alice/whoami").status_code == 200
    assert _client(key).get("/v1/workspaces/shared/whoami").status_code == 403


@pytest.mark.asyncio
async def test_missing_workspace_selection_is_a_programming_error():
    from agentarea_common.auth.dependencies import get_user_context

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/unscoped",
            "query_string": b"",
            "headers": [],
            "path_params": {},
        }
    )

    with pytest.raises(WorkspaceNotSelectedError):
        await get_user_context(request, UserPrincipal(user_id="alice"))


def test_a_principal_has_no_workspace_to_fall_back_on():
    principal = UserPrincipal(user_id="alice")

    assert not hasattr(principal, "workspace_id")
