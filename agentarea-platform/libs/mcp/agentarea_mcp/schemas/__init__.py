"""Pydantic schemas for the agentarea_mcp module.

DTOs that drive REST endpoints, the MCP toolset, and the service layer
live in :mod:`agentarea_mcp.schemas.dto`. The MCP server config and
deployment schemas live in :mod:`agentarea_mcp.schemas.server_config`
and are re-exported here alongside them.
"""

from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)
from agentarea_mcp.schemas.server_config import (
    MCPInstanceStatus,
    MCPServerConfig,
    MCPServerCreateRequest,
    MCPServerDeployment,
    MCPServerListResponse,
    MCPServerResponse,
    MCPServerStatus,
    MCPServerTemplate,
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
