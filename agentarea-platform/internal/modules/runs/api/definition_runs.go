package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// DefinitionRun is the run a saved task starts.
type DefinitionRun struct {
	DefinitionID, AgentID, Description string
	Parameters                         map[string]any
	// CreatedVia is "api" or "mcp".
	CreatedVia string
}

// DefinitionRuns starts a run for a task definition (TaskService.start_run).
type DefinitionRuns interface {
	// StartDefinition returns the TaskResponse body; a refusal is an error
	// that renders with its own status.
	StartDefinition(ctx context.Context, c authn.Caller, in DefinitionRun) (wirejson.Object, error)
}
