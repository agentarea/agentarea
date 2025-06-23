"""MCP Event schemas for event-driven architecture."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MCPEventType(str, Enum):
    """MCP event types for event sourcing."""

    # Server lifecycle events
    SERVER_CREATE_REQUESTED = "mcp.server.create.requested"
    SERVER_CREATING = "mcp.server.creating"
    SERVER_CREATED = "mcp.server.created"
    SERVER_READY = "mcp.server.ready"
    SERVER_FAILED = "mcp.server.failed"
    SERVER_STOPPING = "mcp.server.stopping"
    SERVER_STOPPED = "mcp.server.stopped"
    SERVER_DELETED = "mcp.server.deleted"

    # Health and monitoring events
    SERVER_HEALTH_CHECK = "mcp.server.health.check"
    SERVER_UNHEALTHY = "mcp.server.unhealthy"
    SERVER_RECOVERED = "mcp.server.recovered"

    # Resource events
    SERVER_SCALED = "mcp.server.scaled"
    SERVER_RESOURCE_LIMIT = "mcp.server.resource.limit"


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)


class MCPBaseEvent(BaseModel):
    """Base event model for all MCP events."""

    event_id: UUID = Field(..., description="Unique event identifier")
    event_type: MCPEventType = Field(..., description="Type of the event")
    timestamp: datetime = Field(default_factory=utc_now, description="Event timestamp")
    config_id: UUID = Field(..., description="MCP server configuration ID")
    agent_id: UUID | None = Field(None, description="Associated agent ID")
    correlation_id: str | None = Field(None, description="Request correlation ID")


class MCPServerCreateRequestedEvent(MCPBaseEvent):
    """Event fired when MCP server creation is requested."""

    event_type: MCPEventType = MCPEventType.SERVER_CREATE_REQUESTED
    template: str = Field(..., description="MCP server template name")
    environment: dict[str, Any] = Field(default_factory=dict, description="Environment variables")
    replicas: int = Field(default=1, description="Number of replicas")
    user_id: UUID = Field(..., description="User who requested the server")


class MCPServerCreatingEvent(MCPBaseEvent):
    """Event fired when MCP server creation starts."""

    event_type: MCPEventType = MCPEventType.SERVER_CREATING
    runtime_id: str = Field(..., description="Container/Pod runtime ID")
    image: str = Field(..., description="Container image being deployed")


class MCPServerCreatedEvent(MCPBaseEvent):
    """Event fired when MCP server container is created but not yet ready."""

    event_type: MCPEventType = MCPEventType.SERVER_CREATED
    runtime_id: str = Field(..., description="Container/Pod runtime ID")
    internal_endpoint: str = Field(..., description="Internal service endpoint")


class MCPServerReadyEvent(MCPBaseEvent):
    """Event fired when MCP server is ready to accept connections."""

    event_type: MCPEventType = MCPEventType.SERVER_READY
    runtime_id: str = Field(..., description="Container/Pod runtime ID")
    endpoint: str = Field(..., description="Public endpoint URL")
    internal_endpoint: str = Field(..., description="Internal service endpoint")
    health_check_url: str = Field(..., description="Health check endpoint")


class MCPServerFailedEvent(MCPBaseEvent):
    """Event fired when MCP server deployment fails."""

    event_type: MCPEventType = MCPEventType.SERVER_FAILED
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    runtime_id: str | None = Field(None, description="Container/Pod runtime ID if available")
    retry_count: int = Field(default=0, description="Number of retry attempts")


class MCPServerStoppedEvent(MCPBaseEvent):
    """Event fired when MCP server is stopped."""

    event_type: MCPEventType = MCPEventType.SERVER_STOPPED
    runtime_id: str = Field(..., description="Container/Pod runtime ID")
    reason: str = Field(..., description="Reason for stopping")


class MCPServerHealthEvent(MCPBaseEvent):
    """Event fired for server health status updates."""

    event_type: MCPEventType = MCPEventType.SERVER_HEALTH_CHECK
    runtime_id: str = Field(..., description="Container/Pod runtime ID")
    status: str = Field(..., description="Health status (healthy/unhealthy)")
    response_time_ms: int | None = Field(None, description="Health check response time")
    error: str | None = Field(None, description="Error message if unhealthy")


# Event union type for type checking
MCPEvent = (
    MCPServerCreateRequestedEvent
    | MCPServerCreatingEvent
    | MCPServerCreatedEvent
    | MCPServerReadyEvent
    | MCPServerFailedEvent
    | MCPServerStoppedEvent
    | MCPServerHealthEvent
)
