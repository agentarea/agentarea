"""An agent may not mint a workspace credential its owner could not mint.

``POST /v1/secrets`` requires workspace admin. ``agentarea/secrets.create``
reached the same catalog with no authority check at all, so the gate held on one
door and not on the other: a member who could not create a workspace secret
through the API could create one by asking an agent to.

The reason the second door could not simply copy the first is recorded in
``workspaces/authority.py`` -- ``admin_workspaces`` was filled only by the HTTP
request dependency, so the check would have denied the workspace owner too.
"""

from __future__ import annotations

import json

import pytest
from agentarea_api.tools.secrets_toolset import SecretsToolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton

WORKSPACE = "ws-acme"


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


@pytest.fixture
def catalog(monkeypatch):
    """Record whether the catalog was reached at all."""
    calls: list[str] = []

    class _Catalog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def create_user_secret(self, name, value, description=None):
            calls.append(f"create:{name}")
            raise AssertionError("the guard must run before the catalog is touched")

        async def get_by_name(self, name):
            calls.append(f"get:{name}")
            raise AssertionError("the guard must run before the catalog is touched")

    monkeypatch.setattr("agentarea_api.tools.secrets_toolset.SecretCatalogService", _Catalog)
    return calls


@pytest.fixture
def context(monkeypatch):
    """A platform-tool context with a stubbed session and secret manager."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    @asynccontextmanager
    async def _ctx():
        yield AsyncMock(), _ctx.user, AsyncMock(), AsyncMock(), AsyncMock()

    monkeypatch.setattr("agentarea_api.tools.secrets_toolset.platform_context", _ctx)
    return _ctx


@pytest.mark.asyncio
async def test_a_member_cannot_mint_a_secret_through_an_agent(catalog, context) -> None:
    context.user = UserContext(user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[])

    result = json.loads(await SecretsToolset().create("STRIPE_KEY", "sk-live-x"))

    assert result["created"] is False
    assert "admin" in result["error"].lower()
    assert catalog == [], "the guard must run before the catalog is touched"


@pytest.mark.asyncio
async def test_a_member_cannot_delete_a_secret_through_an_agent(catalog, context) -> None:
    context.user = UserContext(user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[])

    result = json.loads(await SecretsToolset().delete("STRIPE_KEY"))

    assert result["deleted"] is False
    assert catalog == []


@pytest.mark.asyncio
async def test_the_owner_still_reaches_the_catalog(catalog, context) -> None:
    """The gate must not lock out the person it exists to protect."""
    context.user = UserContext(
        user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE]
    )

    with pytest.raises(AssertionError, match="before the catalog"):
        await SecretsToolset().create("STRIPE_KEY", "sk-live-x")
