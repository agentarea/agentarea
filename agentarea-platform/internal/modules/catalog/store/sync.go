package store

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

// Sync is what a catalog sync reads and writes of the catalog's own tables.
type Sync struct{}

func registries(rs []Registry) []domain.Registry {
	out := make([]domain.Registry, len(rs))
	for i, r := range rs {
		out[i] = registry(r)
	}
	return out
}

func nullID(p *string) uuid.NullUUID {
	u, err := nullUUID(p)
	if err != nil {
		return uuid.NullUUID{}
	}
	return u
}

// PlatformByName is get_platform_by_name.
func (Sync) PlatformByName(ctx context.Context, s db.Session, name string) (domain.Registry, bool, error) {
	r, ok, err := one(New(s.Q()).PlatformRegistryByName(ctx, name))
	if !ok || err != nil {
		return domain.Registry{}, false, err
	}
	return registry(r), true, nil
}

// ActiveOfType is list_active(registry_type).
func (Sync) ActiveOfType(ctx context.Context, s db.Session, registryType string) ([]domain.Registry, error) {
	rs, err := New(s.Q()).ActiveRegistriesOfType(ctx, registryType)
	return registries(rs), err
}

// ActiveWorkspaceRegistries is list_active_workspace_registries.
func (Sync) ActiveWorkspaceRegistries(ctx context.Context, s db.Session) ([]domain.Registry, error) {
	rs, err := New(s.Q()).ActiveWorkspaceRegistries(ctx)
	return registries(rs), err
}

// SyncedItem is one item as a sync writes it.
type SyncedItem struct {
	ID, RegistryID, ExternalID, Name string
	Description, Version             *string
	Spec, Tags                       []byte
	Rank                             int
	UpdateAvailable                  bool
	InstalledEntityID                *string
	InstalledVersion                 *string
	Facets                           domain.Facets
}

// InsertItem inserts a new item with the registry's copied fields.
func (Sync) InsertItem(ctx context.Context, s db.Session, it SyncedItem, now time.Time) (domain.Item, error) {
	reg, err := uuid.Parse(it.RegistryID)
	if err != nil {
		return domain.Item{}, err
	}
	f := it.Facets
	r, err := New(s.Q()).InsertSyncedItem(ctx, InsertSyncedItemParams{
		ID: uuid.New(), Now: naive(now), ExternalID: it.ExternalID, Name: it.Name, Description: text(it.Description),
		Version: text(it.Version), Spec: it.Spec, Tags: it.Tags, Category: facetText(f.Category), SortKey: f.SortKey,
		Featured: f.Featured, RecommendationRank: int32(it.Rank), Protocol: facetText(f.Protocol), Hosting: facetText(f.Hosting),
		Pricing: facetText(f.Pricing), RegistryID: reg,
	})
	if err != nil {
		return domain.Item{}, err
	}
	return item(r), nil
}

// SetItem overwrites an existing item with what the source published.
func (Sync) SetItem(ctx context.Context, s db.Session, it SyncedItem, now time.Time) error {
	id, err := uuid.Parse(it.ID)
	if err != nil {
		return err
	}
	f := it.Facets
	return New(s.Q()).SetSyncedItem(ctx, SetSyncedItemParams{
		Name: it.Name, Description: text(it.Description), Version: text(it.Version), Spec: it.Spec, Tags: it.Tags,
		RecommendationRank: int32(it.Rank), UpdateAvailable: it.UpdateAvailable,
		InstalledEntityID: nullID(it.InstalledEntityID), InstalledVersion: text(it.InstalledVersion),
		Category: facetText(f.Category), SortKey: f.SortKey, Featured: f.Featured, Protocol: facetText(f.Protocol),
		Hosting: facetText(f.Hosting), Pricing: facetText(f.Pricing), Now: naive(now), ID: id,
	})
}

// SetInstalled records (or clears) the entity an item materialized.
func (Sync) SetInstalled(ctx context.Context, s db.Session, itemID string, entityID, version *string, now time.Time) error {
	id, err := uuid.Parse(itemID)
	if err != nil {
		return err
	}
	return New(s.Q()).SetItemInstalled(ctx, SetItemInstalledParams{
		InstalledEntityID: nullID(entityID), InstalledVersion: text(version), Now: naive(now), ID: id,
	})
}

// SetVersion is the pointer check's version write.
func (Sync) SetVersion(ctx context.Context, s db.Session, itemID, version string, now time.Time) error {
	id, err := uuid.Parse(itemID)
	if err != nil {
		return err
	}
	return New(s.Q()).SetItemVersion(ctx, SetItemVersionParams{Version: text(&version), Now: naive(now), ID: id})
}

// MarkInSource is mark_in_source: how many items are out of the source after.
func (Sync) MarkInSource(ctx context.Context, s db.Session, registryID string, externalIDs []string) (int, error) {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return 0, err
	}
	if externalIDs == nil {
		externalIDs = []string{}
	}
	q := New(s.Q())
	if err := q.MarkInSource(ctx, MarkInSourceParams{ExternalIds: externalIDs, RegistryID: id}); err != nil {
		return 0, err
	}
	n, err := q.CountOutOfSource(ctx, id)
	return int(n), err
}

func nullable(u uuid.NullUUID) *uuid.UUID {
	if !u.Valid {
		return nil
	}
	v := u.UUID
	return &v
}

func uuids(ids []string) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(ids))
	for _, s := range ids {
		if u, err := uuid.Parse(s); err == nil {
			out = append(out, u)
		}
	}
	return out
}

// Moves pairs the registry's dropped items with the replacements'.
func (Sync) Moves(ctx context.Context, s db.Session, registryID string, replacements []string) ([]api.ItemMove, error) {
	id, err := uuid.Parse(registryID)
	if err != nil || len(replacements) == 0 {
		return nil, err
	}
	rows, err := New(s.Q()).MoveCandidates(ctx, MoveCandidatesParams{RegistryID: id, Replacements: uuids(replacements)})
	out := make([]api.ItemMove, len(rows))
	for i, r := range rows {
		out[i] = api.ItemMove{Old: r.OldID, New: r.NewID, OldCopy: nullable(r.OldCopy), NewCopy: nullable(r.NewCopy)}
	}
	return out, err
}

// MoveOwn moves the installs and servers of moves; how many moved.
func (Sync) MoveOwn(ctx context.Context, s db.Session, moves []api.ItemMove) (int, error) {
	if len(moves) == 0 {
		return 0, nil
	}
	olds, news, copies := make([]uuid.UUID, len(moves)), make([]uuid.UUID, len(moves)), make([]uuid.UUID, len(moves))
	for i, m := range moves {
		olds[i], news[i] = m.Old, m.New
		if m.OldCopy != nil {
			copies[i] = *m.OldCopy
		}
	}
	q := New(s.Q())
	a, err := q.MoveInstalls(ctx, MoveInstallsParams{OldIds: olds, NewIds: news})
	if err != nil {
		return 0, err
	}
	b, err := q.MoveServers(ctx, MoveServersParams{OldIds: olds, NewIds: news, OldCopies: copies})
	return int(a + b), err
}

// ReplacedCopy is a dropped item's platform copy its replacement made unused.
type ReplacedCopy struct{ Item, Copy uuid.UUID }

// ReplacedCopies is replaced_copies.
func (Sync) ReplacedCopies(ctx context.Context, s db.Session, registryID string, replacements []string) ([]ReplacedCopy, error) {
	id, err := uuid.Parse(registryID)
	if err != nil || len(replacements) == 0 {
		return nil, err
	}
	rows, err := New(s.Q()).ReplacedCopies(ctx, ReplacedCopiesParams{RegistryID: id, Replacements: uuids(replacements)})
	out := make([]ReplacedCopy, len(rows))
	for i, r := range rows {
		out[i] = ReplacedCopy{Item: r.ID, Copy: r.Copy}
	}
	return out, err
}

// DeletePlatformServer deletes a platform MCP server copy.
func (Sync) DeletePlatformServer(ctx context.Context, s db.Session, id uuid.UUID) error {
	_, err := New(s.Q()).DeletePlatformServer(ctx, id)
	return err
}

// DroppedProviders locks the provider specs only the registry's dropped items publish.
func (Sync) DroppedProviders(ctx context.Context, s db.Session, registryID string) ([]uuid.UUID, error) {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return nil, err
	}
	return New(s.Q()).DroppedProviderSpecs(ctx, id)
}

// ProviderModels locks the providers' model specs: model id to (provider, copied by a workspace).
type ProviderModel struct {
	ID, Provider uuid.UUID
	Copy         bool
}

// ProviderModels locks the models of providers.
func (Sync) ProviderModels(ctx context.Context, s db.Session, providers []uuid.UUID) ([]ProviderModel, error) {
	rows, err := New(s.Q()).LockModelSpecsOf(ctx, providers)
	out := make([]ProviderModel, len(rows))
	for i, r := range rows {
		out[i] = ProviderModel{ID: r.ID, Provider: r.ProviderSpecID, Copy: r.WorkspaceID != "platform"}
	}
	return out, err
}

// DroppedModels locks the model specs only the registry's dropped items publish.
func (Sync) DroppedModels(ctx context.Context, s db.Session, registryID string) ([]uuid.UUID, error) {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return nil, err
	}
	return New(s.Q()).DroppedModelSpecs(ctx, id)
}

// deleted counts the registry's rows among owners and clears the others' etags (_delete_items).
func deleted(ctx context.Context, q *Queries, registryID string, owners []uuid.UUID) (int, error) {
	n, others := 0, map[uuid.UUID]bool{}
	for _, o := range owners {
		if o.String() == registryID {
			n++
		} else {
			others[o] = true
		}
	}
	if len(others) == 0 {
		return n, nil
	}
	ids := make([]uuid.UUID, 0, len(others))
	for o := range others {
		ids = append(ids, o)
	}
	return n, q.ClearSourceEtags(ctx, ids)
}

// DeleteProviders deletes provider specs, their models and every item naming them.
func (Sync) DeleteProviders(ctx context.Context, s db.Session, registryID string, ids []uuid.UUID) (int, error) {
	if len(ids) == 0 {
		return 0, nil
	}
	q := New(s.Q())
	owners, err := q.DeleteProviderItems(ctx, ids)
	if err != nil {
		return 0, err
	}
	n, err := deleted(ctx, q, registryID, owners)
	if err != nil {
		return 0, err
	}
	return n, q.DeleteProviderSpecs(ctx, ids)
}

// DeleteModels deletes model specs and every item naming them.
func (Sync) DeleteModels(ctx context.Context, s db.Session, registryID string, ids []uuid.UUID) (int, error) {
	if len(ids) == 0 {
		return 0, nil
	}
	q := New(s.Q())
	owners, err := q.DeleteModelItems(ctx, ids)
	if err != nil {
		return 0, err
	}
	n, err := deleted(ctx, q, registryID, owners)
	if err != nil {
		return 0, err
	}
	return n, q.DeleteModelSpecsByID(ctx, ids)
}

// UnheldOutOfSource are the dropped items no catalog row holds.
func (Sync) UnheldOutOfSource(ctx context.Context, s db.Session, registryID string) ([]uuid.UUID, error) {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return nil, err
	}
	return New(s.Q()).OutOfSourceItems(ctx, id)
}

// DeleteItems deletes items by id and gives what stays out of the source its registry's trust.
func (Sync) DeleteItems(ctx context.Context, s db.Session, registryID string, ids []uuid.UUID) (int, error) {
	reg, err := uuid.Parse(registryID)
	if err != nil {
		return 0, err
	}
	q := New(s.Q())
	var n int64
	if len(ids) > 0 {
		if n, err = q.DeleteItemsByID(ctx, ids); err != nil {
			return 0, err
		}
	}
	return int(n), q.SetOutOfSourceTrust(ctx, reg)
}

// RecordSync records a finished sync.
func (Sync) RecordSync(ctx context.Context, s db.Session, registryID string, itemCount int, etag *string, now time.Time) error {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return err
	}
	return New(s.Q()).RecordSync(ctx, RecordSyncParams{Now: naive(now), ItemCount: int32(itemCount), SourceEtag: text(etag), ID: id})
}

// TouchSync records an unchanged source.
func (Sync) TouchSync(ctx context.Context, s db.Session, registryID string, now time.Time) error {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return err
	}
	return New(s.Q()).TouchSync(ctx, TouchSyncParams{Now: naive(now), ID: id})
}

// RecordSyncError records why a sync failed.
func (Sync) RecordSyncError(ctx context.Context, s db.Session, registryID, msg string, now time.Time) error {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return err
	}
	return New(s.Q()).RecordSyncError(ctx, RecordSyncErrorParams{Error: text(&msg), Now: naive(now), ID: id})
}

// InstalledItems is list_installed.
func (Sync) InstalledItems(ctx context.Context, s db.Session, registryID string) ([]domain.Item, error) {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return nil, err
	}
	rows, err := New(s.Q()).InstalledItems(ctx, id)
	return items(rows), err
}

// ProviderContract is the HTTP-contract columns a catalog entry states; a nil entry is absent.
type ProviderContract struct {
	BaseURL, Transport, Auth, ModelsPath, ListShape, ModelsQuery, ReasoningParam *Opt[string]
	ReasoningEfforts                                                             *Opt[[]byte]
	CacheBreakpoints, PDFInput                                                   *Opt[bool]
	MaxImageBytes, MaxImageEdge                                                  *Opt[int]
}

// Opt is a stated value that may be null.
type Opt[T any] struct {
	Value T
	Null  bool
}

func optText(o *Opt[string]) (pgtype.Text, any, bool) {
	if o == nil || o.Null {
		return pgtype.Text{}, nil, o != nil
	}
	return pgtype.Text{String: o.Value, Valid: true}, o.Value, true
}

func optInt4(o *Opt[int]) (pgtype.Int4, bool) {
	if o == nil || o.Null {
		return pgtype.Int4{}, o != nil
	}
	return int4(&o.Value), true
}

// ProviderRow is a provider spec as a catalog entry states it.
type ProviderRow struct {
	Key, Name, Type         string
	Description, Icon       *string
	IsBuiltin, IsFirstParty bool
	Contract                ProviderContract
}

// UpsertProvider is upsert_by_provider_key; the spec's id.
func (Sync) UpsertProvider(ctx context.Context, s db.Session, p ProviderRow, now time.Time) (uuid.UUID, error) {
	c := p.Contract
	arg := UpsertProviderSpecParams{
		ID: uuid.New(), ProviderKey: p.Key, Name: p.Name, Description: text(p.Description), ProviderType: p.Type,
		Icon: text(p.Icon), IsBuiltin: p.IsBuiltin, IsFirstParty: p.IsFirstParty, Now: naive(now),
	}
	arg.BaseUrl, _, arg.SetBaseUrl = optText(c.BaseURL)
	_, arg.Transport, arg.SetTransport = optText(c.Transport)
	_, arg.Auth, arg.SetAuth = optText(c.Auth)
	arg.ModelsPath, _, arg.SetModelsPath = optText(c.ModelsPath)
	_, arg.ListShape, arg.SetListShape = optText(c.ListShape)
	arg.ModelsQuery, _, arg.SetModelsQuery = optText(c.ModelsQuery)
	_, arg.ReasoningParam, arg.SetReasoningParam = optText(c.ReasoningParam)
	if c.ReasoningEfforts != nil {
		arg.SetReasoningEfforts = true
		if !c.ReasoningEfforts.Null {
			arg.ReasoningEfforts = c.ReasoningEfforts.Value
		}
	}
	if c.CacheBreakpoints != nil {
		arg.SetCacheBreakpoints = true
		if !c.CacheBreakpoints.Null {
			arg.CacheBreakpoints = boolean(c.CacheBreakpoints.Value)
		}
	}
	if c.PDFInput != nil {
		arg.SetPdfInput = true
		if !c.PDFInput.Null {
			arg.PdfInput = boolean(c.PDFInput.Value)
		}
	}
	arg.MaxImageBytes, arg.SetMaxImageBytes = optInt4(c.MaxImageBytes)
	arg.MaxImageEdge, arg.SetMaxImageEdge = optInt4(c.MaxImageEdge)
	return New(s.Q()).UpsertProviderSpec(ctx, arg)
}

// ProviderIDByKey is get_by_provider_key's id.
func (Sync) ProviderIDByKey(ctx context.Context, s db.Session, key string) (uuid.UUID, bool, error) {
	return one(New(s.Q()).ProviderSpecIDByKey(ctx, key))
}

// ModelRow is a platform model spec as a catalog entry states it.
type ModelRow struct {
	Provider                                             uuid.UUID
	Name, DisplayName, Kind                              string
	Description                                          *string
	ContextWindow, MaxOutputTokens                       *int
	InputCost, OutputCost, CachedCost, CacheCreationCost *money.Decimal
	FunctionCalling, Vision, Reasoning, Active           bool
	ReasoningEfforts                                     []byte
	ResponsesLite                                        bool
}

func numeric(d *money.Decimal) pgtype.Numeric {
	var n pgtype.Numeric
	if d != nil {
		_ = n.Scan(d.Plain())
	}
	return n
}

// UpsertModel is upsert_by_provider_and_model_kwargs in the platform workspace.
func (Sync) UpsertModel(ctx context.Context, s db.Session, m ModelRow, now time.Time) (uuid.UUID, error) {
	return New(s.Q()).UpsertPlatformModelSpec(ctx, UpsertPlatformModelSpecParams{
		ID: uuid.New(), ProviderSpecID: m.Provider, ModelName: m.Name, DisplayName: m.DisplayName,
		Description: text(m.Description), Kind: m.Kind, ContextWindow: int4(m.ContextWindow),
		MaxOutputTokens: int4(m.MaxOutputTokens), InputCost: numeric(m.InputCost), OutputCost: numeric(m.OutputCost),
		CachedInputCost: numeric(m.CachedCost), CacheCreationCost: numeric(m.CacheCreationCost),
		SupportsFunctionCalling: boolean(m.FunctionCalling), SupportsVision: boolean(m.Vision),
		SupportsReasoning: boolean(m.Reasoning), ReasoningEfforts: m.ReasoningEfforts, ResponsesLite: m.ResponsesLite, IsActive: m.Active, Now: naive(now),
	})
}

// ResyncCachePrices is resync_cache_prices for the two cache columns
// (cached input, cache creation): how many prices changed.
func (Sync) ResyncCachePrices(ctx context.Context, s db.Session, provider uuid.UUID, model string, oldCached, newCached, oldCreation, newCreation *money.Decimal) (int, error) {
	q := New(s.Q())
	n := 0
	if newCached != nil {
		c, err := q.ResyncCachedInputPrice(ctx, ResyncCachedInputPriceParams{
			Price: numeric(newCached), ProviderSpecID: provider, ModelName: model, HasOld: oldCached != nil, Old: numeric(oldCached),
		})
		if err != nil {
			return 0, err
		}
		n += int(c)
	}
	if newCreation != nil {
		c, err := q.ResyncCacheCreationPrice(ctx, ResyncCacheCreationPriceParams{
			Price: numeric(newCreation), ProviderSpecID: provider, ModelName: model, HasOld: oldCreation != nil, Old: numeric(oldCreation),
		})
		if err != nil {
			return 0, err
		}
		n += int(c)
	}
	return n, nil
}

// InsertMirror inserts the platform's MCP server copy of a catalog item.
func (Sync) InsertMirror(ctx context.Context, s db.Session, itemID uuid.UUID, name, slug string, m MirroredServer, now time.Time) (uuid.UUID, error) {
	r, err := New(s.Q()).InsertMCPSpec(ctx, InsertMCPSpecParams{
		ID: uuid.New(), Name: name, Slug: slug, Description: m.Description, DockerImageUrl: text(m.DockerImageURL),
		Version: m.Version, Tags: m.Tags, Status: "active", EnvSchema: m.EnvSchema, Cmd: m.Cmd,
		RemoteUrl: text(m.RemoteURL), RegistryItemID: uuid.NullUUID{UUID: itemID, Valid: true}, JsonSpec: m.JSONSpec,
		RegistryUrl: text(&m.RegistryURL), WorkspaceID: "platform", CreatedBy: "platform", Now: naive(now),
	})
	return r.ID, err
}

// MirrorSlugTaken is get_by_slug in the platform workspace.
func (Sync) MirrorSlugTaken(ctx context.Context, s db.Session, slug string) (bool, error) {
	return New(s.Q()).MCPSpecSlugTaken(ctx, MCPSpecSlugTakenParams{WorkspaceID: "platform", Slug: slug})
}

// BackfillMirror is _backfill_entity on the platform copy.
func (Sync) BackfillMirror(ctx context.Context, s db.Session, id uuid.UUID, jsonSpec, envSchema []byte, remoteURL, registryURL *string) error {
	return New(s.Q()).BackfillMirroredServer(ctx, BackfillMirroredServerParams{
		JsonSpec: jsonSpec, RemoteUrl: text(remoteURL), RegistryUrl: text(registryURL), EnvSchema: envSchema, ID: id,
	})
}

// UpdateMirror rewrites the platform copy (_update_mcp_server).
func (Sync) UpdateMirror(ctx context.Context, s db.Session, id uuid.UUID, m MirroredServer, now time.Time) error {
	_, err := New(s.Q()).UpdateMirroredServer(ctx, UpdateMirroredServerParams{
		Description: m.Description, DockerImageUrl: text(m.DockerImageURL), Version: m.Version,
		Tags: m.Tags, EnvSchema: m.EnvSchema, Cmd: m.Cmd, RemoteUrl: text(m.RemoteURL), JsonSpec: m.JSONSpec,
		RegistryUrl: text(&m.RegistryURL), Now: naive(now), ID: id, WorkspaceID: "platform",
	})
	return err
}

// CountItems is count_by_registry.
func (Sync) CountItems(ctx context.Context, s db.Session, registryID string) (int, error) {
	id, err := uuid.Parse(registryID)
	if err != nil {
		return 0, err
	}
	n, err := New(s.Q()).CountRegistryItems(ctx, id)
	return int(n), err
}
