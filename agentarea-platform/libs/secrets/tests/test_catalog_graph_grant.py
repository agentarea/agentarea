"""A user secret whose ownership the graph could not record is taken back out."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.auth import UserContext
from agentarea_common.rebac.ownership import ResourceOwnershipError
from agentarea_common.testing import TestSecretManager
from agentarea_secrets import catalog_service
from agentarea_secrets.catalog_service import SecretCatalogService


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
