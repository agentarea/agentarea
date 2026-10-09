"""Granting and revoking a role is idempotent, as OpenFGA's tuples are not.

OpenFGA refuses to write a tuple that exists and to delete one that does not.
The explorer passed both refusals through as 503 "Graph authorization ... failed":
granting a role twice -- or ``viewers`` after ``reader``, which name the same
grant -- and revoking a role already gone looked like an outage (#717).

A grant that changes nothing is not audited again; a real outage stays a 503.
"""

from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.deps.services import get_db_session
from agentarea_api.api.v1 import access_control
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.rebac import OpenFGAError, OpenFGAUnavailableError, RelationTuple
from fastapi import FastAPI
from fastapi.testclient import TestClient

WORKSPACE = "ws-acme"
ADMIN = UserContext(user_id="admin-user", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
GRANT = {
    "namespace": "SkillCollection",
    "object": "collection-1",
    "relation": "reader",
    "subject_id": "User:member-user",
}
URL = f"/v1/workspaces/{WORKSPACE}/access-control/relationships"


class OpenFGALikeGraph:
    """Holds tuples and refuses writes the way OpenFGA does."""

    def __init__(self) -> None:
        self.tuples: list[RelationTuple] = []
        self.down = False

    async def write_tuple(self, relationship: RelationTuple) -> None:
        if self.down:
            raise OpenFGAUnavailableError("OpenFGA write unreachable")
        if relationship in self.tuples:
            raise OpenFGAError(
                "write failed (400): cannot write a tuple which already exists: "
                f"user: '{relationship.subject_id}', relation: '{relationship.relation}'"
            )
        self.tuples.append(relationship)

    async def delete_tuple(self, relationship: RelationTuple) -> None:
        if self.down:
            raise OpenFGAUnavailableError("OpenFGA write unreachable")
        if relationship not in self.tuples:
            raise OpenFGAError(
                "write failed (400): cannot delete a tuple which does not exist: "
                f"user: '{relationship.subject_id}', relation: '{relationship.relation}'"
            )
        self.tuples.remove(relationship)


class _Audit:
    calls: ClassVar[list[str]] = []

    def __init__(self, session, user_context) -> None:
        pass

    async def record(self, action, resource_type, resource_id=None, **fields):
        _Audit.calls.append(action)


@pytest.fixture
def graph() -> OpenFGALikeGraph:
    return OpenFGALikeGraph()


@pytest.fixture
def client(monkeypatch, graph) -> TestClient:
    _Audit.calls = []
    monkeypatch.setattr(access_control, "get_graph_client", lambda: graph)
    monkeypatch.setattr(access_control, "_assert_workspace_admin", AsyncMock())
    monkeypatch.setattr(access_control, "_assert_object_in_workspace", AsyncMock())
    monkeypatch.setattr(access_control, "_assert_subject_in_workspace", AsyncMock())
    monkeypatch.setattr(access_control, "AuditService", _Audit)
    app = FastAPI()
    app.include_router(access_control.router, prefix="/v1/workspaces/{workspace}/access-control")
    app.dependency_overrides[get_user_context] = lambda: ADMIN
    app.dependency_overrides[get_db_session] = lambda: object()
    return TestClient(app)


def test_granting_the_same_role_twice_succeeds_and_is_audited_once(client, graph):
    first = client.post(URL, json=GRANT)
    second = client.post(URL, json=GRANT)

    assert (first.status_code, second.status_code) == (201, 201), second.text
    assert len(graph.tuples) == 1
    assert _Audit.calls == ["access.grant"]


def test_a_legacy_alias_of_a_held_role_is_the_same_grant(client, graph):
    client.post(URL, json=GRANT)

    response = client.post(URL, json={**GRANT, "relation": "viewers"})

    assert response.status_code == 201, response.text
    assert {t.relation for t in graph.tuples} == {"reader"}
    assert _Audit.calls == ["access.grant"]


def test_revoking_a_role_already_gone_is_no_content(client, graph):
    client.post(URL, json=GRANT)

    first = client.request("DELETE", URL, json=GRANT)
    second = client.request("DELETE", URL, json=GRANT)

    assert (first.status_code, second.status_code) == (204, 204), second.text
    assert graph.tuples == []
    assert _Audit.calls == ["access.grant", "access.revoke"]


def test_revoking_a_role_never_granted_is_no_content(client):
    response = client.request("DELETE", URL, json=GRANT)

    assert response.status_code == 204, response.text
    assert _Audit.calls == []


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_an_unreachable_graph_is_still_a_503(client, graph, method):
    graph.down = True

    response = client.request(method, URL, json=GRANT)

    assert response.status_code == 503, response.text
    assert _Audit.calls == []
