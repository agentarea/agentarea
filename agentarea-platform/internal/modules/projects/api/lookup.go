package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Lookup reads what other modules need of a workspace's projects.
type Lookup interface {
	// IDs is every project id of ws (ProjectService.list() with no limit).
	IDs(ctx context.Context, ws scope.Workspace) ([]string, error)
}
