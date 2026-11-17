package service

import (
	"context"
	"net/http"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// CatalogItems is what agents reads and writes of the catalog (catalog module):
// its agent and skill items, their installs, and the GitHub folders skills point at.
type CatalogItems = catalogapi.Installs

// SkillCatalog is the update half of catalog skills: moving an install to its
// item's current version, and pinning an install to a version it had.
type SkillCatalog interface {
	// Update is update_from_catalog; false when the workspace has no such skill.
	Update(ctx context.Context, c authn.Caller, skillID uuid.UUID, discardChanges bool) (SkillView, bool, error)
	// UpdateAll is update_all_from_catalog.
	UpdateAll(ctx context.Context, c authn.Caller) ([]SkillUpdateResult, error)
	// Pin is rollback's re-pin of an install to the item version a catalog
	// package had, after the install policy allowed it, in the rollback's transaction s.
	Pin(ctx context.Context, s db.Session, c authn.Caller, skillID uuid.UUID, registryItemID string, catalogVersion *string) error
	// RepinAll and RefreshStubs are the CLI jobs repin-catalog-installs and refresh-stub-installs.
	RepinAll(ctx context.Context, dryRun bool) ([]SkillJobResult, error)
	RefreshStubs(ctx context.Context, dryRun bool) ([]SkillJobResult, error)
}

// SkillSource is where a skill came from, as the install policy decides on it.
type SkillSource struct {
	RegistryID string
	Trust      string
}

// SkillInstallPolicy is the governance install guard (CatalogInstallGuard).
type SkillInstallPolicy interface {
	// RequireAllowed refuses an install from registryID at trust (a 403 the port returns).
	RequireAllowed(ctx context.Context, c authn.Caller, registryID, trust string) error
	// RunRefusal is why the workspace's rules keep a run from a skill of that source.
	RunRefusal(ctx context.Context, ws scope.Workspace, registryID, trust string) (reason string, refused bool, err error)
}

// SkillPorts are the ports the skill routes need beyond the agents service's.
type SkillPorts struct {
	// Blob is the artifacts bucket skill packages live in; nil answers 501.
	Blob blob.Store
	// GitHub is the vendor transport the tokenless codeload download goes through; nil answers 501.
	GitHub http.RoundTripper
	// Items are the catalog's skill items; nil answers 501 for installing one and refuses runs of installed ones.
	Items CatalogItems
	// Catalog moves installs between catalog versions; nil answers 501 for update and catalog rollback.
	Catalog SkillCatalog
	// InstallPolicy is nil until governance serves it: GitHub import answers 501.
	InstallPolicy SkillInstallPolicy
}

// SkillUpdateResult is SkillUpdateResult: what updating one installed skill did.
type SkillUpdateResult struct {
	SkillID string
	Name    string
	Status  string
	Error   *string
	Skill   *SkillView
}

// SkillJobResult is one skill a catalog job handled, with its workspace;
// Error is the reason or detail, SourceURL what a refresh read.
type SkillJobResult struct {
	WorkspaceID string
	SkillID     string
	Name        string
	Status      string
	Error       *string
	SourceURL   *string
}
