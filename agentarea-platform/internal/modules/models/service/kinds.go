package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

var (
	_ api.ModelKinds    = (*Service)(nil)
	_ api.InstanceNames = (*Service)(nil)
)

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

// InstanceName is the instance's own name, its model's name, its kind and the reasoning levels it takes.
func (s *Service) InstanceName(ctx context.Context, ws scope.Workspace, id string) (api.InstanceName, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return api.InstanceName{}, false, nil
	}
	v, ok, err := s.instanceView(ctx, ws, u)
	if err != nil || !ok {
		return api.InstanceName{}, false, err
	}
	if v.Model == nil {
		return api.InstanceName{}, false, fmt.Errorf("model instance %s: model spec %s is not visible to the workspace", id, v.ModelSpecID)
	}
	levels := v.Model.ReasoningEfforts
	if len(levels) == 0 && v.Provider != nil {
		levels = v.Provider.ReasoningEfforts
	}
	return api.InstanceName{ID: v.ID, Name: v.Name, ModelName: v.Model.ModelName, Kind: v.Model.Kind, ReasoningLevels: levels}, true, nil
}
