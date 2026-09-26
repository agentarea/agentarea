"""The MCP instance proxy acts in the instance's workspace.

``/v1/mcp/{instance_id}/mcp`` names no workspace. The binder locates the
instance across workspaces and binds its workspace, provided the caller
reaches it; a foreign, unknown or malformed id answers like a missing one.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.v1.mcp_proxy import bind_mcp_instance_workspace
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import (
    UserContextDep,
    authenticate_principal,
    get_principal,
)
from agentarea_common.config.database import get_read_db_session
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

INSTANCE_ID = uuid4()


def _session(workspace_id: str | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = workspace_id
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _client(located_in: str | None, reaches: list[str]) -> TestClient:
    app = FastAPI()

    @app.get("/v1/mcp/{instance_id}/mcp", dependencies=[Depends(bind_mcp_instance_workspace)])
    async def where(instance_id: str, ctx: UserContextDep) -> dict:
        return {"workspace_id": ctx.workspace_id, "workspace_slug": ctx.workspace_slug}

    principal = UserPrincipal(user_id="caller", accessible_workspaces=reaches)
    app.dependency_overrides[get_principal] = lambda: principal
    app.dependency_overrides[authenticate_principal] = lambda: principal
    app.dependency_overrides[get_read_db_session] = lambda: _session(located_in)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _slug():
    with patch(
        "agentarea_api.api.v1.mcp_proxy.workspace_slug_for",
        new=AsyncMock(return_value="acme"),
    ):
        yield


def test_the_instance_workspace_is_bound():
    response = _client("ws-acme", ["ws-acme"]).get(f"/v1/mcp/{INSTANCE_ID}/mcp")

    assert response.status_code == 200, response.text
    assert response.json() == {"workspace_id": "ws-acme", "workspace_slug": "acme"}


def test_a_foreign_instance_is_not_found():
    assert _client("ws-other", ["ws-acme"]).get(f"/v1/mcp/{INSTANCE_ID}/mcp").status_code == 404


def test_an_unknown_instance_is_not_found():
    assert _client(None, ["ws-acme"]).get(f"/v1/mcp/{INSTANCE_ID}/mcp").status_code == 404


def test_a_malformed_instance_id_is_not_found_rather_than_a_server_error():
    assert _client("ws-acme", ["ws-acme"]).get("/v1/mcp/0/mcp").status_code == 404
