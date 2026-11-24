package api

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ProviderSpec is a provider_specs row (global; no workspace filter, no
// offered_to: read by id or key as ProviderSpecRepository.get_by_id and
// get_by_provider_key do).
type ProviderSpec struct {
	ID             uuid.UUID
	ProviderKey    string
	ProviderType   string
	Name           string
	Description    *string
	Icon           *string
	IsBuiltin      bool
	IsFirstParty   bool
	RequiresAPIKey bool
	// HTTP contract columns, as stored (nil = NULL).
	BaseURL          *string
	Transport        string
	Auth             string
	ModelsPath       *string
	ListShape        string
	ModelsQuery      *string
	ReasoningParam   string
	ReasoningEfforts []string
	CacheBreakpoints bool
	// MaxImageBytes and MaxImageEdge are what the provider takes in one image:
	// the file's bytes and the longer edge in pixels; nil is unstated.
	MaxImageBytes, MaxImageEdge *int
	// PDFInput is whether the provider reads a PDF sent as a file.
	PDFInput  bool
	CreatedAt time.Time
	UpdatedAt time.Time
}

// ModelSpec is a model_specs row.
type ModelSpec struct {
	ID, ProviderSpecID                                         uuid.UUID
	WorkspaceID                                                string
	ModelName, DisplayName                                     string
	Description                                                *string
	Kind                                                       string
	ContextWindow                                              *int
	MaxOutputTokens                                            *int
	InputCostPerToken                                          *money.Decimal
	OutputCostPerToken                                         *money.Decimal
	CachedInputCostPerToken                                    *money.Decimal
	CacheCreationInputCostPerToken                             *money.Decimal
	OutputCostPerImage                                         *money.Decimal
	OutputCostPerVideoPerSecond                                *money.Decimal
	SupportsFunctionCalling, SupportsVision, SupportsReasoning *bool
	ReasoningEfforts                                           []string
	// ResponsesLite: the model takes its tools the Responses Lite way (codex-rs use_responses_lite).
	ResponsesLite          bool
	DefaultContextStrategy *string
	IsActive               bool
	CreatedAt, UpdatedAt   time.Time
}

// DiscoveredSpec is one row of a discovery upsert; nil fields are left alone
// on an existing row.
type DiscoveredSpec struct {
	ModelName, DisplayName                                                                         string
	Description                                                                                    *string
	Kind                                                                                           string
	ContextWindow, MaxOutputTokens                                                                 *int
	InputCostPerToken, OutputCostPerToken, CachedInputCostPerToken, CacheCreationInputCostPerToken *money.Decimal
	SupportsFunctionCalling, SupportsVision, SupportsReasoning                                     bool
}

// Upserted is UpsertedSpec.
type Upserted struct {
	ID    uuid.UUID
	IsNew bool
}

// ModelPricingNotConfiguredError is 422 model_pricing_not_configured.
type ModelPricingNotConfiguredError struct{ ModelName string }

func (e *ModelPricingNotConfiguredError) Error() string {
	return "Model " + e.ModelName + " has no price in the catalog, so runs on it could not be billed"
}

// Specs is what models reads and writes of provider and model specs.
type Specs interface {
	// ProviderSpec by id; ok false when no row.
	ProviderSpec(ctx context.Context, ws scope.Workspace, id uuid.UUID) (ProviderSpec, bool, error)
	ProviderSpecByKey(ctx context.Context, ws scope.Workspace, key string) (ProviderSpec, bool, error)
	// ProviderSpecs by id, missing ids absent from the map.
	ProviderSpecs(ctx context.Context, ws scope.Workspace, ids []uuid.UUID) (map[uuid.UUID]ProviderSpec, error)
	// ModelSpecs by id with no workspace filter (the ORM relationship load); missing ids absent.
	ModelSpecs(ctx context.Context, ws scope.Workspace, ids []uuid.UUID) (map[uuid.UUID]ModelSpec, error)
	// UsableModelSpec is get_usable: id in ws's own rows or workspace_id='platform'.
	UsableModelSpec(ctx context.Context, ws scope.Workspace, id uuid.UUID) (ModelSpec, bool, error)
	// CopyCatalogModelSpec is get_or_copy_catalog_spec, its own committed
	// transaction, created_by userID; ok false when itemID is not a catalog
	// model of an active registry or its provider is not installed;
	// *ModelPricingNotConfiguredError when the preferred copy is unpriced.
	CopyCatalogModelSpec(ctx context.Context, ws scope.Workspace, userID string, itemID uuid.UUID) (ModelSpec, bool, error)
	// UpsertModelSpecs is upsert_many_by_provider_and_model: one transaction,
	// the last duplicate name wins, existing rows take only non-nil fields;
	// keyed by model_name.
	UpsertModelSpecs(ctx context.Context, ws scope.Workspace, userID string, providerSpecID uuid.UUID, rows []DiscoveredSpec) (map[string]Upserted, error)
}
