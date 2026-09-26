"""The inbox status filter is a closed vocabulary.

An unknown ``status`` used to be dropped silently, returning every inbox status
as if no filter had been asked for. Typing it publishes the vocabulary in the
OpenAPI schema too, which is what the webapp maps its filters against.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.api.v1.inbox import INBOX_STATUSES
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def task_repository():
    repository = MagicMock()
    repository.list_by_statuses = AsyncMock(return_value=[])
    repository.count_by_statuses = AsyncMock(return_value=0)
    task_service = MagicMock()
    task_service.task_repository = repository
    agent_service = AsyncMock()
    agent_service.list.return_value = []

    app.dependency_overrides[get_read_task_service] = lambda: task_service
    app.dependency_overrides[get_read_agent_service] = lambda: agent_service
    app.dependency_overrides[get_user_context] = lambda: MagicMock()
    try:
        yield repository
    finally:
        for dep in (get_read_task_service, get_read_agent_service, get_user_context):
            app.dependency_overrides.pop(dep, None)


@pytest.mark.asyncio
async def test_an_unknown_status_is_rejected(async_client, task_repository) -> None:
    response = await async_client.get("/v1/workspaces/acme/inbox/?status=running")

    assert response.status_code == 422, response.text
    task_repository.list_by_statuses.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_known_status_narrows_the_query(async_client, task_repository) -> None:
    response = await async_client.get("/v1/workspaces/acme/inbox/?status=waiting_for_input")

    assert response.status_code == 200, response.text
    assert task_repository.list_by_statuses.await_args.kwargs["statuses"] == ["waiting_for_input"]


@pytest.mark.asyncio
async def test_no_status_asks_for_the_whole_vocabulary(async_client, task_repository) -> None:
    response = await async_client.get("/v1/workspaces/acme/inbox/")

    assert response.status_code == 200, response.text
    assert task_repository.list_by_statuses.await_args.kwargs["statuses"] == list(INBOX_STATUSES)
