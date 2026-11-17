package handlers

import (
	"context"
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
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/service"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type fakeStore struct {
	service.RegistryStore
	registries map[string]domain.Registry
}

func (f *fakeStore) Get(_ context.Context, _ db.Session, id string) (domain.Registry, bool, error) {
	r, ok := f.registries[id]
	return r, ok, nil
}

func (f *fakeStore) ListVisible(context.Context, db.Session, bool, string, string) ([]domain.Registry, error) {
	out := []domain.Registry{}
	for _, r := range f.registries {
		out = append(out, r)
	}
	return out, nil
}

func (f *fakeStore) Create(_ context.Context, _ db.Session, n domain.NewRegistry, now time.Time) (domain.Registry, error) {
	r := domain.Registry{ID: uuid.NewString(), Name: n.Name, RegistryType: n.RegistryType, SourceType: n.SourceType,
		SourceURL: n.SourceURL, IsActive: true, Scope: n.Scope, Mode: n.Mode, Trust: n.Trust,
		RecommendationPriority: n.RecommendationPriority, CreatedAt: now, UpdatedAt: now}
	f.registries[r.ID] = r
	return r, nil
}

func (f *fakeStore) Delete(_ context.Context, _ db.Session, id string) (bool, error) {
	_, ok := f.registries[id]
	delete(f.registries, id)
	return ok, nil
}

type authority bool

func (a authority) CanWrite(context.Context, authn.Caller, string) (bool, error) { return bool(a), nil }

func server(t *testing.T, platform bool, st *fakeStore) *httptest.Server {
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
	svc := service.New(service.Deps{DB: fakeDB{}, Registries: st, Authority: authority(platform)})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, New(svc, nil, nil, nil))
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

func TestPlatformWriteRefusesBeforeValidation(t *testing.T) {
	s := server(t, false, &fakeStore{registries: map[string]domain.Registry{}})
	status, body := call(t, s, http.MethodPost, "/registries/", `[]`)
	if status != http.StatusForbidden || !strings.Contains(body, `"detail":"Only the platform may modify the global registry catalog"`) {
		t.Fatalf("%d %s", status, body)
	}
	status, _ = call(t, s, http.MethodDelete, "/registries/not-a-uuid", ``)
	if status != http.StatusForbidden {
		t.Fatalf("delete: %d", status)
	}
}

func TestCreateRendersRegistryResponse(t *testing.T) {
	st := &fakeStore{registries: map[string]domain.Registry{}}
	s := server(t, true, st)
	status, body := call(t, s, http.MethodPost, "/registries/", `{"name":"Mine","registry_type":"skills","source_type":"managed"}`)
	if status != http.StatusOK {
		t.Fatalf("%d %s", status, body)
	}
	for _, want := range []string{
		`"name":"Mine","description":null,"registry_type":"skills","source_type":"managed","source_url":"managed://catalog","source_ref":null,"source_path":null,"is_active":true,"scope":"platform","workspace_id":null,"mode":"mirror","trust":"official","credentials_secret_id":null,"last_synced_at":null,"last_sync_error":null,"item_count":0,"recommendation_priority":100,"created_at":"`,
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("body %s", body)
		}
	}
	status, body = call(t, s, http.MethodPost, "/registries/", `{"name":"x","registry_type":"bad","source_type":"url","source_url":"https://x"}`)
	if status != http.StatusBadRequest || !strings.Contains(body, `registry_type must be one of ('mcp_servers'`) {
		t.Fatalf("%d %s", status, body)
	}
}

func TestValidationIsOne422(t *testing.T) {
	s := server(t, true, &fakeStore{registries: map[string]domain.Registry{}})
	for _, c := range []struct{ method, path, body, want string }{
		{http.MethodPost, "/registries/", `{}`, `"loc":["body","name"]`},
		{http.MethodPost, "/registries/", `{"name":"x","registry_type":"s","source_type":"u","mode":"copy"}`, `"type":"literal_error"`},
		{http.MethodPost, "/registries/", `{"name":"x","registry_type":"s","source_type":"u","recommendation_priority":-1}`, `"type":"greater_than_equal"`},
		{http.MethodPost, "/registries/", `{"name":"x","registry_type":"s","source_type":"u","recommendation_priority":2147483648}`, `"type":"less_than_equal"`},
		{http.MethodPatch, "/registries/" + uuid.NewString(), `{"recommendation_priority":2147483648}`, `"type":"less_than_equal"`},
		{http.MethodPost, "/registries/" + uuid.NewString() + "/items", `{"external_id":"e","name":"n","recommendation_rank":4294967296}`, `"type":"less_than_equal"`},
		{http.MethodGet, "/registries/?scope=team", ``, `"type":"literal_error"`},
		{http.MethodGet, "/registries/catalog/search?limit=501", ``, `"type":"less_than_equal"`},
		{http.MethodGet, "/registries/nope", ``, `"type":"uuid_parsing"`},
		{http.MethodPost, "/registries/" + uuid.NewString() + "/items", `{"external_id":"","name":"n","tags":[1]}`, `"loc":["body","tags",0]`},
	} {
		status, body := call(t, s, c.method, c.path, c.body)
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s %s %s: %d %s", c.method, c.path, c.body, status, body)
		}
	}
}

func TestEmptyPatchAndMissingRegistry(t *testing.T) {
	s := server(t, true, &fakeStore{registries: map[string]domain.Registry{}})
	status, body := call(t, s, http.MethodPatch, "/registries/"+uuid.NewString(), `{}`)
	if status != http.StatusBadRequest || !strings.Contains(body, `"detail":"No fields to update"`) {
		t.Fatalf("%d %s", status, body)
	}
	status, body = call(t, s, http.MethodGet, "/registries/"+uuid.NewString(), ``)
	if status != http.StatusNotFound || !strings.Contains(body, `"detail":"Registry not found"`) {
		t.Fatalf("%d %s", status, body)
	}
	status, _ = call(t, s, http.MethodGet, "/registries/catalog/browse?registry_type=skills", ``)
	if status != http.StatusNotFound && status != http.StatusMethodNotAllowed {
		t.Fatalf("browse is mounted without its ports: %d", status)
	}
}
