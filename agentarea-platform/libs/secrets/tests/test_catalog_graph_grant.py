"""A user secret whose ownership the graph could not record is taken back out."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.auth import UserContext
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.permission import PermissionService
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.rebac.ownership import ResourceOwnershipError
from agentarea_common.testing import TestSecretManager
from agentarea_secrets import catalog_service
from agentarea_secrets.catalog_service import (
    SecretAccessDeniedError,
    SecretCatalogService,
    named_secret_for_use,
)


async def test_a_failed_grant_removes_the_value_and_raises(monkeypatch):
    secret = SimpleNamespace(id=uuid4(), secret_name="api-key")
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    store = TestSecretManager()
    catalog = SecretCatalogService(session, UserContext(user_id="u", workspace_id="ws"), store)
    monkeypatch.setattr(catalog, "get_by_name", AsyncMock(return_value=secret))
    monkeypatch.setattr(
        catalog_service,
        "grant_resource_owner",
        AsyncMock(side_effect=ResourceOwnershipError("graph down")),
    )

    with pytest.raises(ResourceOwnershipError):
        await catalog.create_user_secret("api-key", "value-1234", None)

    assert await store.get_secret("api-key") is None
    session.rollback.assert_awaited()


def _row(created_by: str, granted: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        secret_name="api-key",
        owner_type=None,
        created_by=created_by,
        graph_granted_at=datetime.now(UTC) if granted else None,
    )


class _Graph:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.asked = 0

    async def check(self, subject, permission, resource_type, resource_id) -> bool:
        self.asked += 1
        return self.allowed


@pytest.mark.parametrize(
    ("user_id", "admin_workspaces", "allowed"),
    [("creator", [], True), ("admin", ["ws"], True), ("member", [], False)],
)
async def test_a_secret_not_yet_in_the_graph_follows_the_rule_it_was_created_under(
    monkeypatch, user_id, admin_workspaces, allowed
):
    graph = _Graph(allowed=False)
    register_singleton(PermissionService, graph)
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    monkeypatch.setattr(catalog_service, "find_secret", AsyncMock(return_value=_row("creator", False)))
    caller = UserContext(user_id=user_id, workspace_id="ws", admin_workspaces=admin_workspaces)

    if allowed:
        await named_secret_for_use(AsyncMock(), caller, "api-key")
    else:
        with pytest.raises(SecretAccessDeniedError):
            await named_secret_for_use(AsyncMock(), caller, "api-key")
    assert graph.asked == 0


async def test_once_granted_only_the_graph_decides(monkeypatch):
    graph = _Graph(allowed=False)
    register_singleton(PermissionService, graph)
    monkeypatch.setattr(catalog_service, "find_secret", AsyncMock(return_value=_row("creator", True)))

    with pytest.raises(SecretAccessDeniedError):
        await named_secret_for_use(AsyncMock(), UserContext(user_id="creator", workspace_id="ws"), "api-key")
    assert graph.asked == 1
