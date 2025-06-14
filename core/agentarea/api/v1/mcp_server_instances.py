from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agentarea.api.deps.services import get_mcp_server_instance_service
from agentarea.modules.mcp.application.service import MCPServerInstanceService
from agentarea.modules.mcp.domain.mpc_server_instance_model import MCPServerInstance

router = APIRouter(prefix="/mcp-server-instances", tags=["mcp-server-instances"])


class MCPServerInstanceCreateRequest(BaseModel):
    name: str = Field(..., description="Name of the MCP server instance")
    description: str | None = Field(None, description="Description of the instance")
    server_spec_id: str | None = Field(None, description="ID of the MCP server spec (optional)")
    json_spec: dict[str, Any] = Field(..., description="Configuration specification as JSON")


class MCPServerInstanceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    json_spec: dict[str, Any] | None = None
    status: str | None = None


class MCPServerInstanceResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    server_spec_id: str | None
    json_spec: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, instance: MCPServerInstance) -> "MCPServerInstanceResponse":
        return cls.model_validate({
            "id": instance.id,
            "name": instance.name,
            "description": instance.description,
            "server_spec_id": instance.server_spec_id,
            "json_spec": instance.json_spec,
            "status": instance.status,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        })


@router.post("/", response_model=MCPServerInstanceResponse)
async def create_mcp_server_instance(
    data: MCPServerInstanceCreateRequest,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    try:
        instance = await mcp_server_instance_service.create_instance(
            name=data.name,
            description=data.description,
            server_spec_id=data.server_spec_id,
            json_spec=data.json_spec,
        )

        if not instance:
            raise HTTPException(status_code=500, detail="Failed to create MCP instance")

        return MCPServerInstanceResponse.from_domain(instance)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create instance: {str(e)}")


@router.get("/{instance_id}/environment")
async def get_instance_environment(
    instance_id: UUID,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Get environment variables for an MCP server instance.
    Note: This endpoint should have proper authentication and authorization in production.
    """
    try:
        env_vars = await mcp_server_instance_service.get_instance_environment(instance_id)

        # Return env var names only for security (don't leak values)
        return {
            "instance_id": instance_id,
            "env_vars": list(env_vars.keys()),
            "message": f"Instance has {len(env_vars)} environment variables configured"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get environment: {str(e)}")


@router.get("/", response_model=list[MCPServerInstanceResponse])
async def list_mcp_server_instances(
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instances = await mcp_server_instance_service.list()
    return [MCPServerInstanceResponse.from_domain(instance) for instance in instances]


@router.get("/{instance_id}", response_model=MCPServerInstanceResponse)
async def get_mcp_server_instance(
    instance_id: UUID,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return MCPServerInstanceResponse.from_domain(instance)


@router.patch("/{instance_id}", response_model=MCPServerInstanceResponse)
async def update_mcp_server_instance(
    instance_id: UUID,
    data: MCPServerInstanceUpdate,
    mcp_server_instance_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await mcp_server_instance_service.update_instance(
        id=instance_id,
        name=data.name,
        description=data.description,
        json_spec=data.json_spec,
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


# REMOVED: Insecure endpoint that exposed secrets via HTTP
# Secrets are now resolved directly in the Go service using Infisical SDK
