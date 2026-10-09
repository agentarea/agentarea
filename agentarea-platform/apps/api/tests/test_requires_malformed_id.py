"""A malformed object id is the caller's mistake, never a graph query.

``requires(id_param=...)`` runs before FastAPI validates the handler's own path
parameters, so the raw path string used to reach the PDP. OpenFGA rejects an
object id it cannot parse, and the fuzz suite saw that as a 500. The id is
validated first: the route answers 422 like any malformed UUID path parameter,
the tool answers with its JSON error, and the PDP is never asked.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_agents_sdk.tools.tool_authz import requires as tool_requires
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.permission import PermissionService
from agentarea_common.auth.route_authz import requires
from agentarea_common.di.container import get_container
from fastapi import FastAPI
from fastapi.testclient import TestClient

CALLER = UserContext(user_id="user-1", workspace_id="ws-1")


class _RecordingPermissions(PermissionService):
    def __init__(self) -> None:
        self.checked: list[str] = []

    async def check(self, user_id, permission, resource_type, resource_id) -> bool:
        self.checked.append(resource_id)
        return True


@pytest.fixture
def permissions():
    container = get_container()
    saved = dict(container._singletons)
    recorder = _RecordingPermissions()
    container.register_singleton(PermissionService, recorder)
    yield recorder
    container._singletons.clear()
    container._singletons.update(saved)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.delete(
        "/things/{thing_id}", dependencies=[requires("delete", "thing", id_param="thing_id")]
    )
    async def delete_thing(thing_id: UUID) -> dict:
        return {"id": str(thing_id)}

    app.dependency_overrides[get_user_context] = lambda: CALLER
    return TestClient(app)


@pytest.mark.parametrize("raw", ["not-a-uuid", "a b#c", "x" * 300])
def test_route_rejects_a_malformed_id_before_the_pdp(client, permissions, raw) -> None:
    response = client.delete(f"/things/{raw}")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "thing_id"]
    assert permissions.checked == []


def test_route_checks_a_well_formed_id(client, permissions) -> None:
    thing_id = uuid4()

    response = client.delete(f"/things/{thing_id}")

    assert response.status_code == 200
    assert permissions.checked == [str(thing_id)]


class _Things:
    @tool_requires("delete", "thing", id_param="thing_id")
    async def delete(self, thing_id: str) -> str:
        return json.dumps({"deleted": thing_id})


@pytest.mark.asyncio
async def test_tool_rejects_a_malformed_id_before_the_pdp(permissions) -> None:
    with use_mcp_user_context(CALLER):
        result = json.loads(await _Things().delete(thing_id="not-a-uuid"))

    assert "thing_id" in result["error"]
    assert permissions.checked == []


@pytest.mark.asyncio
async def test_tool_checks_a_well_formed_id(permissions) -> None:
    thing_id = str(uuid4())

    with use_mcp_user_context(CALLER):
        result = json.loads(await _Things().delete(thing_id=thing_id))

    assert result == {"deleted": thing_id}
    assert permissions.checked == [thing_id]
