package app

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	agentsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// lateTaskDefRunner is runs' definition launcher for agents, which is built first.
type lateTaskDefRunner struct{ m *moduleSet }

var _ agentsservice.TaskDefRunner = lateTaskDefRunner{}

func (t lateTaskDefRunner) Start(ctx context.Context, c authn.Caller, run agentsservice.TaskDefRun) (any, error) {
	params := make(map[string]any, len(run.Parameters))
	for _, m := range run.Parameters {
		params[m.Key] = m.Value
	}
	return t.m.runsSurface.DefinitionRuns().StartDefinition(ctx, c, runsapi.DefinitionRun{
		DefinitionID: run.DefinitionID, AgentID: run.AgentID, Description: run.Description,
		Parameters: params, CreatedVia: run.CreatedVia,
	})
}
