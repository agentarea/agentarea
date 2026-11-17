package store

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// MCPSpecs reads and writes mcp_servers rows for connections, and the
// registry items they are projected from.
type MCPSpecs struct{}

// PlatformWorkspaceID is PLATFORM_WORKSPACE_ID: where catalog mirrors and
// the specs behind platform-managed connections live.
const PlatformWorkspaceID = "platform"

// CatalogMCPItem is a CatalogMcpItem: an mcp_servers item of an active registry.
type CatalogMCPItem struct {
	ID          string
	Name        string
	Description *string
	Version     *string
	Spec        map[string]any
	Tags        []any
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// decodeJSON reads stored JSON keeping numbers as written; nil for NULL.
func decodeJSON(b []byte) (any, error) {
	if len(b) == 0 {
		return nil, nil
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return v, nil
}

func marshal(v any) []byte {
	raw, err := json.Marshal(v)
	if err != nil {
		panic(err) // decoded JSON values always marshal
	}
	return raw
}

func mcpSpecFrom(r McpServer) (api.MCPSpec, error) {
	out := api.MCPSpec{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Name: r.Name, Slug: r.Slug,
		Description: r.Description, Version: r.Version, Status: r.Status, IsPublic: r.IsPublic,
		DockerImageURL: fromText(r.DockerImageUrl), RemoteURL: fromText(r.RemoteUrl), Icon: fromText(r.Icon),
		RegistryURL: fromText(r.RegistryUrl), CreatedAt: fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt),
	}
	if r.RegistryItemID.Valid {
		s := r.RegistryItemID.UUID.String()
		out.RegistryItemID = &s
	}
	for _, f := range []struct {
		raw []byte
		set func(any)
	}{
		{r.Cmd, func(v any) { out.Cmd, _ = v.([]any) }},
		{r.EnvSchema, func(v any) { out.EnvSchema, _ = v.([]any) }},
		{r.JsonSpec, func(v any) { out.JSONSpec, _ = v.(map[string]any) }},
		{r.Tags, func(v any) { out.Tags, _ = v.([]any) }},
	} {
		v, err := decodeJSON(f.raw)
		if err != nil {
			return api.MCPSpec{}, err
		}
		f.set(v)
	}
	return out, nil
}

func (MCPSpecs) one(r McpServer, err error) (api.MCPSpec, bool, error) {
	if errors.Is(err, pgx.ErrNoRows) {
		return api.MCPSpec{}, false, nil
	}
	if err != nil {
		return api.MCPSpec{}, false, err
	}
	out, err := mcpSpecFrom(r)
	return out, err == nil, err
}

// Workspace is the session's workspace's row id.
func (m MCPSpecs) Workspace(ctx context.Context, s db.Session, id uuid.UUID) (api.MCPSpec, bool, error) {
	return m.one(New(s.Q()).GetWorkspaceMCPSpec(ctx, GetWorkspaceMCPSpecParams{ID: id, WorkspaceID: s.Workspace().ID()}))
}

// CatalogMirror is the platform's mirror id of an item of an active registry.
func (m MCPSpecs) CatalogMirror(ctx context.Context, s db.Session, id uuid.UUID) (api.MCPSpec, bool, error) {
	return m.one(New(s.Q()).GetCatalogMirrorMCPSpec(ctx, id))
}

// Platform is the platform workspace's row id.
func (m MCPSpecs) Platform(ctx context.Context, s db.Session, id uuid.UUID) (api.MCPSpec, bool, error) {
	return m.one(New(s.Q()).GetPlatformMCPSpec(ctx, id))
}

// CatalogItem is the mcp_servers item id of an active registry.
func (MCPSpecs) CatalogItem(ctx context.Context, s db.Session, id uuid.UUID) (CatalogMCPItem, bool, error) {
	r, err := New(s.Q()).CatalogMCPItem(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return CatalogMCPItem{}, false, nil
	}
	if err != nil {
		return CatalogMCPItem{}, false, err
	}
	it, err := catalogMCPItemFrom(CatalogMCPItemRow(r))
	return it, err == nil, err
}

func catalogMCPItemFrom(r CatalogMCPItemRow) (CatalogMCPItem, error) {
	spec, err := decodeJSON(r.Spec)
	if err != nil {
		return CatalogMCPItem{}, err
	}
	tags, err := decodeJSON(r.Tags)
	if err != nil {
		return CatalogMCPItem{}, err
	}
	it := CatalogMCPItem{ID: r.ID.String(), Name: r.Name, Description: fromText(r.Description), Version: fromText(r.Version),
		CreatedAt: fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt)}
	if m, ok := spec.(map[string]any); ok {
		it.Spec = m
	} else {
		it.Spec = map[string]any{}
	}
	if l, ok := tags.([]any); ok {
		it.Tags = l
	} else {
		it.Tags = []any{}
	}
	return it, nil
}

// BySlug is get_by_slug: the session's workspace's row with that slug.
func (m MCPSpecs) BySlug(ctx context.Context, s db.Session, slug string) (api.MCPSpec, bool, error) {
	return m.one(New(s.Q()).GetWorkspaceMCPSpecBySlug(ctx, GetWorkspaceMCPSpecBySlugParams{WorkspaceID: s.Workspace().ID(), Slug: slug}))
}

// MCPSpecFilter is list_servers' filters as SQL binds; nil is no filter.
type MCPSpecFilter struct {
	Readable []uuid.UUID
	SpecIDs  []uuid.UUID
	Status   *string
	IsPublic *bool
	Tag      *string
	Search   *string
}

func nullableText(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func (f MCPSpecFilter) binds() (readable []uuid.UUID, status, tag, search pgtype.Text, public pgtype.Bool) {
	readable = f.Readable
	if readable == nil {
		readable = []uuid.UUID{}
	}
	if f.Tag != nil {
		tag = pgtype.Text{String: `%"` + *f.Tag + `"%`, Valid: true}
	}
	if f.Search != nil {
		search = pgtype.Text{String: "%" + *f.Search + "%", Valid: true}
	}
	if f.IsPublic != nil {
		public = pgtype.Bool{Bool: *f.IsPublic, Valid: true}
	}
	return readable, nullableText(f.Status), tag, search, public
}

// Tenant is the tenant half of list_servers: one page and the total.
func (MCPSpecs) Tenant(ctx context.Context, s db.Session, f MCPSpecFilter, limit, offset int32) ([]api.MCPSpec, int, error) {
	q := New(s.Q())
	readable, status, tag, search, public := f.binds()
	total, err := q.CountTenantMCPSpecs(ctx, CountTenantMCPSpecsParams{WorkspaceID: s.Workspace().ID(), Readable: readable,
		SpecIds: f.SpecIDs, Status: status, IsPublic: public, TagPattern: tag, Search: search})
	if err != nil {
		return nil, 0, err
	}
	rows, err := q.ListTenantMCPSpecs(ctx, ListTenantMCPSpecsParams{WorkspaceID: s.Workspace().ID(), Readable: readable,
		SpecIds: f.SpecIDs, Status: status, IsPublic: public, TagPattern: tag, Search: search, Lim: limit, Off: offset})
	if err != nil {
		return nil, 0, err
	}
	out := make([]api.MCPSpec, len(rows))
	for i, r := range rows {
		if out[i], err = mcpSpecFrom(r); err != nil {
			return nil, 0, err
		}
	}
	return out, int(total), nil
}

// Instantiated are the catalog items the tenant half's rows were made from.
func (MCPSpecs) Instantiated(ctx context.Context, s db.Session, f MCPSpecFilter) ([]uuid.UUID, error) {
	readable, status, tag, search, public := f.binds()
	ids, err := New(s.Q()).InstantiatedMCPItems(ctx, InstantiatedMCPItemsParams{WorkspaceID: s.Workspace().ID(), Readable: readable,
		SpecIds: f.SpecIDs, Status: status, IsPublic: public, TagPattern: tag, Search: search})
	if ids == nil {
		ids = []uuid.UUID{}
	}
	return ids, err
}

// CatalogPage is CatalogMcpRepository.list_page: a page of the items the
// workspace sees, none of exclude, and the total.
func (MCPSpecs) CatalogPage(ctx context.Context, s db.Session, exclude, itemIDs []uuid.UUID, tag, search *string, limit, offset int32) ([]CatalogMCPItem, int, error) {
	q := New(s.Q())
	var tagJSON []byte
	if tag != nil {
		tagJSON = marshal([]string{*tag})
	}
	var pattern *string
	if search != nil {
		p := "%" + *search + "%"
		pattern = &p
	}
	total, err := q.CountCatalogMCPItems(ctx, CountCatalogMCPItemsParams{WorkspaceID: s.Workspace().ID(), Exclude: exclude,
		ItemIds: itemIDs, Tag: tagJSON, Search: nullableText(pattern)})
	if err != nil {
		return nil, 0, err
	}
	if limit <= 0 || int64(offset) >= total {
		return nil, int(total), nil
	}
	rows, err := q.ListCatalogMCPItems(ctx, ListCatalogMCPItemsParams{WorkspaceID: s.Workspace().ID(), Exclude: exclude,
		ItemIds: itemIDs, Tag: tagJSON, Search: nullableText(pattern), Lim: limit, Off: offset})
	if err != nil {
		return nil, 0, err
	}
	out := make([]CatalogMCPItem, len(rows))
	for i, r := range rows {
		if out[i], err = catalogMCPItemFrom(CatalogMCPItemRow(r)); err != nil {
			return nil, 0, err
		}
	}
	return out, int(total), nil
}

// SlugTaken reports a slug the session's workspace already has.
func (MCPSpecs) SlugTaken(ctx context.Context, s db.Session, slug string) (bool, error) {
	return New(s.Q()).MCPSpecSlugTaken(ctx, MCPSpecSlugTakenParams{WorkspaceID: s.Workspace().ID(), Slug: slug})
}

// MCPSpecRow is a row Insert writes; the session's workspace owns it.
type MCPSpecRow struct {
	ID        uuid.UUID
	Slug      string
	Status    string
	CreatedBy string
	Now       time.Time
	api.MCPSpecNew
}

// Insert writes a spec row of the session's workspace.
func (MCPSpecs) Insert(ctx context.Context, s db.Session, r MCPSpecRow) (api.MCPSpec, error) {
	tags, env := r.Tags, r.EnvSchema
	if tags == nil {
		tags = []any{}
	}
	if env == nil {
		env = []any{}
	}
	p := InsertMCPSpecParams{
		ID: r.ID, Name: r.Name, Slug: r.Slug, Description: r.Description, DockerImageUrl: text(r.DockerImageURL),
		Version: r.Version, Tags: marshal(tags), Status: r.Status, IsPublic: r.IsPublic, EnvSchema: marshal(env),
		RemoteUrl: text(r.RemoteURL), RegistryUrl: text(r.RegistryURL), Icon: text(r.Icon),
		WorkspaceID: s.Workspace().ID(), CreatedBy: r.CreatedBy, Now: naive(r.Now),
	}
	if r.Cmd != nil {
		p.Cmd = marshal(r.Cmd)
	}
	if r.JSONSpec != nil {
		p.JsonSpec = marshal(r.JSONSpec)
	}
	if r.RegistryItemID != nil {
		u, err := uuid.Parse(*r.RegistryItemID)
		if err != nil {
			return api.MCPSpec{}, err
		}
		p.RegistryItemID = uuid.NullUUID{UUID: u, Valid: true}
	}
	row, err := New(s.Q()).InsertMCPSpec(ctx, p)
	if err != nil {
		return api.MCPSpec{}, err
	}
	return mcpSpecFrom(row)
}

// SetJSONSpec replaces json_spec on a row of the session's workspace; false when it has none.
func (MCPSpecs) SetJSONSpec(ctx context.Context, s db.Session, id uuid.UUID, spec map[string]any) (bool, error) {
	n, err := New(s.Q()).SetMCPSpecJSONSpec(ctx, SetMCPSpecJSONSpecParams{ID: id, WorkspaceID: s.Workspace().ID(), JsonSpec: marshal(spec)})
	return n > 0, err
}

// Update writes every mutable column of the session's workspace's row from sp.
func (m MCPSpecs) Update(ctx context.Context, s db.Session, sp api.MCPSpec, updatedBy string, now time.Time) (api.MCPSpec, bool, error) {
	id, err := uuid.Parse(sp.ID)
	if err != nil {
		return api.MCPSpec{}, false, nil
	}
	tags, env := sp.Tags, sp.EnvSchema
	if tags == nil {
		tags = []any{}
	}
	if env == nil {
		env = []any{}
	}
	p := UpdateMCPSpecParams{
		ID: id, WorkspaceID: s.Workspace().ID(), Name: sp.Name, Description: sp.Description,
		DockerImageUrl: text(sp.DockerImageURL), RemoteUrl: text(sp.RemoteURL), Version: sp.Version,
		Tags: marshal(tags), IsPublic: sp.IsPublic, Status: sp.Status, EnvSchema: marshal(env),
		RegistryUrl: text(sp.RegistryURL), UpdatedBy: text(&updatedBy), Now: naive(now),
	}
	if sp.Cmd != nil {
		p.Cmd = marshal(sp.Cmd)
	}
	if sp.JSONSpec != nil {
		p.JsonSpec = marshal(sp.JSONSpec)
	}
	return m.one(New(s.Q()).UpdateMCPSpec(ctx, p))
}

// Delete removes the session's workspace's row.
func (MCPSpecs) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteMCPSpec(ctx, DeleteMCPSpecParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}
