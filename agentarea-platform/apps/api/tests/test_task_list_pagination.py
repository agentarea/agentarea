"""GET /v1/workspaces/acme/tasks hands status and paging to the repository, and trusts its page.

The endpoint used to accept ``status`` and ``offset`` and then drop them on the
way to the query, filtering and slicing the first ``limit`` rows in memory
instead: ``offset=100`` on a 149-task workspace returned an empty list.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_tasks.domain.models import Task
from agentarea_tasks.domain.statuses import TASK_STATUSES
from httpx import ASGITransport, AsyncClient

AGENT_ID = uuid4()


def _task(status: str) -> Task:
    return Task(
        id=uuid4(),
        agent_id=AGENT_ID,
        description="do the thing",
        parameters={},
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        user_id="user-1",
    )


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def task_repository():
    tasks = [_task("completed"), _task("completed")]
    repository = MagicMock()
    repository.list_page = AsyncMock(return_value=tasks)
    repository._orm_to_domain = MagicMock(side_effect=lambda task: task)

    task_service = MagicMock()
    task_service.task_repository = repository

    agent = MagicMock()
    agent.id = AGENT_ID
    agent.name = "Digest Writer"
    agent_service = AsyncMock()
    agent_service.list.return_value = [agent]

    user_context = MagicMock()
    user_context.user_id = "user-1"
    user_context.workspace_id = "workspace-1"

    app.dependency_overrides[get_read_task_service] = lambda: task_service
    app.dependency_overrides[get_read_agent_service] = lambda: agent_service
    app.dependency_overrides[get_user_context] = lambda: user_context
    try:
        yield repository
    finally:
        for dep in (get_read_task_service, get_read_agent_service, get_user_context):
            app.dependency_overrides.pop(dep, None)


@pytest.mark.asyncio
async def test_status_and_offset_reach_the_query(async_client, task_repository) -> None:
    response = await async_client.get(
        "/v1/workspaces/acme/tasks/?status=failed&limit=50&offset=100"
    )

    assert response.status_code == 200, response.text
    kwargs = task_repository.list_page.await_args.kwargs
    assert kwargs["statuses"] == ["failed"]
    assert kwargs["offset"] == 100
    assert kwargs["limit"] == 50


@pytest.mark.asyncio
async def test_the_page_from_the_query_is_returned_as_is(async_client, task_repository) -> None:
    """No second filter or slice in memory: offset was already applied in SQL."""
    response = await async_client.get("/v1/workspaces/acme/tasks/?status=failed&offset=100")

    assert response.status_code == 200, response.text
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_search_matches_agent_names_through_their_ids(async_client, task_repository) -> None:
    response = await async_client.get("/v1/workspaces/acme/tasks/?search=digest&created_by=user-1")

    assert response.status_code == 200, response.text
    kwargs = task_repository.list_page.await_args.kwargs
    assert kwargs["search"] == "digest"
    assert kwargs["created_by"] == "user-1"
    assert list(kwargs["agent_ids"]) == [AGENT_ID]


@pytest.mark.asyncio
async def test_an_unknown_status_is_rejected(async_client, task_repository) -> None:
    response = await async_client.get("/v1/workspaces/acme/tasks/?status=bogus")

    assert response.status_code == 422, response.text
    task_repository.list_page.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(TASK_STATUSES))
async def test_every_stored_status_can_be_filtered_on(
    async_client, task_repository, status
) -> None:
    response = await async_client.get(f"/v1/workspaces/acme/tasks/?status={status}")

    assert response.status_code == 200, response.text
    assert task_repository.list_page.await_args.kwargs["statuses"] == [status]


@pytest.mark.asyncio
async def test_several_statuses_are_one_filter(async_client, task_repository) -> None:
    """Statuses that read the same on screen are filtered on together."""
    response = await async_client.get("/v1/workspaces/acme/tasks/?status=pending&status=submitted")

    assert response.status_code == 200, response.text
    assert task_repository.list_page.await_args.kwargs["statuses"] == ["pending", "submitted"]
