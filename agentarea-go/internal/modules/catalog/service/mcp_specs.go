package service

import (
	"context"
	"reflect"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

// MCPSpecStore is store.MCPSpecs.
type MCPSpecStore interface {
	Workspace(ctx context.Context, s db.Session, id uuid.UUID) (api.MCPSpec, bool, error)
	CatalogMirror(ctx context.Context, s db.Session, id uuid.UUID) (api.MCPSpec, bool, error)
	Platform(ctx context.Context, s db.Session, id uuid.UUID) (api.MCPSpec, bool, error)
	CatalogItem(ctx context.Context, s db.Session, id uuid.UUID) (store.CatalogMCPItem, bool, error)
	SlugTaken(ctx context.Context, s db.Session, slug string) (bool, error)
	Insert(ctx context.Context, s db.Session, r store.MCPSpecRow) (api.MCPSpec, error)
	SetJSONSpec(ctx context.Context, s db.Session, id uuid.UUID, spec map[string]any) (bool, error)
	BySlug(ctx context.Context, s db.Session, slug string) (api.MCPSpec, bool, error)
	Tenant(ctx context.Context, s db.Session, f store.MCPSpecFilter, limit, offset int32) ([]api.MCPSpec, int, error)
	Instantiated(ctx context.Context, s db.Session, f store.MCPSpecFilter) ([]uuid.UUID, error)
	CatalogPage(ctx context.Context, s db.Session, exclude, itemIDs []uuid.UUID, tag, search *string, limit, offset int32) ([]store.CatalogMCPItem, int, error)
	Update(ctx context.Context, s db.Session, sp api.MCPSpec, updatedBy string, now time.Time) (api.MCPSpec, bool, error)
	Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
}

// MCPSpecs implements api.MCPSpecs (MCPServerRepository as connections uses it).
type MCPSpecs struct {
	s     *Service
	st    MCPSpecStore
	newID func() uuid.UUID
}

var _ api.MCPSpecs = MCPSpecs{}

// MCPSpecs is what connections reads and writes of MCP server specs.
func (s *Service) MCPSpecs() MCPSpecs { return MCPSpecs{s: s, st: store.MCPSpecs{}, newID: uuid.New} }

// Get is get_server_by_id: the workspace's row, an active catalog mirror,
// the platform's row behind a platform-managed connection, then the
// read-only projection of the registry item.
func (x MCPSpecs) Get(ctx context.Context, ws scope.Workspace, id string, o api.MCPSpecGet) (out api.MCPSpec, ok bool, err error) {
	u, perr := uuid.Parse(id)
	if perr != nil {
		return api.MCPSpec{}, false, nil
	}
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		out, ok, err = x.get(ctx, sess, u, o)
		return err
	})
	return out, ok, err
}

type specRead struct {
	read    func(context.Context, db.Session, uuid.UUID) (api.MCPSpec, bool, error)
	catalog bool
}

func (x MCPSpecs) get(ctx context.Context, sess db.Session, id uuid.UUID, o api.MCPSpecGet) (api.MCPSpec, bool, error) {
	rows := []specRead{{x.st.Workspace, false}, {x.st.CatalogMirror, true}}
	if o.PlatformBacked {
		rows = append(rows, specRead{x.st.Platform, false})
	}
	for _, r := range rows {
		sp, ok, err := r.read(ctx, sess, id)
		if err != nil {
			return api.MCPSpec{}, false, err
		}
		if ok {
			sp.Catalog = r.catalog
			sp, err = x.hydrate(ctx, sess, sp)
			return sp, err == nil, err
		}
	}
	it, ok, err := x.st.CatalogItem(ctx, sess, id)
	if err != nil || !ok {
		return api.MCPSpec{}, false, err
	}
	return ProjectCatalogMCPItem(it), true, nil
}

// hydrate is _hydrate_catalog_env_schema: a spec made from a catalog item
// gets its normalized schema, derived from the item when it stores none.
func (x MCPSpecs) hydrate(ctx context.Context, sess db.Session, sp api.MCPSpec) (api.MCPSpec, error) {
	if sp.RegistryItemID == nil {
		return sp, nil
	}
	env := NormalizeMCPEnvSchema(sp.EnvSchema)
	if len(env) == 0 {
		if u, err := uuid.Parse(*sp.RegistryItemID); err == nil {
			it, ok, err := x.st.CatalogItem(ctx, sess, u)
			if err != nil {
				return sp, err
			}
			if ok {
				env = DeriveMCPEnvSchema(it.Spec)
			}
		}
	}
	sp.EnvSchema = env
	return sp, nil
}

// Create inserts a workspace spec in tx under a slug unique in the workspace.
func (x MCPSpecs) Create(ctx context.Context, tx db.Session, createdBy string, n api.MCPSpecNew) (api.MCPSpec, error) {
	slug, err := x.uniqueSlug(ctx, tx, n.Name)
	if err != nil {
		return api.MCPSpec{}, err
	}
	return x.st.Insert(ctx, tx, store.MCPSpecRow{ID: x.newID(), Slug: slug, Status: "draft",
		CreatedBy: createdBy, Now: x.s.d.Now(), MCPSpecNew: n})
}

// MaterializeCopy is _materialize_workspace_spec_copy.
func (x MCPSpecs) MaterializeCopy(ctx context.Context, tx db.Session, createdBy string, source api.MCPSpec) (api.MCPSpec, error) {
	desc := source.Description
	if desc == "" {
		desc = source.Name
	}
	version := source.Version
	if version == "" {
		version = "1.0.0"
	}
	return x.Create(ctx, tx, createdBy, api.MCPSpecNew{
		Name: source.Name, Description: desc, Version: version, DockerImageURL: source.DockerImageURL,
		RemoteURL: source.RemoteURL, Cmd: source.Cmd, EnvSchema: source.EnvSchema, JSONSpec: source.JSONSpec,
		Tags: source.Tags, RegistryItemID: source.RegistryItemID, RegistryURL: source.RegistryURL,
	})
}

func (x MCPSpecs) uniqueSlug(ctx context.Context, sess db.Session, name string) (string, error) {
	base := scope.EntitySlug(name)
	var readErr error
	slug, err := scope.UniqueSlug(base, func(c string) (bool, error) {
		taken, err := x.st.SlugTaken(ctx, sess, c)
		readErr = err
		return taken, err
	})
	if err != nil && readErr == nil {
		return "", &api.ErrSlugsExhausted{Base: base}
	}
	return slug, err
}

// SetAuthMethods caches the probe's auth methods on a workspace row.
func (x MCPSpecs) SetAuthMethods(ctx context.Context, ws scope.Workspace, id string, methods []any) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	var ok bool
	err = x.s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		sp, found, err := x.st.Workspace(ctx, tx, u)
		if err != nil || !found {
			return err
		}
		spec := make(map[string]any, len(sp.JSONSpec)+1)
		for k, v := range sp.JSONSpec {
			spec[k] = v
		}
		spec["auth_methods"] = methods
		ok, err = x.st.SetJSONSpec(ctx, tx, u, spec)
		return err
	})
	return ok, err
}

// CatalogJSONSpec is catalog_json_spec.
func (x MCPSpecs) CatalogJSONSpec(ctx context.Context, ws scope.Workspace, id string) (out map[string]any, ok bool, err error) {
	u, perr := uuid.Parse(id)
	if perr != nil {
		return nil, false, nil
	}
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		sp, found, err := x.get(ctx, sess, u, api.MCPSpecGet{})
		if err != nil || !found {
			return err
		}
		if sp.Catalog || sp.WorkspaceID == store.PlatformWorkspaceID {
			out, ok = sp.JSONSpec, sp.JSONSpec != nil
			return nil
		}
		if sp.RegistryItemID == nil {
			return nil
		}
		iu, perr := uuid.Parse(*sp.RegistryItemID)
		if perr != nil {
			return nil
		}
		it, found, err := x.st.CatalogItem(ctx, sess, iu)
		if err != nil || !found {
			return err
		}
		p := ProjectCatalogMCPItem(it)
		out, ok = p.JSONSpec, p.JSONSpec != nil
		return nil
	})
	return out, ok, err
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

// ProjectCatalogMCPItem is _project_catalog_mcp_server: a transient,
// read-only spec whose id is the item's.
func ProjectCatalogMCPItem(it store.CatalogMCPItem) api.MCPSpec {
	spec := it.Spec
	conn := "url"
	if v, ok := spec["connection_type"]; ok {
		conn = str(v)
	}
	var docker *string
	var cmd []any
	switch conn {
	case "docker":
		if img := str(spec["image"]); img != "" {
			docker = &img
		}
	case "command":
		img := "agentarea/agentarea-mcp-base"
		docker = &img
		if c := str(spec["command"]); c != "" {
			cmd = []any{c}
			if args, ok := spec["args"].([]any); ok {
				cmd = append(cmd, args...)
			}
		}
	}
	var remote *string
	if conn == "url" {
		if u, ok := spec["url"].(string); ok {
			remote = &u
		}
	}
	var raw map[string]any
	if r := spec["raw_spec"]; truthy(r) {
		raw, _ = r.(map[string]any)
	} else {
		raw = spec
	}
	desc := ""
	if it.Description != nil {
		desc = *it.Description
	}
	version := "latest"
	if it.Version != nil && *it.Version != "" {
		version = *it.Version
	}
	var regURL *string
	if r := str(spec["registry_url"]); r != "" {
		regURL = &r
	}
	id := it.ID
	return api.MCPSpec{
		ID: it.ID, Name: it.Name, Slug: scope.EntitySlug(it.Name), Description: desc, Version: version,
		Status: "active", DockerImageURL: docker, RemoteURL: remote, Cmd: cmd, EnvSchema: DeriveMCPEnvSchema(spec),
		JSONSpec: raw, Tags: it.Tags, RegistryItemID: &id, RegistryURL: regURL,
		Catalog: true, Projection: true, CreatedAt: it.CreatedAt, UpdatedAt: it.UpdatedAt,
	}
}

func truthy(v any) bool {
	if m, ok := v.(map[string]any); ok {
		return len(m) > 0
	}
	return PyTruthy(v)
}

// NormalizeMCPEnvSchema is normalize_env_schema over decoded JSON.
func NormalizeMCPEnvSchema(entries any) []any {
	list, ok := entries.([]any)
	if !ok {
		return []any{}
	}
	out := []any{}
	for _, e := range list {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}
		name, ok := entry["name"].(string)
		if !ok || strings.TrimSpace(name) == "" {
			continue
		}
		required, has := entry["isRequired"]
		if !has || required == nil {
			required = entry["required"]
		}
		req, secret := truthy(required), truthy(entry["isSecret"])
		desc := entry["description"]
		if !truthy(desc) {
			desc = ""
		}
		field := map[string]any{"name": name, "description": desc, "isSecret": secret, "isRequired": req, "required": req}
		if d, has := entry["default"]; has && !secret {
			field["default"] = d
		}
		out = append(out, field)
	}
	return out
}

// DeriveMCPEnvSchema is derive_env_schema_from_spec.
func DeriveMCPEnvSchema(spec any) []any {
	m, ok := spec.(map[string]any)
	if !ok {
		return []any{}
	}
	if declared := NormalizeMCPEnvSchema(m["env_schema"]); len(declared) > 0 {
		return declared
	}
	raw, ok := m["raw_spec"].(map[string]any)
	if !ok {
		raw = m
	}
	switch conn := m["connection_type"]; conn {
	case "url":
		remotes, ok := raw["remotes"].([]any)
		if !ok {
			return []any{}
		}
		var matching []map[string]any
		for _, r := range remotes {
			if rm, ok := r.(map[string]any); ok {
				matching = append(matching, rm)
			}
		}
		if url := m["url"]; truthy(url) {
			var byURL []map[string]any
			for _, r := range matching {
				if reflect.DeepEqual(r["url"], url) {
					byURL = append(byURL, r)
				}
			}
			if len(byURL) > 0 {
				matching = byURL
			} else if len(matching) != 1 {
				return []any{}
			}
		} else if len(matching) != 1 {
			return []any{}
		}
		return NormalizeMCPEnvSchema(matching[0]["headers"])
	case "command", "docker":
	default:
		return []any{}
	}
	packages, ok := raw["packages"].([]any)
	if !ok {
		return []any{}
	}
	registry := m["package_registry"]
	pkgName := m["package_name"]
	if !truthy(pkgName) {
		pkgName = m["image"]
	}
	var candidates []map[string]any
	for _, p := range packages {
		pm, ok := p.(map[string]any)
		if ok && (!truthy(registry) || reflect.DeepEqual(pm["registryType"], registry)) {
			candidates = append(candidates, pm)
		}
	}
	if truthy(pkgName) {
		var matching []map[string]any
		for _, p := range candidates {
			if reflect.DeepEqual(p["name"], pkgName) || reflect.DeepEqual(p["identifier"], pkgName) {
				matching = append(matching, p)
			}
		}
		if len(matching) > 0 {
			candidates = matching
		} else if len(candidates) != 1 {
			return []any{}
		}
	} else if len(candidates) != 1 {
		return []any{}
	}
	if len(candidates) != 1 {
		return []any{}
	}
	return NormalizeMCPEnvSchema(candidates[0]["environmentVariables"])
}

func uuids(ids []string) []uuid.UUID {
	if ids == nil {
		return nil
	}
	out := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if u, err := uuid.Parse(id); err == nil {
			out = append(out, u)
		}
	}
	return out
}

// List is list_servers: a projection is always an active, non-public spec,
// so a filter for another status or for public specs pages the tenant half
// alone.
func (x MCPSpecs) List(ctx context.Context, ws scope.Workspace, q api.MCPSpecQuery) (out []api.MCPSpec, total int, err error) {
	f := store.MCPSpecFilter{Readable: uuids(q.Readable), SpecIDs: uuids(q.SpecIDs), Status: q.Status, IsPublic: q.IsPublic, Tag: q.Tag, Search: q.Search}
	if f.Readable == nil {
		f.Readable = []uuid.UUID{}
	}
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		tenant, tenantTotal, err := x.st.Tenant(ctx, sess, f, int32(q.Limit), int32(q.Offset))
		if err != nil {
			return err
		}
		for i := range tenant {
			if tenant[i], err = x.hydrate(ctx, sess, tenant[i]); err != nil {
				return err
			}
		}
		out, total = tenant, tenantTotal
		if (q.Status != nil && *q.Status != "active") || (q.IsPublic != nil && *q.IsPublic) {
			return nil
		}
		exclude, err := x.st.Instantiated(ctx, sess, f)
		if err != nil {
			return err
		}
		items, catalogTotal, err := x.st.CatalogPage(ctx, sess, exclude, f.SpecIDs, q.Tag, q.Search,
			int32(max(0, q.Limit-len(tenant))), int32(max(0, q.Offset-tenantTotal)))
		if err != nil {
			return err
		}
		for _, it := range items {
			out = append(out, ProjectCatalogMCPItem(it))
		}
		total += catalogTotal
		return nil
	})
	return out, total, err
}

// BySlug is get_by_slug.
func (x MCPSpecs) BySlug(ctx context.Context, ws scope.Workspace, slug string) (out api.MCPSpec, ok bool, err error) {
	err = x.s.read(ctx, ws, func(sess db.Session) error {
		out, ok, err = x.st.BySlug(ctx, sess, slug)
		return err
	})
	return out, ok, err
}

// Update rewrites the workspace's row from sp.
func (x MCPSpecs) Update(ctx context.Context, tx db.Session, sp api.MCPSpec, updatedBy string) (api.MCPSpec, bool, error) {
	out, ok, err := x.st.Update(ctx, tx, sp, updatedBy, x.s.d.Now())
	if err != nil || !ok {
		return out, ok, err
	}
	out, err = x.hydrate(ctx, tx, out)
	return out, err == nil, err
}

// Delete removes the workspace's row.
func (x MCPSpecs) Delete(ctx context.Context, tx db.Session, id string) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	return x.st.Delete(ctx, tx, u)
}
