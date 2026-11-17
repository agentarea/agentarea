package api

import (
	"context"

	"github.com/google/uuid"
)

// ProviderDeclaration is a provider configuration a deployment declares: its key goes to the
// workspace's secret store under the configuration's own name, never onto the row.
type ProviderDeclaration struct {
	ConfigID, ProviderSpecID uuid.UUID
	WorkspaceID              string
	Name                     string
	EndpointURL              *string
	IsPublic                 bool
	// PlatformManaged marks the row managed_by platform: visible to every workspace.
	PlatformManaged bool
	APIKey          string
	Instances       []DeclaredInstance
}

// DeclaredInstance is a model instance of the declared configuration. Tags nil leaves an existing
// row's tags; a list, empty included, replaces them.
type DeclaredInstance struct {
	ID, ModelSpecID uuid.UUID
	Name            string
	Tags            []string
}

// DeclaredProviders is what the operator writes of models' tables.
type DeclaredProviders interface {
	DeclareProvider(ctx context.Context, d ProviderDeclaration) error
	// PlatformDefaults is the name of every active platform model tagged default, by name.
	PlatformDefaults(ctx context.Context) ([]string, error)
}
