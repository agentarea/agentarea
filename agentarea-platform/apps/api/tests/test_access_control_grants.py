"""Tests for access-control bootstrap grant helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import _access_control_grants as grants
from agentarea_common.rebac import OpenFGAError, OpenFGAUnavailableError
from fastapi import HTTPException


def _settings(backend: str):
    return SimpleNamespace(
        access_control=SimpleNamespace(ACCESS_CONTROL_BACKEND=backend),
    )


class _Container:
    def __init__(self, client=None, error: Exception | None = None):
        self.client = client
        self.error = error

    def get(self, _client_type):
        if self.error is not None:
            raise self.error
        return self.client


@pytest.mark.asyncio
async def test_grant_resource_owner_fails_when_graph_client_missing(monkeypatch):
    monkeypatch.setattr(grants, "get_settings", lambda: _settings("openfga"))
    monkeypatch.setattr(grants, "get_container", lambda: _Container(error=ValueError("missing")))

    with pytest.raises(HTTPException) as exc:
        await grants.grant_resource_owner(
            resource_id="agent-1",
            workspace_id="ws-1",
            user_id="user-1",
        )

    assert exc.value.status_code == 503
    assert "unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_grant_resource_owner_fails_when_graph_write_fails(monkeypatch):
    client = SimpleNamespace(write_tuple=AsyncMock(side_effect=OpenFGAUnavailableError("down")))
    monkeypatch.setattr(grants, "get_settings", lambda: _settings("openfga"))
    monkeypatch.setattr(grants, "get_container", lambda: _Container(client=client))

    with pytest.raises(HTTPException) as exc:
        await grants.grant_resource_owner(
            resource_id="agent-1",
            workspace_id="ws-1",
            user_id="user-1",
        )

    assert exc.value.status_code == 503
    assert "write failed" in exc.value.detail


@pytest.mark.asyncio
async def test_grant_resource_owner_treats_existing_tuple_as_success(monkeypatch):
    client = SimpleNamespace(
        write_tuple=AsyncMock(
            side_effect=OpenFGAError(
                "write failed (400): cannot write a tuple which already exists"
            )
        )
    )
    monkeypatch.setattr(grants, "get_settings", lambda: _settings("openfga"))
    monkeypatch.setattr(grants, "get_container", lambda: _Container(client=client))

    # Every write reports "already exists"; all are treated as success. The owner
    # bootstrap writes the project attachment plus the three permission bits.
    await grants.grant_resource_owner(
        resource_id="agent-1",
        workspace_id="ws-1",
        user_id="user-1",
    )

    assert client.write_tuple.await_count == 4
