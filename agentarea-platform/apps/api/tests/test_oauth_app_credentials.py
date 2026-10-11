"""A workspace's own OAuth app: which of its secrets a Connect flow may read."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.oauth_app_credentials import workspace_secret_value
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_secrets.catalog_service import SecretCatalogService
from fastapi import HTTPException


def _catalog_holding(secret, user_id: str, admin_workspaces: list[str]) -> SecretCatalogService:
    """The catalog's own selection rule, over a session that finds ``secret``."""
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: secret)
    user = UserContext(user_id=user_id, workspace_id="ws", admin_workspaces=admin_workspaces)
    return SecretCatalogService(session, user, AsyncMock())


def _user_secret(created_by: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        secret_name="member_a_client_id",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
        owner_id=None,
        created_by=created_by,
    )


@pytest.mark.asyncio
async def test_workspace_secret_source_rejects_connection_owned_secret():
    secret = SimpleNamespace(
        id=uuid4(),
        secret_name="mcp_auth_cred:managed",  # noqa: S106  # pragma: allowlist secret
        owner_type="mcp_auth_config",
        owner_id=str(uuid4()),
        created_by="admin",
    )
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="must-not-be-read"))

    with pytest.raises(HTTPException, match="must be a user-owned workspace secret"):
        await workspace_secret_value(
            _catalog_holding(secret, "admin", ["ws"]),
            manager,
            secret.id,
            "client secret",
        )

    manager.get_secret.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_secret_source_refuses_another_members_secret():
    # The client ID comes back inside the authorize URL, so selecting a
    # secret someone else created would read its plaintext.
    secret = _user_secret(created_by="member-a")
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="member-a-value"))

    with pytest.raises(HTTPException) as exc_info:
        await workspace_secret_value(
            _catalog_holding(secret, "member-b", []), manager, secret.id, "client ID"
        )

    assert exc_info.value.status_code == 403
    manager.get_secret.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "admin_workspaces"), [("member-a", []), ("workspace-admin", ["ws"])]
)
async def test_workspace_secret_source_allows_the_creator_or_an_admin(user_id, admin_workspaces):
    secret = _user_secret(created_by="member-a")
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="member-a-value"))

    resolved, value = await workspace_secret_value(
        _catalog_holding(secret, user_id, admin_workspaces), manager, secret.id, "client ID"
    )

    assert resolved is secret
    assert value == "member-a-value"
