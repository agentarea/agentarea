package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// SpecLists implements api.SpecLists over the provider and model spec lists.
type SpecLists struct{ S *Service }

var _ api.SpecLists = SpecLists{}

func (x SpecLists) OfferedProviderSpecs(ctx context.Context, ws scope.Workspace) ([]api.ProviderSpec, error) {
	vs, err := x.S.ProviderSpecs(ctx, ws, nil)
	if err != nil {
		return nil, err
	}
	out := make([]api.ProviderSpec, len(vs))
	for i, v := range vs {
		out[i] = v.ProviderSpec
	}
	return out, nil
}

func (x SpecLists) ListModelSpecs(ctx context.Context, ws scope.Workspace) ([]api.ModelSpec, error) {
	vs, err := x.S.ModelSpecs(ctx, ws, ModelFilter{})
	if err != nil {
		return nil, err
	}
	out := make([]api.ModelSpec, len(vs))
	for i, v := range vs {
		out[i] = v.ModelSpec
	}
	return out, nil
}
