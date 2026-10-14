"""A URL MCP server receives the call's signed context and can report progress.

The server here is a real MCP server behind the SDK's streamable HTTP app; the
call goes through ``MCPServerInstanceService.execute_tool`` exactly as the tool
activity makes it.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import jwt
import pytest
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application import service as service_module
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.schemas.dto import MCPServerInstanceUpdate
from agentarea_mcp.tool_context import (
    CONTEXT_HEADER,
    CONTEXT_SECRET_NAME,
    CONTEXT_SIGNING_FLAG,
    ToolCallContext,
    call_context_from_task,
    context_meta,
)
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

ENDPOINT = "http://127.0.0.1/"
SPEC_ID = "00000000-0000-4000-8000-0000000000cc"
SECRET = "s" * 40  # pragma: allowlist secret

CONTEXT = ToolCallContext(
    task_id="task-1",
    tool_call_id="call-1",
    workspace_id="ws-1",
    agent_id="agent-1",
    end_user_id="user-42",
    metadata={"chatId": "c-9"},
)


class _App:
    """An MCP server whose one tool echoes what it was told and reports progress."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        server = MCPServer(name="app")

        async def whoami(steps: int, ctx: Context) -> dict[str, Any]:
            meta = dict(ctx.request_context.meta or {})
            self.seen.append({"meta": meta, "headers": dict(ctx.headers or {})})
            for step in range(1, steps + 1):
                await ctx.report_progress(step, steps, f"step {step} of {steps}")
            return {"task": meta.get("agentarea/task_id"), "steps": steps}

        server.add_tool(whoami, name="whoami")
        self.asgi = server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                allowed_hosts=["127.0.0.1"], allowed_origins=["http://127.0.0.1"]
            ),
        )

    def factory(self, _wrapped=None):
        def build(headers=None, timeout=None, auth=None, **_kwargs):
            return httpx2.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=auth,
                transport=httpx2.ASGITransport(app=self.asgi),
            )

        return build


def _server() -> MagicMock:
    server = MagicMock()
    server.id = SPEC_ID
    server.workspace_id = "ws-1"
    server.remote_url = ENDPOINT
    server.cmd = None
    server.docker_image_url = None
    server.json_spec = {
        "type": "url",
        "endpoint_url": ENDPOINT,
        "remotes": [{"type": "streamable-http", "url": ENDPOINT}],
    }
    server.env_schema = []
    return server


def _instance(*, signing: bool) -> MCPServerInstance:
    json_spec: dict[str, Any] = {"type": "url"}
    if signing:
        json_spec[CONTEXT_SIGNING_FLAG] = True
    instance = MCPServerInstance(
        name="app", server_spec_id=SPEC_ID, transport="url", json_spec=json_spec
    )
    instance.id = uuid.uuid4()
    instance.auth_config_id = None
    return instance


def _service(instance: MCPServerInstance) -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(publish=AsyncMock()),
            secret_manager=InMemorySecrets(),
        )
    service.era_verdict_store = None
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=_server())
    repository = MagicMock()
    repository.user_context = MagicMock(user_id="user", workspace_id="ws-1")
    repository.get_by_id = AsyncMock(return_value=instance)
    repository.update = AsyncMock(
        side_effect=lambda _id, **kwargs: (
            [setattr(instance, key, value) for key, value in kwargs.items()],
            instance,
        )[1]
    )
    service.repository = repository
    return service


async def _call(service, instance, app, **kwargs):
    with (
        patch.object(service_module, "pinned_client_factory", app.factory),
        patch.object(service_module, "record_dispatch"),
    ):
        async with app.asgi.router.lifespan_context(app.asgi):
            return await service.execute_tool(instance.id, "whoami", {"steps": 3}, **kwargs)


@pytest.mark.asyncio
async def test_signed_context_reaches_the_server_and_progress_comes_back():
    instance = _instance(signing=True)
    service = _service(instance)
    await service.env_service.set_instance_environment(instance.id, {CONTEXT_SECRET_NAME: SECRET})
    app = _App()
    progress: list[tuple[float, float | None, str | None]] = []

    async def on_progress(value, total, message):
        progress.append((value, total, message))

    result = await _call(
        service, instance, app, call_context=CONTEXT, progress_callback=on_progress
    )

    assert result["success"] is True
    assert result["structured_content"] == {"task": "task-1", "steps": 3}
    assert progress == [
        (1, 3, "step 1 of 3"),
        (2, 3, "step 2 of 3"),
        (3, 3, "step 3 of 3"),
    ]

    [seen] = app.seen
    agentarea_meta = {k: v for k, v in seen["meta"].items() if k.startswith("agentarea/")}
    assert agentarea_meta == context_meta(CONTEXT)
    assert agentarea_meta["agentarea/idempotency_key"] == "task-1:call-1"
    assert agentarea_meta["agentarea/protocol"] == "1"

    token = seen["headers"][CONTEXT_HEADER.lower()]
    assert jwt.get_unverified_header(token) == {"alg": "HS256", "typ": "JWT"}
    claims = jwt.decode(
        token, SECRET.encode(), algorithms=["HS256"], audience=str(instance.id), issuer="agentarea"
    )
    assert claims["tool"] == "whoami"
    assert claims["exp"] - claims["iat"] == 300
    for name in ("task_id", "tool_call_id", "workspace_id", "agent_id", "end_user_id"):
        assert claims[name] == agentarea_meta[f"agentarea/{name}"]
    assert claims["metadata"] == {"chatId": "c-9"}
    assert claims["idempotency_key"] == "task-1:call-1"
    assert claims["protocol"] == "1"


@pytest.mark.asyncio
async def test_an_instance_without_a_signing_secret_gets_no_context():
    instance = _instance(signing=False)
    service = _service(instance)
    app = _App()

    result = await _call(service, instance, app, call_context=CONTEXT)

    assert result["success"] is True
    [seen] = app.seen
    assert not any(key.startswith("agentarea/") for key in seen["meta"])
    assert CONTEXT_HEADER.lower() not in seen["headers"]


@pytest.mark.asyncio
async def test_oversized_structured_content_is_dropped_not_sent():
    instance = _instance(signing=False)
    service = _service(instance)
    app = _App()

    with patch.object(service_module, "STRUCTURED_CONTENT_MAX_CHARS", 10):
        result = await _call(service, instance, app)

    assert result["success"] is True
    assert result["structured_content"] is None
    assert result["structured_content_dropped"] is True
    assert result["result"]  # the model still gets the text


@pytest.mark.asyncio
async def test_setting_and_removing_the_signing_secret():
    instance = _instance(signing=False)
    service = _service(instance)

    await service.update_instance(instance.id, MCPServerInstanceUpdate(context_secret=SECRET))
    assert instance.json_spec[CONTEXT_SIGNING_FLAG] is True
    assert await service._context_secret(instance) == SECRET
    # The secret is not one of the instance's headers.
    assert CONTEXT_SECRET_NAME not in instance.get_configured_env_vars()

    # A json_spec edit keeps it; a caller cannot set or clear the flag itself.
    await service.update_instance(
        instance.id, MCPServerInstanceUpdate(json_spec={"context_signing": False})
    )
    assert instance.json_spec[CONTEXT_SIGNING_FLAG] is True

    await service.update_instance(instance.id, MCPServerInstanceUpdate(context_secret=None))
    assert CONTEXT_SIGNING_FLAG not in instance.json_spec
    assert await service.env_service.get_instance_environment(
        instance.id, [CONTEXT_SECRET_NAME]
    ) == {}


def test_call_context_from_task_reads_only_the_caller_keys():
    context = call_context_from_task(
        task_id="t",
        tool_call_id="c",
        workspace_id="w",
        agent_id=None,
        task_metadata={
            "created_via": "api",
            "project_id": "p",
            "end_user_id": "u-1",
            "app_metadata": {"chatId": "x"},
        },
    )
    assert context == ToolCallContext(
        task_id="t", tool_call_id="c", workspace_id="w", end_user_id="u-1", metadata={"chatId": "x"}
    )
    assert "agentarea/agent_id" not in context_meta(context)
    assert (
        call_context_from_task(
            task_id=None, tool_call_id="c", workspace_id="w", agent_id=None, task_metadata={}
        )
        is None
    )
