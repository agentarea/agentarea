package service

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// writesStore is openapi_connections for reads and writes.
type writesStore struct {
	rows      map[uuid.UUID]domain.Connection
	dispatch  map[uuid.UUID]map[string]any
	insertErr error
}

func (m *writesStore) List(context.Context, db.Session, ConnectionFilter, int32, int32) ([]domain.Connection, error) {
	var out []domain.Connection
	for _, c := range m.rows {
		out = append(out, c)
	}
	return out, nil
}
func (m *writesStore) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	c, ok := m.rows[id]
	return c, ok, nil
}
func (m *writesStore) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	_, ok := m.rows[id]
	delete(m.rows, id)
	return ok, nil
}
func (m *writesStore) Full(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	return m.Get(ctx, s, id)
}
func (m *writesStore) Lock(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	return m.Get(ctx, s, id)
}

func writesTools(raw json.RawMessage) []domain.Tool {
	var ts []struct {
		Name        string         `json:"name"`
		Description string         `json:"description"`
		InputSchema map[string]any `json:"inputSchema"`
	}
	if err := json.Unmarshal(raw, &ts); err != nil {
		panic(err)
	}
	out := make([]domain.Tool, len(ts))
	for i, t := range ts {
		out[i] = domain.Tool{Name: t.Name, Description: t.Description, InputSchema: t.InputSchema}
	}
	return out
}

func writesSpec(raw json.RawMessage) any {
	if raw == nil {
		return nil
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		panic(err)
	}
	return v
}

func (m *writesStore) Insert(_ context.Context, _ db.Session, n store.ConnectionNew) (domain.Connection, error) {
	if m.insertErr != nil {
		return domain.Connection{}, m.insertErr
	}
	c := domain.Connection{
		ID: n.ID.String(), CreatedBy: n.CreatedBy, Name: n.Name, Description: n.Description, SpecURL: n.SpecURL,
		BaseURL: n.BaseURL, CustomHeaders: n.CustomHeaders, CustomQuery: n.CustomQuery, URLVariables: n.URLVariables,
		AvailableTools: writesTools(n.AvailableTools), Status: n.Status, CreatedAt: n.Now, UpdatedAt: n.Now,
		SpecContent: writesSpec(n.SpecContent), AllowedAuthOrigins: n.AllowedAuthOrigins,
	}
	if n.AuthConfigID != nil {
		s := n.AuthConfigID.String()
		c.AuthConfigID = &s
	}
	m.rows[n.ID] = c
	return c, nil
}
func (m *writesStore) Save(_ context.Context, _ db.Session, id uuid.UUID, r store.ConnectionRow) (bool, error) {
	c, ok := m.rows[id]
	if !ok {
		return false, nil
	}
	c.Name, c.Description, c.SpecURL, c.BaseURL = r.Name, r.Description, r.SpecURL, r.BaseURL
	c.CustomHeaders, c.CustomQuery, c.URLVariables, c.Cost = r.CustomHeaders, r.CustomQuery, r.URLVariables, r.Cost
	c.AvailableTools, c.SpecContent, c.UpdatedAt = writesTools(r.AvailableTools), writesSpec(r.SpecContent), r.Now
	c.AuthConfigID = nil
	if r.AuthConfigID != nil {
		s := r.AuthConfigID.String()
		c.AuthConfigID = &s
	}
	m.rows[id] = c
	return true, nil
}
func (m *writesStore) SetDiscovery(_ context.Context, _ db.Session, id uuid.UUID, tools, spec json.RawMessage, now time.Time) (bool, error) {
	c, ok := m.rows[id]
	if !ok {
		return false, nil
	}
	c.AvailableTools, c.SpecContent, c.UpdatedAt = writesTools(tools), writesSpec(spec), now
	m.rows[id] = c
	return true, nil
}
func (m *writesStore) SetLastDispatch(_ context.Context, _ db.Session, id uuid.UUID, d map[string]any) (bool, error) {
	m.dispatch[id] = d
	return true, nil
}

// writesGraph answers personal tuples it was written; writeErr fails writes.
type writesGraph struct {
	personal map[string]bool
	owners   map[string]bool
	// allowed holds the subject#resource checks that pass.
	allowed  map[string]bool
	writeErr error
}

func (g *writesGraph) Check(_ context.Context, subject, _, _, id string) (bool, error) {
	return g.allowed[subject+"#"+id], nil
}
func (g *writesGraph) Read(_ context.Context, q authz.Query) ([]authz.Tuple, error) {
	if g.personal[q.ID] {
		return []authz.Tuple{{User: authz.EveryUser, Relation: authz.RelPersonal, Object: "resource:" + q.ID}}, nil
	}
	return nil, nil
}
func (g *writesGraph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	if g.writeErr != nil {
		return g.writeErr
	}
	for _, t := range writes {
		id := strings.TrimPrefix(t.Object, "resource:")
		if t.Relation == authz.RelPersonal {
			g.personal[id] = true
		} else {
			g.owners[id] = true
		}
	}
	return nil
}

// writesOut admits every address and dials directly.
type writesOut struct{ guard *netguard.Guard }

func (o writesOut) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (o writesOut) Guard() *netguard.Guard                           { return o.guard }

func newWritesOut(t *testing.T, allowPrivate bool) writesOut {
	t.Helper()
	p, err := netguard.NewAddressPolicy(allowPrivate, nil)
	if err != nil {
		t.Fatal(err)
	}
	return writesOut{guard: &netguard.Guard{Policy: p}}
}

// writesPolicies is governance's tool policy read: one effective policy.
type writesPolicies struct{ effective governanceapi.Policy }

func (p writesPolicies) Workspace(context.Context, authn.Caller) ([]governanceapi.WorkspaceRule, governanceapi.Policy, error) {
	return nil, p.effective, nil
}
func (p writesPolicies) Effective(context.Context, scope.Workspace, string) (governanceapi.Policy, error) {
	return p.effective, nil
}

type writesFixture struct {
	svc     *Service
	conns   *writesStore
	secrets *memSecrets
	graph   *writesGraph
	ws      scope.Workspace
	caller  authn.Caller
}

func newWritesFixture(t *testing.T, allowPrivate bool, policy governanceapi.Policy) *writesFixture {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	f := &writesFixture{
		conns:   &writesStore{rows: map[uuid.UUID]domain.Connection{}, dispatch: map[uuid.UUID]map[string]any{}},
		secrets: &memSecrets{values: map[string]string{}},
		graph:   &writesGraph{personal: map[string]bool{}, owners: map[string]bool{}, allowed: map[string]bool{}},
		ws:      ws,
		caller:  authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws},
	}
	f.svc = New(Deps{
		DB: memDB{}, Auth: &memAuth{rows: map[uuid.UUID]domain.AuthConfig{}}, Connections: f.conns, OpenAPIWrites: f.conns,
		Secrets: f.secrets, Graph: f.graph, Out: newWritesOut(t, allowPrivate), Policies: writesPolicies{policy},
		Now: func() time.Time { return time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC) },
	})
	return f
}

const writesPetSpec = `{"openapi":"3.0.0","info":{"title":"Pets","version":"1"},"paths":{
"/pets/{id}":{"get":{"operationId":"getPet","summary":"Get a pet","parameters":[{"name":"id","in":"path","required":true,"schema":{"type":"string"}}]}},
"/pets":{"get":{"operationId":"listPets","summary":"List pets"}}}}`

func writesSpecOf(t *testing.T, raw string) any {
	t.Helper()
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestCreateConnectionStoresSecretsAndOwnsIt(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	ctx := context.Background()
	v, err := f.svc.CreateConnection(ctx, f.caller, ConnectionCreate{
		Name: "pets", BaseURL: "https://api.example.com/{tenant}", SpecContent: writesSpecOf(t, writesPetSpec),
		Headers:      []HeaderIn{{Name: "Authorization", Value: "Bearer k"}, {Name: "Accept", Value: "application/json"}, {Name: "X-Empty"}},
		Query:        []QueryIn{{Name: "key", Secret: true, Value: "q"}, {Name: "fmt", Value: "json"}},
		URLVariables: []VarIn{{Name: "tenant", Value: "acme"}},
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	id := v.Connection.ID
	if !v.Sharing.Personal || !v.Sharing.IsOwner || !f.graph.personal[id] || !f.graph.owners[id] {
		t.Fatalf("sharing = %+v, graph = %+v", v.Sharing, f.graph)
	}
	want := map[string]string{
		domain.SecretHeaderKey(id, "Authorization"): "Bearer k",
		domain.SecretQueryKey(id, "key"):            "q",
		domain.SecretURLVarKey(id, "tenant"):        "acme",
	}
	if len(f.secrets.values) != len(want) {
		t.Fatalf("secrets = %v", f.secrets.values)
	}
	for k, val := range want {
		if f.secrets.values[k] != val {
			t.Fatalf("secret %s = %q", k, f.secrets.values[k])
		}
	}
	hs := v.Connection.CustomHeaders
	if len(hs) != 2 || !hs[0].Secret || hs[0].Value != nil || hs[1].Secret || *hs[1].Value != "application/json" {
		t.Fatalf("headers = %+v", hs)
	}
	if names := []string{v.Connection.AvailableTools[0].Name, v.Connection.AvailableTools[1].Name}; names[0] != "getPet" || names[1] != "listPets" {
		t.Fatalf("tools = %v", names)
	}
}

// The Python create stored the secrets before the row: a failure after them
// left values no connection names.
func TestCreateConnectionFailureLeavesNoSecrets(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	f.graph.writeErr = errors.New("graph down")
	_, err := f.svc.CreateConnection(context.Background(), f.caller, ConnectionCreate{
		Name: "pets", BaseURL: "https://api.example.com", Headers: []HeaderIn{{Name: "Authorization", Value: "k"}},
	}, nil)
	if err == nil || len(f.secrets.values) != 0 {
		t.Fatalf("err = %v, secrets = %v", err, f.secrets.values)
	}
}

func TestCreateConnectionRefusesBeforeWriting(t *testing.T) {
	f := newWritesFixture(t, false, governanceapi.Policy{})
	ctx := context.Background()
	cases := []struct {
		in   ConnectionCreate
		want string
	}{
		{ConnectionCreate{Name: "a", BaseURL: "http://127.0.0.1/"}, "127.0.0.1"},
		{ConnectionCreate{Name: "a", BaseURL: "https://8.8.8.8/", Query: []QueryIn{{Name: "k", Secret: true}}}, "Secret query parameter 'k' needs a value."},
		{ConnectionCreate{Name: "a", BaseURL: "https://{x}.example.com"}, "only allowed in the base URL path"},
	}
	for _, c := range cases {
		_, err := f.svc.CreateConnection(ctx, f.caller, c.in, nil)
		var inv *domain.Invalid
		if !errors.As(err, &inv) || !strings.Contains(inv.Msg, c.want) {
			t.Fatalf("%+v: err = %v", c.in, err)
		}
	}
	if len(f.conns.rows) != 0 || len(f.secrets.values) != 0 {
		t.Fatal("a refused create wrote")
	}
}

func seedWritesConnection(t *testing.T, f *writesFixture) uuid.UUID {
	t.Helper()
	v, err := f.svc.CreateConnection(context.Background(), f.caller, ConnectionCreate{
		Name: "pets", BaseURL: "https://api.example.com", SpecContent: writesSpecOf(t, writesPetSpec),
		Headers: []HeaderIn{{Name: "Authorization", Value: "old"}},
		Query:   []QueryIn{{Name: "key", Secret: true, Value: "q"}},
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	return uuid.MustParse(v.Connection.ID)
}

// The Python update stored the query secrets and deleted and rewrote the
// header secrets before it refused a later field with a 400.
func TestUpdateConnectionRefusalWritesNothing(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	id := seedWritesConnection(t, f)
	before := map[string]string{}
	for k, v := range f.secrets.values {
		before[k] = v
	}
	row := f.conns.rows[id]
	_, err := f.svc.UpdateConnection(context.Background(), f.caller, id, ConnectionPatch{
		HeadersSet: true, Headers: []HeaderIn{{Name: "Authorization", Value: "new"}},
		QuerySet: true, Query: []QueryIn{{Name: "other", Secret: true}},
	})
	var inv *domain.Invalid
	if !errors.As(err, &inv) || inv.Msg != "Secret query parameter 'other' needs a value." {
		t.Fatalf("err = %v", err)
	}
	if len(f.secrets.values) != len(before) {
		t.Fatalf("secrets = %v", f.secrets.values)
	}
	for k, v := range before {
		if f.secrets.values[k] != v {
			t.Fatalf("secret %s changed to %q", k, f.secrets.values[k])
		}
	}
	if f.conns.rows[id].CustomHeaders[0].Name != row.CustomHeaders[0].Name {
		t.Fatal("row changed")
	}
}

func TestUpdateConnectionReplacesSecrets(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	id := seedWritesConnection(t, f)
	s := id.String()
	v, err := f.svc.UpdateConnection(context.Background(), f.caller, id, ConnectionPatch{
		HeadersSet: true, Headers: []HeaderIn{{Name: "X-Key", Value: "new"}},
		QuerySet: true, Query: []QueryIn{{Name: "key", Secret: true}, {Name: "plain", Value: "p"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := f.secrets.values[domain.SecretHeaderKey(s, "Authorization")]; ok {
		t.Fatal("old header secret kept")
	}
	if f.secrets.values[domain.SecretHeaderKey(s, "X-Key")] != "new" || f.secrets.values[domain.SecretQueryKey(s, "key")] != "q" {
		t.Fatalf("secrets = %v", f.secrets.values)
	}
	if q := v.Connection.CustomQuery; len(q) != 2 || *q[1].Value != "p" {
		t.Fatalf("query = %+v", q)
	}
}

func TestUpdateConnectionSpecRederivesTools(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	id := seedWritesConnection(t, f)
	v, err := f.svc.UpdateConnection(context.Background(), f.caller, id, ConnectionPatch{
		SpecContentSet: true,
		SpecContent:    writesSpecOf(t, `{"openapi":"3.0.0","paths":{"/a":{"post":{"operationId":"makeA"}}}}`),
	})
	if err != nil {
		t.Fatal(err)
	}
	if ts := v.Connection.AvailableTools; len(ts) != 1 || ts[0].Name != "makeA" {
		t.Fatalf("tools = %+v", ts)
	}
}

func TestPreviewSpec(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	p, err := f.svc.PreviewSpec(context.Background(), nil, writesSpecOf(t, writesPetSpec))
	if err != nil {
		t.Fatal(err)
	}
	if p.Info.Title == nil || *p.Info.Title != "Pets" || len(p.Tools) != 2 {
		t.Fatalf("preview = %+v", p)
	}
	_, err = f.svc.PreviewSpec(context.Background(), nil, wirejson.Object{})
	var inv *domain.Invalid
	if !errors.As(err, &inv) || inv.Msg != "Provide spec_url or spec_content" {
		t.Fatalf("err = %v", err)
	}
}

func TestDiscoverToolsFetchesWithHeaders(t *testing.T) {
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		_, _ = io.WriteString(w, writesPetSpec)
	}))
	defer srv.Close()
	f := newWritesFixture(t, true, governanceapi.Policy{})
	u := srv.URL + "/openapi.json"
	v, err := f.svc.CreateConnection(context.Background(), f.caller, ConnectionCreate{
		Name: "pets", BaseURL: srv.URL, SpecURL: &u, Headers: []HeaderIn{{Name: "Authorization", Value: "Bearer k"}},
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(v.Connection.ID)
	c := f.conns.rows[id]
	c.SpecContent = nil
	f.conns.rows[id] = c
	d, err := f.svc.DiscoverTools(context.Background(), f.caller, id)
	if err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer k" || len(d.Tools) != 2 || len(f.conns.rows[id].AvailableTools) != 2 {
		t.Fatalf("auth = %q, discovery = %+v", auth, d)
	}
	_, err = f.svc.DiscoverTools(context.Background(), f.caller, uuid.New())
	var inv *domain.Invalid
	if !errors.As(err, &inv) || !strings.HasSuffix(inv.Msg, " not found") {
		t.Fatalf("err = %v", err)
	}
}

func TestCallOpenAPIResolvesCredentialsAndRecordsDispatch(t *testing.T) {
	var got *http.Request
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"7","name":"Rex"}`)
	}))
	defer srv.Close()
	f := newWritesFixture(t, true, governanceapi.Policy{})
	v, err := f.svc.CreateConnection(context.Background(), f.caller, ConnectionCreate{
		Name: "pets", BaseURL: srv.URL, SpecContent: writesSpecOf(t, writesPetSpec),
		Headers: []HeaderIn{{Name: "Authorization", Value: "Bearer k"}},
		Query:   []QueryIn{{Name: "key", Secret: true, Value: "q"}},
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	f.graph.allowed["Agent:a1#"+v.Connection.ID] = true
	res := f.svc.CallOpenAPI(context.Background(), f.ws, api.OpenAPICall{
		UserID: "owner", AgentID: "a1", ConnectionID: v.Connection.ID, Operation: "getPet", Args: map[string]any{"id": "a b"},
	})
	if !res.Success || res.Result != `{"id": "7", "name": "Rex"}` || res.ToolName != "getPet" {
		t.Fatalf("result = %+v", res)
	}
	if got.URL.EscapedPath() != "/pets/a%20b" || got.URL.Query().Get("key") != "q" || got.Header.Get("Authorization") != "Bearer k" {
		t.Fatalf("request = %s %v", got.URL, got.Header)
	}
	d := f.conns.dispatch[uuid.MustParse(v.Connection.ID)]
	if d["status"] != "succeeded" || d["at"] != "2026-11-12T10:00:00+00:00" || d["error"] != nil {
		t.Fatalf("dispatch = %v", d)
	}

	delete(f.secrets.values, domain.SecretQueryKey(v.Connection.ID, "key"))
	res = f.svc.CallOpenAPI(context.Background(), f.ws, api.OpenAPICall{UserID: "owner", AgentID: "a1", ConnectionID: v.Connection.ID, Operation: "listPets"})
	if res.Success || !strings.HasPrefix(res.Error, "Failed to resolve query parameters: Connection ") {
		t.Fatalf("result = %+v", res)
	}
}

func TestCallOpenAPIRefusesBlockedBaseURL(t *testing.T) {
	f := newWritesFixture(t, false, governanceapi.Policy{})
	id := uuid.New()
	f.conns.rows[id] = domain.Connection{ID: id.String(), Name: "x", BaseURL: "http://127.0.0.1:1", SpecContent: writesSpecOf(t, writesPetSpec)}
	f.graph.allowed["Agent:a1#"+id.String()] = true
	res := f.svc.CallOpenAPI(context.Background(), f.ws, api.OpenAPICall{AgentID: "a1", ConnectionID: id.String(), Operation: "listPets"})
	if res.Success || !strings.HasPrefix(res.Error, "SSRF validation failed: ") {
		t.Fatalf("result = %+v", res)
	}
}

// Python's run-time OpenAPI call trusted the binding and never checked the
// connection again, so a run could call through someone's personal
// connection (with their credentials) that was never lent to its agent.
func TestCallOpenAPIRechecksTheAgentMayUseTheConnection(t *testing.T) {
	hits := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		hits++
		_, _ = io.WriteString(w, `[]`)
	}))
	defer srv.Close()
	f := newWritesFixture(t, true, governanceapi.Policy{})
	id := uuid.New()
	f.conns.rows[id] = domain.Connection{ID: id.String(), Name: "x", BaseURL: srv.URL, SpecContent: writesSpecOf(t, writesPetSpec)}
	for _, agent := range []string{"", "a1"} {
		res := f.svc.CallOpenAPI(context.Background(), f.ws, api.OpenAPICall{UserID: "owner", AgentID: agent, ConnectionID: id.String(), Operation: "listPets"})
		if res.Success || !strings.Contains(res.Error, "may not call through connection") || hits != 0 {
			t.Fatalf("agent %q: result = %+v, hits %d", agent, res, hits)
		}
	}
	f.graph.allowed["Agent:a1#"+id.String()] = true
	if res := f.svc.CallOpenAPI(context.Background(), f.ws, api.OpenAPICall{UserID: "owner", AgentID: "a1", ConnectionID: id.String(), Operation: "listPets"}); !res.Success || hits != 1 {
		t.Fatalf("lent: result = %+v, hits %d", res, hits)
	}
	managed := domain.ManagedByPlatform
	other := uuid.New()
	f.conns.rows[other] = domain.Connection{ID: other.String(), Name: "p", BaseURL: srv.URL, ManagedBy: &managed, SpecContent: writesSpecOf(t, writesPetSpec)}
	if res := f.svc.CallOpenAPI(context.Background(), f.ws, api.OpenAPICall{AgentID: "a2", ConnectionID: other.String(), Operation: "listPets"}); !res.Success {
		t.Fatalf("platform connection: %+v", res)
	}
}

// A run calls with its starter's user id: matching only that let an agent put
// its starter's credentials on a connection it then owned and called through.
func TestAnAgentUsesOnlyAnAuthConfigLentToIt(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	cfg := uuid.New()
	f.svc.d.Auth.(*memAuth).rows[cfg] = domain.AuthConfig{ID: cfg.String(), CreatedBy: "owner", AuthType: "api_key"}
	agent := f.caller
	agent.Subject = &authn.Subject{Kind: authn.SubjectAgent, ID: "a1"}
	create := func(c authn.Caller) error {
		_, err := f.svc.CreateConnection(context.Background(), c, ConnectionCreate{Name: "pets", BaseURL: "https://api.example.com", AuthConfigID: &cfg}, nil)
		return err
	}
	var forbidden *domain.Forbidden
	if err := create(agent); !errors.As(err, &forbidden) || len(f.conns.rows) != 0 {
		t.Fatalf("agent: err = %v, rows %d", err, len(f.conns.rows))
	}
	if err := create(f.caller); err != nil {
		t.Fatalf("creator: %v", err)
	}
	f.graph.allowed["Agent:a1#"+cfg.String()] = true
	if err := create(agent); err != nil {
		t.Fatalf("lent: %v", err)
	}
}

// The port judged a proxied connection call without the audit row Python's
// _governed_call files against the connection for every verdict.
func TestCallConnectionToolIsAudited(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = io.WriteString(w, `[]`) }))
	defer srv.Close()
	f := newWritesFixture(t, true, governanceapi.Policy{Tools: &governanceapi.Tools{Denied: []string{"getPet"}}})
	audit := &fakeAudit{}
	f.svc.d.Audit = audit
	v, err := f.svc.CreateConnection(context.Background(), f.caller, ConnectionCreate{
		Name: "pets", BaseURL: srv.URL, SpecContent: writesSpecOf(t, writesPetSpec),
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.CallConnectionTool(context.Background(), f.caller, v.Connection.ID, "listPets", json.RawMessage(`{"q":1}`)); err != nil {
		t.Fatal(err)
	}
	client := f.caller
	client.ClientID = "cl-1"
	if _, err := f.svc.CallConnectionTool(context.Background(), client, v.Connection.ID, "getPet", nil); err != nil {
		t.Fatal(err)
	}
	if len(audit.rows) != 2 {
		t.Fatalf("audit = %+v", audit.rows)
	}
	allowed, denied := audit.rows[0], audit.rows[1]
	if allowed.Action != "tool.call.allowed" || allowed.ResourceType != "openapi_connection" || allowed.ResourceID != v.Connection.ID ||
		allowed.ActorType != "user" || allowed.ActorID != "owner" || allowed.Metadata["tool"] != "listPets" {
		t.Fatalf("allowed row = %+v", allowed)
	}
	if keys, _ := allowed.Metadata["argument_keys"].([]string); len(keys) != 1 || keys[0] != "q" {
		t.Fatalf("argument_keys = %v", allowed.Metadata["argument_keys"])
	}
	if denied.Action != "tool.call.denied" || denied.ActorType != "client" || denied.Metadata["decision"] != string(governanceapi.ToolDeny) {
		t.Fatalf("denied row = %+v", denied)
	}
}

func TestConnectionToolsAndCallFollowPolicy(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{Tools: &governanceapi.Tools{Denied: []string{"listPets"}}})
	v, err := f.svc.CreateConnection(context.Background(), f.caller, ConnectionCreate{
		Name: "pets", BaseURL: "https://api.example.com", SpecContent: writesSpecOf(t, writesPetSpec),
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	tools, err := f.svc.ConnectionTools(context.Background(), f.caller, v.Connection.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(tools) != 1 || tools[0].Name != "getPet" {
		t.Fatalf("tools = %+v", tools)
	}
	res, err := f.svc.CallConnectionTool(context.Background(), f.caller, v.Connection.ID, "listPets", nil)
	if err != nil || !res.IsError || res.Text != "Tool call refused: tool 'listPets' is denied by policy" {
		t.Fatalf("res = %+v, err = %v", res, err)
	}
	res, err = f.svc.CallConnectionTool(context.Background(), f.caller, v.Connection.ID, "nope", nil)
	if err != nil || !res.IsError || res.Text != "pets has no tool nope" {
		t.Fatalf("res = %+v, err = %v", res, err)
	}
}

func TestUpdateConnectionAuthRefusalKeepsHeaders(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	id := seedWritesConnection(t, f)
	missing := uuid.New()
	_, err := f.svc.UpdateConnection(context.Background(), f.caller, id, ConnectionPatch{
		HeadersSet: true, Headers: []HeaderIn{{Name: "X-Key", Value: "new"}},
		AuthConfigSet: true, AuthConfigID: &missing,
	})
	if err == nil {
		t.Fatal("an unknown auth config was accepted")
	}
	if f.secrets.values[domain.SecretHeaderKey(id.String(), "Authorization")] != "old" {
		t.Fatalf("secrets = %v", f.secrets.values)
	}
	if _, ok := f.secrets.values[domain.SecretHeaderKey(id.String(), "X-Key")]; ok {
		t.Fatal("new header stored")
	}
}

func TestConnectCatalogAPI(t *testing.T) {
	f := newWritesFixture(t, true, governanceapi.Policy{})
	keyed, signIn, broken := uuid.New(), uuid.New(), uuid.New()
	f.svc.d.CatalogItems = oaItems{
		keyed: {ID: keyed, Name: "Pets", Spec: map[string]any{"base_url": "https://api.example.com",
			"api_key": map[string]any{"fields": []any{map[string]any{"name": "X-Key", "location": "header", "label": "Key"}}}}},
		signIn: {ID: signIn, Name: "Mail", Spec: map[string]any{"base_url": "https://mail.example.com"}},
		broken: {ID: broken, Name: "Bad", Spec: map[string]any{"api_key": "nope"}},
	}
	ctx := context.Background()
	if _, err := f.svc.CatalogConnectForm(ctx, f.caller, broken); !errors.Is(err, ErrCatalogMisconfigured) {
		t.Fatalf("broken: %v", err)
	}
	var inv *domain.Invalid
	if _, err := f.svc.ConnectCatalogAPI(ctx, f.caller, signIn, [][2]string{{"X-Key", "k"}}); !errors.As(err, &inv) || inv.Msg != "This catalog API connects by signing in" {
		t.Fatalf("sign-in: %v", err)
	}
	if _, err := f.svc.ConnectCatalogAPI(ctx, f.caller, keyed, [][2]string{{"X-Key", "a"}, {"X-Key", "b"}}); !errors.As(err, &inv) || inv.Msg != "A field was given twice" {
		t.Fatalf("twice: %v", err)
	}
	v, err := f.svc.ConnectCatalogAPI(ctx, f.caller, keyed, [][2]string{{"X-Key", "k"}})
	if err != nil {
		t.Fatal(err)
	}
	if v.Connection.Name != "Pets" || f.secrets.values[domain.SecretHeaderKey(v.Connection.ID, "X-Key")] != "k" {
		t.Fatalf("connection = %+v, secrets = %v", v.Connection, f.secrets.values)
	}
}

// Python judged a proxied connection call by its bare tool name with the name
// allowing it: a rule on openapi:<connection>:<tool> never matched there,
// and a bare-name allowlist entry allowed that operation on any connection.
func TestCallConnectionToolJudgesTheCanonicalIdentity(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = io.WriteString(w, `[]`) }))
	defer srv.Close()
	f := newWritesFixture(t, true, governanceapi.Policy{})
	v, err := f.svc.CreateConnection(context.Background(), f.caller, ConnectionCreate{
		Name: "pets", BaseURL: srv.URL, SpecContent: writesSpecOf(t, writesPetSpec),
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	target := "openapi:" + v.Connection.ID + ":listPets"
	for _, tc := range []struct {
		tools  governanceapi.Tools
		refuse string
	}{
		{governanceapi.Tools{Allowed: []string{target}}, ""},
		{governanceapi.Tools{Allowed: []string{"listPets"}}, "Tool call refused: tool 'listPets' is not permitted by the policy allowlist"},
		{governanceapi.Tools{Denied: []string{target}}, "Tool call refused: tool 'listPets' is denied by policy"},
		{governanceapi.Tools{Denied: []string{"pets"}}, "Tool call refused: tool 'listPets' is denied by policy"},
	} {
		f.svc.d.Policies = writesPolicies{governanceapi.Policy{Tools: &tc.tools}}
		res, err := f.svc.CallConnectionTool(context.Background(), f.caller, v.Connection.ID, "listPets", nil)
		if err != nil {
			t.Fatal(err)
		}
		if tc.refuse == "" && res.IsError || tc.refuse != "" && res.Text != tc.refuse {
			t.Fatalf("%+v: res = %+v", tc.tools, res)
		}
	}
}
