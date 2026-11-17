package handlers

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/service"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type fakeStore struct {
	service.Store
	rows map[uuid.UUID]domain.Project
}

func (f *fakeStore) Create(_ context.Context, s db.Session, id uuid.UUID, by string, n domain.New, _ time.Time) (domain.Project, error) {
	p := domain.Project{ID: id.String(), WorkspaceID: s.Workspace().ID(), CreatedBy: by, Name: n.Name,
		Description: n.Description, Instructions: n.Instructions, ParentProjectID: n.ParentProjectID}
	f.rows[id] = p
	return p, nil
}

func (f *fakeStore) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Project, bool, error) {
	p, ok := f.rows[id]
	return p, ok, nil
}

func (f *fakeStore) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	_, ok := f.rows[id]
	delete(f.rows, id)
	return ok, nil
}

func (f *fakeStore) Links(_ context.Context, _ db.Session, ids []uuid.UUID) (map[string]*domain.Links, error) {
	out := map[string]*domain.Links{}
	for _, id := range ids {
		out[id.String()] = &domain.Links{}
	}
	return out, nil
}

type noLookups struct{}

func (noLookups) AgentExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, nil
}
func (noLookups) SkillExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, nil
}
func (noLookups) MCPInstanceExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, nil
}
func (noLookups) AgentNames(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return nil, nil
}
func (noLookups) SkillNames(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return nil, nil
}
func (noLookups) AgentIDBySlug(context.Context, scope.Workspace, string) (string, bool, error) {
	return "", false, nil
}
func (noLookups) MCPInstanceNames(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return nil, nil
}

func server(t *testing.T) *httptest.Server {
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
	svc := service.New(service.Deps{DB: fakeDB{}, Store: &fakeStore{rows: map[uuid.UUID]domain.Project{}}, Agents: noLookups{}, Connections: noLookups{}})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, New(svc), false)
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s
}

func call(t *testing.T, s *httptest.Server, method, path, body string) (int, string) {
	t.Helper()
	req, err := http.NewRequest(method, s.URL+"/v1/workspaces/acme"+path, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(raw)
}

func TestCreateStripsAndRendersInPythonOrder(t *testing.T) {
	s := server(t)
	status, body := call(t, s, http.MethodPost, "/projects/", `{"name":"  Roadmap  ","description":"d"}`)
	if status != http.StatusCreated {
		t.Fatalf("%d %s", status, body)
	}
	var p map[string]any
	if err := json.Unmarshal([]byte(body), &p); err != nil {
		t.Fatal(err)
	}
	prefix := `{"id":"` + p["id"].(string) + `","workspace_id":"` + p["workspace_id"].(string) +
		`","created_by":"owner","name":"Roadmap","description":"d","instructions":null,"parent_project_id":null,"skills":[],"mcp_instances":[],"agents":[]}`
	if body != prefix {
		t.Fatalf("body %s", body)
	}
	status, got := call(t, s, http.MethodGet, "/projects/"+strings.ToUpper(p["id"].(string)), "")
	if status != http.StatusOK || got != body {
		t.Fatalf("read back %d %s", status, got)
	}
}

func TestValidationIsOne422(t *testing.T) {
	s := server(t)
	for _, c := range []struct{ method, path, body, want string }{
		{http.MethodPost, "/projects/", `{"name":"   "}`, `"type":"value_error"`},
		{http.MethodPost, "/projects/", `{"name":"x","color":"red"}`, `"type":"extra_forbidden"`},
		{http.MethodPost, "/projects/", `[]`, `"type":"model_attributes_type"`},
		{http.MethodPost, "/projects/", ``, `"type":"missing"`},
		{http.MethodPatch, "/projects/" + uuid.NewString(), `{"name":null}`, `may be omitted, but not set to null`},
		{http.MethodGet, "/projects/nope", ``, `"type":"uuid_parsing"`},
		{http.MethodGet, "/projects/?limit=0", ``, `"type":"greater_than_equal"`},
		{http.MethodGet, "/projects/?offset=1000000001", ``, `"type":"less_than_equal"`},
	} {
		status, body := call(t, s, c.method, c.path, c.body)
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s %s %s: %d %s", c.method, c.path, c.body, status, body)
		}
	}
}

func TestMissingProjectIs404HTTPError(t *testing.T) {
	s := server(t)
	status, body := call(t, s, http.MethodGet, "/projects/"+uuid.NewString(), "")
	if status != http.StatusNotFound || !strings.Contains(body, `"detail":"Project not found"`) || !strings.Contains(body, `"code":"http_error"`) {
		t.Fatalf("%d %s", status, body)
	}
	status, body = call(t, s, http.MethodPost, "/projects/"+uuid.NewString()+"/agents", `{"id":"x"}`)
	if status != http.StatusNotFound || !strings.Contains(body, `"detail":"Project not found"`) || !strings.Contains(body, `"code":"not_found"`) {
		t.Fatalf("link to a missing project: %d %s", status, body)
	}
	status, _ = call(t, s, http.MethodDelete, "/projects/"+uuid.NewString(), "")
	if status != http.StatusNotFound {
		t.Fatalf("delete missing: %d", status)
	}
}
