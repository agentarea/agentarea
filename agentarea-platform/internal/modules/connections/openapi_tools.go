package connections

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
)

// OpenAPITools is what runs call OpenAPI connection operations through. It
// reads the service as last built, so the ports Use sets reach it.
func (m *Module) OpenAPITools() api.OpenAPITools { return openAPITools{m} }

type openAPITools struct{ m *Module }

func (t openAPITools) CallOpenAPI(ctx context.Context, ws scope.Workspace, call api.OpenAPICall) api.OpenAPIResult {
	return t.m.svc.CallOpenAPI(ctx, ws, call)
}
