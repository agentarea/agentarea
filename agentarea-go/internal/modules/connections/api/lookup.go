package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// Lookup answers whether MCP server instances are visible to a workspace and
// what they are called: its own, or managed by the platform
// (MCPServerInstanceRepository's visibility).
type Lookup interface {
	MCPInstanceExists(ctx context.Context, ws scope.Workspace, id string) (bool, error)
	// MCPInstanceNames maps each id of ids visible to ws to its name.
	MCPInstanceNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
}
