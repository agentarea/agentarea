package connections

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
)

// RunTools resolves a run's tools (runs' RunDefinitions.Tools). It reads the
// service as last built, so the ports Use sets reach it.
func (m *Module) RunTools() api.RunTools { return runTools{m} }

type runTools struct{ m *Module }

func (t runTools) RunTools(ctx context.Context, req api.RunToolsRequest) (api.RunToolSet, error) {
	return t.m.svc.RunTools(ctx, req)
}
