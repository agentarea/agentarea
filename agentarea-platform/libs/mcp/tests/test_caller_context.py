"""Caller context for platform-run MCP apps: the derived key, the claims, the opt-in."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import jwt
import pytest
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application import service as service_module
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.schemas.dto import validate_spec_context
from agentarea_mcp.tool_context import (
    CONTEXT_HEADER,
    CallerContext,
    context_enabled,
    context_header,
    derived_context_key,
)

GATEWAY_SECRET = "gateway-secret-of-at-least-32-bytes!!"  # pragma: allowlist secret
INSTANCE_ID = "c92f0870-465a-4c70-8c11-b33d08fd8c54"
CALLER = CallerContext(workspace_id="ws-1", user_id="user-1", user_email="maya@acme.ru")


def test_the_derived_key_matches_the_managers():
    # The value agentarea-mcp-manager/internal/mcpcontext's test pins for the same inputs.
    assert (
        derived_context_key(GATEWAY_SECRET, INSTANCE_ID)
        == "4896aeffbc037762218722536c6b3909507c657b401b1dfd840e39b056c940f8"
    )


def test_a_caller_token_names_the_person_for_one_instance_and_tool():
    key = derived_context_key(GATEWAY_SECRET, INSTANCE_ID)
    headers = context_header(CALLER, key, instance_id=INSTANCE_ID, tool="create_task")
    claims = jwt.decode(headers[CONTEXT_HEADER], key, algorithms=["HS256"], audience=INSTANCE_ID)
    assert claims["workspace_id"] == "ws-1"
    assert claims["user_id"] == "user-1"
    assert claims["user_email"] == "maya@acme.ru"
    assert claims["tool"] == "create_task"
    assert claims["exp"] - claims["iat"] == 300
    assert "task_id" not in claims and "client_id" not in claims


def test_a_request_that_is_not_one_tool_call_is_signed_without_a_tool():
    headers = context_header(CALLER, "k" * 64, instance_id=INSTANCE_ID, tool=None)
    claims = jwt.decode(
        headers[CONTEXT_HEADER], "k" * 64, algorithms=["HS256"], audience=INSTANCE_ID
    )
    assert "tool" not in claims


def test_without_a_key_nothing_is_signed():
    assert context_header(CALLER, None, instance_id=INSTANCE_ID, tool="x") == {}


def test_the_spec_flag_is_exactly_enabled_true():
    assert context_enabled({"context": {"enabled": True}})
    assert not context_enabled({}) and not context_enabled(None)
    assert validate_spec_context({"context": {"enabled": True}})
    for bad in (True, {"enabled": False}, {"enabled": True, "x": 1}):
        with pytest.raises(ValueError, match="json_spec.context"):
            validate_spec_context({"context": bad})


def _service() -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        return MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(),
            secret_manager=InMemorySecrets(),
        )


def _docker(spec: dict) -> MCPServerInstance:
    instance = MCPServerInstance(
        name="tasks", server_spec_id="spec", transport="docker", json_spec=spec
    )
    instance.id = UUID(INSTANCE_ID)
    return instance


@pytest.mark.asyncio
async def test_a_platform_run_instance_that_opts_in_is_signed_with_the_derived_key(monkeypatch):
    settings = SimpleNamespace(mcp=SimpleNamespace(gateway_secret=lambda: GATEWAY_SECRET))
    monkeypatch.setattr(service_module, "get_settings", lambda: settings)
    service = _service()
    service.get_transport_spec_for_instance = AsyncMock(
        return_value={"type": "docker", "context": {"enabled": True}}
    )
    assert await service.context_key(_docker({})) == derived_context_key(
        GATEWAY_SECRET, INSTANCE_ID
    )

    service.get_transport_spec_for_instance = AsyncMock(return_value={"type": "docker"})
    assert await service.context_key(_docker({})) is None
