package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// ToolInstance is an MCP server instance with its available tools as stored.
type ToolInstance struct {
	ID, Name string
	Tools    []any
}

// MCPToolCatalogue lists the MCP tools of the caller's workspace.
type MCPToolCatalogue interface {
	// ToolInstances is MCPServerInstanceService.list() in its order; with
	// instanceID set it is that instance (mcp_service.get), or none.
	ToolInstances(ctx context.Context, c authn.Caller, instanceID string) ([]ToolInstance, error)
}
