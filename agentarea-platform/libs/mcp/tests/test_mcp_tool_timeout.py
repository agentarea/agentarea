"""An instance's ``tool_timeout_seconds`` bounds its tool calls, in place of a fixed 5 minutes."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application import service as service_module
from agentarea_mcp.application.mcp_session_pool import MCPSessionPool
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.application.validation_service import (
    MCPConfigurationValidator,
    MCPValidationError,
)
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.schemas.dto import MCPServerInstanceUpdate
from agentarea_mcp.tool_timeout import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    MAX_TOOL_TIMEOUT_SECONDS,
    TOOL_TIMEOUT_KEY,
    tool_timeout_error,
    tool_timeout_seconds,
)
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

ENDPOINT = "http://127.0.0.1/"
SPEC_ID = "00000000-0000-4000-8000-0000000000ee"


class _App:
    def __init__(self) -> None:
        server = MCPServer(name="slow")

        async def recognize(seconds: float) -> str:
            await asyncio.sleep(seconds)
            return f"recognized after {seconds}s"

        server.add_tool(recognize, name="recognize")
        self.asgi = server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                allowed_hosts=["127.0.0.1"], allowed_origins=["http://127.0.0.1"]
            ),
        )
        self.timeouts: list[Any] = []

    def factory(self, _wrapped=None):
        def build(headers=None, timeout=None, auth=None, **_kwargs):
            self.timeouts.append(timeout)
            return httpx2.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=auth,
                transport=httpx2.ASGITransport(app=self.asgi),
            )

        return build


def _service(instance: MCPServerInstance) -> MCPServerInstanceService:
    server = MagicMock(id=SPEC_ID, remote_url=ENDPOINT, cmd=None, docker_image_url=None)
    server.json_spec = {"type": "url", "endpoint_url": ENDPOINT}
    server.env_schema = []
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(publish=AsyncMock()),
            secret_manager=InMemorySecrets(),
        )
    service.era_verdict_store = None
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=server)
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


def _instance(json_spec: dict[str, Any]) -> MCPServerInstance:
    instance = MCPServerInstance(
        name="slow", server_spec_id=SPEC_ID, transport="url", json_spec={"type": "url", **json_spec}
    )
    instance.id = uuid.uuid4()
    instance.auth_config_id = None
    return instance


async def _call(json_spec: dict[str, Any], seconds: float) -> tuple[dict[str, Any], _App]:
    instance = _instance(json_spec)
    service = _service(instance)
    app = _App()
    pool = MCPSessionPool()
    with (
        patch.object(service_module, "pinned_client_factory", app.factory),
        patch.object(service_module, "record_dispatch"),
        patch.object(service_module, "session_pool", lambda: pool),
    ):
        async with app.asgi.router.lifespan_context(app.asgi):
            result = await service.execute_tool(instance.id, "recognize", {"seconds": seconds})
            await pool.aclose()
    return result, app


@pytest.mark.asyncio
async def test_a_call_longer_than_the_instance_timeout_fails_as_timed_out():
    result, _ = await _call({TOOL_TIMEOUT_KEY: 1}, seconds=3)

    assert result["success"] is False
    assert result["error"] == "MCP tool call timed out: no result within 1 s"
    assert TOOL_TIMEOUT_KEY in result["result"]


@pytest.mark.asyncio
async def test_a_call_within_the_instance_timeout_returns_its_result():
    result, app = await _call({TOOL_TIMEOUT_KEY: 5}, seconds=1.5)

    assert result["success"] is True
    assert result["result"] == "recognized after 1.5s"
    # The connection waits on a silent response past the call's own limit.
    assert {timeout.read for timeout in app.timeouts} == {5 + 30}


@pytest.mark.asyncio
async def test_without_a_setting_the_call_waits_the_default():
    _, app = await _call({}, seconds=0)

    assert {timeout.read for timeout in app.timeouts} == {DEFAULT_TOOL_TIMEOUT_SECONDS + 30}


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        (1, True),
        (240.5, True),
        (MAX_TOOL_TIMEOUT_SECONDS, True),
        (0, False),
        (MAX_TOOL_TIMEOUT_SECONDS + 1, False),
        ("600", False),
        (True, False),
    ],
)
def test_the_timeout_must_be_seconds_within_the_platform_maximum(value, accepted):
    spec = {TOOL_TIMEOUT_KEY: value}
    assert (tool_timeout_error(spec) is None) is accepted
    assert (
        not MCPConfigurationValidator.validate_json_spec({"type": "url", "url": ENDPOINT, **spec})
    ) is accepted
    if accepted:
        assert tool_timeout_seconds(spec) == float(value)
    else:
        with pytest.raises(ValueError):
            tool_timeout_seconds(spec)


@pytest.mark.asyncio
async def test_an_update_with_an_out_of_range_timeout_is_refused_and_a_valid_one_kept():
    instance = _instance({})
    service = _service(instance)

    with pytest.raises(MCPValidationError):
        await service.update_instance(
            instance.id,
            MCPServerInstanceUpdate(json_spec={TOOL_TIMEOUT_KEY: MAX_TOOL_TIMEOUT_SECONDS * 2}),
        )

    await service.update_instance(
        instance.id, MCPServerInstanceUpdate(json_spec={TOOL_TIMEOUT_KEY: 900})
    )
    assert instance.json_spec[TOOL_TIMEOUT_KEY] == 900
