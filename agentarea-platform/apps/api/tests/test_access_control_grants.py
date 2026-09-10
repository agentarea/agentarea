"""A failed ownership grant reaches the client as 503, not as a 500 or a shrug.

The grant itself moved to ``agentarea_common.rebac.ownership`` so that every
creation path writes it (see
``libs/common/tests/test_graph_resource_ownership.py``). What this module still
covers is the API's half of the contract: the graph being down, or not wired up
at all, must surface as a retryable failure, because the tuples are idempotent
and the alternative -- a committed row nobody can reach -- is worse.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import _access_control_grants as grants
from agentarea_common.rebac import OpenFGAError, OpenFGAUnavailableError, ownership
from fastapi import HTTPException


def _settings(backend: str):
    return SimpleNamespace(
        access_control=SimpleNamespace(BACKEND=backend),
    )


class _Container:
    def __init__(self, client=None, error: Exception | None = None):
        self.client = client
        self.error = error

    def get(self, _client_type):
        if self.error is not None:
            raise self.error
        return self.client


@pytest.fixture
def graph(monkeypatch):
    """Install a container and settings the ownership module will resolve."""

    def _install(client=None, error: Exception | None = None):
        monkeypatch.setattr("agentarea_common.config.get_settings", lambda: _settings("openfga"))
        monkeypatch.setattr(
            "agentarea_common.di.container.get_container",
            lambda: _Container(client=client, error=error),
        )

    return _install


@pytest.mark.asyncio
async def test_grant_resource_owner_fails_when_graph_client_missing(graph):
    graph(error=ValueError("missing"))

    with pytest.raises(HTTPException) as exc:
        await grants.grant_resource_owner(
            resource_id="agent-1",
            workspace_id="ws-1",
            user_id="user-1",
        )

    assert exc.value.status_code == 503
    assert "cannot be recorded" in exc.value.detail


@pytest.mark.asyncio
async def test_grant_resource_owner_fails_when_graph_write_fails(graph):
    graph(
        client=SimpleNamespace(write_tuple=AsyncMock(side_effect=OpenFGAUnavailableError("down")))
    )

    with pytest.raises(HTTPException) as exc:
        await grants.grant_resource_owner(
            resource_id="agent-1",
            workspace_id="ws-1",
            user_id="user-1",
        )

    assert exc.value.status_code == 503
    assert "write failed" in exc.value.detail


@pytest.mark.asyncio
async def test_grant_resource_owner_treats_existing_tuple_as_success(graph):
    client = SimpleNamespace(
        write_tuple=AsyncMock(
            side_effect=OpenFGAError(
                "write failed (400): cannot write a tuple which already exists"
            )
        )
    )
    graph(client=client)

    # Every write reports "already exists"; all are treated as success. The owner
    # bootstrap writes the project attachment plus the three permission bits.
    await grants.grant_resource_owner(
        resource_id="agent-1",
        workspace_id="ws-1",
        user_id="user-1",
    )

    assert client.write_tuple.await_count == 1 + len(ownership.OWNER_RELATIONS)


@pytest.mark.asyncio
async def test_seeding_a_workspace_reports_an_unreachable_graph(graph):
    graph(
        client=SimpleNamespace(write_tuple=AsyncMock(side_effect=OpenFGAUnavailableError("down")))
    )

    with pytest.raises(HTTPException) as exc:
        await grants.seed_workspace(workspace_id="ws-1", creator_user_id="user-1")

    assert exc.value.status_code == 503
