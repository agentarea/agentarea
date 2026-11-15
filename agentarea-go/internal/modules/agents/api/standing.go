package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// Agent statuses (AgentStatus).
const (
	StatusActive   = "active"
	StatusArchived = "archived"
)

// Standing is what a module acting without a caller reads of an agent and its
// saved tasks: a trigger checks its agent still stands and loads its saved task.
// An id that is not a UUID names nothing.
type Standing interface {
	// AgentStatus is the status of the workspace's agent; false when it has none.
	AgentStatus(ctx context.Context, ws scope.Workspace, id string) (string, bool, error)
	// TaskDefinition is the workspace's saved task; false when it has none.
	TaskDefinition(ctx context.Context, ws scope.Workspace, id string) (TaskDef, bool, error)
}
