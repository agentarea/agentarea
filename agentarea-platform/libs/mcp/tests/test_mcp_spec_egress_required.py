"""A server spec can require its workload to leave the internet through an egress exit.

``json_spec.egress = {"required": true}`` is the image's property (a browser image
that refuses to start without a proxy), so it is declared on the server spec and
every instance inherits it; the enterprise dataplane seals a default exit for an
instance that binds none. Nothing in the open-source edition can, so there such a
spec, and an instance of one, is refused.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_common.exceptions.errors import BadRequestError
from agentarea_common.extensions.egress_exits import EGRESS_EXITS_EXTENSION
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_mcp.application.service import MCPServerInstanceService, MCPServerService
from agentarea_mcp.application.validation_service import MCPValidationError
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)
from agentarea_mcp.transport_spec import instance_transport_spec
from pydantic import ValidationError

IMAGE = "ghcr.io/acme/browser:1"
REQUIRED = {"required": True}


@pytest.fixture
def enterprise():
    ExtensionRegistry.clear()
    ExtensionRegistry.register(EGRESS_EXITS_EXTENSION, lambda: True)
    yield
    ExtensionRegistry.clear()


@pytest.fixture
def public_endpoints(monkeypatch):
    monkeypatch.setattr("agentarea_mcp.application.service._endpoint_refusal", lambda url: None)


@pytest.fixture
def oss():
    ExtensionRegistry.clear()
    yield
    ExtensionRegistry.clear()


BAD_EGRESS = [
    {"required": "true"},
    {"required": 1},
    {"required": None},
    {},
    {"required": True, "exit": "office"},
    True,
    None,
    "required",
]


@pytest.mark.parametrize("egress", BAD_EGRESS)
def test_every_other_egress_value_on_a_spec_is_refused(egress) -> None:
    spec = {"type": "docker", "image": IMAGE, "egress": egress}
    with pytest.raises(ValidationError, match="egress"):
        MCPServerCreate(name="s", description="d", json_spec=spec)
    with pytest.raises(ValidationError, match="egress"):
        MCPServerUpdate(json_spec=spec)


@pytest.mark.parametrize("required", [True, False])
def test_a_spec_says_whether_its_workload_needs_an_exit(required: bool) -> None:
    spec = {"type": "docker", "image": IMAGE, "egress": {"required": required}}

    assert MCPServerCreate(name="s", description="d", json_spec=spec).json_spec == spec
    assert MCPServerUpdate(json_spec=spec).json_spec == spec


@pytest.mark.parametrize("egress", [REQUIRED, {"required": False}])
def test_an_instance_cannot_override_what_its_image_needs(egress) -> None:
    with pytest.raises(ValidationError, match="egress"):
        MCPServerInstanceCreate(name="i", server_spec_id=uuid.uuid4(), json_spec={"egress": egress})
    with pytest.raises(ValidationError, match="egress"):
        MCPServerInstanceUpdate(json_spec={"egress": egress})


def _spec_service() -> MCPServerService:
    service = MCPServerService(repository_factory=MagicMock())
    service.repository.resolve_unique_slug = AsyncMock(return_value="browser")
    service.create = AsyncMock(side_effect=lambda server: server)
    service.update = AsyncMock(side_effect=lambda server: server)
    return service


def _container_spec_payload() -> MCPServerCreate:
    return MCPServerCreate(
        name="browser",
        description="d",
        docker_image_url=IMAGE,
        json_spec={"egress": REQUIRED},
    )


async def test_a_spec_requiring_an_exit_is_refused_where_nothing_could_start_it(oss) -> None:
    service = _spec_service()

    with pytest.raises(BadRequestError, match="enterprise"):
        await service.create_mcp_server(_container_spec_payload())
    service.create.assert_not_awaited()


async def test_a_spec_requiring_an_exit_is_stored_where_exits_exist(enterprise) -> None:
    server = await _spec_service().create_mcp_server(_container_spec_payload())

    assert server.json_spec == {"egress": REQUIRED}


async def test_a_spec_that_needs_no_exit_needs_no_enterprise_edition(oss) -> None:
    payload = MCPServerCreate(
        name="browser",
        description="d",
        docker_image_url=IMAGE,
        json_spec={"egress": {"required": False}},
    )

    server = await _spec_service().create_mcp_server(payload)

    assert server.json_spec == {"egress": {"required": False}}


async def test_only_a_workload_the_platform_runs_can_require_an_exit(
    enterprise, public_endpoints
) -> None:
    payload = MCPServerCreate(
        name="remote",
        description="d",
        remote_url="https://mcp.example.com/mcp",
        json_spec={"egress": REQUIRED},
    )

    with pytest.raises(BadRequestError, match="docker and command"):
        await _spec_service().create_mcp_server(payload)


def _stored_spec(**fields) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "workspace_id": "ws",
        "remote_url": None,
        "cmd": None,
        "docker_image_url": IMAGE,
        "json_spec": {},
    }
    return SimpleNamespace(**{**defaults, **fields})


async def test_a_spec_cannot_be_changed_to_require_an_exit_nothing_could_seal(oss) -> None:
    service = _spec_service()
    server = _stored_spec()
    service.get = AsyncMock(return_value=server)

    with pytest.raises(BadRequestError, match="enterprise"):
        await service.update_mcp_server(server.id, MCPServerUpdate(json_spec={"egress": REQUIRED}))
    assert server.json_spec == {}
    service.update.assert_not_awaited()


async def test_a_requirement_on_a_spec_that_becomes_remote_is_refused(
    enterprise, public_endpoints
) -> None:
    service = _spec_service()
    server = _stored_spec(json_spec={"egress": REQUIRED})
    service.get = AsyncMock(return_value=server)

    with pytest.raises(BadRequestError, match="docker and command"):
        await service.update_mcp_server(
            server.id,
            MCPServerUpdate(docker_image_url=None, remote_url="https://mcp.example.com/mcp"),
        )
    service.update.assert_not_awaited()


def _instance_service(server) -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(publish=AsyncMock()),
            secret_manager=MagicMock(),
        )
    service.repository = MagicMock()
    service.repository.session = MagicMock(
        rollback=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock()
    )
    service.repository.user_context = MagicMock(workspace_id="ws", user_id="u")
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=server)
    service._grant_creator_ownership = AsyncMock()
    return service


def _instance_payload(server) -> MCPServerInstanceCreate:
    return MCPServerInstanceCreate(name="browser", server_spec_id=server.id, json_spec={})


async def test_an_instance_of_a_spec_requiring_an_exit_is_refused_in_oss(oss) -> None:
    server = _stored_spec(json_spec={"egress": REQUIRED})
    service = _instance_service(server)

    with pytest.raises(MCPValidationError, match="enterprise"):
        await service.create_instance(_instance_payload(server))
    service.repository.session.commit.assert_not_awaited()


async def test_an_instance_inherits_the_requirement_its_spec_declares(enterprise) -> None:
    server = _stored_spec(json_spec={"egress": REQUIRED})
    service = _instance_service(server)

    with patch("agentarea_mcp.application.service.verify", AsyncMock()):
        instance = await service.create_instance(_instance_payload(server))

    assert "egress" not in instance.json_spec
    assert instance_transport_spec(server, instance)["egress"] == REQUIRED


async def test_an_instance_of_a_remote_spec_carrying_the_requirement_is_refused(
    enterprise, public_endpoints
) -> None:
    server = _stored_spec(
        docker_image_url=None,
        remote_url="https://mcp.example.com/mcp",
        json_spec={"egress": REQUIRED},
    )
    service = _instance_service(server)

    with pytest.raises(MCPValidationError, match="docker and command"):
        await service.create_instance(_instance_payload(server))
    service.repository.session.commit.assert_not_awaited()
