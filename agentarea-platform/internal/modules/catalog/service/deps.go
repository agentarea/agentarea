package service

import (
	"context"
	"log/slog"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

// SpecStore is store.Specs.
type SpecStore interface {
	ProviderSpec(ctx context.Context, s db.Session, id uuid.UUID) (api.ProviderSpec, bool, error)
	ProviderSpecByKey(ctx context.Context, s db.Session, key string) (api.ProviderSpec, bool, error)
	ProviderSpecs(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]api.ProviderSpec, error)
	ModelSpecs(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]api.ModelSpec, error)
	UsableModelSpec(ctx context.Context, s db.Session, id uuid.UUID) (api.ModelSpec, bool, error)
	ModelSpecByProviderAndName(ctx context.Context, s db.Session, providerSpecID uuid.UUID, name string) (api.ModelSpec, bool, error)
	ModelSpecIDs(ctx context.Context, s db.Session, providerSpecID uuid.UUID, names []string) (map[string]uuid.UUID, error)
	InsertModelSpec(ctx context.Context, s db.Session, n store.NewModelSpec, now time.Time) error
	InsertModelSpecIfAbsent(ctx context.Context, s db.Session, n store.NewModelSpec, now time.Time) error
	UpdateDiscoveredSpec(ctx context.Context, s db.Session, id uuid.UUID, d api.DiscoveredSpec, now time.Time) error
	CatalogModels(ctx context.Context, s db.Session) ([]store.CatalogModel, error)
	CatalogModel(ctx context.Context, s db.Session, id uuid.UUID) (store.CatalogModel, bool, error)
	OfferedProviderSpecs(ctx context.Context, s db.Session, isBuiltin *bool, configProviders, instanceSpecs []uuid.UUID) ([]api.ProviderSpec, error)
	ModelSpecsOfProviders(ctx context.Context, s db.Session, ids []uuid.UUID) ([]api.ModelSpec, error)
	OwnModelSpecs(ctx context.Context, s db.Session, f store.SpecFilter) ([]api.ModelSpec, error)
	OwnModelSpec(ctx context.Context, s db.Session, id uuid.UUID) (api.ModelSpec, bool, error)
	OwnModelKeys(ctx context.Context, s db.Session) (map[store.ModelKey]bool, error)
	CreateModelSpec(ctx context.Context, s db.Session, id, providerSpecID uuid.UUID, createdBy, modelName string, f store.SpecFields, now time.Time) error
	UpdateModelSpec(ctx context.Context, s db.Session, id uuid.UUID, f store.SpecFields, touch bool, now time.Time) (bool, error)
	DeleteModelSpec(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
}

// RegistryStore is store.Registries.
type RegistryStore interface {
	Get(ctx context.Context, s db.Session, id string) (domain.Registry, bool, error)
	Many(ctx context.Context, s db.Session, ids []string) (map[string]domain.Registry, error)
	ListVisible(ctx context.Context, s db.Session, activeOnly bool, registryType, scope string) ([]domain.Registry, error)
	Create(ctx context.Context, s db.Session, n domain.NewRegistry, now time.Time) (domain.Registry, error)
	Update(ctx context.Context, s db.Session, id string, p domain.RegistryPatch, clearEtag bool, now time.Time) (domain.Registry, bool, error)
	SetItemCount(ctx context.Context, s db.Session, id string, now time.Time) error
	Delete(ctx context.Context, s db.Session, id string) (bool, error)
	GetItem(ctx context.Context, s db.Session, id string) (domain.Item, bool, error)
	ItemByExternalID(ctx context.Context, s db.Session, registryID, externalID string) (domain.Item, bool, error)
	ListItems(ctx context.Context, s db.Session, registryID string, limit, offset int32) ([]domain.Item, error)
	NextRank(ctx context.Context, s db.Session, registryID string) (int, error)
	CreateItem(ctx context.Context, s db.Session, registryID string, n domain.NewItem, rank int, f domain.Facets, now time.Time) (domain.Item, error)
	UpdateItem(ctx context.Context, s db.Session, id string, p domain.ItemPatch, f domain.Facets, now time.Time) (domain.Item, bool, error)
	DeleteItem(ctx context.Context, s db.Session, id string) (bool, error)
	Search(ctx context.Context, s db.Session, pattern, tag string, updateAvailable *bool, limit, offset int32) ([]domain.Item, error)
	Browse(ctx context.Context, s db.Session, f domain.BrowseFilter, byName bool, limit, offset int32) (domain.Browse, error)
	AllItems(ctx context.Context, s db.Session, registryID string) ([]domain.Item, error)
	MarkItemApplied(ctx context.Context, s db.Session, id, installedVersion string, now time.Time) error
	UpdateMirroredServer(ctx context.Context, s db.Session, id string, m store.MirroredServer, now time.Time) (bool, error)
}

// SpecUse is models' answer to which provider and model specs the
// workspace's configurations and instances use (offered_to's use arms).
type SpecUse interface {
	ProviderSpecIDsWithVisibleConfigs(ctx context.Context, ws scope.Workspace) ([]uuid.UUID, error)
	ModelSpecIDsWithVisibleInstances(ctx context.Context, ws scope.Workspace) ([]uuid.UUID, error)
}

// SecretUse is the secret catalog a workspace registry's credentials go
// through (SecretCatalogService.get_for_use, add_reference, clear_references).
type SecretUse interface {
	GetForUse(ctx context.Context, id string) (ksecrets.Secret, error)
	AddReference(ctx context.Context, secretID, consumerType, consumerID, field string) error
	ClearReferences(ctx context.Context, consumerType, consumerID string) error
}

// Authority is the platform-write decision (AuthorizationService.can_write_workspace).
type Authority interface {
	CanWrite(ctx context.Context, c authn.Caller, workspaceID string) (bool, error)
}

// Deps are the service's ports.
type Deps struct {
	DB         db.Database
	Specs      SpecStore
	Registries RegistryStore
	Authority  Authority
	// PublicHTTPS is _require_public_https's outbound check past the scheme:
	// whether every address the URL's host resolves to may be reached.
	PublicHTTPS func(ctx context.Context, url string) bool
	// SpecUse is models'; nil leaves the provider-spec lists unmounted.
	SpecUse SpecUse
	// Secrets binds the secret catalog to a caller; nil leaves the
	// workspace-registry writes unmounted.
	Secrets func(ws scope.Workspace, actor ksecrets.Actor) SecretUse
	// APIURL is AGENTAREA_API_URL, the base built-in icons are served from.
	APIURL string
	Log    *slog.Logger
	// Now is the wall clock rows are stamped with; nil is time.Now.
	Now func() time.Time
	// Sync is store.Sync.
	Sync SyncStore
	// Uses are the rows other modules hold that name catalog items; nil
	// leaves sync, retire and reconcile unavailable.
	Uses api.ItemUses
	// Fetch reads sources through the outbound clients; a nil Net leaves
	// sync unavailable.
	Fetch Fetcher
	// Mirror stores a mirror-mode skills registry's content; nil fails
	// such a registry's sync.
	Mirror api.ContentMirror
	// Credentials resolves a registry's credentials reference; nil fails
	// the sync of a registry that has one.
	Credentials api.RegistryCredentials
	// PlatformSecrets resolves a manifest's credentials reference; nil
	// fails a reconcile entry that names one.
	PlatformSecrets api.PlatformSecrets
}

// CatalogConnections is readable_catalog_connections: per catalog item, the
// caller's connections made from it that the graph lets them read, each a
// rendered CatalogConnection. Owned by connections.
type CatalogConnections interface {
	Of(ctx context.Context, c authn.Caller, itemIDs []string) (map[string][]any, error)
}

// CatalogPricing is price_catalog_items: each item's rendered
// CatalogItemPricingResponse, or nil for one with no pricing dimension.
// Billing prices calls on the platform's key.
type CatalogPricing interface {
	Price(ctx context.Context, items []domain.Item) ([]any, error)
}
