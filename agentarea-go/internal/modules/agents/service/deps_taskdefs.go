package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// TaskDefTriggers counts the triggers that run a saved task (streams module, TriggerRepository.count).
type TaskDefTriggers interface {
	CountByTaskDefinition(ctx context.Context, ws scope.Workspace, definitionID string) (int64, error)
}

// TaskDefRun is the run a saved task starts: RunCreate plus its provenance.
type TaskDefRun struct {
	DefinitionID string
	AgentID      string
	Description  string
	// Parameters are the saved ones with the call's merged over them.
	Parameters wirejson.Object
	// CreatedVia is "api" or "mcp".
	CreatedVia string
}

// TaskDefRunner starts runs (runs module, TaskService.start_run).
type TaskDefRunner interface {
	// Start returns the TaskResponse body; its refusals are errors the module's
	// error mapping renders (404 agent, 422 policy or model, 409 archived).
	Start(ctx context.Context, c authn.Caller, run TaskDefRun) (any, error)
}

// TaskDefPorts are the task definition routes' own ports; a nil port answers 501 where it is needed.
type TaskDefPorts struct {
	Triggers TaskDefTriggers
	Runner   TaskDefRunner
}
