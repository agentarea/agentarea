"""MCP configuration and request schemas."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MCPServerStatus(str, Enum):
    """MCP server status enum."""

    REQUESTED = "requested"
    CREATING = "creating"
    CREATED = "created"
    READY = "ready"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"
    DELETED = "deleted"


class MCPServerTemplate(str, Enum):
    """Available MCP server templates."""

    FASTAPI = "fastapi"
    NODEJS = "nodejs"
    PYTHON = "python"
    GOLANG = "golang"
    NGINX = "nginx"
    REDIS = "redis"
    POSTGRES = "postgres"


class MCPServerConfig(BaseModel):
    """MCP server configuration model."""

    id: UUID | None = Field(None, description="Configuration ID (auto-generated)")
    agent_id: UUID = Field(..., description="Associated agent ID")
    service_name: str = Field(..., description="Unique service name")
    template: MCPServerTemplate = Field(..., description="Server template to use")
    environment: dict[str, Any] = Field(default_factory=dict, description="Environment variables")
    replicas: int = Field(default=1, ge=1, le=10, description="Number of replicas")
    resources: dict[str, str] | None = Field(None, description="Resource limits")

    class Config:
        """Pydantic config."""

        json_encoders = {UUID: str}  # noqa: RUF012


class MCPServerDeployment(BaseModel):
    """MCP server deployment information."""

    id: UUID = Field(..., description="Deployment ID")
    config_id: UUID = Field(..., description="Configuration ID")
    status: MCPServerStatus = Field(..., description="Current deployment status")
    runtime_id: str | None = Field(None, description="Container/Pod runtime ID")
    endpoint: str | None = Field(None, description="Public endpoint URL")
    internal_endpoint: str | None = Field(None, description="Internal service endpoint")
    health_check_url: str | None = Field(None, description="Health check endpoint")
    error: str | None = Field(None, description="Error message if failed")
    created_at: datetime = Field(..., description="Deployment creation time")
    updated_at: datetime = Field(..., description="Last update time")

    class Config:
        """Pydantic config."""

        json_encoders = {  # noqa: RUF012
            UUID: str,
            datetime: lambda v: v.isoformat(),  # type: ignore
        }


class MCPServerCreateRequest(BaseModel):
    """Request to create a new MCP server."""

    agent_id: UUID = Field(..., description="Agent ID")
    service_name: str = Field(..., min_length=1, max_length=50, description="Service name")
    template: MCPServerTemplate = Field(..., description="Server template")
    environment: dict[str, Any] = Field(default_factory=dict, description="Environment variables")
    replicas: int = Field(default=1, ge=1, le=10, description="Number of replicas")
    resources: dict[str, str] | None = Field(None, description="Resource limits")


class MCPServerListResponse(BaseModel):
    """Response for listing MCP servers."""

    servers: list[MCPServerDeployment] = Field(..., description="List of MCP server deployments")
    total: int = Field(..., description="Total number of servers")


class MCPServerResponse(BaseModel):
    """Response for MCP server operations."""

    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Response message")
    config_id: UUID | None = Field(None, description="Configuration ID")
    deployment_id: UUID | None = Field(None, description="Deployment ID")
    server: MCPServerDeployment | None = Field(None, description="Server deployment info")
