"""Reads that expose the workspace's security posture require authority over it.

Declaring authorization on reads (2026-09-23) turned up endpoints that any
member could call: the audit log, the usage ledger, the API key inventory and
-- worst of the set -- ``GET /v1/workspaces/{WORKSPACE}/mcp-oauth-links/{id}``, whose response model
carries a live ``token``. Nothing about workspace scoping stopped any of it;
workspace scoping answers "whose data", never "which of us may see it".

The full route table is covered by ``test_authz_ratchet``; this test proves the
markers on the admin-grade reads actually deny, rather than merely being
present.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from agentarea_api.api.v1.router import workspace_v1_router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from fastapi import FastAPI
from fastapi.testclient import TestClient

WORKSPACE = "ws-acme"
SOME_ID = str(uuid4())

ADMIN_READS = [
    f"/v1/workspaces/{WORKSPACE}/access-control/graph",
    f"/v1/workspaces/{WORKSPACE}/access-control/relationships",
    f"/v1/workspaces/{WORKSPACE}/api-keys/",
    f"/v1/workspaces/{WORKSPACE}/api-keys/{SOME_ID}",
    f"/v1/workspaces/{WORKSPACE}/audit-logs/",
    f"/v1/workspaces/{WORKSPACE}/mcp-auth-configs/",
    f"/v1/workspaces/{WORKSPACE}/mcp-auth-configs/{SOME_ID}",
    f"/v1/workspaces/{WORKSPACE}/mcp-oauth-links/{SOME_ID}",
    f"/v1/workspaces/{WORKSPACE}/mcp-oauth-links/instance/{SOME_ID}",
    f"/v1/workspaces/{WORKSPACE}/mcp-server-instances/{SOME_ID}/environment",
    f"/v1/workspaces/{WORKSPACE}/mcp-server-instances/{SOME_ID}/oauth-links",
    f"/v1/workspaces/{WORKSPACE}/network/people-access",
    f"/v1/workspaces/{WORKSPACE}/policies",
    f"/v1/workspaces/{WORKSPACE}/policies/{SOME_ID}",
    f"/v1/workspaces/{WORKSPACE}/usage/events",
    f"/v1/workspaces/{WORKSPACE}/export",
    f"/v1/workspaces/{WORKSPACE}/invitations",
]


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _client(context: UserContext) -> TestClient:
    app = FastAPI()
    app.include_router(workspace_v1_router)
    app.dependency_overrides[get_user_context] = lambda: context
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", ADMIN_READS)
def test_a_member_cannot_read_the_workspaces_security_posture(path: str) -> None:
    client = _client(UserContext(user_id="user-member", workspace_id=WORKSPACE))

    assert client.get(path).status_code == 403, path


@pytest.mark.parametrize("path", ADMIN_READS)
def test_the_owner_is_not_locked_out(path: str) -> None:
    """The gate must let the person it exists to protect through to the handler.

    Past the guard the request reaches real services with no database behind
    them, so anything but 403 means the authority check itself passed.
    """
    client = _client(
        UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
    )

    assert client.get(path).status_code != 403, path
