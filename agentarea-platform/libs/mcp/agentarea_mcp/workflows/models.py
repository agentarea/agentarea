"""Pydantic models for MCP instance lifecycle workflows and activities."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ── Workflow request / result ────────────────────────────────────────────


class StartMCPInstanceRequest(BaseModel):
    """Request to start an MCP server instance via Temporal workflow."""

    instance_id: UUID
    user_id: str
    workspace_id: str
    json_spec: dict[str, Any] = Field(default_factory=dict)
    instance_name: str


class StartMCPInstanceResult(BaseModel):
    """Result of the start workflow."""

    instance_id: UUID
    success: bool
    status: str  # "running" | "failed"
    tools_discovered: int = 0
    error_message: str | None = None


class StopMCPInstanceRequest(BaseModel):
    """Request to stop an MCP server instance via Temporal workflow."""

    instance_id: UUID
    user_id: str
    workspace_id: str


class StopMCPInstanceResult(BaseModel):
    """Result of the stop workflow."""

    instance_id: UUID
    success: bool
    status: str  # "stopped" | "failed"
    error_message: str | None = None


# ── Activity models ──────────────────────────────────────────────────────


class UpdateInstanceStatusRequest(BaseModel):
    """Request to update MCP instance status in DB."""

    instance_id: UUID
    status: str
    user_id: str
    workspace_id: str
    json_spec_patch: dict[str, Any] | None = None


class UpdateInstanceStatusResult(BaseModel):
    success: bool
    error: str | None = None


class CreateContainerRequest(BaseModel):
    """Request to call Go MCP Manager POST /instances."""

    instance_id: UUID
    instance_name: str
    workspace_id: str
    json_spec: dict[str, Any]


class CreateContainerResult(BaseModel):
    success: bool
    error: str | None = None


class DeleteContainerRequest(BaseModel):
    """Request to call Go MCP Manager DELETE /instances/:id."""

    instance_id: UUID


class DeleteContainerResult(BaseModel):
    success: bool
    error: str | None = None


class PollContainerHealthRequest(BaseModel):
    """Request to poll Go MCP Manager GET /instances/:id/health."""

    instance_id: UUID


class PollContainerHealthResult(BaseModel):
    healthy: bool
    status: str  # raw status from Go manager
    error: str | None = None


class DiscoverToolsRequest(BaseModel):
    """Request to discover tools from a running MCP server."""

    instance_id: UUID
    instance_name: str  # slug used in gateway URL


class DiscoverToolsResult(BaseModel):
    success: bool
    tools: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class PublishMCPEventRequest(BaseModel):
    """Request to publish a status event for UI SSE."""

    instance_id: UUID
    workspace_id: str
    user_id: str
    event_type: str
    event_data: dict[str, Any] = Field(default_factory=dict)


class PublishMCPEventResult(BaseModel):
    success: bool
    error: str | None = None


class GetInstanceEnvironmentRequest(BaseModel):
    """Request to retrieve env vars from secret manager for container startup."""

    instance_id: UUID
    user_id: str
    workspace_id: str


class GetInstanceEnvironmentResult(BaseModel):
    env_vars: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
