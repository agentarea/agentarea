"""A member sees the API keys they made; a workspace admin sees every key.

Listing used to be admin-only, which left a member no way to find, and so no
way to revoke, a key they had created themselves. Another member's key stays
invisible: asking for it by id answers 404, as for a key that does not exist,
so ids of colleagues' keys cannot be confirmed.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.api_keys import get_api_key_service, router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from fastapi import FastAPI
from fastapi.testclient import TestClient

MEMBER = UserContext(user_id="user-member", workspace_id="ws-acme", admin_workspaces=[])
ADMIN = UserContext(user_id="user-owner", workspace_id="ws-acme", admin_workspaces=["ws-acme"])


def _key(created_by: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=f"key of {created_by}",
        token_prefix="aat_abcdefgh",  # noqa: S106
        is_active=True,
        expires_at=None,
        access_count=0,
        last_accessed_at=None,
        created_at="2026-09-01T00:00:00Z",
        created_by=created_by,
    )


MINE = _key(MEMBER.user_id)
THEIRS = _key(ADMIN.user_id)


@pytest.fixture(autouse=True)
def _authz():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


def _client(context: UserContext) -> TestClient:
    keys = {MINE.id: MINE, THEIRS.id: THEIRS}

    async def list_tokens(created_by: str | None = None):
        return [k for k in keys.values() if created_by is None or k.created_by == created_by]

    service = AsyncMock()
    service.list_tokens.side_effect = list_tokens
    service.get_token.side_effect = lambda token_id: keys.get(token_id)
    app = FastAPI()
    app.include_router(router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_api_key_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: context
    return TestClient(app)


def test_a_member_lists_only_their_own_keys() -> None:
    response = _client(MEMBER).get("/v1/workspaces/acme/api-keys/")

    assert response.status_code == 200, response.text
    assert [k["id"] for k in response.json()] == [str(MINE.id)]


def test_an_admin_lists_every_key_in_the_workspace() -> None:
    response = _client(ADMIN).get("/v1/workspaces/acme/api-keys/")

    assert response.status_code == 200, response.text
    assert {k["id"] for k in response.json()} == {str(MINE.id), str(THEIRS.id)}


def test_a_member_reads_their_own_key() -> None:
    response = _client(MEMBER).get(f"/v1/workspaces/acme/api-keys/{MINE.id}")

    assert response.status_code == 200, response.text


def test_a_member_asking_for_someone_elses_key_gets_404() -> None:
    response = _client(MEMBER).get(f"/v1/workspaces/acme/api-keys/{THEIRS.id}")

    assert response.status_code == 404, response.text


def test_an_admin_reads_any_key() -> None:
    response = _client(ADMIN).get(f"/v1/workspaces/acme/api-keys/{MINE.id}")

    assert response.status_code == 200, response.text
