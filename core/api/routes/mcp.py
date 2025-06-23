"""MCP API routes for server instance management."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.api.deps.events import EventBrokerDep, get_event_broker
from agentarea.common.infrastructure.database import get_db_session
from agentarea.modules.mcp.application.service import MCPServerInstanceService, MCPServerService
from agentarea.modules.mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea.modules.mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Pydantic Schemas for this router ---


class MCPServerInstanceCreate(BaseModel):
    """Schema for creating a new MCP server instance."""

    server_spec_id: UUID | None = Field(
        None, description="ID of the MCPServer specification to use."
    )
    name: str = Field(..., description="A unique name for the instance.")
    description: str | None = Field(None, description="Optional description for the instance.")
    json_spec: dict[str, Any] = Field(..., description="Container specification as JSON.")


class MCPServerInstanceResponse(BaseModel):
    """Schema for MCP server instance response."""

    id: str
    name: str
    description: str | None
    server_spec_id: str | None
    json_spec: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


# --- Dependencies ---


async def get_mcp_server_instance_service(
    db_session: AsyncSession = Depends(get_db_session),
    event_broker: EventBrokerDep = Depends(get_event_broker),
) -> MCPServerInstanceService:
    """Get MCP server instance service with dependencies."""
    instance_repo = MCPServerInstanceRepository(db_session)
    server_repo = MCPServerRepository(db_session)

    # Create a minimal service for database operations only
    # The actual container management is handled by the Go MCP infrastructure
    class MinimalMCPService:
        def __init__(self, instance_repo, server_repo, event_broker):
            self.repository = instance_repo
            self.server_repository = server_repo
            self.event_broker = event_broker

    return MinimalMCPService(instance_repo, server_repo, event_broker)


async def get_mcp_server_service(
    db_session: AsyncSession = Depends(get_db_session),
    event_broker: EventBrokerDep = Depends(get_event_broker),
) -> MCPServerService:
    """Get MCP server service with dependencies."""
    server_repo = MCPServerRepository(db_session)
    return MCPServerService(repository=server_repo, event_broker=event_broker)


# --- API Routes ---


@router.get("/v1/mcp-server-instances/", response_model=list[MCPServerInstanceResponse])
async def list_mcp_server_instances(
    service=Depends(get_mcp_server_instance_service),
):
    """List all MCP server instances."""
    try:
        instances = await service.repository.list()
        return [
            MCPServerInstanceResponse(
                id=str(instance.id),
                name=instance.name,
                description=instance.description,
                server_spec_id=instance.server_spec_id,
                json_spec=instance.json_spec,
                status=instance.status,
                created_at=instance.created_at.isoformat(),
                updated_at=instance.updated_at.isoformat(),
            )
            for instance in instances
        ]
    except Exception as e:
        logger.error(f"Error listing MCP server instances: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP server instances",
        ) from e


@router.post("/v1/mcp-server-instances/", response_model=MCPServerInstanceResponse)
async def create_mcp_server_instance(
    data: MCPServerInstanceCreate,
    service=Depends(get_mcp_server_instance_service),
    server_service: MCPServerService = Depends(get_mcp_server_service),
):
    """Create a new MCP server instance and publish event for Go infrastructure."""
    try:
        # Build the json_spec based on the architecture pattern
        json_spec = data.json_spec.copy()

        # If server_spec_id is provided, merge with server's env_schema
        if data.server_spec_id:
            server = await server_service.get(data.server_spec_id)
            if not server:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"MCP server with ID {data.server_spec_id} not found",
                )

            # For managed MCP providers, add container info from server
            json_spec.update(
                {
                    "image": server.docker_image_url,
                    "version": server.version,
                    "port": json_spec.get("port", 8000),  # Default MCP port
                }
            )

            # Add cmd from server specification if available
            if server.cmd:
                json_spec["cmd"] = server.cmd

            # Add env_vars from server's env_schema if provided
            if server.env_schema and "environment" not in json_spec:
                json_spec["environment"] = {
                    var["name"]: var.get("default", "") for var in server.env_schema
                }

        # Create the instance in database
        instance = MCPServerInstance(
            name=data.name,
            description=data.description,
            server_spec_id=str(data.server_spec_id) if data.server_spec_id else None,
            json_spec=json_spec,
            status="requested",
        )

        # Save to database
        created_instance = await service.repository.create(instance)

        # Publish domain event - Go MCP Infrastructure will listen and create the actual container
        if service.event_broker:
            from agentarea.modules.mcp.domain.events import MCPServerInstanceCreated

            await service.event_broker.publish(
                MCPServerInstanceCreated(
                    instance_id=str(created_instance.id),
                    server_spec_id=created_instance.server_spec_id,
                    name=created_instance.name,
                    json_spec=created_instance.json_spec,
                )
            )

        return MCPServerInstanceResponse(
            id=str(created_instance.id),
            name=created_instance.name,
            description=created_instance.description,
            server_spec_id=created_instance.server_spec_id,
            json_spec=created_instance.json_spec,
            status=created_instance.status,
            created_at=created_instance.created_at.isoformat(),
            updated_at=created_instance.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating MCP server instance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create MCP server instance",
        ) from e


@router.get("/v1/mcp-server-instances/{instance_id}", response_model=MCPServerInstanceResponse)
async def get_mcp_server_instance(
    instance_id: UUID,
    service=Depends(get_mcp_server_instance_service),
):
    """Get a specific MCP server instance."""
    try:
        instance = await service.repository.get(instance_id)
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MCP server instance with ID {instance_id} not found",
            )

        return MCPServerInstanceResponse(
            id=str(instance.id),
            name=instance.name,
            description=instance.description,
            server_spec_id=instance.server_spec_id,
            json_spec=instance.json_spec,
            status=instance.status,
            created_at=instance.created_at.isoformat(),
            updated_at=instance.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting MCP server instance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get MCP server instance",
        ) from e


@router.delete("/v1/mcp-server-instances/{instance_id}")
async def delete_mcp_server_instance(
    instance_id: UUID,
    service=Depends(get_mcp_server_instance_service),
):
    """Delete an MCP server instance and publish event for Go infrastructure."""
    try:
        success = await service.repository.delete(instance_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MCP server instance with ID {instance_id} not found",
            )

        # Publish domain event for deletion - Go infrastructure will handle container cleanup
        if service.event_broker:
            from agentarea.modules.mcp.domain.events import MCPServerInstanceDeleted

            await service.event_broker.publish(MCPServerInstanceDeleted(instance_id=instance_id))

        return {"message": "MCP server instance deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting MCP server instance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP server instance",
        ) from e
