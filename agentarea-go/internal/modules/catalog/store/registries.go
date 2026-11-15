package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
)

// Registries reads and writes registries and registry_items: global
// catalog tables; reads a caller makes filter by the session's workspace.
type Registries struct{}

func fromNullUUID(u uuid.NullUUID) *string {
	if !u.Valid {
		return nil
	}
	s := u.UUID.String()
	return &s
}

func nullUUID(p *string) (uuid.NullUUID, error) {
	if p == nil {
		return uuid.NullUUID{}, nil
	}
	u, err := uuid.Parse(*p)
	if err != nil {
		return uuid.NullUUID{}, err
	}
	return uuid.NullUUID{UUID: u, Valid: true}, nil
}

func timePtr(t pgtype.Timestamp) *time.Time {
	if !t.Valid {
		return nil
	}
	v := t.Time
	return &v
}

func registry(r Registry) domain.Registry {
	return domain.Registry{
		ID: r.ID.String(), Name: r.Name, Description: fromText(r.Description), RegistryType: r.RegistryType,
		SourceType: r.SourceType, SourceURL: r.SourceUrl, IsActive: r.IsActive, LastSyncedAt: timePtr(r.LastSyncedAt),
		LastSyncError: fromText(r.LastSyncError), SourceEtag: fromText(r.SourceEtag), SourceRef: fromText(r.SourceRef),
		SourcePath: fromText(r.SourcePath), Scope: r.Scope, WorkspaceID: fromText(r.WorkspaceID), Mode: r.Mode,
		Trust: r.Trust, CredentialsSecretRef: fromNullUUID(r.CredentialsSecretRef), ItemCount: int(r.ItemCount),
		RecommendationPriority: int(r.RecommendationPriority), CreatedAt: r.CreatedAt.Time, UpdatedAt: r.UpdatedAt.Time,
	}
}

func item(r RegistryItem) domain.Item {
	return domain.Item{
		ID: r.ID.String(), RegistryID: r.RegistryID.String(), ExternalID: r.ExternalID, Name: r.Name,
		Description: fromText(r.Description), Version: fromText(r.Version), Spec: r.Spec, Tags: r.Tags,
		InstalledEntityID: fromNullUUID(r.InstalledEntityID), UpdateAvailable: r.UpdateAvailable,
		InstalledVersion: fromText(r.InstalledVersion), Category: fromText(r.Category), SortKey: r.SortKey,
		Featured: r.Featured, RecommendationRank: int(r.RecommendationRank), Protocol: fromText(r.Protocol),
		Hosting: fromText(r.Hosting), Pricing: fromText(r.Pricing), RegistryType: r.RegistryType,
		RegistryPriority: int(r.RegistryPriority), RegistryActive: r.RegistryActive,
		RegistryWorkspaceID: fromText(r.RegistryWorkspaceID), RegistryTrust: r.RegistryTrust, InSource: r.InSource,
		CreatedAt: r.CreatedAt.Time, UpdatedAt: r.UpdatedAt.Time,
	}
}

func items(rs []RegistryItem) []domain.Item {
	out := make([]domain.Item, len(rs))
	for i, r := range rs {
		out[i] = item(r)
	}
	return out
}

func parseID(id string) (uuid.UUID, bool) {
	u, err := uuid.Parse(id)
	return u, err == nil
}

// Get is the registry, whatever its scope.
func (Registries) Get(ctx context.Context, s db.Session, id string) (domain.Registry, bool, error) {
	u, ok := parseID(id)
	if !ok {
		return domain.Registry{}, false, nil
	}
	r, ok, err := one(New(s.Q()).GetRegistry(ctx, u))
	if !ok || err != nil {
		return domain.Registry{}, false, err
	}
	return registry(r), true, nil
}

// Many are the registries among ids.
func (Registries) Many(ctx context.Context, s db.Session, ids []string) (map[string]domain.Registry, error) {
	us := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if u, ok := parseID(id); ok {
			us = append(us, u)
		}
	}
	out := map[string]domain.Registry{}
	if len(us) == 0 {
		return out, nil
	}
	rows, err := New(s.Q()).RegistriesByIDs(ctx, us)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.ID.String()] = registry(r)
	}
	return out, nil
}

// ListVisible is list_visible for the session's workspace.
func (Registries) ListVisible(ctx context.Context, s db.Session, activeOnly bool, registryType, scope string) ([]domain.Registry, error) {
	rows, err := New(s.Q()).ListVisibleRegistries(ctx, ListVisibleRegistriesParams{
		WorkspaceID: pgtype.Text{String: s.Workspace().ID(), Valid: true}, ActiveOnly: activeOnly,
		RegistryType: registryType, Scope: scope,
	})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Registry, len(rows))
	for i, r := range rows {
		out[i] = registry(r)
	}
	return out, nil
}

// Create inserts a registry.
func (Registries) Create(ctx context.Context, s db.Session, n domain.NewRegistry, now time.Time) (domain.Registry, error) {
	creds, err := nullUUID(n.CredentialsSecretRef)
	if err != nil {
		return domain.Registry{}, err
	}
	r, err := New(s.Q()).CreateRegistry(ctx, CreateRegistryParams{
		ID: uuid.New(), Now: naive(now), Name: n.Name, Description: text(n.Description), RegistryType: n.RegistryType,
		SourceType: n.SourceType, SourceUrl: n.SourceURL, RecommendationPriority: int32(n.RecommendationPriority),
		Scope: n.Scope, WorkspaceID: text(n.WorkspaceID), Mode: n.Mode, Trust: n.Trust, CredentialsSecretRef: creds,
		SourceRef: text(n.SourceRef), SourcePath: text(n.SourcePath),
	})
	if err != nil {
		return domain.Registry{}, err
	}
	return registry(r), nil
}

func deref[T any](p *T) T {
	var zero T
	if p == nil {
		return zero
	}
	return *p
}

// Update writes p (nulls included, as setattr does) and copies the
// registry's weight, active flag and trust onto its items; clearEtag drops
// source_etag. ok is false when there is no such registry.
func (Registries) Update(ctx context.Context, s db.Session, id string, p domain.RegistryPatch, clearEtag bool, now time.Time) (domain.Registry, bool, error) {
	u, ok := parseID(id)
	if !ok {
		return domain.Registry{}, false, nil
	}
	creds, err := nullUUID(p.CredentialsSecretRef.Value)
	if err != nil {
		return domain.Registry{}, false, err
	}
	q := New(s.Q())
	r, ok, err := one(q.UpdateRegistry(ctx, UpdateRegistryParams{
		SetName: p.Name.Set, Name: deref(p.Name.Value),
		SetDescription: p.Description.Set, Description: text(p.Description.Value),
		SetSourceUrl: p.SourceURL.Set, SourceUrl: deref(p.SourceURL.Value),
		SetSourceType: p.SourceType.Set, SourceType: deref(p.SourceType.Value),
		SetIsActive: p.IsActive.Set, IsActive: deref(p.IsActive.Value),
		SetPriority: p.RecommendationPriority.Set, RecommendationPriority: int32(deref(p.RecommendationPriority.Value)),
		SetMode: p.Mode.Set, Mode: deref(p.Mode.Value), SetTrust: p.Trust.Set, Trust: deref(p.Trust.Value),
		SetCredentials: p.CredentialsSecretRef.Set, CredentialsSecretRef: creds,
		SetSourceRef: p.SourceRef.Set, SourceRef: text(p.SourceRef.Value),
		SetSourcePath: p.SourcePath.Set, SourcePath: text(p.SourcePath.Value),
		ClearEtag: clearEtag, Now: naive(now), ID: u,
	}))
	if !ok || err != nil {
		return domain.Registry{}, false, err
	}
	if p.RecommendationPriority.Set || p.IsActive.Set || p.Trust.Set {
		if err := q.CopyRegistryToItems(ctx, CopyRegistryToItemsParams{
			SetPriority: p.RecommendationPriority.Set, RegistryPriority: r.RecommendationPriority,
			SetActive: p.IsActive.Set, RegistryActive: r.IsActive,
			SetTrust: p.Trust.Set, RegistryTrust: r.Trust, Now: naive(now), RegistryID: u,
		}); err != nil {
			return domain.Registry{}, false, err
		}
	}
	return registry(r), true, nil
}

// SetItemCount stores the registry's exact item count.
func (Registries) SetItemCount(ctx context.Context, s db.Session, id string, now time.Time) error {
	u, _ := parseID(id)
	q := New(s.Q())
	n, err := q.CountRegistryItems(ctx, u)
	if err != nil {
		return err
	}
	return q.SetRegistryItemCount(ctx, SetRegistryItemCountParams{ItemCount: int32(n), Now: naive(now), ID: u})
}

// Delete removes the registry; its items go with it (FK cascade).
func (Registries) Delete(ctx context.Context, s db.Session, id string) (bool, error) {
	u, ok := parseID(id)
	if !ok {
		return false, nil
	}
	n, err := New(s.Q()).DeleteRegistry(ctx, u)
	return n > 0, err
}

// GetItem is the item, whatever its registry.
func (Registries) GetItem(ctx context.Context, s db.Session, id string) (domain.Item, bool, error) {
	u, ok := parseID(id)
	if !ok {
		return domain.Item{}, false, nil
	}
	r, ok, err := one(New(s.Q()).GetItem(ctx, u))
	if !ok || err != nil {
		return domain.Item{}, false, err
	}
	return item(r), true, nil
}

// ItemByExternalID is the registry's item with this external id.
func (Registries) ItemByExternalID(ctx context.Context, s db.Session, registryID, externalID string) (domain.Item, bool, error) {
	u, _ := parseID(registryID)
	r, ok, err := one(New(s.Q()).GetItemByExternalID(ctx, GetItemByExternalIDParams{RegistryID: u, ExternalID: externalID}))
	if !ok || err != nil {
		return domain.Item{}, false, err
	}
	return item(r), true, nil
}

// ListItems is list_by_registry: case-insensitive name order.
func (Registries) ListItems(ctx context.Context, s db.Session, registryID string, limit, offset int32) ([]domain.Item, error) {
	u, _ := parseID(registryID)
	rows, err := New(s.Q()).ListRegistryItems(ctx, ListRegistryItemsParams{RegistryID: u, Lim: limit, Off: offset})
	if err != nil {
		return nil, err
	}
	return items(rows), nil
}

// NextRank is next_recommendation_rank.
func (Registries) NextRank(ctx context.Context, s db.Session, registryID string) (int, error) {
	u, _ := parseID(registryID)
	n, err := New(s.Q()).NextRecommendationRank(ctx, u)
	return int(n), err
}

func facetText(v string) pgtype.Text { return pgtype.Text{String: v, Valid: v != ""} }

// CreateItem inserts n with its facets, stamped with its registry's copies.
func (Registries) CreateItem(ctx context.Context, s db.Session, registryID string, n domain.NewItem, rank int, f domain.Facets, now time.Time) (domain.Item, error) {
	u, _ := parseID(registryID)
	r, err := New(s.Q()).CreateItem(ctx, CreateItemParams{
		ID: uuid.New(), Now: naive(now), ExternalID: n.ExternalID, Name: n.Name, Description: text(n.Description),
		Version: text(n.Version), Spec: n.Spec, Tags: n.Tags, Category: facetText(f.Category), SortKey: f.SortKey,
		Featured: f.Featured, RecommendationRank: int32(rank), Protocol: facetText(f.Protocol),
		Hosting: facetText(f.Hosting), Pricing: facetText(f.Pricing), RegistryID: u,
	})
	if err != nil {
		return domain.Item{}, err
	}
	return item(r), nil
}

// UpdateItem writes p and the recomputed facets.
func (Registries) UpdateItem(ctx context.Context, s db.Session, id string, p domain.ItemPatch, f domain.Facets, now time.Time) (domain.Item, bool, error) {
	u, ok := parseID(id)
	if !ok {
		return domain.Item{}, false, nil
	}
	spec, tags := p.Spec.Value, p.Tags.Value
	if spec == nil {
		spec = json.RawMessage("{}")
	}
	if tags == nil {
		tags = json.RawMessage("[]")
	}
	r, ok, err := one(New(s.Q()).UpdateItem(ctx, UpdateItemParams{
		SetExternalID: p.ExternalID.Set, ExternalID: deref(p.ExternalID.Value),
		SetName: p.Name.Set, Name: deref(p.Name.Value),
		SetDescription: p.Description.Set, Description: text(p.Description.Value),
		SetVersion: p.Version.Set, Version: text(p.Version.Value),
		SetSpec: p.Spec.Set, Spec: spec, SetTags: p.Tags.Set, Tags: tags,
		Category: facetText(f.Category), SortKey: f.SortKey, Featured: f.Featured, Protocol: facetText(f.Protocol),
		Hosting: facetText(f.Hosting), Pricing: facetText(f.Pricing), Now: naive(now), ID: u,
	}))
	if !ok || err != nil {
		return domain.Item{}, false, err
	}
	return item(r), true, nil
}

// DeleteItem removes the item.
func (Registries) DeleteItem(ctx context.Context, s db.Session, id string) (bool, error) {
	u, ok := parseID(id)
	if !ok {
		return false, nil
	}
	n, err := New(s.Q()).DeleteItem(ctx, u)
	return n > 0, err
}

// Search is RegistryItemRepository.search for the session's workspace.
func (Registries) Search(ctx context.Context, s db.Session, pattern, tag string, updateAvailable *bool, limit, offset int32) ([]domain.Item, error) {
	rows, err := New(s.Q()).SearchItems(ctx, SearchItemsParams{
		WorkspaceID: pgtype.Text{String: s.Workspace().ID(), Valid: true}, Tag: tag, FilterUpdate: updateAvailable != nil,
		UpdateAvailable: deref(updateAvailable), Pattern: pattern, Lim: limit, Off: offset,
	})
	if err != nil {
		return nil, err
	}
	return items(rows), nil
}

// Browse is browse plus the four facet counts, all from one filter.
func (Registries) Browse(ctx context.Context, s db.Session, f domain.BrowseFilter, byName bool, limit, offset int32) (domain.Browse, error) {
	q := New(s.Q())
	pattern := ""
	if f.Query != "" {
		pattern = "%" + f.Query + "%"
	}
	p := BrowseRecommendedParams{
		RegistryType: f.RegistryType, WorkspaceID: s.Workspace().ID(), Category: f.Category, Protocol: f.Protocol,
		Hosting: f.Hosting, Pricing: f.Pricing, Pattern: pattern, Lim: limit, Off: offset,
	}
	var out domain.Browse
	var rows []RegistryItem
	var err error
	if byName {
		rows, err = q.BrowseByName(ctx, BrowseByNameParams(p))
	} else {
		rows, err = q.BrowseRecommended(ctx, p)
	}
	if err != nil {
		return out, err
	}
	out.Items = items(rows)
	total, err := q.BrowseTotal(ctx, BrowseTotalParams{
		RegistryType: p.RegistryType, WorkspaceID: p.WorkspaceID, Category: p.Category, Protocol: p.Protocol,
		Hosting: p.Hosting, Pricing: p.Pricing, Pattern: p.Pattern,
	})
	if err != nil {
		return out, err
	}
	out.Total = int(total)
	cats, err := q.CategoryCounts(ctx, CategoryCountsParams{
		RegistryType: p.RegistryType, WorkspaceID: p.WorkspaceID, Protocol: p.Protocol,
		Hosting: p.Hosting, Pricing: p.Pricing, Pattern: p.Pattern,
	})
	if err != nil {
		return out, err
	}
	out.Categories = []domain.Facet{}
	for _, c := range cats {
		out.Categories = append(out.Categories, domain.Facet{Value: c.Value, Count: int(c.N)})
	}
	out.Protocols, out.Hostings, out.Pricing = []domain.Facet{}, []domain.Facet{}, []domain.Facet{}
	if f.RegistryType != domain.TypeMCPServers {
		return out, nil
	}
	counted := func(rows []ProtocolCountsRow, order []string) []domain.Facet {
		n := map[string]int{}
		for _, r := range rows {
			if r.Value.Valid {
				n[r.Value.String] = int(r.N)
			}
		}
		fs := []domain.Facet{}
		for _, v := range order {
			if n[v] > 0 {
				fs = append(fs, domain.Facet{Value: v, Count: n[v]})
			}
		}
		return fs
	}
	prot, err := q.ProtocolCounts(ctx, ProtocolCountsParams{
		RegistryType: p.RegistryType, WorkspaceID: p.WorkspaceID, Category: p.Category,
		Hosting: p.Hosting, Pricing: p.Pricing, Pattern: p.Pattern,
	})
	if err != nil {
		return out, err
	}
	out.Protocols = counted(prot, domain.Protocols())
	host, err := q.HostingCounts(ctx, HostingCountsParams{
		RegistryType: p.RegistryType, WorkspaceID: p.WorkspaceID, Category: p.Category,
		Protocol: p.Protocol, Pricing: p.Pricing, Pattern: p.Pattern,
	})
	if err != nil {
		return out, err
	}
	hrows := make([]ProtocolCountsRow, len(host))
	for i, r := range host {
		hrows[i] = ProtocolCountsRow(r)
	}
	out.Hostings = counted(hrows, domain.Hostings())
	pric, err := q.PricingCounts(ctx, PricingCountsParams{
		RegistryType: p.RegistryType, WorkspaceID: p.WorkspaceID, Category: p.Category,
		Protocol: p.Protocol, Hosting: p.Hosting, Pattern: p.Pattern,
	})
	if err != nil {
		return out, err
	}
	prows := make([]ProtocolCountsRow, len(pric))
	for i, r := range pric {
		prows[i] = ProtocolCountsRow(r)
	}
	out.Pricing = counted(prows, domain.Pricings())
	return out, nil
}
