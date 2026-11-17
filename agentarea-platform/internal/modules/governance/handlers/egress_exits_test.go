package handlers

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
)

type memExits struct{ rows map[string]domain.EgressExit }

func (m *memExits) List(context.Context, db.Session) ([]domain.EgressExit, error) {
	out := []domain.EgressExit{}
	for _, e := range m.rows {
		out = append(out, e)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt.After(out[j].CreatedAt) })
	return out, nil
}

func (m *memExits) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.EgressExit, bool, error) {
	e, ok := m.rows[id.String()]
	return e, ok, nil
}

func (m *memExits) Create(_ context.Context, s db.Session, e domain.EgressExit, now time.Time) (domain.EgressExit, error) {
	e.WorkspaceID, e.CreatedAt, e.UpdatedAt = s.Workspace().ID(), now, now
	m.rows[e.ID] = e
	return e, nil
}

func (m *memExits) Update(_ context.Context, _ db.Session, id uuid.UUID, ch store.EgressExitChanges, now time.Time) (domain.EgressExit, bool, error) {
	e, ok := m.rows[id.String()]
	if !ok {
		return e, false, nil
	}
	if v, sent := ch["description"]; sent {
		e.Description = v.(*string)
	}
	e.UpdatedAt = now
	m.rows[e.ID] = e
	return e, true, nil
}

func (m *memExits) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	_, ok := m.rows[id.String()]
	delete(m.rows, id.String())
	return ok, nil
}

type noBindings struct{}

func (noBindings) BoundToEgressExit(context.Context, scope.Workspace, string) ([]connectionsapi.EgressBoundInstance, error) {
	return nil, nil
}

func (noBindings) RetireBeforeMutation(context.Context, string) error { return nil }

type egressGraph struct {
	authz.Graph
	allow bool
}

func (g *egressGraph) Check(context.Context, string, string, string, string) (bool, error) {
	return g.allow, nil
}
func (g *egressGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error)  { return nil, nil }
func (g *egressGraph) Write(context.Context, []authz.Tuple, []authz.Tuple) error { return nil }

type egressCatalog struct{ secrets.Catalog }

func (egressCatalog) GetForUse(_ context.Context, id string) (secrets.Secret, error) {
	return secrets.Secret{ID: id}, nil
}

func (egressCatalog) StageReferences(context.Context, db.Session, string, string, []secrets.Reference) error {
	return nil
}

func newEgressEnv(t *testing.T) (env, *egressGraph) {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), caller)))
		})
	}
	admin := func(context.Context) error { return nil }
	graph := &egressGraph{allow: true}
	svc := service.New(service.Deps{DB: fakeDB{}, Policies: &memRules{}, Audit: &memAudit{}, Log: slog.New(slog.DiscardHandler),
		Now:     func() time.Time { return time.Date(2026, 5, 1, 10, 0, 0, 0, time.UTC) },
		Secrets: func(scope.Workspace, secrets.Actor, secrets.Auditor) secrets.Catalog { return egressCatalog{} },
		EgressExits: &service.EgressExitPorts{Store: &memExits{rows: map[string]domain.EgressExit{}}, Graph: graph, Instances: noBindings{},
			Upstream: func(context.Context, string) error { return nil }}})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, admin, New(svc, admin), Routes{EgressExits: true})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return env{srv: s}, graph
}

func TestEgressExitLifecycle(t *testing.T) {
	e, graph := newEgressEnv(t)
	secret := uuid.NewString()
	status, body := e.call(t, http.MethodPost, "/egress-exits/", `{"name":"  office  ","upstream_url":"HTTPS://proxy.example.com:443/","username":"u","password_secret_id":"`+strings.ToUpper(secret)+`"}`)
	if status != http.StatusCreated {
		t.Fatalf("%d %s", status, body)
	}
	var created map[string]any
	if err := json.Unmarshal([]byte(body), &created); err != nil {
		t.Fatal(err)
	}
	id := created["id"].(string)
	want := `{"id":"` + id + `","name":"office","description":null,"upstream_url":"https://proxy.example.com:443","username":"u",` +
		`"password_secret_id":"` + secret + `","via":null,"allow_plaintext_credentials":false,"managed_by":null,"created_by":"owner",` +
		`"created_at":"2026-05-01T10:00:00Z","updated_at":"2026-05-01T10:00:00Z"}`
	if body != want {
		t.Fatalf("body %s\nwant %s", body, want)
	}
	if status, got := e.call(t, http.MethodGet, "/egress-exits/", ""); status != http.StatusOK || got != "["+want+"]" {
		t.Fatalf("list %d %s", status, got)
	}
	if status, got := e.call(t, http.MethodGet, "/egress-exits/"+strings.ToUpper(id), ""); status != http.StatusOK || got != want {
		t.Fatalf("get %d %s", status, got)
	}
	if status, got := e.call(t, http.MethodPatch, "/egress-exits/"+id, `{"description":"the office"}`); status != http.StatusOK ||
		!strings.Contains(got, `"description":"the office"`) {
		t.Fatalf("patch %d %s", status, got)
	}
	if status, got := e.call(t, http.MethodPatch, "/egress-exits/"+id, `{"upstream_url":null}`); status != http.StatusBadRequest ||
		!strings.Contains(got, `"detail":"upstream_url cannot be cleared"`) {
		t.Fatalf("clear upstream %d %s", status, got)
	}

	graph.allow = false
	for _, m := range []string{http.MethodPatch, http.MethodDelete} {
		if status, got := e.call(t, m, "/egress-exits/"+id, `{"color":1}`); status != http.StatusForbidden || !strings.Contains(got, `"detail":"Permission denied"`) {
			t.Fatalf("%s without the grant: %d %s", m, status, got)
		}
		if status, got := e.call(t, m, "/egress-exits/nope", `{"color":1}`); status != http.StatusUnprocessableEntity ||
			!strings.Contains(got, `[{"type":"uuid_parsing","loc":["path","exit_id"],"msg":"Input should be a valid UUID"`) ||
			strings.Contains(got, "color") {
			t.Fatalf("%s with a bad id: %d %s", m, status, got)
		}
	}
	graph.allow = true

	if status, _ := e.call(t, http.MethodDelete, "/egress-exits/"+id, ""); status != http.StatusNoContent {
		t.Fatalf("delete %d", status)
	}
	if status, got := e.call(t, http.MethodGet, "/egress-exits/"+id, ""); status != http.StatusNotFound || !strings.Contains(got, `"detail":"Egress exit `+id+` not found"`) {
		t.Fatalf("get deleted %d %s", status, got)
	}
}

func TestEgressExitBodiesAreValidatedAsPydanticDoes(t *testing.T) {
	e, _ := newEgressEnv(t)
	for _, c := range []struct{ method, body, want string }{
		{http.MethodPost, `{"upstream_url":"https://p:1"}`, `"type":"missing","loc":["body","name"]`},
		{http.MethodPost, `{"name":"x"}`, `"type":"missing","loc":["body","upstream_url"]`},
		{http.MethodPost, `{"name":"   ","upstream_url":"https://p:1"}`, `"type":"value_error","loc":["body","name"],"msg":"Value error, name cannot be empty or whitespace"`},
		{http.MethodPost, `{"name":"","upstream_url":"https://p:1"}`, `"type":"string_too_short","loc":["body","name"]`},
		{http.MethodPost, `{"name":"x","upstream_url":"https://p:1/path"}`, `"msg":"Value error, upstream_url must be scheme://host:port with no path, query or fragment"`},
		{http.MethodPost, `{"name":"x","upstream_url":"ftp://p:1"}`, `"msg":"Value error, upstream_url scheme must be http, https or socks5"`},
		{http.MethodPost, `{"name":"x","upstream_url":"https://p:1","password_secret_id":7}`, `"type":"uuid_type","loc":["body","password_secret_id"]`},
		{http.MethodPost, `{"name":"x","upstream_url":"https://p:1","password_secret_id":"nope"}`, `"type":"uuid_parsing","loc":["body","password_secret_id"]`},
		{http.MethodPost, `{"name":"x","upstream_url":"https://p:1","allow_plaintext_credentials":null}`, `"type":"bool_type"`},
		{http.MethodPost, `{"name":"x","upstream_url":"https://p:1","via":"hop"}`, `"type":"extra_forbidden","loc":["body","via"]`},
		{http.MethodPost, `{"name":"x","upstream_url":"http://p:1","username":"u"}`, `"type":"value_error","loc":["body"],"msg":"Value error, credentials to an http or socks5 proxy travel unencrypted; use https or set allow_plaintext_credentials"`},
		{http.MethodPost, ``, `"type":"missing","loc":["body"]`},
	} {
		status, body := e.call(t, c.method, "/egress-exits/", c.body)
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s %s: %d %s", c.method, c.body, status, body)
		}
	}
	id := uuid.NewString()
	for _, c := range []struct{ body, want string }{
		{`{"name":""}`, `"type":"string_too_short","loc":["body","name"]`},
		{`{"upstream_url":"https://u@p:1"}`, `"msg":"Value error, upstream_url must not carry credentials; set username and password_secret_id"`},
		{`{"managed_by":"platform"}`, `"type":"extra_forbidden","loc":["body","managed_by"]`},
		{`{"allow_plaintext_credentials":"maybe"}`, `"type":"bool_parsing"`},
	} {
		status, body := e.call(t, http.MethodPatch, "/egress-exits/"+id, c.body)
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("PATCH %s: %d %s", c.body, status, body)
		}
	}
}
