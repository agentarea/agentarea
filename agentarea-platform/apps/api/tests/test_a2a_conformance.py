"""The official A2A SDK client can talk to our A2A endpoint.

Our real routes (agent card, JSON-RPC, the shared edge auth dependency) are
mounted in-process and driven by ``a2a.client``; only the domain services
behind them are stubbed. If the SDK cannot resolve the card, parse a result or
follow a stream, a real A2A peer cannot either.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from a2a.client import A2ACardResolver, A2AClientError, ClientConfig, ClientFactory
from a2a.types import (
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTasksRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    SubscribeToTaskRequest,
    TaskPushNotificationConfig,
    TaskState,
)
from a2a.utils.errors import TaskNotCancelableError, TaskNotFoundError, UnsupportedOperationError
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_secret_manager,
    get_task_service,
)
from agentarea_api.api.v1 import a2a_auth, a2a_request_handler, agents_a2a, agents_well_known
from agentarea_common.auth import access
from agentarea_common.auth.access import EdgeDecision
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import get_optional_principal
from agentarea_common.events.contract import LLM_CHUNK, TASK_COMPLETED, TASK_STARTED
from agentarea_common.events.task_stream import TaskEventEnvelope
from agentarea_tasks.domain.models import AgentTask
from fastapi import FastAPI, Request
from google.protobuf.json_format import MessageToDict

WORKSPACE = "ws-acme"
MEMBER = "user-member"
OUTSIDER = "user-outsider"
AGENT_ID = uuid4()
MEMBER_BEARER = "member-key"
OUTSIDER_BEARER = "outsider-key"
PUSH_CALLBACK_KEY = "push-callback-key"
BASE = "http://agentarea.test"
AGENT_BASE = f"{BASE}/v1/agents/{AGENT_ID}"

AGENT = SimpleNamespace(
    id=AGENT_ID,
    name="researcher",
    description="Finds things out.",
    status="active",
    workspace_id=WORKSPACE,
    tools=[{"name": "web_search"}],
    planning=False,
    a2ui_enabled=False,
)


class FakeTaskRepository:
    def __init__(self, tasks: dict[UUID, AgentTask]):
        self._tasks = tasks

    async def update_by_id(self, task_id: UUID, update: Any) -> None:
        self._tasks[task_id].task_parameters = update.task_parameters


class FakeTaskService:
    """The slice of ``TaskService`` the A2A handler uses, in memory."""

    def __init__(self) -> None:
        self.tasks: dict[UUID, AgentTask] = {}
        self.task_repository = FakeTaskRepository(self.tasks)

    async def submit_task(self, task: AgentTask) -> AgentTask:
        self.tasks[task.id] = task
        return task

    async def get_task(self, task_id: UUID) -> AgentTask | None:
        return self.tasks.get(task_id)

    async def get_task_with_workflow_status(self, task_id: UUID) -> AgentTask | None:
        return self.tasks.get(task_id)

    async def cancel_task(self, task_id: UUID) -> bool:
        self.tasks[task_id].status = "cancelled"
        return True

    async def get_agent_tasks(self, agent_id: UUID, limit: int, offset: int) -> list[AgentTask]:
        owned = [t for t in self.tasks.values() if t.agent_id == agent_id]
        return owned[offset : offset + limit]

    async def count_agent_tasks(self, agent_id: UUID) -> int:
        return sum(1 for t in self.tasks.values() if t.agent_id == agent_id)


class FakeSecretManager:
    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}

    async def set_secret(self, name: str, value: str) -> None:
        self.secrets[name] = value

    async def delete_secret(self, name: str) -> bool:
        return self.secrets.pop(name, None) is not None


class FakeAgentService:
    async def get(self, agent_id: UUID) -> Any:
        return AGENT if agent_id == AGENT_ID else None


def _events(*items: tuple[str, dict[str, Any]]) -> list[TaskEventEnvelope]:
    return [
        TaskEventEnvelope(event_type=t, event_id=str(i), timestamp=None, data=d)
        for i, (t, d) in enumerate(items)
    ]


def _subject(request: Request) -> UserPrincipal | None:
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
    if bearer == MEMBER_BEARER:
        return UserPrincipal(user_id=MEMBER, accessible_workspaces=[WORKSPACE])
    if bearer == OUTSIDER_BEARER:
        return UserPrincipal(user_id=OUTSIDER, accessible_workspaces=["ws-elsewhere"])
    return None


async def _authorize(subject, action, *, agent_workspace_id, agent_id) -> EdgeDecision:
    if subject is None:
        return EdgeDecision(allowed=False, reason="anonymous")
    return EdgeDecision(
        allowed=agent_workspace_id in (subject.accessible_workspaces or []),
        reason="workspace scope",
    )


@pytest.fixture
def services(monkeypatch):
    tasks = FakeTaskService()
    secrets = FakeSecretManager()
    feed_script: list[TaskEventEnvelope] = []
    feed_calls: list[dict[str, Any]] = []

    async def feed(task_id, **kwargs) -> AsyncIterator[TaskEventEnvelope]:
        feed_calls.append({"task_id": task_id, **kwargs})
        for env in feed_script:
            yield env

    async def public_agent(agent_id, session):
        return AGENT if agent_id == AGENT_ID else None

    monkeypatch.setattr(access, "authorize_agent_action", _authorize)
    monkeypatch.setattr(agents_a2a, "open_task_event_feed", feed)
    monkeypatch.setattr(agents_well_known, "get_public_agent", public_agent)
    monkeypatch.setattr(a2a_request_handler, "validate_outbound_url", lambda url: None)
    monkeypatch.setattr(a2a_auth, "workspace_slug_for", AsyncMock(return_value="acme"))
    return SimpleNamespace(tasks=tasks, secrets=secrets, feed=feed_script, feed_calls=feed_calls)


@pytest.fixture
def app(services) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_well_known.router, prefix="/v1/agents/{agent_id}")
    app.include_router(agents_a2a.router, prefix="/v1/agents/{agent_id}")
    app.dependency_overrides[get_optional_principal] = _subject
    app.dependency_overrides[get_task_service] = lambda: services.tasks
    app.dependency_overrides[get_agent_service] = FakeAgentService
    app.dependency_overrides[get_secret_manager] = lambda: services.secrets
    app.dependency_overrides[agents_well_known.get_read_db_session] = lambda: None
    return app


def _http(app: FastAPI, bearer: str | None = None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE, headers=headers)


@pytest_asyncio.fixture
async def client(app):
    http = _http(app, MEMBER_BEARER)
    card = await A2ACardResolver(http, AGENT_BASE).get_agent_card()
    async with ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(
        card
    ) as sdk_client:
        yield sdk_client


@pytest_asyncio.fixture
async def streaming_client(app):
    http = _http(app, MEMBER_BEARER)
    card = await A2ACardResolver(http, AGENT_BASE).get_agent_card()
    async with ClientFactory(ClientConfig(httpx_client=http, streaming=True)).create(
        card
    ) as sdk_client:
        yield sdk_client


def _send(text: str, **message: Any) -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            message_id=uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=text)], **message
        )
    )


async def _send_one(client, request: SendMessageRequest):
    responses = [r async for r in client.send_message(request)]
    assert len(responses) == 1
    return responses[0].task


def _stored_task(services, *, agent_id: UUID = AGENT_ID, status: str = "running") -> AgentTask:
    task = AgentTask(
        id=uuid4(),
        title="t",
        description="d",
        query="q",
        user_id=MEMBER,
        workspace_id=WORKSPACE,
        agent_id=agent_id,
        status=status,
    )
    services.tasks.tasks[task.id] = task
    return task


@pytest.mark.asyncio
async def test_card_resolves_to_our_rpc_endpoint(app):
    card = await A2ACardResolver(_http(app), AGENT_BASE).get_agent_card()

    assert card.name == "researcher"
    interface = card.supported_interfaces[0]
    assert interface.url == f"{AGENT_BASE}/a2a/rpc"
    assert (interface.protocol_binding, interface.protocol_version) == ("JSONRPC", "1.0")
    assert card.security_schemes["bearer"].http_auth_security_scheme.scheme == "bearer"
    assert list(card.security_requirements[0].schemes) == ["bearer"]


@pytest.mark.asyncio
async def test_send_message_creates_a_task_for_this_agent(client, services):
    task = await _send_one(client, _send("Summarise the release notes", context_id="ctx-7"))

    assert task.status.state == TaskState.TASK_STATE_SUBMITTED
    assert task.context_id == "ctx-7"
    stored = services.tasks.tasks[UUID(task.id)]
    assert stored.agent_id == AGENT_ID
    assert stored.query == "Summarise the release notes"
    assert (stored.user_id, stored.workspace_id) == (MEMBER, WORKSPACE)
    assert stored.metadata["source"] == "a2a"
    assert stored.metadata["a2a_method"] == "SendMessage"


@pytest.mark.asyncio
async def test_get_task_returns_the_final_answer(client, services):
    task = await _send_one(client, _send("hello"))
    stored = services.tasks.tasks[UUID(task.id)]
    stored.status = "completed"
    stored.result = {"response": "The answer is 42."}

    got = await client.get_task(GetTaskRequest(id=task.id))

    assert got.status.state == TaskState.TASK_STATE_COMPLETED
    assert got.artifacts[0].parts[0].text == "The answer is 42."
    assert got.status.message.role == Role.ROLE_AGENT
    assert got.status.message.parts[0].text == "The answer is 42."


@pytest.mark.asyncio
async def test_get_task_of_another_agent_is_not_found(client, services):
    other = _stored_task(services, agent_id=uuid4())

    with pytest.raises(TaskNotFoundError):
        await client.get_task(GetTaskRequest(id=str(other.id)))


@pytest.mark.asyncio
async def test_cancel_task_then_cancel_again_is_not_cancelable(client, services):
    task = await _send_one(client, _send("long job"))

    cancelled = await client.cancel_task(CancelTaskRequest(id=task.id))
    assert cancelled.status.state == TaskState.TASK_STATE_CANCELED

    with pytest.raises(TaskNotCancelableError):
        await client.cancel_task(CancelTaskRequest(id=task.id))


@pytest.mark.asyncio
async def test_streaming_send_follows_the_task_to_completion(streaming_client, services):
    services.feed.extend(
        _events(
            (TASK_STARTED, {}),
            (LLM_CHUNK, {"chunk": "The answer "}),
            (TASK_COMPLETED, {"original_data": {"result": "The answer is 42."}}),
        )
    )

    responses = [r async for r in streaming_client.send_message(_send("stream it"))]

    kinds = [r.WhichOneof("payload") for r in responses]
    assert kinds == ["task", "status_update", "artifact_update", "artifact_update", "status_update"]
    task_id = responses[0].task.id
    assert responses[1].status_update.status.state == TaskState.TASK_STATE_WORKING
    chunk, final = responses[2].artifact_update, responses[3].artifact_update
    assert (chunk.append, chunk.artifact.parts[0].text) == (True, "The answer ")
    assert (final.last_chunk, final.artifact.parts[0].text) == (True, "The answer is 42.")
    assert responses[4].status_update.task_id == task_id
    assert responses[4].status_update.status.state == TaskState.TASK_STATE_COMPLETED
    assert services.feed_calls[0]["workspace_id"] == WORKSPACE


@pytest.mark.asyncio
async def test_subscribe_starts_with_the_task_and_refuses_terminal_ones(streaming_client, services):
    task = str(_stored_task(services).id)
    services.feed.extend(_events((TASK_COMPLETED, {"result": "done"})))

    responses = [r async for r in streaming_client.subscribe(SubscribeToTaskRequest(id=task))]
    assert responses[0].task.id == task
    assert responses[-1].status_update.status.state == TaskState.TASK_STATE_COMPLETED

    services.tasks.tasks[UUID(task)].status = "completed"
    with pytest.raises(UnsupportedOperationError):
        [r async for r in streaming_client.subscribe(SubscribeToTaskRequest(id=task))]


@pytest.mark.asyncio
async def test_list_tasks_pages_through_this_agents_tasks(client, services):
    for _ in range(3):
        await _send_one(client, _send("job"))

    first = await client.list_tasks(ListTasksRequest(page_size=2))
    assert (len(first.tasks), first.total_size, first.page_size) == (2, 3, 2)
    second = await client.list_tasks(
        ListTasksRequest(page_size=2, page_token=first.next_page_token)
    )
    assert len(second.tasks) == 1
    assert second.next_page_token == ""


@pytest.mark.asyncio
async def test_push_config_round_trip_keeps_the_token_secret(client, services):
    task = await _send_one(client, _send("notify me"))

    created = await client.create_task_push_notification_config(
        TaskPushNotificationConfig(
            task_id=task.id, url="https://hooks.example/a2a", token=PUSH_CALLBACK_KEY
        )
    )
    assert created.url == "https://hooks.example/a2a"
    assert created.token == ""
    assert services.secrets.secrets == {f"a2a_push_token:{task.id}:{created.id}": PUSH_CALLBACK_KEY}

    listed = await client.list_task_push_notification_configs(
        ListTaskPushNotificationConfigsRequest(task_id=task.id)
    )
    assert [c.id for c in listed.configs] == [created.id]

    await client.delete_task_push_notification_config(
        DeleteTaskPushNotificationConfigRequest(task_id=task.id, id=created.id)
    )
    listed = await client.list_task_push_notification_configs(
        ListTaskPushNotificationConfigsRequest(task_id=task.id)
    )
    assert list(listed.configs) == []
    assert services.secrets.secrets == {}


@pytest.mark.asyncio
async def test_send_message_registers_an_inline_push_config(client, services):
    request = _send("notify me when done")
    request.configuration.task_push_notification_config.CopyFrom(
        TaskPushNotificationConfig(url="https://hooks.example/a2a", token=PUSH_CALLBACK_KEY)
    )

    task = await _send_one(client, request)

    stored = services.tasks.tasks[UUID(task.id)]
    [config] = stored.task_parameters["a2a_push_configs"]
    assert config["url"] == "https://hooks.example/a2a"
    assert services.secrets.secrets == {
        f"a2a_push_token:{task.id}:{config['id']}": PUSH_CALLBACK_KEY
    }


@pytest.mark.asyncio
async def test_extended_card_matches_the_public_card_plus_member_skills(client, app):
    public = await A2ACardResolver(_http(app), AGENT_BASE).get_agent_card()

    extended = await client.get_extended_agent_card(GetExtendedAgentCardRequest())

    assert extended.supported_interfaces == public.supported_interfaces
    assert extended.security_schemes == public.security_schemes
    assert [s.id for s in extended.skills] == ["text-processing", "tool-execution"]


@pytest.mark.asyncio
async def test_requests_without_the_version_header_are_refused(app):
    body = {"jsonrpc": "2.0", "id": "1", "method": "GetTask", "params": {"id": str(uuid4())}}

    response = await _http(app, MEMBER_BEARER).post(f"{AGENT_BASE}/a2a/rpc", json=body)

    assert response.json()["error"]["code"] == -32009


@pytest.mark.asyncio
async def test_anonymous_caller_is_refused_before_the_protocol(app):
    http = _http(app)
    body = {"jsonrpc": "2.0", "id": "1", "method": "GetTask", "params": {"id": str(uuid4())}}

    response = await http.post(f"{AGENT_BASE}/a2a/rpc", json=body, headers={"A2A-Version": "1.0"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    card = await A2ACardResolver(http, AGENT_BASE).get_agent_card()
    async with ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card) as c:
        with pytest.raises(A2AClientError, match="401"):
            await c.get_task(GetTaskRequest(id=str(uuid4())))


@pytest.mark.asyncio
async def test_caller_outside_the_agents_workspace_is_forbidden(app):
    body = {"jsonrpc": "2.0", "id": "1", "method": "GetTask", "params": {"id": str(uuid4())}}

    response = await _http(app, OUTSIDER_BEARER).post(
        f"{AGENT_BASE}/a2a/rpc", json=body, headers={"A2A-Version": "1.0"}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unknown_agent_is_not_found(app):
    body = {"jsonrpc": "2.0", "id": "1", "method": "GetTask", "params": {"id": str(uuid4())}}

    response = await _http(app, MEMBER_BEARER).post(
        f"{BASE}/v1/agents/{uuid4()}/a2a/rpc", json=body, headers={"A2A-Version": "1.0"}
    )

    assert response.status_code == 404


def test_task_json_uses_proto_enum_names():
    from agentarea_api.api.v1.a2a_mapping import to_a2a_task

    task = AgentTask(
        id=uuid4(),
        title="t",
        description="d",
        query="q",
        user_id=MEMBER,
        workspace_id=WORKSPACE,
        agent_id=AGENT_ID,
        status="completed",
        result={"response": "ok"},
    )

    wire = MessageToDict(to_a2a_task(task))

    assert wire["status"]["state"] == "TASK_STATE_COMPLETED"
    assert wire["status"]["message"]["role"] == "ROLE_AGENT"
    assert "index" not in wire["artifacts"][0]
