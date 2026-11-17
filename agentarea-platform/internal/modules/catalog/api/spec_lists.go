package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// SpecLists lists the provider and model specs a workspace sees, as the
// providers and models platform toolsets read them.
type SpecLists interface {
	// OfferedProviderSpecs is ProviderSpecRepository.list_specs: the provider
	// specs offered to ws.
	OfferedProviderSpecs(ctx context.Context, ws scope.Workspace) ([]ProviderSpec, error)
	// ListModelSpecs is ModelSpecRepository.list_specs: ws's own specs, then
	// the catalog models they do not shadow; at most 100.
	ListModelSpecs(ctx context.Context, ws scope.Workspace) ([]ModelSpec, error)
}
