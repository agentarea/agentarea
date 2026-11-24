package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Lookup answers whether MCP server instances are visible to a workspace and
// what they are called: its own, or managed by the platform
// (MCPServerInstanceRepository's visibility).
type Lookup interface {
	MCPInstanceExists(ctx context.Context, ws scope.Workspace, id string) (bool, error)
	// MCPInstanceNames maps each id of ids visible to ws to its name.
	MCPInstanceNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
}

// Attachable is what attaching a connection to a client reads: whether ws sees
// an MCP instance or an OpenAPI connection (its own or the platform's), whether
// the platform manages it, and what OpenAPI connections are called.
type Attachable interface {
	MCPInstance(ctx context.Context, ws scope.Workspace, id string) (found, platform bool, err error)
	OpenAPIConnection(ctx context.Context, ws scope.Workspace, id string) (found, platform bool, err error)
	OpenAPIConnectionNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
}
