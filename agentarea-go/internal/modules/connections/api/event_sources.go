package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// MCPEventSource is what an MCP Events source reads of an MCP server instance.
type MCPEventSource struct {
	AuthConfigID *string
	ManagedBy    *string
	// Events is the instance's stored events record (MCPServerInstance.events).
	Events map[string]any
}

// MCPEventSources reads the workspace's MCP server instances an MCP Events source may name.
type MCPEventSources interface {
	// MCPEventSource is false when the workspace has no such instance.
	MCPEventSource(ctx context.Context, ws scope.Workspace, id string) (MCPEventSource, bool, error)
}
