package api

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

// DeclaredModelSpec is a model a deployment declares for a provider: the whole truth for the
// fields it sets, nil leaving an existing row's value.
type DeclaredModelSpec struct {
	ModelName, DisplayName                                                                         string
	Description                                                                                    *string
	ContextWindow                                                                                  int
	MaxOutputTokens                                                                                *int
	SupportsVision, SupportsReasoning                                                              *bool
	ReasoningEfforts                                                                               []string
	InputCostPerToken, OutputCostPerToken, CachedInputCostPerToken, CacheCreationInputCostPerToken *money.Decimal
}

// PlatformMCPServer is a platform-declared remote MCP server spec. JSONSpec is the whole json_spec.
type PlatformMCPServer struct {
	ID          uuid.UUID
	Name        string
	Description string
	RemoteURL   string
	JSONSpec    map[string]any
}

// PlatformDeclarations is what the operator writes of the catalog's tables, into the workspace the
// declaration names ("platform" for platform rows). Every write is idempotent.
type PlatformDeclarations interface {
	// ProviderSpecID is the provider spec with key; ok false when the catalog has none (yet).
	ProviderSpecID(ctx context.Context, key string) (uuid.UUID, bool, error)
	// DeclareModelSpecs upserts the workspace's specs under the provider, keyed by model name.
	DeclareModelSpecs(ctx context.Context, workspaceID string, providerSpecID uuid.UUID, specs []DeclaredModelSpec) (map[string]uuid.UUID, error)
	// CatalogItem is the active registry item with external_id, preferred registry first.
	CatalogItem(ctx context.Context, externalID string) (uuid.UUID, map[string]any, bool, error)
	// DeclareMCPServer upserts the platform server; changed is true when an existing server's
	// remote URL or remotes moved.
	DeclareMCPServer(ctx context.Context, s PlatformMCPServer) (changed bool, err error)
}
