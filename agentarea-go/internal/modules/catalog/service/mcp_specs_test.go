package service

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strconv"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

type fakeMCPSpecs struct {
	own, mirrors, platform map[uuid.UUID]api.MCPSpec
	items                  map[uuid.UUID]store.CatalogMCPItem
	slugs                  map[string]bool
	inserted               []store.MCPSpecRow
	written                map[uuid.UUID]map[string]any
}

func newFakeMCPSpecs() *fakeMCPSpecs {
	return &fakeMCPSpecs{own: map[uuid.UUID]api.MCPSpec{}, mirrors: map[uuid.UUID]api.MCPSpec{}, platform: map[uuid.UUID]api.MCPSpec{},
		items: map[uuid.UUID]store.CatalogMCPItem{}, slugs: map[string]bool{}, written: map[uuid.UUID]map[string]any{}}
}

func (f *fakeMCPSpecs) Workspace(_ context.Context, _ db.Session, id uuid.UUID) (api.MCPSpec, bool, error) {
	sp, ok := f.own[id]
	return sp, ok, nil
}

func (f *fakeMCPSpecs) CatalogMirror(_ context.Context, _ db.Session, id uuid.UUID) (api.MCPSpec, bool, error) {
	sp, ok := f.mirrors[id]
	return sp, ok, nil
}

func (f *fakeMCPSpecs) Platform(_ context.Context, _ db.Session, id uuid.UUID) (api.MCPSpec, bool, error) {
	sp, ok := f.platform[id]
	return sp, ok, nil
}

func (f *fakeMCPSpecs) CatalogItem(_ context.Context, _ db.Session, id uuid.UUID) (store.CatalogMCPItem, bool, error) {
	it, ok := f.items[id]
	return it, ok, nil
}

func (f *fakeMCPSpecs) SlugTaken(_ context.Context, _ db.Session, slug string) (bool, error) {
	return f.slugs[slug], nil
}

func (f *fakeMCPSpecs) Insert(_ context.Context, s db.Session, r store.MCPSpecRow) (api.MCPSpec, error) {
	f.inserted = append(f.inserted, r)
	return api.MCPSpec{ID: r.ID.String(), WorkspaceID: s.Workspace().ID(), Name: r.Name, Slug: r.Slug, Status: r.Status,
		Description: r.Description, Version: r.Version, RegistryItemID: r.RegistryItemID}, nil
}

func (f *fakeMCPSpecs) SetJSONSpec(_ context.Context, _ db.Session, id uuid.UUID, spec map[string]any) (bool, error) {
	if _, ok := f.own[id]; !ok {
		return false, nil
	}
	f.written[id] = spec
	return true, nil
}

func mcpSpecs(f *fakeMCPSpecs) MCPSpecs {
	s := New(Deps{DB: fakeDB{}, Now: func() time.Time { return time.Unix(0, 0) }})
	return MCPSpecs{s: s, st: f, newID: uuid.New}
}

func testWS(t *testing.T) scope.Workspace {
	t.Helper()
	ws, err := scope.NewWorkspace("ws1", "ws1")
	if err != nil {
		t.Fatal(err)
	}
	return ws
}

func decoded(t *testing.T, raw string) map[string]any {
	t.Helper()
	var v map[string]any
	if err := json.Unmarshal([]byte(raw), &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func TestMCPSpecGetChain(t *testing.T) {
	ctx, ws := context.Background(), testWS(t)
	f := newFakeMCPSpecs()
	itemID := uuid.New()
	f.items[itemID] = store.CatalogMCPItem{ID: itemID.String(), Name: "Git Hub!", Tags: []any{"x"},
		Spec: decoded(t, `{"connection_type":"url","url":"https://a/mcp","raw_spec":{"remotes":[{"url":"https://a/mcp","headers":[{"name":"X-Key","isSecret":true}]}]}}`)}
	ref := itemID.String()
	ownID, mirrorID, platID := uuid.New(), uuid.New(), uuid.New()
	f.own[ownID] = api.MCPSpec{ID: ownID.String(), WorkspaceID: "ws1", RegistryItemID: &ref, EnvSchema: []any{}}
	f.mirrors[mirrorID] = api.MCPSpec{ID: mirrorID.String(), WorkspaceID: "platform"}
	f.platform[platID] = api.MCPSpec{ID: platID.String(), WorkspaceID: "platform"}
	x := mcpSpecs(f)

	own, ok, err := x.Get(ctx, ws, ownID.String(), api.MCPSpecGet{})
	if err != nil || !ok || own.Catalog || len(own.EnvSchema) != 1 || own.EnvSchema[0].(map[string]any)["name"] != "X-Key" {
		t.Fatalf("own = %+v", own)
	}
	if m, ok, _ := x.Get(ctx, ws, mirrorID.String(), api.MCPSpecGet{}); !ok || !m.Catalog || m.Projection {
		t.Fatalf("mirror = %+v", m)
	}
	if _, ok, _ := x.Get(ctx, ws, platID.String(), api.MCPSpecGet{}); ok {
		t.Fatal("platform row read without PlatformBacked")
	}
	if p, ok, _ := x.Get(ctx, ws, platID.String(), api.MCPSpecGet{PlatformBacked: true}); !ok || p.Catalog {
		t.Fatalf("platform-backed = %+v", p)
	}
	proj, ok, _ := x.Get(ctx, ws, itemID.String(), api.MCPSpecGet{})
	if !ok || !proj.Projection || !proj.Catalog || proj.Slug != "git-hub" || proj.Status != "active" || proj.Version != "latest" ||
		*proj.RemoteURL != "https://a/mcp" || proj.DockerImageURL != nil || proj.JSONSpec["remotes"] == nil || *proj.RegistryItemID != itemID.String() {
		t.Fatalf("projection = %+v", proj)
	}
	if _, ok, err := x.Get(ctx, ws, "not-a-uuid", api.MCPSpecGet{}); ok || err != nil {
		t.Fatal("bad id found")
	}
}

func TestProjectCatalogMCPItemTransports(t *testing.T) {
	cmd := ProjectCatalogMCPItem(store.CatalogMCPItem{ID: uuid.NewString(), Name: "c",
		Spec: decoded(t, `{"connection_type":"command","command":"npx","args":["-y","pkg"],"url":"https://ignored"}`)})
	if *cmd.DockerImageURL != "agentarea/agentarea-mcp-base" || !reflect.DeepEqual(cmd.Cmd, []any{"npx", "-y", "pkg"}) || cmd.RemoteURL != nil {
		t.Fatalf("command = %+v", cmd)
	}
	dk := ProjectCatalogMCPItem(store.CatalogMCPItem{ID: uuid.NewString(), Name: "d",
		Spec: decoded(t, `{"connection_type":"docker","image":"img:1","raw_spec":["not","a","map"]}`)})
	if *dk.DockerImageURL != "img:1" || dk.Cmd != nil || dk.JSONSpec != nil {
		t.Fatalf("docker = %+v", dk)
	}
}

func TestMCPSpecCreateSlugs(t *testing.T) {
	ctx, ws := context.Background(), testWS(t)
	f := newFakeMCPSpecs()
	f.slugs["my-server"], f.slugs["my-server-2"] = true, true
	x := mcpSpecs(f)
	tx := db.NewTxSession(ws, nil)
	sp, err := x.Create(ctx, tx, "u1", api.MCPSpecNew{Name: "My Server", Description: "d", Version: "1.0.0"})
	if err != nil || sp.Slug != "my-server-3" || sp.Status != "draft" || f.inserted[0].CreatedBy != "u1" {
		t.Fatalf("created = %+v %v", sp, err)
	}
	f.slugs["full"] = true
	for i := 2; i <= scope.MaxSlugCollisionSuffix; i++ {
		f.slugs["full-"+strconv.Itoa(i)] = true
	}
	_, err = x.Create(ctx, tx, "u1", api.MCPSpecNew{Name: "Full"})
	var ex *api.ErrSlugsExhausted
	if !errors.As(err, &ex) || ex.Base != "full" {
		t.Fatalf("exhausted err = %v", err)
	}
}

func TestMCPSpecMaterializeCopy(t *testing.T) {
	ctx, ws := context.Background(), testWS(t)
	f := newFakeMCPSpecs()
	x := mcpSpecs(f)
	ref := uuid.NewString()
	_, err := x.MaterializeCopy(ctx, db.NewTxSession(ws, nil), "u1", api.MCPSpec{ID: uuid.NewString(), WorkspaceID: "platform",
		Name: "Mirror", RegistryItemID: &ref, Tags: []any{"t"}, JSONSpec: map[string]any{"a": "b"}})
	if err != nil {
		t.Fatal(err)
	}
	r := f.inserted[0]
	if r.Description != "Mirror" || r.Version != "1.0.0" || *r.RegistryItemID != ref || r.Slug != "mirror" || r.JSONSpec["a"] != "b" {
		t.Fatalf("copy = %+v", r)
	}
}

func TestMCPSpecSetAuthMethodsAndCatalogJSONSpec(t *testing.T) {
	ctx, ws := context.Background(), testWS(t)
	f := newFakeMCPSpecs()
	itemID := uuid.New()
	f.items[itemID] = store.CatalogMCPItem{ID: itemID.String(), Name: "i", Spec: decoded(t, `{"connection_type":"url","raw_spec":{"from":"item"}}`)}
	ref := itemID.String()
	ownID, bareID, mirrorID := uuid.New(), uuid.New(), uuid.New()
	f.own[ownID] = api.MCPSpec{ID: ownID.String(), WorkspaceID: "ws1", RegistryItemID: &ref, JSONSpec: map[string]any{"type": "url"}}
	f.own[bareID] = api.MCPSpec{ID: bareID.String(), WorkspaceID: "ws1", JSONSpec: map[string]any{"type": "url"}}
	f.mirrors[mirrorID] = api.MCPSpec{ID: mirrorID.String(), WorkspaceID: "platform", JSONSpec: map[string]any{"from": "mirror"}}
	x := mcpSpecs(f)

	if ok, err := x.SetAuthMethods(ctx, ws, ownID.String(), []any{"oauth"}); err != nil || !ok {
		t.Fatalf("set = %v %v", ok, err)
	}
	if w := f.written[ownID]; w["type"] != "url" || !reflect.DeepEqual(w["auth_methods"], []any{"oauth"}) {
		t.Fatalf("written = %v", w)
	}
	if ok, _ := x.SetAuthMethods(ctx, ws, mirrorID.String(), []any{"oauth"}); ok {
		t.Fatal("mirror written")
	}

	for id, want := range map[uuid.UUID]any{ownID: "item", mirrorID: "mirror", itemID: "item"} {
		js, ok, err := x.CatalogJSONSpec(ctx, ws, id.String())
		if err != nil || !ok || js["from"] != want {
			t.Fatalf("catalog json_spec of %s = %v %v %v", id, js, ok, err)
		}
	}
	if _, ok, _ := x.CatalogJSONSpec(ctx, ws, bareID.String()); ok {
		t.Fatal("spec without an item has a catalog json_spec")
	}
}

func TestDeriveMCPEnvSchema(t *testing.T) {
	pkg := decoded(t, `{"connection_type":"command","package_registry":"npm","package_name":"@x/a","raw_spec":{"packages":[
		{"registryType":"npm","identifier":"@x/a","environmentVariables":[{"name":"TOKEN","isSecret":true,"default":"no"},{"name":"MODE","required":1,"default":"fast"}]},
		{"registryType":"npm","identifier":"@x/b","environmentVariables":[{"name":"OTHER"}]}]}}`)
	got := DeriveMCPEnvSchema(pkg)
	want := []any{
		map[string]any{"name": "TOKEN", "description": "", "isSecret": true, "isRequired": false, "required": false},
		map[string]any{"name": "MODE", "description": "", "isSecret": false, "isRequired": true, "required": true, "default": "fast"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("package env = %#v", got)
	}
	twoRemotes := decoded(t, `{"connection_type":"url","remotes":[{"url":"a","headers":[{"name":"A"}]},{"url":"b","headers":[{"name":"B"}]}]}`)
	if len(DeriveMCPEnvSchema(twoRemotes)) != 0 {
		t.Fatal("ambiguous remotes derived a schema")
	}
	twoRemotes["url"] = "b"
	if got := DeriveMCPEnvSchema(twoRemotes); len(got) != 1 || got[0].(map[string]any)["name"] != "B" {
		t.Fatalf("remote env = %v", got)
	}
	declared := decoded(t, `{"connection_type":"url","env_schema":[{"name":"D","isRequired":null,"required":true}]}`)
	if got := DeriveMCPEnvSchema(declared); got[0].(map[string]any)["isRequired"] != true {
		t.Fatalf("declared env = %v", got)
	}
}
