"""Giving or taking a role on a resource leaves an entry in the audit trail.

A grant changes who may act on an agent or a connection as surely as inviting a
member does; before this it changed the graph and left no record of who did it.
"""

from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.deps.services import get_db_session
from agentarea_api.api.v1 import access_control
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from fastapi.testclient import TestClient

WORKSPACE = "ws-acme"
ADMIN = UserContext(user_id="admin-user", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
GRANT = {
    "namespace": "Agent",
    "object": "agent-1",
    "relation": "writer",
    "subject_id": "member-user",
}


class _Audit:
    calls: ClassVar[list[tuple]] = []

    def __init__(self, session, user_context) -> None:
        self.user_context = user_context

    async def record(self, action, resource_type, resource_id=None, **fields):
        _Audit.calls.append((self.user_context.user_id, action, resource_type, resource_id, fields))


@pytest.fixture
def client(monkeypatch) -> TestClient:
    _Audit.calls = []
    graph = AsyncMock()
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


@pytest.mark.parametrize(
    ("method", "action"), [("POST", "access.grant"), ("DELETE", "access.revoke")]
)
def test_a_role_change_is_audited(client, method, action):
    response = client.request(
        method, f"/v1/workspaces/{WORKSPACE}/access-control/relationships", json=GRANT
    )

    assert response.status_code < 300, response.text
    assert _Audit.calls == [
        (
            "admin-user",
            action,
            "access_grant",
            "agent-1",
            {
                "event_metadata": {
                    "namespace": "Agent",
                    "relation": "writer",
                    "subject_id": "member-user",
                }
            },
        )
    ]
