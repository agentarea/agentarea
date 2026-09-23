"""A workspace member may not rotate or delete the workspace's secrets.

Before 2026-09-22 they could. The secret endpoints carried no authority check
at all, and the check they would have used -- ``assert_workspace_admin`` --
resolved through ``can_write_workspace(ctx, ctx.workspace_id)``, which the
open-core implementation answers as ``workspace_id == user_context.workspace_id``:
true for anyone already acting in that workspace.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_secret_catalog_service
from agentarea_api.api.v1.workspace_secrets import router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from fastapi import FastAPI
from fastapi.testclient import TestClient

SECRET_ID = str(uuid4())


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _client(context: UserContext) -> tuple[TestClient, AsyncMock]:
    catalog = AsyncMock()
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_secret_catalog_service] = lambda: catalog
    app.dependency_overrides[get_user_context] = lambda: context
    return TestClient(app), catalog


def _member() -> UserContext:
    return UserContext(user_id="user-member", workspace_id="ws-acme")


def _owner() -> UserContext:
    return UserContext(user_id="user-owner", workspace_id="ws-acme", admin_workspaces=["ws-acme"])


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/v1/secrets", {"name": "STRIPE_KEY", "value": "sk-live-x"}),
        ("put", f"/v1/secrets/{SECRET_ID}/value", {"value": "sk-live-rotated"}),
        ("delete", f"/v1/secrets/{SECRET_ID}", None),
        ("patch", f"/v1/secrets/{SECRET_ID}", {"description": "renamed"}),
    ],
)
def test_a_member_cannot_mutate_workspace_secrets(method, path, body) -> None:
    client, catalog = _client(_member())

    response = getattr(client, method)(path, **({"json": body} if body else {}))

    assert response.status_code == 403, response.text
    assert not catalog.method_calls, "the guard must run before the catalog is touched"


def test_the_owner_still_rotates_a_secret() -> None:
    """The gate must not lock out the person it exists to protect."""
    client, catalog = _client(_owner())
    catalog.rotate_user_secret.return_value = SimpleNamespace(
        id=SECRET_ID,
        secret_name="STRIPE_KEY",  # noqa: S106 -- a secret's name, not its value
        description=None,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        updated_at=datetime(2026, 9, 22, tzinfo=UTC),
        owner_type=None,
        owner_id=None,
    )
    catalog.consumers.return_value = []

    response = client.put(f"/v1/secrets/{SECRET_ID}/value", json={"value": "sk-live-rotated"})

    assert response.status_code == 200, response.text
    catalog.rotate_user_secret.assert_awaited()
