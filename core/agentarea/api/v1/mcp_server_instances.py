from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl

from agentarea.modules.mcp.application.service import MCPServerInstanceService
from agentarea.modules.mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea.api.deps.services import get_mcp_server_instance_service

router = APIRouter(prefix="/mcp-server-instances", tags=["mcp-server-instances"])


class MCPServerInstanceCreate(BaseModel):
    server_id: UUID
    name: str
    endpoint_url: str
    config: Dict[str, Any] = {}


class MCPServerInstanceUpdate(BaseModel):
    name: Optional[str] = None
    endpoint_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class MCPServerInstanceResponse(BaseModel):
    id: UUID
    server_id: UUID
    name: str
    endpoint_url: str
    status: str
    config: Dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, instance: MCPServerInstance) -> "MCPServerInstanceResponse":
        return cls(
            id=instance.id,
            server_id=instance.server_id,
            name=instance.name,
            endpoint_url=instance.endpoint_url,
            status=instance.status,
            config=instance.config,
            created_at=instance.created_at.isoformat(),
            updated_at=instance.updated_at.isoformat(),
        )


@router.post("/", response_model=MCPServerInstanceResponse)
async def create_mcp_server_instance(
    data: MCPServerInstanceCreate,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await mcp_server_instance_service.create_instance(
        server_id=data.server_id,
        name=data.name,
        endpoint_url=data.endpoint_url,
        config=data.config,
    )
    
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server not found")
        
    return MCPServerInstanceResponse.from_domain(instance)


@router.get("/{instance_id}", response_model=MCPServerInstanceResponse)
async def get_mcp_server_instance(
    instance_id: UUID,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return MCPServerInstanceResponse.from_domain(instance)


@router.get("/", response_model=List[MCPServerInstanceResponse])
async def list_mcp_server_instances(
    server_id: Optional[UUID] = None,
    status: Optional[str] = None,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instances = await mcp_server_instance_service.list(server_id=server_id, status=status)
    return [MCPServerInstanceResponse.from_domain(instance) for instance in instances]


@router.patch("/{instance_id}", response_model=MCPServerInstanceResponse)
async def update_mcp_server_instance(
    instance_id: UUID,
    data: MCPServerInstanceUpdate,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await mcp_server_instance_service.update_instance(
        id=instance_id,
        name=data.name,
        endpoint_url=data.endpoint_url,
        config=data.config,
        status=data.status,
    )
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return MCPServerInstanceResponse.from_domain(instance)


@router.delete("/{instance_id}")
async def delete_mcp_server_instance(
    instance_id: UUID,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    success = await mcp_server_instance_service.delete_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success"}


@router.post("/{instance_id}/start")
async def start_mcp_server_instance(
    instance_id: UUID,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    success = await mcp_server_instance_service.start_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success", "message": "Instance started successfully"}


@router.post("/{instance_id}/stop")
async def stop_mcp_server_instance(
    instance_id: UUID,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    success = await mcp_server_instance_service.stop_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success", "message": "Instance stopped successfully"} 