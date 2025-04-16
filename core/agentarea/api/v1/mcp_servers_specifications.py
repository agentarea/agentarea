from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl

from agentarea.modules.mcp.application.service import MCPServerService
from agentarea.modules.mcp.domain.models import MCPServer
from agentarea.api.deps.services import get_mcp_server_service

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


class MCPServerCreate(BaseModel):
    name: str
    description: str
    docker_image_url: str
    version: str
    tags: list[str] = []
    is_public: bool = False


class MCPServerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    docker_image_url: HttpUrl | None = None
    version: str | None = None
    tags: list[str] | None = None
    is_public: bool | None = None
    status: str | None = None


class MCPServerResponse(BaseModel):
    id: UUID
    name: str
    description: str
    docker_image_url: HttpUrl
    version: str
    tags: List[str]
    status: str
    is_public: bool
    last_updated: str

    @classmethod
    def from_domain(cls, server: MCPServer) -> "MCPServerResponse":
        return cls(
            id=server.id,
            name=server.name,
            description=server.description,
            docker_image_url=server.docker_image_url,
            version=server.version,
            tags=server.tags,
            status=server.status,
            is_public=server.is_public,
            last_updated=server.last_updated,
        )


@router.post("/", response_model=MCPServerResponse)
async def create_mcp_server(
    data: MCPServerCreate,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    server = await mcp_server_service.create_mcp_server(
        name=data.name,
        description=data.description,
        docker_image_url=data.docker_image_url,
        version=data.version,
        tags=data.tags,
        is_public=data.is_public,
    )
    return MCPServerResponse.from_domain(server)


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: UUID,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    server = await mcp_server_service.get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return MCPServerResponse.from_domain(server)


@router.get("/", response_model=List[MCPServerResponse])
async def list_mcp_servers(
    status: Optional[str] = None,
    is_public: Optional[bool] = None,
    tag: Optional[str] = None,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    servers = await mcp_server_service.list(status=status, is_public=is_public, tag=tag)
    return [MCPServerResponse.from_domain(server) for server in servers]


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: UUID,
    data: MCPServerUpdate,
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
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    success = await mcp_server_service.delete_mcp_server(server_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return {"status": "success"}


@router.post("/{server_id}/deploy")
async def deploy_mcp_server(
    server_id: UUID,
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
