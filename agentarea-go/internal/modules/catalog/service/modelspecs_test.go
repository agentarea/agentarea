package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

type fakeSpecs struct {
	SpecStore
	own       []api.ModelSpec
	catalog   []store.CatalogModel
	updates   []bool
	createErr error
	provider  uuid.UUID
}

func (f *fakeSpecs) OwnModelSpecs(context.Context, db.Session, store.SpecFilter) ([]api.ModelSpec, error) {
	return f.own, nil
}

func (f *fakeSpecs) OwnModelSpec(_ context.Context, _ db.Session, id uuid.UUID) (api.ModelSpec, bool, error) {
	for _, m := range f.own {
		if m.ID == id {
			return m, true, nil
		}
	}
	return api.ModelSpec{}, false, nil
}

func (f *fakeSpecs) OwnModelKeys(context.Context, db.Session) (map[store.ModelKey]bool, error) {
	out := map[store.ModelKey]bool{}
	for _, m := range f.own {
		out[store.ModelKey{ProviderSpecID: m.ProviderSpecID, ModelName: m.ModelName}] = true
	}
	return out, nil
}

func (f *fakeSpecs) ProviderSpecs(context.Context, db.Session, []uuid.UUID) (map[uuid.UUID]api.ProviderSpec, error) {
	return map[uuid.UUID]api.ProviderSpec{}, nil
}

func (f *fakeSpecs) ProviderSpec(_ context.Context, _ db.Session, id uuid.UUID) (api.ProviderSpec, bool, error) {
	if id == f.provider {
		return api.ProviderSpec{ID: id}, true, nil
	}
	return api.ProviderSpec{}, false, nil
}

func (f *fakeSpecs) ModelSpecsOfProviders(context.Context, db.Session, []uuid.UUID) ([]api.ModelSpec, error) {
	return nil, nil
}

func (f *fakeSpecs) CatalogModels(context.Context, db.Session) ([]store.CatalogModel, error) {
	return f.catalog, nil
}

func (f *fakeSpecs) CatalogModel(_ context.Context, _ db.Session, id uuid.UUID) (store.CatalogModel, bool, error) {
	for _, c := range f.catalog {
		if c.ID == id {
			return c, true, nil
		}
	}
	return store.CatalogModel{}, false, nil
}

func (f *fakeSpecs) ModelSpecByProviderAndName(_ context.Context, _ db.Session, p uuid.UUID, name string) (api.ModelSpec, bool, error) {
	for _, m := range f.own {
		if m.ProviderSpecID == p && m.ModelName == name {
			return m, true, nil
		}
	}
	return api.ModelSpec{}, false, nil
}

func (f *fakeSpecs) CreateModelSpec(_ context.Context, _ db.Session, id, p uuid.UUID, _, name string, fs store.SpecFields, now time.Time) error {
	if f.createErr != nil {
		return f.createErr
	}
	f.own = append(f.own, api.ModelSpec{ID: id, ProviderSpecID: p, ModelName: name, DisplayName: *fs.DisplayName, Kind: *fs.Kind, IsActive: *fs.IsActive, CreatedAt: now})
	return nil
}

func (f *fakeSpecs) UpdateModelSpec(_ context.Context, _ db.Session, id uuid.UUID, fs store.SpecFields, touch bool, _ time.Time) (bool, error) {
	f.updates = append(f.updates, touch)
	for i, m := range f.own {
		if m.ID == id {
			if fs.DisplayName != nil {
				f.own[i].DisplayName = *fs.DisplayName
			}
			return true, nil
		}
	}
	return false, nil
}

func priced(id uuid.UUID, provider uuid.UUID, name, display string, withPrice bool) store.CatalogModel {
	spec := fmt.Sprintf(`{"model_name":%q,"context_window":1000}`, name)
	if withPrice {
		spec = fmt.Sprintf(`{"model_name":%q,"context_window":1000,"input_cost_per_token":"0.1","output_cost_per_token":"0.2"}`, name)
	}
	return store.CatalogModel{ID: id, Name: display, Spec: []byte(spec), ProviderSpecID: &provider}
}

func specService(sp *fakeSpecs, reg *fakeRegistries) *Service {
	return New(Deps{DB: fakeDB{}, Specs: sp, Registries: reg, Authority: authority(true), Log: slog.New(slog.DiscardHandler)})
}

func TestModelSpecsMergesProjections(t *testing.T) {
	prov := uuid.New()
	own := api.ModelSpec{ID: uuid.New(), ProviderSpecID: prov, ModelName: "mine", DisplayName: "Mine", Kind: KindChat, IsActive: true}
	sp := &fakeSpecs{own: []api.ModelSpec{own}, catalog: []store.CatalogModel{
		priced(uuid.New(), prov, "mine", "Shadowed", true),
		priced(uuid.New(), prov, "zeta", "Zeta", true),
		priced(uuid.New(), prov, "zeta", "Zeta again", true),
		priced(uuid.New(), prov, "free", "Unpriced", false),
		priced(uuid.New(), prov, "alpha", "Alpha", true),
	}}
	got, err := specService(sp, nil).ModelSpecs(context.Background(), ws(t), ModelFilter{})
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, v := range got {
		names = append(names, v.DisplayName)
	}
	if fmt.Sprint(names) != "[Mine Alpha Zeta]" {
		t.Fatalf("names = %v", names)
	}
}

func TestUpdateModelSpecTouchesOnlyOnChange(t *testing.T) {
	prov := uuid.New()
	own := api.ModelSpec{ID: uuid.New(), ProviderSpecID: prov, ModelName: "m", DisplayName: "M", Kind: KindChat, IsActive: true}
	sp := &fakeSpecs{own: []api.ModelSpec{own}}
	s, w := specService(sp, nil), ws(t)
	ctx := context.Background()
	if _, err := s.UpdateModelSpec(ctx, w, own.ID, store.SpecFields{DisplayName: ptr("M")}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.UpdateModelSpec(ctx, w, own.ID, store.SpecFields{DisplayName: ptr("N")}); err != nil {
		t.Fatal(err)
	}
	if fmt.Sprint(sp.updates) != "[false true]" {
		t.Fatalf("touches = %v", sp.updates)
	}
	var nf *NotFoundError
	if _, err := s.UpdateModelSpec(ctx, w, uuid.New(), store.SpecFields{}); !errors.As(err, &nf) || nf.Detail != "Model specification not found" {
		t.Fatalf("err = %v", err)
	}
}

func TestChangedComparesPricesByValue(t *testing.T) {
	a, _ := money.Parse("0.10")
	b, _ := money.Parse("0.1")
	m := api.ModelSpec{InputCostPerToken: &a}
	if changed(m, store.SpecFields{InputCostPerToken: &b}) {
		t.Fatal("0.10 and 0.1 differ")
	}
	c, _ := money.Parse("0.2")
	if !changed(m, store.SpecFields{InputCostPerToken: &c}) {
		t.Fatal("0.1 and 0.2 are equal")
	}
}

func TestCreateModelSpecRefusals(t *testing.T) {
	prov := uuid.New()
	sp := &fakeSpecs{provider: prov, own: []api.ModelSpec{{ID: uuid.New(), ProviderSpecID: prov, ModelName: "m"}}}
	s, w := specService(sp, nil), ws(t)
	n := NewModelSpec{ProviderSpecID: prov, ModelName: "m", Fields: store.SpecFields{DisplayName: ptr("M"), Kind: ptr(KindChat), IsActive: ptr(true)}}
	var ce *ConflictError
	if _, err := s.CreateModelSpec(context.Background(), w, "u", n); !errors.As(err, &ce) ||
		ce.Detail != "Model specification 'm' already exists for this provider" {
		t.Fatalf("err = %v", err)
	}
	sp.createErr = &store.ConstraintError{Code: store.UniqueViolation}
	n.ModelName = "raced"
	if _, err := s.CreateModelSpec(context.Background(), w, "u", n); !errors.As(err, &ce) {
		t.Fatalf("unique violation: err = %v", err)
	}
	var nf *NotFoundError
	for _, call := range []func(NewModelSpec) error{
		func(n NewModelSpec) error { _, err := s.CreateModelSpec(context.Background(), w, "u", n); return err },
		func(n NewModelSpec) error { _, err := s.UpsertModelSpec(context.Background(), w, "u", n); return err },
	} {
		n.ProviderSpecID = uuid.New()
		if err := call(n); !errors.As(err, &nf) || nf.Detail != "Provider specification not found" {
			t.Fatalf("unknown provider: err = %v", err)
		}
	}
}

func TestCatalogProjectionsAreReadOnlyAndNeedTheirProvider(t *testing.T) {
	prov := uuid.New()
	item, orphan := priced(uuid.New(), prov, "cat", "Cat", true), priced(uuid.New(), prov, "orphan", "Orphan", true)
	orphan.ProviderSpecID = nil
	sp := &fakeSpecs{catalog: []store.CatalogModel{item, orphan}}
	s, w := specService(sp, nil), ws(t)
	ctx := context.Background()
	if v, found, err := s.ModelSpec(ctx, w, item.ID); err != nil || !found || v.ProviderSpecID != prov {
		t.Fatalf("projection = %+v %v %v", v, found, err)
	}
	var nf *NotFoundError
	if _, err := s.UpdateModelSpec(ctx, w, item.ID, store.SpecFields{DisplayName: ptr("X")}); !errors.As(err, &nf) || len(sp.updates) != 0 {
		t.Fatalf("patching a projection: %v, updates %v", err, sp.updates)
	}
	if _, found, _ := s.ModelSpec(ctx, w, orphan.ID); found {
		t.Fatal("a projection with no installed provider is found")
	}
	got, err := s.ModelSpecs(ctx, w, ModelFilter{})
	if err != nil || len(got) != 1 || got[0].ID != item.ID {
		t.Fatalf("list = %+v %v", got, err)
	}
}

type applyRegistries struct {
	fakeRegistries
	mirrored []store.MirroredServer
	applied  []string
}

func (f *applyRegistries) UpdateMirroredServer(_ context.Context, _ db.Session, _ string, m store.MirroredServer, _ time.Time) (bool, error) {
	f.mirrored = append(f.mirrored, m)
	return true, nil
}

func (f *applyRegistries) MarkItemApplied(_ context.Context, _ db.Session, id, v string, _ time.Time) error {
	f.applied = append(f.applied, id+"@"+v)
	return nil
}

func (f *applyRegistries) AllItems(_ context.Context, _ db.Session, registryID string) ([]domain.Item, error) {
	var out []domain.Item
	for _, it := range f.items {
		if it.RegistryID == registryID {
			out = append(out, it)
		}
	}
	return out, nil
}

func TestUpdateItemSpec(t *testing.T) {
	ent := "srv"
	st := &applyRegistries{fakeRegistries: fakeRegistries{
		registries: map[string]domain.Registry{
			"mcp": {ID: "mcp", RegistryType: domain.TypeMCPServers, SourceURL: "https://reg"},
			"llm": {ID: "llm", RegistryType: domain.TypeLLMProviders},
		},
		items: map[string]domain.Item{
			"bare":  {ID: "bare", Name: "Bare", RegistryID: "mcp"},
			"fresh": {ID: "fresh", Name: "Fresh", RegistryID: "mcp", InstalledEntityID: &ent},
			"llm":   {ID: "llm", Name: "L", RegistryID: "llm", InstalledEntityID: &ent, UpdateAvailable: true},
			"mcp": {ID: "mcp", Name: "M", RegistryID: "mcp", InstalledEntityID: &ent, UpdateAvailable: true, Version: ptr("2"),
				Spec: []byte(`{"connection_type":"docker","image":"img:1","transport":"stdio","env_vars":[]}`)},
		},
	}}
	s := New(Deps{DB: fakeDB{}, Registries: st, Log: slog.New(slog.DiscardHandler)})
	ctx, w := context.Background(), ws(t)
	for id, want := range map[string]string{
		"gone":  "Registry item gone not found",
		"bare":  "Item Bare has no installed entity",
		"fresh": "Item Fresh is already up to date",
		"llm":   "Provider spec repository not available",
	} {
		if got := valueMsg(t, s.UpdateItemSpec(ctx, w, id)); got != want {
			t.Errorf("%s: %q", id, got)
		}
	}
	if err := s.UpdateItemSpec(ctx, w, "mcp"); err != nil {
		t.Fatal(err)
	}
	m := st.mirrored[0]
	if string(m.Tags) != `["registry", "docker", "stdio"]` || *m.DockerImageURL != "img:1" || m.Version != "2" ||
		string(m.Cmd) != "null" || m.RegistryURL != "https://reg" {
		t.Fatalf("mirrored = %+v tags=%s cmd=%s", m, m.Tags, m.Cmd)
	}
	if fmt.Sprint(st.applied) != "[mcp@2]" {
		t.Fatalf("applied = %v", st.applied)
	}
	updated, failed, err := s.UpdateAllSpecs(ctx, w, "llm")
	if err != nil || updated != 0 || failed != 1 {
		t.Fatalf("update-all = %d %d %v", updated, failed, err)
	}
}

type fakeSecrets struct {
	err  error
	refs []string
}

func (f *fakeSecrets) GetForUse(_ context.Context, id string) (ksecrets.Secret, error) {
	if f.err != nil {
		return ksecrets.Secret{}, f.err
	}
	return ksecrets.Secret{ID: id}, nil
}

func (f *fakeSecrets) AddReference(_ context.Context, secretID, ct, cid, field string) error {
	f.refs = append(f.refs, "+"+secretID+":"+ct+":"+field)
	return nil
}

func (f *fakeSecrets) ClearReferences(_ context.Context, ct, _ string) error {
	f.refs = append(f.refs, "-"+ct)
	return nil
}

type createRegistries struct {
	fakeRegistries
	createErr error
}

func (f *createRegistries) Create(_ context.Context, _ db.Session, n domain.NewRegistry, _ time.Time) (domain.Registry, error) {
	if f.createErr != nil {
		return domain.Registry{}, f.createErr
	}
	return domain.Registry{ID: "r1", Name: n.Name, CredentialsSecretRef: n.CredentialsSecretRef}, nil
}

func TestCreateWorkspaceRegistrySecrets(t *testing.T) {
	sec := &fakeSecrets{}
	st := &createRegistries{}
	s := New(Deps{DB: fakeDB{}, Registries: st, Secrets: func(scope.Workspace, ksecrets.Actor) SecretUse { return sec },
		PublicHTTPS: func(context.Context, string) bool { return true }})
	w := ws(t)
	c := authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: w}
	wid := w.ID()
	n := domain.NewRegistry{Name: "x", RegistryType: "skills", SourceType: "url", SourceURL: "https://x", Scope: "workspace",
		WorkspaceID: &wid, Mode: "mirror", Trust: "private", CredentialsSecretRef: ptr("s1")}
	ctx := context.Background()

	sec.err = &ksecrets.NotFoundError{Message: "Secret s1 not found"}
	var nf *NotFoundError
	if _, err := s.CreateWorkspaceRegistry(ctx, c, n); !errors.As(err, &nf) || nf.Detail != "Secret s1 not found" {
		t.Fatalf("err = %v", err)
	}
	sec.err = ksecrets.ErrManaged
	var fe *ForbiddenError
	if _, err := s.CreateWorkspaceRegistry(ctx, c, n); !errors.As(err, &fe) {
		t.Fatalf("err = %v", err)
	}
	sec.err = nil
	if _, err := s.CreateWorkspaceRegistry(ctx, c, n); err != nil || fmt.Sprint(sec.refs) != "[+s1:registry:credentials]" {
		t.Fatalf("refs = %v, err = %v", sec.refs, err)
	}
	st.createErr = &store.ConstraintError{Code: store.UniqueViolation}
	var ce *ConflictError
	if _, err := s.CreateWorkspaceRegistry(ctx, c, n); !errors.As(err, &ce) || ce.Detail != "This workspace already has a registry named 'x'" {
		t.Fatalf("err = %v", err)
	}
}
