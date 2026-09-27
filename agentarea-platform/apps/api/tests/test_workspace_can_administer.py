"""Each listed workspace says whether the caller may administer it.

The webapp needs this to show an admin-only page as admin-only instead of
calling it and failing. The answer must come from the same
``AuthorizationService.can_administer_workspace`` the admin-gated routes use,
so an implementation with real roles changes both at once.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.api.v1 import workspaces
from agentarea_api.main import app
from agentarea_api.tools import workspaces_toolset
from agentarea_api.tools.workspaces_toolset import WorkspacesToolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.auth.dependencies import get_principal
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from fastapi.testclient import TestClient

PERSONAL = SimpleNamespace(id="alice", slug="alice", name="Alice", owner_user_id="alice")
OWNED = SimpleNamespace(id="ws-acme", slug="acme", name="Acme", owner_user_id="alice")
JOINED = SimpleNamespace(id="ws-other", slug="other", name="Other", owner_user_id="bob")


def _alice(**overrides) -> UserPrincipal:
    fields = {
        "user_id": "alice",
        "accessible_workspaces": ["alice", "ws-acme", "ws-other"],
        "admin_workspaces": ["ws-acme"],
    }
    fields.update(overrides)
    return UserPrincipal(**fields)


@pytest.fixture(autouse=True)
def _authz(monkeypatch):
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    monkeypatch.setattr(workspaces, "get_workspace_membership_graph", lambda: None)
    yield
    container._singletons.clear()
    container._singletons.update(saved)


def _service() -> AsyncMock:
    service = AsyncMock()
    service.list_for_user.return_value = [PERSONAL, OWNED, JOINED]
    return service


def _list(principal: UserPrincipal) -> dict[str, bool]:
    service = _service()
    app.dependency_overrides[get_principal] = lambda: principal
    app.dependency_overrides[workspaces.get_workspace_service] = lambda: service
    try:
        response = TestClient(app).get("/v1/workspaces")
    finally:
        app.dependency_overrides.pop(get_principal, None)
        app.dependency_overrides.pop(workspaces.get_workspace_service, None)
    assert response.status_code == 200, response.text
    return {w["slug"]: w["can_administer"] for w in response.json()}


def test_the_owner_administers_their_workspace_and_their_personal_one() -> None:
    listed = _list(_alice())

    assert listed["alice"] is True
    assert listed["acme"] is True


def test_a_member_does_not_administer_a_workspace_they_joined() -> None:
    assert _list(_alice())["other"] is False


def test_an_api_key_administers_only_the_workspace_it_was_issued_for() -> None:
    bound_to_joined = _alice(
        bound_workspace_id="ws-other", accessible_workspaces=["ws-other"], admin_workspaces=[]
    )

    assert _list(bound_to_joined) == {"other": False}


def test_the_creator_administers_the_workspace_they_just_created() -> None:
    service = _service()
    created = SimpleNamespace(id="ws-new", slug="new", name="New", owner_user_id="alice")
    service.create_shared.return_value = created
    app.dependency_overrides[get_principal] = lambda: _alice()
    app.dependency_overrides[workspaces.get_workspace_service] = lambda: service
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(workspaces, "seed_workspace", AsyncMock())
            response = TestClient(app).post("/v1/workspaces", json={"name": "New"})
    finally:
        app.dependency_overrides.pop(get_principal, None)
        app.dependency_overrides.pop(workspaces.get_workspace_service, None)

    assert response.status_code == 201, response.text
    assert response.json()["can_administer"] is True


def test_an_unresolved_principal_is_resolved_rather_than_denied(monkeypatch) -> None:
    resolve_admin = AsyncMock(return_value=["ws-acme"])
    monkeypatch.setattr(workspaces, "administered_workspace_ids", resolve_admin)

    listed = _list(_alice(admin_workspaces=None))

    resolve_admin.assert_awaited_once_with("alice")
    assert listed == {"alice": True, "acme": True, "other": False}


def test_the_authorization_service_sees_the_context_a_gated_route_would() -> None:
    seen: list[UserContext] = []

    class Recording(WorkspaceScopedAuthorizationService):
        async def can_administer_workspace(self, user_context, workspace_id):
            seen.append(user_context)
            return await super().can_administer_workspace(user_context, workspace_id)

    get_container().register_singleton(AuthorizationService, Recording())

    _list(_alice())

    assert {(c.workspace_id, c.workspace_slug) for c in seen} == {
        ("alice", "alice"),
        ("ws-acme", "acme"),
        ("ws-other", "other"),
    }
    assert all(c.accessible_workspaces for c in seen)


@pytest.mark.asyncio
async def test_the_mcp_workspaces_list_carries_the_same_answer(monkeypatch) -> None:
    @asynccontextmanager
    async def _session():
        yield object()

    monkeypatch.setattr(
        workspaces_toolset,
        "get_database",
        lambda: SimpleNamespace(async_session_factory=_session),
    )
    monkeypatch.setattr(workspaces_toolset, "get_workspace_service", lambda *_: _service())

    with use_mcp_user_context(_alice()):
        listed = json.loads(await WorkspacesToolset().list())

    assert {w["slug"]: w["can_administer"] for w in listed} == {
        "alice": True,
        "acme": True,
        "other": False,
    }
