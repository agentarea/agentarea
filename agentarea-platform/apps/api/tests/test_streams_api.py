from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.v1.streams import get_stream_service
from agentarea_api.main import app
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.openfga_permission import OpenFGAPermissionService
from agentarea_common.auth.permission import PermissionService
from agentarea_common.config.database import get_db_session
from agentarea_common.di.container import get_container
from agentarea_common.rebac.openfga_client import OpenFGAClient
from agentarea_streams.domain import ForwardLoopError, JournaledEvent, StreamNameTakenError
from httpx import ASGITransport, AsyncClient

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _stream(name="feed"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description="",
        kind="custom",
        retention_days=30,
        workspace_id="ws",
        created_by="u",
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def graph():
    client = AsyncMock(spec=OpenFGAClient)
    client.check.return_value = SimpleNamespace(allowed=True)
    client.list_objects.return_value = []
    container = get_container()
    container.register_singleton(OpenFGAClient, client)
    container.register_singleton(PermissionService, OpenFGAPermissionService(client))
    yield client
    container.clear()


@pytest.fixture
def service():
    svc = AsyncMock()
    app.dependency_overrides[get_stream_service] = lambda: svc
    app.dependency_overrides[get_user_context] = lambda: UserContext(user_id="u", workspace_id="ws")
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    yield svc
    for dep in (get_stream_service, get_user_context, get_db_session):
        app.dependency_overrides.pop(dep, None)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.mark.asyncio
async def test_the_list_shows_only_streams_the_graph_allows(client, service, graph):
    mine = _stream("mine")
    service.list_streams.return_value = [mine]
    graph.list_objects.return_value = [str(mine.id)]
    response = await client.get("/v1/workspaces/acme/streams/")
    assert response.status_code == 200, response.text
    assert [s["name"] for s in response.json()] == ["mine"]
    assert service.list_streams.await_args.kwargs["ids"] == {str(mine.id)}


@pytest.mark.asyncio
async def test_events_come_with_every_subscription_outcome(client, service, graph):
    stream = _stream()
    sub_id, task_id = uuid4(), uuid4()
    event = JournaledEvent(
        type="push",
        source="webhook:github",
        data={"n": 1},
        stream_id=stream.id,
        sequence=41,
        event_key="k",
        received_at=NOW,
    )
    service.get_stream.return_value = stream
    service.list_events.return_value = [event]
    service.list_subscriptions.return_value = [
        SimpleNamespace(
            id=sub_id,
            kind="trigger",
            trigger_id=uuid4(),
            filter={},
            output_stream_ids=[],
            cursor_sequence=41,
            status="active",
            attempts=0,
            last_error=None,
            next_attempt_at=None,
            created_at=NOW,
        )
    ]
    service.outcomes_for.return_value = [
        SimpleNamespace(
            subscription_id=sub_id,
            event_sequence=41,
            verdict="reacted",
            reason="refund",
            score=0.8,
            task_id=task_id,
            derived_sequences=[],
            created_at=NOW,
        )
    ]
    response = await client.get(f"/v1/workspaces/acme/streams/{stream.id}/events?after=40")
    assert response.status_code == 200, response.text
    page = response.json()
    (row,) = page["events"]
    assert row["sequence"] == 41
    assert row["outcomes"][0]["verdict"] == "reacted"
    assert row["outcomes"][0]["task_id"] == str(task_id)
    assert row["outcomes"][0]["subscription_kind"] == "trigger"
    assert page["next_after"] is None
    one = await client.get(f"/v1/workspaces/acme/streams/{stream.id}/events?after=40&limit=1")
    assert one.json()["next_after"] == 41


@pytest.mark.asyncio
async def test_a_forward_into_itself_is_a_400(client, service, graph):
    stream = _stream()
    service.create_forward.side_effect = ForwardLoopError(
        "A forward may not write into its own input stream"
    )
    response = await client.post(
        f"/v1/workspaces/acme/streams/{stream.id}/forwards",
        json={"output_stream_ids": [str(stream.id)]},
    )
    assert response.status_code == 400
    assert "own input" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_webhook_source_shows_its_public_url(client, service, graph, monkeypatch):
    monkeypatch.setattr(
        "agentarea_api.api.v1.streams.public_webhook_url",
        lambda wid: f"https://api.example/webhooks/{wid}",
    )
    stream = _stream()
    service.get_stream.return_value = stream
    service.list_sources.return_value = [
        SimpleNamespace(
            id=uuid4(),
            kind="webhook",
            webhook_id="abc",
            webhook_type="github",
            allowed_methods=["POST"],
            created_at=NOW,
        )
    ]
    response = await client.get(f"/v1/workspaces/acme/streams/{stream.id}/sources")
    assert response.json()[0]["webhook_url"] == "https://api.example/webhooks/abc"


@pytest.mark.asyncio
async def test_a_stream_name_already_taken_is_a_conflict(client, service, graph):
    service.create_stream.side_effect = StreamNameTakenError("orders")
    response = await client.post("/v1/workspaces/acme/streams/", json={"name": "orders"})
    assert response.status_code == 409, response.text
    assert "orders" in response.json()["detail"]
