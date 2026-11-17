package api

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// MCPSpec is an mcp_servers row, or the read-only projection of a catalog
// item of an active mcp_servers registry. JSON values are decoded with
// numbers kept as written (json.Number).
type MCPSpec struct {
	ID             string
	WorkspaceID    string
	CreatedBy      string
	Name           string
	Slug           string
	Description    string
	Version        string
	Status         string
	IsPublic       bool
	DockerImageURL *string
	RemoteURL      *string
	Icon           *string
	RegistryURL    *string
	RegistryItemID *string
	// Cmd is the command list; nil when NULL.
	Cmd []any
	// EnvSchema is normalized (normalize_env_schema), hydrated from the catalog
	// item when a mirror stores none.
	EnvSchema []any
	JSONSpec  map[string]any
	Tags      []any
	// Catalog marks platform data: a catalog mirror or a projection. Routes
	// skip the per-object read check for it; it is never written.
	Catalog bool
	// Projection marks a spec that exists only in registry_items.
	Projection bool
	CreatedAt  time.Time
	UpdatedAt  time.Time
}

// MCPSpecNew is a spec row a connection creates in its workspace.
type MCPSpecNew struct {
	Name           string
	IsPublic       bool
	Description    string
	Version        string
	DockerImageURL *string
	RemoteURL      *string
	Cmd            []any
	EnvSchema      []any
	JSONSpec       map[string]any
	Tags           []any
	Icon           *string
	RegistryItemID *string
	RegistryURL    *string
}

// MCPSpecGet says which specs beyond the workspace's own a read may reach.
type MCPSpecGet struct {
	// PlatformBacked: the caller reads the spec behind a platform-managed
	// connection, so a platform-workspace row is readable by id.
	PlatformBacked bool
}

// MCPSpecs is what connections reads and writes of MCP server specs
// (MCPServerRepository as the instance service uses it).
type MCPSpecs interface {
	// Get is get_server_by_id: the workspace's row, else an active catalog
	// mirror in the platform workspace, else (PlatformBacked) the platform's
	// row, else the projection of the registry item with that id.
	Get(ctx context.Context, ws scope.Workspace, id string, o MCPSpecGet) (MCPSpec, bool, error)
	// Create inserts a workspace spec in tx, slug resolve_unique_slug(name)
	// (base, base-2..base-999; exhaustion is ErrSlugsExhausted).
	Create(ctx context.Context, tx db.Session, createdBy string, n MCPSpecNew) (MCPSpec, error)
	// MaterializeCopy is _materialize_workspace_spec_copy: a workspace copy of
	// a catalog or platform spec, in tx.
	MaterializeCopy(ctx context.Context, tx db.Session, createdBy string, source MCPSpec) (MCPSpec, error)
	// SetAuthMethods writes json_spec.auth_methods on a workspace row; false
	// when the workspace has no such row (a catalog mirror).
	SetAuthMethods(ctx context.Context, ws scope.Workspace, id string, methods []any) (bool, error)
	// CatalogJSONSpec is catalog_json_spec: the server JSON the catalog holds
	// for a spec (its own for platform data, the registry item's for a
	// workspace copy, none for a member's own spec).
	CatalogJSONSpec(ctx context.Context, ws scope.Workspace, id string) (map[string]any, bool, error)
	// List is list_servers: the workspace's readable rows first, then the
	// catalog items none of them instantiates, paged together.
	List(ctx context.Context, ws scope.Workspace, q MCPSpecQuery) ([]MCPSpec, int, error)
	// BySlug is get_by_slug: the workspace's row with that slug.
	BySlug(ctx context.Context, ws scope.Workspace, slug string) (MCPSpec, bool, error)
	// Update rewrites the workspace's row sp.ID from sp in tx; false when the
	// workspace has no such row.
	Update(ctx context.Context, tx db.Session, sp MCPSpec, updatedBy string) (MCPSpec, bool, error)
	// Delete removes the workspace's row id in tx.
	Delete(ctx context.Context, tx db.Session, id string) (bool, error)
}

// MCPSpecQuery is list_servers' filters; nil is no filter. Readable narrows
// the workspace's rows only, SpecIDs both halves.
type MCPSpecQuery struct {
	Readable      []string
	SpecIDs       []string
	Status        *string
	IsPublic      *bool
	Tag           *string
	Search        *string
	Limit, Offset int
}

// ErrSlugsExhausted is resolve_unique_slug running out of suffixes; its text is Python's.
type ErrSlugsExhausted struct{ Base string }

func (e *ErrSlugsExhausted) Error() string {
	return "Exhausted collision suffixes (-2..-999) for slug base '" + e.Base + "'"
}
