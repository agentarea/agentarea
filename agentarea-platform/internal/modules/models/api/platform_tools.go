package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// ProviderSpecSummary is one entry of providers_list_specs.
type ProviderSpecSummary struct {
	ID, Name, Key string
}

// ProviderConfigSummary is one entry of providers_list_configs.
type ProviderConfigSummary struct {
	ID, Name, ProviderSpecID string
	IsActive                 bool
}

// ProviderConfigRef is providers_create_config's and providers_update_config's output.
type ProviderConfigRef struct {
	ID, Name string
}

// NewProviderConfig is providers_create_config's arguments; an empty
// APIKey, EndpointURL or Description is none.
type NewProviderConfig struct {
	ProviderSpecID, Name, APIKey, EndpointURL, Description string
	IsPublic                                               bool
}

// ProviderConfigPatch is providers_update_config's arguments: nil leaves the field.
type ProviderConfigPatch struct {
	Name, APIKey, EndpointURL, Description *string
	IsActive, IsPublic                     *bool
}

// PlatformProviders is what the platform providers toolset calls
// (tools/providers_toolset.py). The config writes refuse a caller who does
// not administer the workspace (requires_workspace_admin); a refusal or a
// refused document is an error whose text the toolset reports.
type PlatformProviders interface {
	ListSpecs(ctx context.Context, c authn.Caller) ([]ProviderSpecSummary, error)
	ListConfigs(ctx context.Context, c authn.Caller) ([]ProviderConfigSummary, error)
	CreateConfig(ctx context.Context, c authn.Caller, n NewProviderConfig) (ProviderConfigRef, error)
	// UpdateConfig returns ErrNotFound when the workspace has no such configuration.
	UpdateConfig(ctx context.Context, c authn.Caller, configID string, p ProviderConfigPatch) (ProviderConfigRef, error)
	// DeleteConfig is false when no such configuration existed.
	DeleteConfig(ctx context.Context, c authn.Caller, configID string) (bool, error)
}

// ModelSpecSummary is one entry of models_list_specs.
type ModelSpecSummary struct {
	ID, Name, ProviderSpecID string
}

// ModelInstanceSummary is a model instance as the models toolset returns it.
type ModelInstanceSummary struct {
	ID, Name, ModelSpecID, ProviderConfigID string
	IsActive                                bool
}

// NewModelInstance is models_create_instance's arguments; an empty
// Description is none.
type NewModelInstance struct {
	ProviderConfigID, ModelSpecID, Name, Description string
}

// PlatformModels is what the platform models toolset calls (tools/models_toolset.py).
type PlatformModels interface {
	ListSpecs(ctx context.Context, c authn.Caller) ([]ModelSpecSummary, error)
	ListInstances(ctx context.Context, c authn.Caller) ([]ModelInstanceSummary, error)
	CreateInstance(ctx context.Context, c authn.Caller, n NewModelInstance) (ModelInstanceSummary, error)
	// GetInstance returns ErrNotFound for an id the workspace sees no instance for.
	GetInstance(ctx context.Context, c authn.Caller, id string) (ModelInstanceSummary, error)
}
