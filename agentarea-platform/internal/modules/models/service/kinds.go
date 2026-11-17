package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

var _ api.ModelKinds = (*Service)(nil)

// ModelKind is AgentService._model_instance_kind's read: instance.model_spec.kind.
func (s *Service) ModelKind(ctx context.Context, ws scope.Workspace, id string) (string, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return "", false, nil
	}
	v, ok, err := s.instanceView(ctx, ws, u)
	if err != nil || !ok {
		return "", false, err
	}
	if v.Model == nil {
		return "", false, fmt.Errorf("model instance %s: model spec %s is not visible to the workspace", id, v.ModelSpecID)
	}
	return v.Model.Kind, true, nil
}
