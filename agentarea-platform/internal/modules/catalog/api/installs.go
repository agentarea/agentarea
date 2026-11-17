package api

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// CatalogItem is a catalog agent or skill item as an install reads it
// (CatalogAgentItem, CatalogSkillItem).
type CatalogItem struct {
	ID                  string
	Name                string
	Description         *string
	Version             *string
	Spec                json.RawMessage
	RegistryID          string
	RegistryTrust       string
	RegistryWorkspaceID *string
	// InstalledVersion is the version the workspace installed, read by AgentItem and SkillItem.
	InstalledVersion *string
}

// ItemVersions are an item's current version and the one the workspace installed.
type ItemVersions struct{ Current, Installed *string }

// ItemSource is an item's registry and trust, as the install policy decides on it.
type ItemSource struct{ RegistryID, Trust string }

// GitHubFolder is one folder of a repository at a commit (GitHubFolder).
type GitHubFolder struct {
	Commit  string
	TreeSHA string
	// Files are the folder's files by path relative to it: no links, no hidden files.
	Files map[string][]byte
}

// Installs is what agents reads and writes of the catalog to install its
// agents and skills into a workspace. Every read sees the platform's
// registries and the workspace's own, active ones only.
type Installs interface {
	// AgentPresets are the agents tagged preset (list_presets).
	AgentPresets(ctx context.Context, ws scope.Workspace) ([]CatalogItem, error)
	// AgentItems are every agent item, by name (list_items).
	AgentItems(ctx context.Context, ws scope.Workspace) ([]CatalogItem, error)
	// AgentItem and SkillItem are get_item; false when no such item.
	AgentItem(ctx context.Context, ws scope.Workspace, id string) (CatalogItem, bool, error)
	SkillItem(ctx context.Context, ws scope.Workspace, id string) (CatalogItem, bool, error)
	// SkillByKey is find_by_key: the newest skill named key or key--<hash>.
	SkillByKey(ctx context.Context, ws scope.Workspace, key string) (CatalogItem, bool, error)
	// MarkInstalled records the workspace's copy of an item, in the install's transaction s.
	MarkInstalled(ctx context.Context, s db.Session, itemID, entityID string, version *string) error
	// SkillVersions is versions_for: by item id, of the active items among itemIDs.
	SkillVersions(ctx context.Context, ws scope.Workspace, itemIDs []string) (map[string]ItemVersions, error)
	// SkillProvenance is provenance_for: the source of each item id that still has an
	// item, a retired registry's included.
	SkillProvenance(ctx context.Context, ws scope.Workspace, itemIDs []string) (map[string]ItemSource, error)
	// Folder is download_folder: folder of repo at ref (the default branch
	// when nil), which must be tree treeSHA when set. Without a token it reads
	// the commit archive, with one the REST API and raw files as that token.
	Folder(ctx context.Context, token, repo, folder string, ref, treeSHA *string) (GitHubFolder, error)
}

// FolderError is a GitHub read of a skill folder that failed.
type FolderError struct {
	Msg         string
	NotFound    bool
	RateLimited bool
}

func (e *FolderError) Error() string { return e.Msg }
