"""Pydantic schemas for the agentarea_mcp module.

DTOs that drive REST endpoints, the MCP toolset, and the service layer
live in :mod:`agentarea_mcp.schemas.dto`. Legacy MCP server config /
deployment schemas remain accessible via re-export from
:mod:`agentarea_mcp.schemas` for backwards compatibility.
"""

from agentarea_mcp._schemas_legacy import (
    MCPInstanceStatus,
    MCPServerConfig,
    MCPServerCreateRequest,
    MCPServerDeployment,
    MCPServerListResponse,
    MCPServerResponse,
    MCPServerStatus,
    MCPServerTemplate,
)
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)

__all__ = [
    "MCPInstanceStatus",
    "MCPServerConfig",
    "MCPServerCreate",
    "MCPServerCreateRequest",
    "MCPServerDeployment",
    "MCPServerInstanceCreate",
    "MCPServerInstanceUpdate",
    "MCPServerListResponse",
    "MCPServerResponse",
    "MCPServerStatus",
    "MCPServerTemplate",
    "MCPServerUpdate",
]
