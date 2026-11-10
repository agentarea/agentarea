"""A server spec never carries a secret reference, and redirecting one takes can_use_secret.

A spec is shared and editable by anyone with edit on it, while a reference is
authorized against the instance that carries it. A reference in a spec would
reach whatever endpoint or image the spec names, and moving a spec moves every
referenced secret of its instances with it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.exceptions.errors import BadRequestError
from agentarea_mcp.application.service import MCPServerService
from agentarea_mcp.schemas.dto import MCPServerCreate, MCPServerUpdate
from agentarea_secrets.catalog_service import SecretAccessDeniedError, SecretNotFoundError
from pydantic import ValidationError

REF = {"secret_name": "PROD_KEY"}  # pragma: allowlist secret


def _service(server, instances=()):
    repository = MagicMock()
    repository.user_context = UserContext(user_id="writer", workspace_id="ws")
    repository.session = MagicMock()
    instance_repository = MagicMock(list_by_server_spec=AsyncMock(return_value=list(instances)))
    factory = MagicMock(create_repository=lambda cls: instance_repository)
    with patch.object(MCPServerService, "__init__", return_value=None):
        service = MCPServerService(factory)
    service.repository = repository
    service.repository_factory = factory
    service.event_broker = None
    service.get = AsyncMock(return_value=server)
    service.update = AsyncMock(side_effect=lambda s: s)
    return service


def _server():
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="mcp",
        description="d",
        docker_image_url="ghcr.io/example/mcp:1",
        remote_url=None,
        cmd=None,
        json_spec={"type": "docker", "image": "ghcr.io/example/mcp:1"},
        version="1",
        tags=[],
        is_public=False,
        status="active",
        env_schema=[],
        registry_url=None,
    )


def _instance(json_spec):
    return SimpleNamespace(id=uuid.uuid4(), json_spec=json_spec)


@pytest.mark.parametrize(
    "json_spec",
    [
        {"type": "docker", "image": "attacker/img:1", "environment": {"API_KEY": REF}},
        {"type": "url", "endpoint_url": "https://evil.example/mcp", "headers": {"X": REF}},
        {"type": "url", "remotes": [{"url": "https://e.example", "headers": [REF]}]},
    ],
)
def test_a_spec_payload_carrying_a_reference_is_refused(json_spec):
    with pytest.raises(ValidationError, match="may not reference a workspace secret"):
        MCPServerCreate(name="x", description="x", json_spec=json_spec)
    with pytest.raises(ValidationError, match="may not reference a workspace secret"):
        MCPServerUpdate(json_spec=json_spec)


async def test_the_service_refuses_a_reference_in_a_spec_however_the_payload_was_built():
    service = _service(_server())
    payload = MCPServerUpdate.model_construct(
        json_spec={"type": "docker", "environment": {"API_KEY": REF}}
    )

    with pytest.raises(BadRequestError, match="may not reference"):
        await MCPServerService.update_mcp_server.__wrapped__(service, uuid.uuid4(), payload)

    service.update.assert_not_awaited()


async def test_moving_a_spec_whose_instances_reference_a_secret_needs_can_use_secret():
    server = _server()
    service = _service(server, [_instance({"environment": {"API_KEY": REF, "MODE": "x"}})])
    refused = AsyncMock(side_effect=SecretAccessDeniedError("You may not use secret 'PROD_KEY'"))

    with (
        patch("agentarea_mcp.application.service.named_secret_for_use", refused),
        pytest.raises(PermissionError, match="PROD_KEY"),
    ):
        await MCPServerService.update_mcp_server.__wrapped__(
            service, server.id, MCPServerUpdate(docker_image_url="attacker/img:1")
        )

    service.update.assert_not_awaited()
    assert refused.await_args.args[2] == "PROD_KEY"


async def test_moving_a_spec_is_allowed_to_whoever_may_use_its_secrets():
    server = _server()
    service = _service(server, [_instance({"headers": {"Authorization": REF}})])
    allowed = AsyncMock()

    with patch("agentarea_mcp.application.service.named_secret_for_use", allowed):
        await MCPServerService.update_mcp_server.__wrapped__(
            service, server.id, MCPServerUpdate(docker_image_url="ghcr.io/example/mcp:2")
        )

    service.update.assert_awaited_once()
    allowed.assert_awaited_once()


async def test_a_change_that_does_not_move_the_spec_asks_nothing():
    server = _server()
    service = _service(server, [_instance({"headers": {"Authorization": REF}})])
    check = AsyncMock()

    with patch("agentarea_mcp.application.service.named_secret_for_use", check):
        await MCPServerService.update_mcp_server.__wrapped__(
            service, server.id, MCPServerUpdate(description="new words")
        )

    check.assert_not_awaited()


async def test_a_referenced_secret_that_is_gone_does_not_block_a_move():
    server = _server()
    service = _service(server, [_instance({"headers": {"Authorization": REF}})])
    gone = AsyncMock(side_effect=SecretNotFoundError("No secret named 'PROD_KEY'"))

    with patch("agentarea_mcp.application.service.named_secret_for_use", gone):
        await MCPServerService.update_mcp_server.__wrapped__(
            service, server.id, MCPServerUpdate(remote_url="https://new.example/mcp")
        )

    service.update.assert_awaited_once()
