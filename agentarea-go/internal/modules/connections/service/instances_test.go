package service

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

// memSpecs is catalog's MCPSpecs over a map.
type memSpecs struct {
	mu    sync.Mutex
	specs map[string]catalogapi.MCPSpec
}

func (m *memSpecs) Get(_ context.Context, _ scope.Workspace, id string, _ catalogapi.MCPSpecGet) (catalogapi.MCPSpec, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, ok := m.specs[id]
	return s, ok, nil
}

func (m *memSpecs) Create(_ context.Context, tx db.Session, createdBy string, n catalogapi.MCPSpecNew) (catalogapi.MCPSpec, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s := catalogapi.MCPSpec{ID: uuid.NewString(), WorkspaceID: tx.Workspace().ID(), CreatedBy: createdBy, Name: n.Name,
		RemoteURL: n.RemoteURL, DockerImageURL: n.DockerImageURL, Cmd: n.Cmd, EnvSchema: n.EnvSchema, JSONSpec: n.JSONSpec}
	m.specs[s.ID] = s
	return s, nil
}

func (m *memSpecs) MaterializeCopy(ctx context.Context, tx db.Session, createdBy string, src catalogapi.MCPSpec) (catalogapi.MCPSpec, error) {
	return m.Create(ctx, tx, createdBy, catalogapi.MCPSpecNew{Name: src.Name, RemoteURL: src.RemoteURL,
		DockerImageURL: src.DockerImageURL, Cmd: src.Cmd, EnvSchema: src.EnvSchema, JSONSpec: src.JSONSpec})
}

func (m *memSpecs) SetAuthMethods(context.Context, scope.Workspace, string, []any) (bool, error) {
	return false, nil
}

func (m *memSpecs) CatalogJSONSpec(context.Context, scope.Workspace, string) (map[string]any, bool, error) {
	return nil, false, nil
}

func (m *memSpecs) List(_ context.Context, ws scope.Workspace, _ catalogapi.MCPSpecQuery) ([]catalogapi.MCPSpec, int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []catalogapi.MCPSpec
	for _, s := range m.specs {
		if s.WorkspaceID == ws.ID() {
			out = append(out, s)
		}
	}
	return out, len(out), nil
}

func (m *memSpecs) BySlug(_ context.Context, ws scope.Workspace, slug string) (catalogapi.MCPSpec, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, s := range m.specs {
		if s.WorkspaceID == ws.ID() && s.Slug == slug {
			return s, true, nil
		}
	}
	return catalogapi.MCPSpec{}, false, nil
}

func (m *memSpecs) Update(_ context.Context, tx db.Session, sp catalogapi.MCPSpec, _ string) (catalogapi.MCPSpec, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	cur, ok := m.specs[sp.ID]
	if !ok || cur.WorkspaceID != tx.Workspace().ID() {
		return catalogapi.MCPSpec{}, false, nil
	}
	m.specs[sp.ID] = sp
	return sp, true, nil
}

func (m *memSpecs) Delete(_ context.Context, tx db.Session, id string) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	cur, ok := m.specs[id]
	if !ok || cur.WorkspaceID != tx.Workspace().ID() {
		return false, nil
	}
	delete(m.specs, id)
	return true, nil
}

// recGraph records the tuples written.
type recGraph struct {
	mu     sync.Mutex
	writes []authz.Tuple
}

func (g *recGraph) Check(context.Context, string, string, string, string) (bool, error) {
	return true, nil
}
func (g *recGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error) { return nil, nil }
func (g *recGraph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.writes = append(g.writes, writes...)
	return nil
}

type recRuntime struct {
	Runtime
	retired []string
	refuse  error
}

func (r *recRuntime) Gateway() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusServiceUnavailable) })
}

func (r *recRuntime) Retire(_ context.Context, id string) error {
	if r.refuse != nil {
		return r.refuse
	}
	r.retired = append(r.retired, id)
	return nil
}

type guardOut struct{ g *netguard.Guard }

func (o guardOut) Guard() *netguard.Guard { return o.g }

type deny struct{}

func (deny) RoundTrip(r *http.Request) (*http.Response, error) {
	return &http.Response{StatusCode: http.StatusUnauthorized, Header: http.Header{}, Body: http.NoBody, Request: r}, nil
}

func (o guardOut) Transport(netguard.Destination) http.RoundTripper { return deny{} }

func globalExec(t *testing.T, p *db.Pools, sql string, args ...any) {
	t.Helper()
	if err := p.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, sql, args...)
		return err
	}); err != nil {
		t.Fatal(err)
	}
}

// rawSQL runs a test's setup and assertion statements outside any workspace.
type rawSQL struct{ p *db.Pools }

type scanner interface{ Scan(dest ...any) error }

type scanThenRelease struct {
	row  scanner
	done func()
}

func (s scanThenRelease) Scan(dest ...any) error {
	defer s.done()
	return s.row.Scan(dest...)
}

type errRow struct{ err error }

func (r errRow) Scan(...any) error { return r.err }

func (r rawSQL) Exec(ctx context.Context, sql string, args ...any) (struct{}, error) {
	return struct{}{}, r.p.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, sql, args...)
		return err
	})
}

func (r rawSQL) QueryRow(ctx context.Context, sql string, args ...any) scanner {
	q, done, err := r.p.Global().Read(ctx)
	if err != nil {
		return errRow{err}
	}
	return scanThenRelease{row: q.QueryRow(ctx, sql, args...), done: done}
}

type instFixture struct {
	svc     *Service
	pools   *db.Pools
	pool    rawSQL
	specs   *memSpecs
	graph   *recGraph
	runtime *recRuntime
	secrets *memSecrets
	audit   *fakeAudit
	c       authn.Caller
}

func newInstFixture(t *testing.T) *instFixture {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pw, _ := u.User.Password()
	pools, err := db.Open(context.Background(), db.Config{Host: u.Hostname(), Port: port, Name: u.Path[1:], User: u.User.Username(),
		Password: pw, SSLMode: u.Query().Get("sslmode"), PoolSize: 5, PoolOverflow: 5, PoolTimeout: 5 * time.Second, PoolRecycle: time.Hour},
		slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	id := uuid.NewString()
	globalExec(t, pools, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, "ws-"+id[:8])
	ws, err := scope.NewWorkspace(id, "ws-"+id[:8])
	if err != nil {
		t.Fatal(err)
	}
	policy, err := netguard.NewAddressPolicy(true, nil)
	if err != nil {
		t.Fatal(err)
	}
	f := &instFixture{pools: pools, pool: rawSQL{pools}, specs: &memSpecs{specs: map[string]catalogapi.MCPSpec{}}, graph: &recGraph{},
		runtime: &recRuntime{}, secrets: &memSecrets{values: map[string]string{}}, audit: &fakeAudit{},
		c: authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}}
	catalog := &memCatalog{}
	f.svc = New(Deps{DB: pools, Auth: store.Auth{}, Instances: store.Instances{}, Secrets: f.secrets,
		Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return catalog },
		Graph:   f.graph, Specs: f.specs, Runtime: f.runtime, Out: guardOut{&netguard.Guard{Policy: policy}}, Audit: f.audit})
	return f
}

func (f *instFixture) spec(t *testing.T, s catalogapi.MCPSpec) string {
	t.Helper()
	s.ID = uuid.NewString()
	s.WorkspaceID = f.c.Workspace.ID()
	f.specs.specs[s.ID] = s
	return s.ID
}

func (f *instFixture) outbox(t *testing.T, eventType string) int {
	t.Helper()
	var n int
	q, done, err := f.pools.Global().Read(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer done()
	if err := q.QueryRow(context.Background(),
		`SELECT count(*) FROM event_outbox WHERE workspace_id = $1 AND event_type = $2`, f.c.Workspace.ID(), eventType).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func TestCreateCommandInstanceStoresSecretsAndGrants(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"npx", "-y", "fs"},
		EnvSchema: []any{map[string]any{"name": "ROOT", "isSecret": false}}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID,
		JSONSpec: map[string]any{"environment": map[string]any{"ROOT": "/data", "TOKEN": "t0k"}}})
	if err != nil {
		t.Fatal(err)
	}
	i := v.Instance
	if i.Transport != domain.TransportCommand {
		t.Fatalf("transport = %s", i.Transport)
	}
	env := i.JSONSpec["environment"].(map[string]any)
	if _, leaked := env["TOKEN"]; leaked || env["ROOT"] != "/data" {
		t.Fatalf("stored environment = %v", env)
	}
	if f.secrets.values[domain.InstanceSecretName(i.ID, "TOKEN")] != "t0k" {
		t.Fatalf("secret not stored: %v", f.secrets.values)
	}
	masked := domain.MaskedSpec(i.JSONSpec, v.SecretNames)["environment"].(map[string]any)
	if masked["TOKEN"] != domain.MaskedValue {
		t.Fatalf("response not masked: %v", masked)
	}
	if f.outbox(t, EventInstanceCreated) != 1 {
		t.Fatal("created event not in the outbox")
	}
	personal := false
	for _, w := range f.graph.writes {
		if w.Object == authz.ObjectRef(authz.TypeResource, i.ID) && w.Relation == authz.RelPersonal {
			personal = true
		}
	}
	if !personal {
		t.Fatalf("instance not made personal: %v", f.graph.writes)
	}
}

func TestCreateRefusesEgressExitWithoutTheEdition(t *testing.T) {
	f := newInstFixture(t)
	img := "ghcr.io/acme/mcp:1"
	specID := f.spec(t, catalogapi.MCPSpec{Name: "img", DockerImageURL: &img})
	_, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "x", ServerSpecID: specID,
		JSONSpec: map[string]any{domain.EgressExitSpecKey: uuid.NewString()}})
	var si *domain.SpecInvalid
	if !errors.As(err, &si) || si.Errors[0] != domain.EgressExitsUnsupported {
		t.Fatalf("err = %v", err)
	}
	views, err := f.svc.ListInstances(context.Background(), f.c)
	if err != nil {
		t.Fatal(err)
	}
	for _, v := range views {
		if v.Instance.WorkspaceID == f.c.Workspace.ID() {
			t.Fatalf("a refused create left a row: %+v", v.Instance)
		}
	}
}

func TestCreateMissingSpecIsValidationError(t *testing.T) {
	f := newInstFixture(t)
	_, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "x", ServerSpecID: uuid.NewString(), JSONSpec: map[string]any{}})
	var si *domain.SpecInvalid
	if !errors.As(err, &si) || !strings.Contains(si.Errors[0], "was not found") {
		t.Fatalf("err = %v", err)
	}
}

func TestUpdateRetiresBeforeWritingAndKeepsStateWhenRetirementFails(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"npx", "fs"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID, JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(v.Instance.ID)
	f.runtime.refuse = &RuntimeRetirementError{Conflict: true, Msg: "busy"}
	_, err = f.svc.UpdateInstance(ctx, f.c, id, InstancePatchIn{JSONSpec: map[string]any{"environment": map[string]any{"A": "1"}}})
	var rr *RuntimeRetirementError
	if !errors.As(err, &rr) {
		t.Fatalf("err = %v", err)
	}
	got, _ := f.svc.GetInstance(ctx, f.c, id)
	if _, has := got.JSONSpec["environment"]; has || len(f.secrets.values) != 0 {
		t.Fatalf("a failed retirement wrote state: %v %v", got.JSONSpec, f.secrets.values)
	}
	f.runtime.refuse = nil
	name := "renamed"
	v, err = f.svc.UpdateInstance(ctx, f.c, id, InstancePatchIn{Name: &name, JSONSpec: map[string]any{"environment": map[string]any{"A": "1"}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(f.runtime.retired) != 1 || v.Instance.Name != "renamed" || v.Instance.JSONSpec["command"] != nil {
		t.Fatalf("retired=%v instance=%+v", f.runtime.retired, v.Instance)
	}
	if f.secrets.values[domain.InstanceSecretName(v.Instance.ID, "A")] != "1" || f.outbox(t, EventInstanceUpdated) != 1 {
		t.Fatalf("update did not store the secret or the event: %v", f.secrets.values)
	}
}

func TestUpdateRefusesCostOfPlatformConnection(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	id := uuid.New()
	globalExec(t, f.pools, `INSERT INTO mcp_server_instances (id, workspace_id, created_by, name, server_spec_id, transport, json_spec, managed_by)
		VALUES ($1, 'platform-ws', 'p', 'plat', 's', 'url', '{}', 'platform')`, id)
	_, err := f.svc.UpdateInstance(ctx, f.c, id, InstancePatchIn{CostSet: true, Cost: map[string]any{"source": "free"}})
	var si *domain.SpecInvalid
	if !errors.As(err, &si) || si.Errors[0] != "the cost of a platform connection is not set on it" {
		t.Fatalf("err = %v", err)
	}
	if err := f.svc.DeleteInstance(ctx, f.c, id); err == nil || !strings.Contains(err.Error(), "not found") {
		t.Fatalf("a platform instance must not be deletable here: %v", err)
	}
	if len(f.runtime.retired) != 0 {
		t.Fatal("a platform runtime was retired")
	}
}

func TestDeleteRetiresAndRemovesSecretsAndRow(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"npx", "fs"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID,
		JSONSpec: map[string]any{"environment": map[string]any{"TOKEN": "x"}}})
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(v.Instance.ID)
	if err := f.svc.DeleteInstance(ctx, f.c, id); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.GetInstance(ctx, f.c, id); err == nil {
		t.Fatal("row survived")
	}
	if len(f.secrets.values) != 0 || len(f.runtime.retired) != 1 || f.outbox(t, EventInstanceDeleted) != 1 {
		t.Fatalf("secrets=%v retired=%v", f.secrets.values, f.runtime.retired)
	}
}

func TestCreateWithSpecMakesBothAndGrantsTheSpec(t *testing.T) {
	f := newInstFixture(t)
	url := "https://mcp.example.com/mcp"
	v, err := f.svc.CreateInstanceWithSpec(context.Background(), f.c, catalogapi.MCPSpecNew{Name: "remote", RemoteURL: &url},
		InstanceCreate{Name: "remote", JSONSpec: map[string]any{"headers": map[string]any{"Authorization": "Bearer x"}}})
	if err != nil {
		t.Fatal(err)
	}
	if v.Instance.Transport != domain.TransportURL || f.specs.specs[v.Instance.ServerSpecID].Name != "remote" {
		t.Fatalf("instance = %+v", v.Instance)
	}
	granted := map[string]bool{}
	for _, w := range f.graph.writes {
		granted[w.Object] = true
	}
	if !granted[authz.ObjectRef(authz.TypeResource, v.Instance.ServerSpecID)] {
		t.Fatal("the spec created with the instance was not granted")
	}
}

func TestInstanceWritesAreAudited(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	f.c.Credential = &authn.Credential{Kind: authn.KindAPIKey, KeyID: "k1", Surface: authn.SurfaceAPI}
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"npx", "fs"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID, JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(v.Instance.ID)
	name := "renamed"
	if _, err := f.svc.UpdateInstance(ctx, f.c, id, InstancePatchIn{Name: &name}); err != nil {
		t.Fatal(err)
	}
	if err := f.svc.DeleteInstance(ctx, f.c, id); err != nil {
		t.Fatal(err)
	}
	want := []string{"mcp_instance.create", "mcp_instance.update", "mcp_instance.delete"}
	if len(f.audit.rows) != len(want) {
		t.Fatalf("audit rows = %+v", f.audit.rows)
	}
	for i, r := range f.audit.rows {
		if r.Action != want[i] || r.ResourceType != "mcp_instance" || r.ResourceID != v.Instance.ID ||
			r.ActorType != "user" || r.ActorID != "owner" || r.EventID == "" {
			t.Fatalf("row %d = %+v", i, r)
		}
		if r.Metadata["credential"] != "api_key" || r.Metadata["surface"] != "api" || r.Metadata["api_key_id"] != "k1" {
			t.Fatalf("row %d metadata = %v", i, r.Metadata)
		}
	}
}

func TestCreateWithSpecAuditsTheInstanceOnce(t *testing.T) {
	f := newInstFixture(t)
	url := "https://mcp.example.com/mcp"
	v, err := f.svc.CreateInstanceWithSpec(context.Background(), f.c, catalogapi.MCPSpecNew{Name: "remote", RemoteURL: &url},
		InstanceCreate{Name: "remote", JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	if len(f.audit.rows) != 1 || f.audit.rows[0].Action != "mcp_instance.create" || f.audit.rows[0].ResourceID != v.Instance.ID {
		t.Fatalf("audit rows = %+v", f.audit.rows)
	}
}

func TestRefusedInstanceWriteIsNotAudited(t *testing.T) {
	f := newInstFixture(t)
	_, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "x", ServerSpecID: uuid.NewString(), JSONSpec: map[string]any{}})
	if err == nil || len(f.audit.rows) != 0 {
		t.Fatalf("err = %v rows = %+v", err, f.audit.rows)
	}
}

type fakeAgents struct {
	AgentTools
	uses []agentsapi.AgentConnectionUse
}

func (a fakeAgents) MCPConsumers(context.Context, scope.Workspace, string, string) ([]agentsapi.AgentConnectionUse, error) {
	return a.uses, nil
}

type fakeApprovals map[string][]string

func (a fakeApprovals) Targets(context.Context, scope.Workspace, []string) (map[string][]string, error) {
	return a, nil
}

func TestConsumersConfirmToolsFromApprovalRules(t *testing.T) {
	f := newInstFixture(t)
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"npx", "fs"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID, JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	f.svc.d.Agents = fakeAgents{uses: []agentsapi.AgentConnectionUse{
		{AgentID: "a1", AgentName: "One", ServerRef: "fs", EnabledTools: []string{"read", "write"}},
		{AgentID: "a2", AgentName: "Two", ServerRef: v.Instance.ID, EnabledTools: []string{"read"}},
	}}
	f.svc.d.Approvals = fakeApprovals{"a1": {"tool:mcp:fs:write"}, "a2": {"tool:read"}}
	got, err := f.svc.Consumers(ctx, f.c, uuid.MustParse(v.Instance.ID))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || !reflect.DeepEqual(got[0].ConfirmTools, []string{"write"}) || !reflect.DeepEqual(got[1].ConfirmTools, []string{"read"}) {
		t.Fatalf("consumers = %+v", got)
	}
}

func TestCreateKeepsContextBlock(t *testing.T) {
	f := newInstFixture(t)
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"npx", "fs"}})
	v, err := f.svc.CreateInstance(context.Background(), f.c, InstanceCreate{Name: "fs", ServerSpecID: specID,
		JSONSpec: map[string]any{domain.ContextSpecKey: map[string]any{"enabled": true}}})
	if err != nil {
		t.Fatal(err)
	}
	got, err := f.svc.GetInstance(context.Background(), f.c, uuid.MustParse(v.Instance.ID))
	if err != nil || !reflect.DeepEqual(got.JSONSpec[domain.ContextSpecKey], map[string]any{"enabled": true}) {
		t.Fatalf("stored spec %v (%v)", got.JSONSpec, err)
	}
}
