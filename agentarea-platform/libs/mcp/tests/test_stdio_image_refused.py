"""An image whose server speaks stdio cannot be run, so its instance is refused at create."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.application.validation_service import MCPValidationError
from agentarea_mcp.schemas.dto import MCPServerInstanceCreate
from agentarea_mcp.transport_spec import image_serves_stdio


def _oci(identifier: str, transport: str) -> dict:
    return {"registryType": "oci", "identifier": identifier, "transport": {"type": transport}}


@pytest.mark.parametrize(
    ("spec", "stdio"),
    [
        ({"image": "mcp/fetch", "packages": [_oci("mcp/fetch", "stdio")]}, True),
        (
            {
                "image": "docker.io/vendor/server:latest",
                "packages": [_oci("docker.io/vendor/server", "stdio")],
            },
            True,
        ),
        ({"image": "vendor/server:2", "packages": [_oci("vendor/server:1", "stdio")]}, True),
        (
            {"image": "vendor/server:1", "packages": [_oci("vendor/server:1", "streamable-http")]},
            False,
        ),
        ({"image": "mcp/fetch", "port": 8000, "packages": [_oci("mcp/fetch", "stdio")]}, False),
        ({"image": "mcp/fetch", "port": None, "packages": [_oci("mcp/fetch", "stdio")]}, True),
        ({"image": "vendor/server:1"}, False),
        (
            {
                "image": "vendor/server:1",
                "packages": [
                    {"registryType": "npm", "identifier": "server", "transport": {"type": "stdio"}}
                ],
            },
            False,
        ),
    ],
)
def test_image_serves_stdio(spec: dict, stdio: bool) -> None:
    assert image_serves_stdio(spec) is stdio


def _service_for(server: MagicMock) -> MCPServerInstanceService:
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
    return service


def _stdio_image_server() -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        workspace_id="ws",
        remote_url=None,
        cmd=None,
        docker_image_url="mcp/fetch",
        json_spec={"packages": [_oci("mcp/fetch", "stdio")]},
    )


@pytest.mark.asyncio
async def test_an_instance_of_an_image_that_speaks_stdio_is_refused():
    server = _stdio_image_server()
    service = _service_for(server)

    with pytest.raises(MCPValidationError, match="speaks stdio"):
        await service.create_instance(
            MCPServerInstanceCreate(name="fetch", server_spec_id=str(server.id), json_spec={})
        )
    service.repository.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_instance_that_declares_the_port_its_image_listens_on_is_not_refused_as_stdio():
    server = _stdio_image_server()
    service = _service_for(server)
    service._extract_secrets_from_spec = AsyncMock(return_value=({"port": 8000}, []))
    service._grant_creator_ownership = AsyncMock()

    with patch("agentarea_mcp.application.service.verify", AsyncMock()):
        await service.create_instance(
            MCPServerInstanceCreate(
                name="fetch", server_spec_id=str(server.id), json_spec={"port": 8000}
            )
        )
    service.repository.session.commit.assert_awaited_once()
