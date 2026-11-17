package api

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// ItemMove is one catalog item a registry dropped and the same item a
// replacement registry still publishes, with each one's platform MCP copy.
type ItemMove struct {
	Old, New         uuid.UUID
	OldCopy, NewCopy *uuid.UUID
}

// ItemUses is what a catalog sync needs of the rows other modules hold that
// name catalog items or specs (repository.py move_references,
// delete_unreferenced_out_of_source, delete_unused_dropped_*). Every method
// runs in the sync's transaction tx and sees every workspace.
type ItemUses interface {
	// MoveItemUses points the forks (skills.registry_item_id, except where the
	// workspace already forked the new item), agents.registry_item_id and
	// openapi_connections.registry_item_id of each Old at New, and the
	// mcp_server_instances running from OldCopy at NewCopy (both set);
	// how many rows moved.
	MoveItemUses(ctx context.Context, tx db.Session, moves []ItemMove) (int, error)
	// ReferencedItems are those of ids a skill, agent or OpenAPI connection names.
	ReferencedItems(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error)
	// UsedProviderSpecs are those of ids a provider config is on.
	UsedProviderSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error)
	// UsedModelSpecs are those of ids a model instance runs on.
	UsedModelSpecs(ctx context.Context, tx db.Session, ids []uuid.UUID) (map[uuid.UUID]bool, error)
	// DropPlatformSkills deletes the platform workspace's legacy skill rows
	// ids (_drop_platform_skill), revoking their ownership.
	DropPlatformSkills(ctx context.Context, tx db.Session, ids []uuid.UUID) error
}

// ItemMirror stores one mirror-mode item's content (its spec) as an
// immutable package and answers where (the spec's `package`, ADR-0044).
type ItemMirror func(ctx context.Context, spec map[string]any) (map[string]any, error)

// ContentMirror opens the mirror of one sync of a registry: the platform's
// catalog area, or the owning workspace's; token reads private sources.
type ContentMirror interface {
	Open(ctx context.Context, registryID string, workspaceID *string, token string) (ItemMirror, error)
}

// RegistryCredentials resolves a registry's credentials reference to the
// value at sync time: secretID of workspaceID ("platform" for a platform
// registry); never stored.
type RegistryCredentials func(ctx context.Context, workspaceID, secretID string) (string, error)

// ReconcileOptions is `agentarea-api reconcile`.
type ReconcileOptions struct {
	// Manifest entries (REGISTRIES_CONFIG, --config-file, --source).
	Manifest []map[string]any
	// Force re-reads every source whatever its stored ETag.
	Force bool
	// WorkspaceRegistries also syncs every active workspace registry.
	WorkspaceRegistries bool
}

// ReconcileResult is what a reconcile run did, by registry name.
type ReconcileResult struct {
	Succeeded, Skipped []string
	Failed             map[string]string
	WorkspaceSynced    []string
	WorkspaceFailed    map[string]string
}

// Reconciler is the operator role's entry point into catalog.
type Reconciler interface {
	Reconcile(ctx context.Context, o ReconcileOptions) (ReconcileResult, error)
}

// PlatformSecrets is the platform workspace's secret catalog as reconcile
// uses it (registry_credentials.py).
type PlatformSecrets interface {
	// SecretID is the id of the platform secret ref names, by id or by name.
	SecretID(ctx context.Context, ref string) (string, error)
	// RecordReference lists registryID among secretID's consumers, or
	// nowhere when secretID is nil.
	RecordReference(ctx context.Context, registryID string, secretID *string) error
}
