package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ModelKinds reads the kind and names of a workspace's model instances (agents' model_id validation).
type ModelKinds interface {
	InstanceNames
	// ModelKind is the kind of the instance's model spec; found is false when
	// the workspace sees no instance id.
	ModelKind(ctx context.Context, ws scope.Workspace, id string) (kind string, found bool, err error)
}

// InstanceNames reads what a workspace's model instances are called (the agentarea/llm toolset's models).
type InstanceNames interface {
	// InstanceName is the instance's names, kind and reasoning levels; found
	// is false when the workspace sees no instance id.
	InstanceName(ctx context.Context, ws scope.Workspace, id string) (name InstanceName, found bool, err error)
}
