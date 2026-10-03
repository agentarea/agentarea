"""A docker MCP image reaches `docker run` argv in the flag position; a flag-shaped
value there hands the container the host, so the API refuses it with a 422."""

from uuid import uuid4

import pytest
from agentarea_mcp.schemas.dto import MCPServerCreate, MCPServerInstanceCreate
from pydantic import ValidationError

FLAG_IMAGES = [
    "--volume=/var/run/docker.sock:/var/run/docker.sock",
    "--privileged",
    "alpine --network=host",
]


@pytest.mark.parametrize("image", FLAG_IMAGES)
def test_instance_json_spec_refuses_flag_shaped_image(image: str) -> None:
    with pytest.raises(ValidationError):
        MCPServerInstanceCreate(
            name="x",
            server_spec_id=uuid4(),
            json_spec={"type": "docker", "image": image, "port": 8080},
        )


@pytest.mark.parametrize("image", FLAG_IMAGES)
def test_spec_refuses_flag_shaped_docker_image_url(image: str) -> None:
    with pytest.raises(ValidationError):
        MCPServerCreate(name="x", description="d", docker_image_url=image)


def test_real_references_are_accepted() -> None:
    spec = MCPServerCreate(
        name="x",
        description="d",
        docker_image_url="ghcr.io/github/github-mcp-server:v0.4.0",
        json_spec={"type": "docker", "image": "mcp/fetch:latest", "port": 8000},
    )
    assert spec.docker_image_url == "ghcr.io/github/github-mcp-server:v0.4.0"


@pytest.mark.parametrize("image", ["alpine:tagé", "alpine:\uff561", "alpine:標籤"])
def test_non_ascii_tag_is_refused_as_the_manager_refuses_it(image: str) -> None:
    """The manager's Go grammar is ASCII-only; a tag it would refuse must be a 422 here."""
    with pytest.raises(ValidationError):
        MCPServerCreate(name="x", description="d", docker_image_url=image)
