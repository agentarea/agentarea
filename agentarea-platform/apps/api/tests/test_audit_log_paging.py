"""Paging the audit log neither restarts nor promises a page that is not there.

An unknown ``cursor`` used to be ignored, so the request silently answered with
page one again and a client walking the log looped over it forever. And
``next_cursor`` was set whenever the page had any event at all, so the last
page still pointed at one more, empty, page.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import audit
from agentarea_common.audit.repository import UnknownAuditCursorError
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.config.database import get_db_session
from agentarea_common.di.container import register_singleton
from fastapi import FastAPI
from fastapi.testclient import TestClient

WORKSPACE = "ws-acme"
URL = f"/v1/workspaces/{WORKSPACE}/audit-logs/"


def _event():
    return SimpleNamespace(
        id=uuid4(),
        created_at=datetime(2026, 10, 9, 12, 0),
        actor_id="u",
        actor_type="user",
        workspace_id=WORKSPACE,
        source_ip=None,
        user_agent=None,
        request_id=None,
        action="agent.create",
        resource_type="agent",
        resource_id=None,
        changes=None,
        event_metadata={},
    )


@pytest.fixture
def repository(monkeypatch):
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    repo = MagicMock()
    repo.query = AsyncMock(return_value=[])
    monkeypatch.setattr(audit, "AuditRepository", lambda _session: repo)
    return repo


@pytest.fixture
def client(repository):
    app = FastAPI()
    app.include_router(audit.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE]
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    return TestClient(app)


def test_an_unknown_cursor_is_a_400_not_page_one(client, repository) -> None:
    cursor = uuid4()
    repository.query.side_effect = UnknownAuditCursorError(f"Unknown audit cursor {cursor}")

    response = client.get(URL, params={"cursor": str(cursor)})

    assert response.status_code == 400, response.text
    assert str(cursor) in response.json()["detail"]


def test_a_full_page_points_at_the_next_one(client, repository) -> None:
    events = [_event(), _event()]
    repository.query.return_value = events

    body = client.get(URL, params={"limit": 2}).json()

    assert body["next_cursor"] == str(events[-1].id)


def test_a_short_page_is_the_last_one(client, repository) -> None:
    repository.query.return_value = [_event()]

    body = client.get(URL, params={"limit": 2}).json()

    assert len(body["events"]) == 1
    assert body["next_cursor"] is None


def test_an_empty_page_has_no_next_cursor(client, repository) -> None:
    assert client.get(URL).json() == {"events": [], "next_cursor": None}
