package service

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type fakeRegistries struct {
	RegistryStore
	registries map[string]domain.Registry
	items      map[string]domain.Item
	search     []domain.Item
	created    []domain.NewItem
	facets     []domain.Facets
	searched   []string
}

func (f *fakeRegistries) Get(_ context.Context, _ db.Session, id string) (domain.Registry, bool, error) {
	r, ok := f.registries[id]
	return r, ok, nil
}

func (f *fakeRegistries) GetItem(_ context.Context, _ db.Session, id string) (domain.Item, bool, error) {
	i, ok := f.items[id]
	return i, ok, nil
}

func (f *fakeRegistries) ItemByExternalID(_ context.Context, _ db.Session, registryID, ext string) (domain.Item, bool, error) {
	for _, i := range f.items {
		if i.RegistryID == registryID && i.ExternalID == ext {
			return i, true, nil
		}
	}
	return domain.Item{}, false, nil
}

func (f *fakeRegistries) NextRank(context.Context, db.Session, string) (int, error) { return 5, nil }

func (f *fakeRegistries) CreateItem(_ context.Context, _ db.Session, registryID string, n domain.NewItem, rank int, fc domain.Facets, _ time.Time) (domain.Item, error) {
	f.created = append(f.created, n)
	f.facets = append(f.facets, fc)
	return domain.Item{ID: "new", RegistryID: registryID, ExternalID: n.ExternalID, RecommendationRank: rank}, nil
}

func (f *fakeRegistries) SetItemCount(context.Context, db.Session, string, time.Time) error {
	return nil
}

func (f *fakeRegistries) Search(_ context.Context, _ db.Session, pattern, tag string, _ *bool, _, _ int32) ([]domain.Item, error) {
	f.searched = append(f.searched, pattern+"|"+tag)
	return f.search, nil
}

type authority bool

func (a authority) CanWrite(context.Context, authn.Caller, string) (bool, error) { return bool(a), nil }

func ws(t *testing.T) scope.Workspace {
	t.Helper()
	w, err := scope.NewWorkspace("w1", "w1")
	if err != nil {
		t.Fatal(err)
	}
	return w
}

func newService(st *fakeRegistries, write bool) *Service {
	return New(Deps{DB: fakeDB{}, Registries: st, Authority: authority(write)})
}

func valueMsg(t *testing.T, err error) string {
	t.Helper()
	var ve *ValueError
	if !errors.As(err, &ve) {
		t.Fatalf("err = %v, want a ValueError", err)
	}
	return ve.Msg
}

func TestPyRepr(t *testing.T) {
	for in, want := range map[string]string{`a`: `'a'`, `it's`: `"it's"`, `a'"b`: `'a\'"b'`, "x\ny": `'x\ny'`} {
		if got := PyRepr(in); got != want {
			t.Errorf("PyRepr(%q) = %s, want %s", in, got, want)
		}
	}
	if got := PyTuple("url", "github"); got != "('url', 'github')" {
		t.Errorf("PyTuple = %s", got)
	}
}

func TestCreateRegistryRefusals(t *testing.T) {
	s := newService(&fakeRegistries{}, true)
	w := ws(t)
	cases := []struct {
		n    domain.NewRegistry
		prio *int
		want string
	}{
		{domain.NewRegistry{RegistryType: "nope", SourceType: "url"}, nil,
			"registry_type must be one of ('mcp_servers', 'skills', 'llm_providers', 'llm_models', 'agents', 'bundles', 'source_types')"},
		{domain.NewRegistry{RegistryType: "skills", SourceType: "ftp"}, nil, "source_type must be one of ('url', 'github', 'api', 'managed')"},
		{domain.NewRegistry{RegistryType: "skills", SourceType: "url"}, nil, "source_url is required for synchronized registries"},
		{domain.NewRegistry{RegistryType: "agents", SourceType: "github", SourceURL: "o/r", Scope: "platform", Mode: "mirror", Trust: "official"}, nil,
			"a GitHub repository source holds skills"},
		{domain.NewRegistry{RegistryType: "skills", SourceType: "github", SourceURL: "o/..", Scope: "platform", Mode: "mirror", Trust: "official"}, nil,
			"a GitHub source_url is the repository as owner/repo"},
		{domain.NewRegistry{RegistryType: "skills", SourceType: "github", SourceURL: "o/r", SourceRef: ptr("a..b"), Scope: "platform", Mode: "mirror", Trust: "official"}, nil,
			"source_ref must be a branch, tag or commit name"},
		{domain.NewRegistry{RegistryType: "skills", SourceType: "github", SourceURL: "o/r", SourcePath: ptr("a/../b"), Scope: "platform", Mode: "mirror", Trust: "official"}, nil,
			"source_path must be a plain relative folder path"},
		{domain.NewRegistry{RegistryType: "skills", SourceType: "managed", Scope: "platform", Mode: "mirror", Trust: "official"}, ptr(-1),
			"recommendation_priority must be a non-negative integer, got -1"},
	}
	for _, c := range cases {
		_, err := s.CreateRegistry(context.Background(), w, c.n, c.prio)
		if got := valueMsg(t, err); got != c.want {
			t.Errorf("got %q, want %q", got, c.want)
		}
	}
}

func ptr[T any](v T) *T { return &v }

func TestPlatformWrite(t *testing.T) {
	err := newService(&fakeRegistries{}, false).RequirePlatformWrite(context.Background(), authn.Caller{})
	var fe *ForbiddenError
	if !errors.As(err, &fe) || fe.Detail != PlatformWriteDetail {
		t.Fatalf("err = %v", err)
	}
	if err := newService(&fakeRegistries{}, true).RequirePlatformWrite(context.Background(), authn.Caller{}); err != nil {
		t.Fatal(err)
	}
}

func TestSearchHandsTheTagToTheStore(t *testing.T) {
	st := &fakeRegistries{search: []domain.Item{{ID: "1"}}}
	got, err := newService(st, true).Search(context.Background(), ws(t), "x", "b", nil, 50, 0)
	if err != nil || len(got) != 1 || len(st.searched) != 1 || st.searched[0] != "%x%|b" {
		t.Fatalf("got %+v, searched %v, %v", got, st.searched, err)
	}
}

func TestCreateCatalogItem(t *testing.T) {
	st := &fakeRegistries{
		registries: map[string]domain.Registry{
			"m": {ID: "m", SourceType: "managed", RegistryType: domain.TypeMCPServers},
			"u": {ID: "u", SourceType: "url", RegistryType: domain.TypeSkills},
		},
		items: map[string]domain.Item{"i": {ID: "i", RegistryID: "m", ExternalID: "dup"}, "x": {ID: "x", RegistryID: "u"}},
	}
	s, w := newService(st, true), ws(t)
	ctx := context.Background()
	if _, err := s.CreateCatalogItem(ctx, w, "u", domain.NewItem{ExternalID: "x"}); valueMsg(t, err) != "Catalog items can only be written to a managed registry" {
		t.Fatal(err)
	}
	if err := s.DeleteCatalogItem(ctx, w, "x"); valueMsg(t, err) != "Catalog items can only be written to a managed registry" {
		t.Fatal(err)
	}
	var ce *ConflictError
	if _, err := s.CreateCatalogItem(ctx, w, "m", domain.NewItem{ExternalID: "dup"}); !errors.As(err, &ce) ||
		ce.Detail != "Catalog item 'dup' already exists in registry m" {
		t.Fatalf("err = %v", err)
	}
	var nf *NotFoundError
	if _, err := s.CreateCatalogItem(ctx, w, "gone", domain.NewItem{}); !errors.As(err, &nf) || nf.Detail != "Registry gone not found" {
		t.Fatalf("err = %v", err)
	}
	it, err := s.CreateCatalogItem(ctx, w, "m", domain.NewItem{
		ExternalID: "x", Name: "srv",
		Spec: json.RawMessage(`{"connection_type":"url","raw_spec":{"metadata":{"agentarea:category":"Data"}}}`),
		Tags: json.RawMessage(`["featured"]`),
	})
	if err != nil || it.RecommendationRank != 5 {
		t.Fatalf("item = %+v, %v", it, err)
	}
	f := st.facets[0]
	if f.Category != "Data" || f.Protocol != "mcp" || f.Hosting != "vendor" || f.Pricing != "free" || !f.Featured || f.SortKey != "srv" {
		t.Fatalf("facets = %+v", f)
	}
}
