package api

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// MCPServer is a workspace's own mcp_servers row by id and name.
type MCPServer struct{ ID, Name string }

// MCPInventory is MCPServerRepository list_all and get_by_id as the access
// explorer reads them: the workspace's own rows only.
type MCPInventory interface {
	// MCPServers is newest first.
	MCPServers(ctx context.Context, ws scope.Workspace) ([]MCPServer, error)
	MCPServerExists(ctx context.Context, ws scope.Workspace, id uuid.UUID) (bool, error)
}
