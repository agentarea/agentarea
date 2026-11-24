package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ModelKinds reads the kind of a workspace's model instances (agents' model_id validation).
type ModelKinds interface {
	// ModelKind is the kind of the instance's model spec; found is false when
	// the workspace sees no instance id.
	ModelKind(ctx context.Context, ws scope.Workspace, id string) (kind string, found bool, err error)
}
