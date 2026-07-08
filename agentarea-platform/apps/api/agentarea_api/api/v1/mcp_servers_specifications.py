from contextlib import suppress
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import get_mcp_server_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.permission import require_permission
from agentarea_common.base.pagination import PaginatedResponse, PaginationParams
from agentarea_common.utils.types import UtcDatetime
from agentarea_mcp.application.service import MCPServerService
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.schemas.dto import MCPServerCreate, MCPServerUpdate
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ._access_control_grants import grant_user_relation

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


class MCPServerResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    docker_image_url: str | None = None
    version: str
    tags: list[str]
    is_public: bool
    env_schema: list[dict[str, Any]]
    cmd: list[str] | None
    remote_url: str | None = None
    json_spec: dict[str, Any] | None = None
    registry_url: str | None = None
    status: str
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def from_domain(cls, server: MCPServer) -> "MCPServerResponse":
        return cls(
            id=server.id,
            slug=server.slug,
            name=server.name,
            description=server.description,
            docker_image_url=server.docker_image_url,
            version=server.version,
            tags=server.tags,
            is_public=server.is_public,
            env_schema=server.env_schema or [],
            cmd=server.cmd,
            remote_url=server.remote_url,
            json_spec=server.json_spec,
            registry_url=server.registry_url,
            status=server.status,
            created_at=server.created_at,
            updated_at=server.updated_at,
        )


async def _resolve_server_id(mcp_server_service: MCPServerService, identifier: str) -> UUID | None:
    """Resolve a UUID for an MCP server referenced by UUID *or* slug."""
    with suppress(ValueError):
        return UUID(identifier)
    server = await mcp_server_service.get_by_slug(identifier)
    return server.id if server else None


@router.post("/", response_model=MCPServerResponse)
async def create_mcp_server(
    data: MCPServerCreate,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    server = await mcp_server_service.create_mcp_server(data)
    await grant_user_relation(
        namespace="MCPServer",
        object_id=server.id,
        relation="operators",
        user_id=user_context.user_id,
    )
    return MCPServerResponse.from_domain(server)


@router.get("/", response_model=PaginatedResponse[MCPServerResponse])
async def list_mcp_servers(
    user_context: UserContextDep,
    pagination: PaginationParams = Depends(),
    status: str | None = None,
    is_public: bool | None = None,
    tag: str | None = None,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    servers, total = await mcp_server_service.list_servers(
        status=status,
        is_public=is_public,
        tag=tag,
        search=pagination.search,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return PaginatedResponse(
        items=[MCPServerResponse.from_domain(server) for server in servers],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=(pagination.offset + pagination.page_size) < total,
    )


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    resolved_id = await _resolve_server_id(mcp_server_service, server_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    server = await mcp_server_service.get(resolved_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return MCPServerResponse.from_domain(server)


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: str,
    data: MCPServerUpdate,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    resolved_id = await _resolve_server_id(mcp_server_service, server_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    await require_permission("edit", "mcp_server", str(resolved_id), user_context.user_id)
    server = await mcp_server_service.update_mcp_server(resolved_id, data)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return MCPServerResponse.from_domain(server)


@router.delete("/{server_id}")
async def delete_mcp_server(
    server_id: str,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    resolved_id = await _resolve_server_id(mcp_server_service, server_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    await require_permission("delete", "mcp_server", str(resolved_id), user_context.user_id)
    success = await mcp_server_service.delete_mcp_server(resolved_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return {"status": "success"}


@router.post("/{server_id}/deploy")
async def deploy_mcp_server(
    server_id: str,
    user_context: UserContextDep,
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
):
    resolved_id = await _resolve_server_id(mcp_server_service, server_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    server = await mcp_server_service.get(resolved_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # This would trigger the deployment process using the docker_image_url
    deployment_result = await mcp_server_service.deploy_server(resolved_id)
    if not deployment_result:
        raise HTTPException(status_code=500, detail="Failed to deploy MCP server")

    return {
        "status": "success",
        "message": f"MCP server {server.name} deployed successfully",
    }
