import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from agentarea_api.api.deps.services import get_mcp_server_instance_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_settings
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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
        return cls.model_validate(
            {
                "id": instance.id,
                "name": instance.name,
                "description": instance.description,
                "server_spec_id": instance.server_spec_id,
                "json_spec": instance.json_spec,
                "status": instance.status,
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            }
        )


@router.post("/", response_model=MCPServerInstanceResponse)
async def create_mcp_server_instance(
    data: MCPServerInstanceCreateRequest,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create instance: {e!s}") from e


@router.post("/check")
async def check_mcp_server_instance_configuration(
    data: dict[str, Any],
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """Check if an MCP server instance configuration is valid by validating it
    through the golang manager.
    """
    try:
        settings = get_settings()

        # Extract json_spec from the request (the frontend sends { json_spec: {...} })
        json_spec = data.get("json_spec", data)

        # Format the request for the golang manager
        validation_request = {
            "instance_id": "validation-check",  # Temporary ID for validation
            "name": "validation-test",  # Temporary name for validation
            "json_spec": json_spec,
            "dry_run": True,
        }

        # Validate the configuration through the golang manager
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.mcp.MCP_MANAGER_URL}/containers/validate",
                json=validation_request,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 200:
                return {
                    "valid": True,
                    "message": "Configuration is valid",
                    "details": response.json(),
                }
            else:
                return {
                    "valid": False,
                    "message": f"Configuration validation failed: {response.text}",
                    "status_code": response.status_code,
                }
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503, detail=f"Unable to connect to container manager for validation: {e!s}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to validate configuration: {e!s}"
        ) from e


@router.get("/{instance_id}/environment")
async def get_instance_environment(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
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
            "message": f"Instance has {len(env_vars)} environment variables configured",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get environment: {e!s}") from e


@router.get("/", response_model=list[MCPServerInstanceResponse])
async def list_mcp_server_instances(
    user_context: UserContextDep,
    created_by: str | None = Query(
        None, description="Filter by creator: 'me' for current user's instances only"
    ),
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    # Determine if we should filter by creator
    creator_scoped = created_by == "me"

    # Get instances from database (configuration/metadata)
    instances = await mcp_server_instance_service.list(creator_scoped=creator_scoped)

    # Get real-time status from golang manager
    try:
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mcp.MCP_MANAGER_URL}/containers/health")
            if response.status_code == 200:
                health_data = response.json()
                health_lookup = {
                    check["service_name"]: check for check in health_data.get("health_checks", [])
                }
            else:
                health_lookup = {}
    except Exception as e:
        logger.warning(f"Failed to get real-time status from container manager: {e}")
        health_lookup = {}

    # Merge database config with real-time status
    response_instances = []
    for instance in instances:
        response_instance = MCPServerInstanceResponse.from_domain(instance)

        # Override status with real-time data if available
        if instance.name in health_lookup:
            health_check = health_lookup[instance.name]
            if health_check["container_status"] == "running" and health_check["healthy"]:
                response_instance.status = "running"
            elif health_check["container_status"] == "running" and not health_check["healthy"]:
                response_instance.status = "unhealthy"
            elif health_check["container_status"] == "stopped":
                response_instance.status = "stopped"

        response_instances.append(response_instance)

    return response_instances


@router.get("/{instance_id}", response_model=MCPServerInstanceResponse)
async def get_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    # Get instance from database (configuration/metadata)
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    response_instance = MCPServerInstanceResponse.from_domain(instance)

    # Get real-time status from golang manager
    try:
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mcp.MCP_MANAGER_URL}/containers/health")
            if response.status_code == 200:
                health_data = response.json()
                health_lookup = {
                    check["service_name"]: check for check in health_data.get("health_checks", [])
                }

                # Override status with real-time data if available
                if instance.name in health_lookup:
                    health_check = health_lookup[instance.name]
                    if health_check["container_status"] == "running" and health_check["healthy"]:
                        response_instance.status = "running"
                    elif (
                        health_check["container_status"] == "running"
                        and not health_check["healthy"]
                    ):
                        response_instance.status = "unhealthy"
                    elif health_check["container_status"] == "stopped":
                        response_instance.status = "stopped"
    except Exception as e:
        logger.warning(f"Failed to get real-time status from container manager: {e}")
        # Fall back to database status

    return response_instance


@router.patch("/{instance_id}", response_model=MCPServerInstanceResponse)
async def update_mcp_server_instance(
    instance_id: UUID,
    data: MCPServerInstanceUpdate,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
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
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    success = await mcp_server_instance_service.delete_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success"}


@router.post("/{instance_id}/start")
async def start_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    success = await mcp_server_instance_service.start_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success", "message": "Instance started successfully"}


@router.post("/{instance_id}/stop")
async def stop_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    success = await mcp_server_instance_service.stop_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success", "message": "Instance stopped successfully"}


# REMOVED: Insecure endpoint that exposed secrets via HTTP
# Secrets are now resolved directly in the Go service using Infisical SDK


@router.get("/health/containers")
async def get_containers_health(
    user_context: UserContextDep,
):
    """Get health status of all MCP containers by proxying to the golang manager."""
    try:
        settings = get_settings()
        # Proxy request to golang manager
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mcp.MCP_MANAGER_URL}/containers/health")

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get container health: {response.text}",
                )

            # No URL transformation needed - Go manager returns correct external URLs
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503, detail=f"Unable to connect to container manager: {e!s}"
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get container health: {e!s}") from e


@router.get("/{instance_id}/tools", response_model=list[dict[str, Any]])
async def get_instance_available_tools(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Get available tools for a specific MCP server instance."""
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP server instance not found")

    return instance.get_available_tools()


@router.post("/{instance_id}/discover-tools")
async def discover_instance_tools(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Trigger tool discovery for a specific MCP server instance."""
    success = await service.discover_and_store_tools(instance_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to discover tools for the instance")

    return {"message": "Tool discovery completed successfully"}
