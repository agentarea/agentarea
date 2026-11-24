package service

import (
	"context"
	"net"
	"net/http"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type fakeStore struct {
	configs   map[string]domain.Config
	instances map[string]domain.Instance
	locks     int
}

func visible(ws, owner string, managed *string) bool {
	return owner == ws || (managed != nil && *managed == domain.ManagedByPlatform)
}

func (f *fakeStore) Config(_ context.Context, s db.Session, id uuid.UUID) (domain.Config, bool, error) {
	c, ok := f.configs[id.String()]
	if !ok || !visible(s.Workspace().ID(), c.WorkspaceID, c.ManagedBy) {
		return domain.Config{}, false, nil
	}
	return c, true, nil
}

func (f *fakeStore) Configs(_ context.Context, s db.Session, _ store.ConfigFilter) ([]domain.Config, error) {
	out := []domain.Config{}
	for _, c := range f.configs {
		if visible(s.Workspace().ID(), c.WorkspaceID, c.ManagedBy) {
			out = append(out, c)
		}
	}
	return out, nil
}

func (f *fakeStore) InstanceSpecIDs(_ context.Context, _ db.Session, ids []uuid.UUID) (map[string][]string, error) {
	out := map[string][]string{}
	for _, in := range f.instances {
		if slices.Contains(ids, uuid.MustParse(in.ProviderConfigID)) {
			out[in.ProviderConfigID] = append(out[in.ProviderConfigID], in.ModelSpecID)
		}
	}
	return out, nil
}

func (f *fakeStore) InsertConfig(_ context.Context, s db.Session, c domain.Config, now time.Time) error {
	c.WorkspaceID, c.CreatedAt, c.UpdatedAt = s.Workspace().ID(), now, now
	f.configs[c.ID] = c
	return nil
}

func (f *fakeStore) UpdateConfig(_ context.Context, s db.Session, c domain.Config, now time.Time) (bool, error) {
	old, ok := f.configs[c.ID]
	if !ok || old.WorkspaceID != s.Workspace().ID() {
		return false, nil
	}
	c.UpdatedAt = now
	f.configs[c.ID] = c
	return true, nil
}

func (f *fakeStore) DeleteConfig(_ context.Context, s db.Session, id uuid.UUID) (bool, error) {
	c, ok := f.configs[id.String()]
	if !ok || c.WorkspaceID != s.Workspace().ID() {
		return false, nil
	}
	delete(f.configs, id.String())
	return true, nil
}

func (f *fakeStore) LockConfig(_ context.Context, s db.Session, id uuid.UUID) (bool, error) {
	c, ok := f.configs[id.String()]
	f.locks++
	return ok && c.WorkspaceID == s.Workspace().ID(), nil
}

func (f *fakeStore) ProviderSpecIDsWithVisibleConfigs(context.Context, db.Session) ([]uuid.UUID, error) {
	return nil, nil
}

func (f *fakeStore) Instance(_ context.Context, s db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	in, ok := f.instances[id.String()]
	if !ok || in.WorkspaceID != s.Workspace().ID() {
		return domain.Instance{}, false, nil
	}
	return in, true, nil
}

func (f *fakeStore) Instances(_ context.Context, s db.Session, flt store.InstanceFilter) ([]domain.Instance, error) {
	out := []domain.Instance{}
	for _, in := range f.instances {
		if in.WorkspaceID == s.Workspace().ID() && (!flt.ByIDs || slices.Contains(flt.IDs, uuid.MustParse(in.ID))) {
			out = append(out, in)
		}
	}
	return out, nil
}

func (f *fakeStore) VisibleInstanceSpecs(_ context.Context, s db.Session) (map[uuid.UUID]uuid.UUID, error) {
	out := map[uuid.UUID]uuid.UUID{}
	for _, in := range f.instances {
		if in.WorkspaceID == s.Workspace().ID() {
			out[uuid.MustParse(in.ID)] = uuid.MustParse(in.ModelSpecID)
		}
	}
	return out, nil
}

func (f *fakeStore) ConfigsOfInstances(_ context.Context, _ db.Session, ids []uuid.UUID) (map[string]domain.Config, error) {
	out := map[string]domain.Config{}
	for _, id := range ids {
		if c, ok := f.configs[id.String()]; ok {
			out[c.ID] = c
		}
	}
	return out, nil
}

func (f *fakeStore) InsertInstance(_ context.Context, s db.Session, in domain.Instance, now time.Time) error {
	in.WorkspaceID, in.CreatedAt, in.UpdatedAt, in.Tags = s.Workspace().ID(), now, now, []string{}
	f.instances[in.ID] = in
	return nil
}

func (f *fakeStore) DeleteInstance(_ context.Context, s db.Session, id uuid.UUID) (bool, error) {
	in, ok := f.instances[id.String()]
	if !ok || in.WorkspaceID != s.Workspace().ID() {
		return false, nil
	}
	delete(f.instances, id.String())
	return true, nil
}

type fakeCatalog struct {
	catalogapi.Specs
	providers map[uuid.UUID]catalogapi.ProviderSpec
	models    map[uuid.UUID]catalogapi.ModelSpec
	upserted  []catalogapi.DiscoveredSpec
}

func (f *fakeCatalog) ProviderSpec(_ context.Context, _ scope.Workspace, id uuid.UUID) (catalogapi.ProviderSpec, bool, error) {
	p, ok := f.providers[id]
	return p, ok, nil
}

func (f *fakeCatalog) ProviderSpecByKey(_ context.Context, _ scope.Workspace, key string) (catalogapi.ProviderSpec, bool, error) {
	for _, p := range f.providers {
		if p.ProviderKey == key {
			return p, true, nil
		}
	}
	return catalogapi.ProviderSpec{}, false, nil
}

func (f *fakeCatalog) ProviderSpecs(_ context.Context, _ scope.Workspace, ids []uuid.UUID) (map[uuid.UUID]catalogapi.ProviderSpec, error) {
	out := map[uuid.UUID]catalogapi.ProviderSpec{}
	for _, id := range ids {
		if p, ok := f.providers[id]; ok {
			out[id] = p
		}
	}
	return out, nil
}

func (f *fakeCatalog) ModelSpecs(_ context.Context, _ scope.Workspace, ids []uuid.UUID) (map[uuid.UUID]catalogapi.ModelSpec, error) {
	out := map[uuid.UUID]catalogapi.ModelSpec{}
	for _, id := range ids {
		if m, ok := f.models[id]; ok {
			out[id] = m
		}
	}
	return out, nil
}

func (f *fakeCatalog) UsableModelSpec(_ context.Context, ws scope.Workspace, id uuid.UUID) (catalogapi.ModelSpec, bool, error) {
	m, ok := f.models[id]
	if !ok || (m.WorkspaceID != ws.ID() && m.WorkspaceID != PlatformWorkspaceID) {
		return catalogapi.ModelSpec{}, false, nil
	}
	return m, true, nil
}

func (f *fakeCatalog) CopyCatalogModelSpec(context.Context, scope.Workspace, string, uuid.UUID) (catalogapi.ModelSpec, bool, error) {
	return catalogapi.ModelSpec{}, false, nil
}

func (f *fakeCatalog) UpsertModelSpecs(_ context.Context, _ scope.Workspace, _ string, _ uuid.UUID, rows []catalogapi.DiscoveredSpec) (map[string]catalogapi.Upserted, error) {
	f.upserted = append(f.upserted, rows...)
	out := map[string]catalogapi.Upserted{}
	for i, r := range rows {
		out[r.ModelName] = catalogapi.Upserted{ID: uuid.New(), IsNew: i == 0}
	}
	return out, nil
}

type secretRow struct {
	ws, name, value string
	id              string
	ownerType       *string
}

type fakeSecrets struct {
	rows []*secretRow
	refs map[string][]ksecrets.Reference
	gets []string
}

type fakeManager struct {
	f  *fakeSecrets
	ws string
}

func (m fakeManager) Get(_ context.Context, name string) (string, error) {
	m.f.gets = append(m.f.gets, m.ws+"/"+name)
	for _, r := range m.f.rows {
		if r.ws == m.ws && r.name == name {
			return r.value, nil
		}
	}
	return "", ksecrets.ErrNotFound
}

func (m fakeManager) Set(_ context.Context, name, value string) error {
	for _, r := range m.f.rows {
		if r.ws == m.ws && r.name == name {
			r.value = value
			return nil
		}
	}
	m.f.rows = append(m.f.rows, &secretRow{ws: m.ws, name: name, value: value, id: uuid.NewString()})
	return nil
}

func (m fakeManager) Delete(_ context.Context, name string) (bool, error) {
	for i, r := range m.f.rows {
		if r.ws == m.ws && r.name == name {
			m.f.rows = slices.Delete(m.f.rows, i, i+1)
			return true, nil
		}
	}
	return false, nil
}

func (m fakeManager) Has(context.Context, string) (bool, error) { return false, nil }
func (m fakeManager) ExternalRef(string) (string, bool)         { return "", false }

func (f *fakeSecrets) Manager(s db.Session, _ string) ksecrets.Manager {
	return fakeManager{f: f, ws: s.Workspace().ID()}
}

func (f *fakeSecrets) find(ws string, match func(*secretRow) bool) (ksecrets.Secret, bool, error) {
	for _, r := range f.rows {
		if r.ws == ws && match(r) {
			return ksecrets.Secret{ID: r.id, Name: r.name, OwnerType: r.ownerType}, true, nil
		}
	}
	return ksecrets.Secret{}, false, nil
}

func (f *fakeSecrets) Secret(_ context.Context, s db.Session, id string) (ksecrets.Secret, bool, error) {
	return f.find(s.Workspace().ID(), func(r *secretRow) bool { return r.id == id })
}

func (f *fakeSecrets) SecretNamed(_ context.Context, s db.Session, name string) (ksecrets.Secret, bool, error) {
	return f.find(s.Workspace().ID(), func(r *secretRow) bool { return r.name == name })
}

func (f *fakeSecrets) StageReferences(_ context.Context, _ db.Session, _, consumerID string, refs []ksecrets.Reference) error {
	f.refs[consumerID] = refs
	return nil
}

type fakeOut struct{ guard *netguard.Guard }

func (fakeOut) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (fakeOut) Dialer() netguard.Dialer                          { return nil }
func (o fakeOut) Guard() *netguard.Guard                         { return o.guard }

type env struct {
	svc     *Service
	st      *fakeStore
	cat     *fakeCatalog
	sec     *fakeSecrets
	ws      scope.Workspace
	other   scope.Workspace
	prov    catalogapi.ProviderSpec
	chat    catalogapi.ModelSpec
	admin   error
	ctx     context.Context
	otherCx context.Context
}

func newEnv(t *testing.T) *env {
	t.Helper()
	ws, _ := scope.NewWorkspace(uuid.NewString(), "a")
	other, _ := scope.NewWorkspace(uuid.NewString(), "b")
	policy, err := netguard.NewAddressPolicy(false, nil)
	if err != nil {
		t.Fatal(err)
	}
	cw := 1000
	prov := catalogapi.ProviderSpec{ID: uuid.New(), ProviderKey: "openai", ProviderType: "openai", Name: "OpenAI",
		RequiresAPIKey: true, Transport: domain.TransportOpenAI, Auth: domain.AuthBearer, ListShape: domain.ListDataID,
		ReasoningParam: domain.ReasoningEffortParam, Icon: ptr("openai")}
	chat := catalogapi.ModelSpec{ID: uuid.New(), ProviderSpecID: prov.ID, WorkspaceID: PlatformWorkspaceID,
		ModelName: "gpt-x", DisplayName: "GPT X", Kind: "chat", ContextWindow: &cw}
	e := &env{
		st:  &fakeStore{configs: map[string]domain.Config{}, instances: map[string]domain.Instance{}},
		cat: &fakeCatalog{providers: map[uuid.UUID]catalogapi.ProviderSpec{prov.ID: prov}, models: map[uuid.UUID]catalogapi.ModelSpec{chat.ID: chat}},
		sec: &fakeSecrets{refs: map[string][]ksecrets.Reference{}}, ws: ws, other: other, prov: prov, chat: chat,
	}
	e.svc = New(Deps{
		DB: fakeDB{}, Store: e.st, Catalog: e.cat, Secrets: e.sec,
		Out:   fakeOut{guard: &netguard.Guard{Policy: policy, Resolver: net.DefaultResolver}},
		Admin: func(context.Context) error { return e.admin }, APIURL: "http://api.test/", LocalHost: "localhost",
		Now: func() time.Time { return time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC) },
	})
	e.ctx = authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws})
	e.otherCx = authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{UserID: "u2"}, Workspace: other})
	return e
}
