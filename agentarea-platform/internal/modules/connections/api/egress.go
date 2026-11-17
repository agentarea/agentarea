package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// EgressBoundInstance is an MCP instance whose json_spec binds an egress exit.
type EgressBoundInstance struct {
	ID, Name, Transport string
}

// EgressBindings is what egress exits read and do of the instances bound to
// one (bound_instances, retire_runtime_before_mutation).
type EgressBindings interface {
	BoundToEgressExit(ctx context.Context, ws scope.Workspace, exitID string) ([]EgressBoundInstance, error)
	// RetireBeforeMutation stops a running instance before the route it
	// started with changes; an error keeps the change from being stored.
	RetireBeforeMutation(ctx context.Context, instanceID string) error
}
