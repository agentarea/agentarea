package handlers

import (
	"context"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/sandbox"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

func (s *Server) ListSandboxesV1SandboxesGet(ctx context.Context, _ gen.ListSandboxesV1SandboxesGetRequestObject) (gen.ListSandboxesV1SandboxesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	l, err := s.svc.Sandboxes(ctx, c.Workspace.ID())
	if err != nil {
		return nil, err
	}
	items := make([]any, len(l.Items))
	for i, it := range l.Items {
		items[i] = wirejson.Object{
			{Key: "id", Value: it.ID}, {Key: "provider", Value: it.Provider}, {Key: "task_id", Value: it.TaskID},
			{Key: "state", Value: it.State}, {Key: "created_at", Value: it.CreatedAt}, {Key: "expires_at", Value: it.ExpiresAt},
			{Key: "resources", Value: wirejson.Object{{Key: "cpu", Value: it.CPU}, {Key: "memory", Value: it.Memory}}},
			{Key: "isolation", Value: it.Isolation},
		}
	}
	return ok(wirejson.Object{{Key: "items", Value: items}, {Key: "total", Value: l.Total}}), nil
}
