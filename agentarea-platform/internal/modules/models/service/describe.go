package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

var _ api.Describer = (*Service)(nil)

// Describe is ModelService.describe: the instance a call of kind would run on, its credential unread.
func (s *Service) Describe(ctx context.Context, p api.Principal, modelID, kind string) (api.ResolvedModel, error) {
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		return api.ResolvedModel{}, err
	}
	id, err := uuid.Parse(modelID)
	if err != nil {
		return api.ResolvedModel{}, &resolveError{api.ErrNotFound, fmt.Sprintf("Model instance %s not found", modelID)}
	}
	v, ok, err := s.instanceView(ctx, ws, id)
	if err != nil {
		return api.ResolvedModel{}, err
	}
	if !ok || v.Config == nil || v.Provider == nil || v.Model == nil {
		return api.ResolvedModel{}, &resolveError{api.ErrNotFound, fmt.Sprintf("Model instance %s not found", modelID)}
	}
	if !v.IsActive {
		return api.ResolvedModel{}, &resolveError{api.ErrRefused, fmt.Sprintf("Model instance %s is inactive", modelID)}
	}
	if part := foreignPart(v); part != "" {
		return api.ResolvedModel{}, &resolveError{api.ErrRefused, fmt.Sprintf("Model instance %s uses a %s from another workspace", modelID, part)}
	}
	if v.Model.Kind != kind {
		return api.ResolvedModel{}, &resolveError{api.ErrKindMismatch, fmt.Sprintf("Model instance %s is a %s model; a %s model is required", modelID, v.Model.Kind, kind)}
	}
	m := v.Model
	out := api.ResolvedModel{
		ModelID: modelID, ModelName: m.ModelName, DisplayName: m.DisplayName, ProviderType: v.Provider.ProviderType, ProviderDisplayName: v.Provider.Name,
		MaxOutputTokens: m.MaxOutputTokens,
		Prices: api.ModelPrices{
			Input: m.InputCostPerToken, Output: m.OutputCostPerToken, CachedInput: m.CachedInputCostPerToken,
			CacheCreation: m.CacheCreationInputCostPerToken, Image: m.OutputCostPerImage, VideoSecond: m.OutputCostPerVideoPerSecond,
		},
		Provider: providerProfile(*v.Provider), APIKeySecret: str(v.Config.APIKey), ManagedBy: str(v.Config.ManagedBy), EndpointURL: str(v.Config.EndpointURL),
	}
	if m.ContextWindow != nil {
		out.ContextWindow = *m.ContextWindow
	}
	return out, nil
}
