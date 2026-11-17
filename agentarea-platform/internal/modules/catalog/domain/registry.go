package domain

import (
	"encoding/json"
	"time"
)

// Registry is a registries row.
type Registry struct {
	ID                     string
	Name                   string
	Description            *string
	RegistryType           string
	SourceType             string
	SourceURL              string
	IsActive               bool
	LastSyncedAt           *time.Time
	LastSyncError          *string
	SourceEtag             *string
	SourceRef              *string
	SourcePath             *string
	Scope                  string
	WorkspaceID            *string
	Mode                   string
	Trust                  string
	CredentialsSecretRef   *string
	ItemCount              int
	RecommendationPriority int
	CreatedAt, UpdatedAt   time.Time
}

// Item is a registry_items row.
type Item struct {
	ID                  string
	RegistryID          string
	ExternalID          string
	Name                string
	Description         *string
	Version             *string
	Spec                json.RawMessage
	Tags                json.RawMessage
	InstalledEntityID   *string
	UpdateAvailable     bool
	InstalledVersion    *string
	Category            *string
	SortKey             string
	Featured            bool
	RecommendationRank  int
	Protocol            *string
	Hosting             *string
	Pricing             *string
	RegistryType        string
	RegistryPriority    int
	RegistryActive      bool
	RegistryWorkspaceID *string
	RegistryTrust       string
	InSource            bool
	CreatedAt           time.Time
	UpdatedAt           time.Time
}

// Visible is whether a workspace may see an item: the platform's or its own.
func (i Item) Visible(workspaceID string) bool {
	return i.RegistryWorkspaceID == nil || *i.RegistryWorkspaceID == workspaceID
}

// Visible is whether a workspace may see a registry.
func (r Registry) Visible(workspaceID string) bool {
	return r.WorkspaceID == nil || *r.WorkspaceID == workspaceID
}

// NewRegistry is a registry to insert.
type NewRegistry struct {
	Name, RegistryType, SourceType, SourceURL string
	Description                               *string
	RecommendationPriority                    int
	Scope, Mode, Trust                        string
	WorkspaceID, CredentialsSecretRef         *string
	SourceRef, SourcePath                     *string
}

// Field is a PATCH field: Set when the body named it.
type Field[T any] struct {
	Set   bool
	Value T
}

// RegistryPatch is what RegistryUpdate (or WorkspaceRegistryUpdate) set.
type RegistryPatch struct {
	Name                   Field[*string]
	Description            Field[*string]
	SourceURL              Field[*string]
	SourceType             Field[*string]
	IsActive               Field[*bool]
	RecommendationPriority Field[*int]
	Mode                   Field[*string]
	Trust                  Field[*string]
	CredentialsSecretRef   Field[*string]
	SourceRef              Field[*string]
	SourcePath             Field[*string]
}

// Empty is model_dump(exclude_unset=True) == {}.
func (p RegistryPatch) Empty() bool {
	return !p.Name.Set && !p.Description.Set && !p.SourceURL.Set && !p.SourceType.Set && !p.IsActive.Set &&
		!p.RecommendationPriority.Set && !p.Mode.Set && !p.Trust.Set && !p.CredentialsSecretRef.Set &&
		!p.SourceRef.Set && !p.SourcePath.Set
}

// NewItem is a managed catalog item to insert.
type NewItem struct {
	ExternalID, Name   string
	Description        *string
	Version            *string
	Spec, Tags         json.RawMessage
	RecommendationRank *int
}

// ItemPatch is CatalogItemUpdate.
type ItemPatch struct {
	ExternalID  Field[*string]
	Name        Field[*string]
	Description Field[*string]
	Version     Field[*string]
	Spec        Field[json.RawMessage]
	Tags        Field[json.RawMessage]
}

// Empty is model_dump(exclude_unset=True) == {}.
func (p ItemPatch) Empty() bool {
	return !p.ExternalID.Set && !p.Name.Set && !p.Description.Set && !p.Version.Set && !p.Spec.Set && !p.Tags.Set
}

// BrowseFilter is _browse_filter's arguments; "" is no filter.
type BrowseFilter struct {
	RegistryType, Query, Category, Protocol, Hosting, Pricing string
}

// Facet is one facet value and its count.
type Facet struct {
	Value string
	Count int
}

// Browse is browse_catalog's result.
type Browse struct {
	Items                                    []Item
	Total                                    int
	Categories, Protocols, Hostings, Pricing []Facet
}
