import os
from datetime import datetime
from typing import Any
from uuid import UUID

import yaml
from agentarea_api.api.deps.services import get_mcp_server_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_mcp.application.service import MCPServerService
from agentarea_mcp.domain.models import MCPServer
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


class MCPServerCreate(BaseModel):
    name: str = Field(..., description="Name of the MCP server")
    description: str = Field(..., description="Description of the MCP server")
    docker_image_url: str = Field(..., description="Docker image URL")
    version: str = Field(default="1.0.0", description="Version of the MCP server")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    is_public: bool = Field(default=False, description="Whether the server is public")
    env_schema: list[dict[str, Any]] | None = Field(
        default_factory=list, description="Environment variable schema"
    )
    cmd: list[str] | None = Field(
        default=None,
        description="Custom command to override container CMD "
        "(useful for switching between stdio and HTTP modes)",
    )


class MCPServerUpdate(BaseModel):
    name: str | None = Field(None, description="Name of the MCP server")
    description: str | None = Field(None, description="Description of the MCP server")
    docker_image_url: str | None = Field(None, description="Docker image URL")
    version: str | None = Field(None, description="Version of the MCP server")
    tags: list[str] | None = Field(None, description="Tags for categorization")
    is_public: bool | None = Field(None, description="Whether the server is public")
    status: str | None = Field(None, description="Status of the MCP server")
    cmd: list[str] | None = Field(None, description="Custom command to override container CMD")


class MCPServerResponse(BaseModel):
    id: UUID
    name: str
    description: str
    docker_image_url: str
    version: str
    tags: list[str]
    is_public: bool
    env_schema: list[dict[str, Any]]
    cmd: list[str] | None
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, server: MCPServer) -> "MCPServerResponse":
        return cls(
            id=server.id,
            name=server.name,
            description=server.description,
            docker_image_url=server.docker_image_url,
            version=server.version,
            tags=server.tags,
            is_public=server.is_public,
            env_schema=server.env_schema or [],
            cmd=server.cmd,
            status=server.status,
            created_at=server.created_at,
            updated_at=server.updated_at,
        )


@router.post("/", response_model=MCPServerResponse)
async def create_mcp_server(
    data: MCPServerCreate,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    server = await mcp_server_service.create_mcp_server(
        name=data.name,
        description=data.description,
        docker_image_url=data.docker_image_url,
        version=data.version,
        tags=data.tags,
        is_public=data.is_public,
        env_schema=data.env_schema,
        cmd=data.cmd,
    )
    return MCPServerResponse.from_domain(server)


@router.get("/", response_model=list[MCPServerResponse])
async def list_mcp_servers(
    user_context: UserContextDep,
    status: str | None = None,
    is_public: bool | None = None,
    tag: str | None = None,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    # Get all servers first, then filter manually since base service doesn't support filtering
    all_servers = await mcp_server_service.list()

    # Apply filters manually
    filtered_servers = []
    for server in all_servers:
        # Filter by status
        if status is not None and server.status != status:
            continue
        # Filter by is_public
        if is_public is not None and server.is_public != is_public:
            continue
        # Filter by tag (check if tag is in the server's tags list)
        if tag is not None and (not server.tags or tag not in server.tags):
            continue
        filtered_servers.append(server)

    return [MCPServerResponse.from_domain(server) for server in filtered_servers]


def load_mcp_provider_templates() -> dict[str, Any]:
    """Load MCP provider templates from YAML file."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up to project root and then to data directory
    # From core/apps/api/agentarea_api/api/v1/ -> go up to project root
    root_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "..", "..", ".."))
    yaml_path = os.path.join(root_dir, "data", "mcp_providers.yaml")

    try:
        with open(yaml_path) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # Fallback: try alternative paths
        alternative_paths = [
            os.path.join(root_dir, "core", "..", "data", "mcp_providers.yaml"),
            os.path.join(os.getcwd(), "data", "mcp_providers.yaml"),
            os.path.join(os.getcwd(), "..", "data", "mcp_providers.yaml"),
        ]

        for alt_path in alternative_paths:
            try:
                with open(alt_path) as f:
                    return yaml.safe_load(f)
            except FileNotFoundError:
                continue

        # If all paths fail, raise the original error with helpful info
        raise FileNotFoundError(
            f"Could not find mcp_providers.yaml. Tried paths: {yaml_path}, {alternative_paths}"
        ) from None


@router.get("/templates", response_model=list[dict[str, Any]])
async def get_mcp_server_templates(
    user_context: UserContextDep,
):
    """Get all available MCP server templates from the YAML configuration."""
    try:
        data = load_mcp_provider_templates()
        providers = data.get("providers", {})

        return [
            {
                "id": provider_data.get("id"),
                "key": provider_key,
                "name": provider_data.get("name", provider_key),
                "description": provider_data.get("description", ""),
                "icon": provider_data.get("icon", ""),
                "docker_image": provider_data.get("docker_image", ""),
                "env_vars": provider_data.get("env_vars", []),
                "capabilities": provider_data.get("capabilities", []),
            }
            for provider_key, provider_data in providers.items()
        ]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to load MCP server templates: {e!s}"
        ) from e


@router.get("/templates/{template_key}", response_model=dict[str, Any])
async def get_mcp_server_template(
    template_key: str,
    user_context: UserContextDep,
):
    """Get a specific MCP server template by key."""
    try:
        data = load_mcp_provider_templates()
        providers = data.get("providers", {})

        if template_key not in providers:
            raise HTTPException(status_code=404, detail="MCP Server template not found")

        provider_data = providers[template_key]
        return {
            "id": provider_data.get("id"),
            "key": template_key,
            "name": provider_data.get("name", template_key),
            "description": provider_data.get("description", ""),
            "icon": provider_data.get("icon", ""),
            "docker_image": provider_data.get("docker_image", ""),
            "env_vars": provider_data.get("env_vars", []),
            "capabilities": provider_data.get("capabilities", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get MCP server template: {e!s}"
        ) from e


@router.post("/from-template/{template_key}", response_model=MCPServerResponse)
async def create_mcp_server_from_template(
    template_key: str,
    user_context: UserContextDep,
    server_name: str,
    server_description: str = "",
    version: str = "latest",
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    """Create an MCP server from a template."""
    try:
        data = load_mcp_provider_templates()
        providers = data.get("providers", {})

        if template_key not in providers:
            raise HTTPException(status_code=404, detail="MCP Server template not found")

        provider_data = providers[template_key]

        # Create MCP server using the template
        server = await mcp_server_service.create_mcp_server(
            name=server_name,
            description=server_description or provider_data.get("description", ""),
            docker_image_url=provider_data.get("docker_image", ""),
            version=version,
            tags=[template_key],
            is_public=True,
            env_schema=provider_data.get("env_vars", []),
            json_spec=provider_data.get("json_spec", {}),
        )
        return MCPServerResponse.from_domain(server)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create server from template: {e!s}"
        ) from e


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: UUID,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    server = await mcp_server_service.get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return MCPServerResponse.from_domain(server)


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: UUID,
    data: MCPServerUpdate,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    server = await mcp_server_service.update_mcp_server(
        id=server_id,
        name=data.name,
        description=data.description,
        docker_image_url=data.docker_image_url,
        version=data.version,
        tags=data.tags,
        is_public=data.is_public,
        status=data.status,
    )
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return MCPServerResponse.from_domain(server)


@router.delete("/{server_id}")
async def delete_mcp_server(
    server_id: UUID,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    success = await mcp_server_service.delete_mcp_server(server_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return {"status": "success"}


@router.post("/{server_id}/deploy")
async def deploy_mcp_server(
    server_id: UUID,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    server = await mcp_server_service.get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # This would trigger the deployment process using the docker_image_url
    deployment_result = await mcp_server_service.deploy_server(server_id)
    if not deployment_result:
        raise HTTPException(status_code=500, detail="Failed to deploy MCP server")

    return {
        "status": "success",
        "message": f"MCP server {server.name} deployed successfully",
    }
