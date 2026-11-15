package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
)

type syncStore struct {
	service.SyncStore
	errors []string
}

func (f *syncStore) RecordSyncError(_ context.Context, _ db.Session, _, msg string, _ time.Time) error {
	f.errors = append(f.errors, msg)
	return nil
}

type plainNet struct{}

func (plainNet) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (plainNet) Dialer() netguard.Dialer                          { return nil }

type limiter bool

func (l limiter) Take(context.Context, string, string, int) (bool, int, error) {
	return bool(l), 42, nil
}

func syncServer(t *testing.T, regs map[string]domain.Registry, ws scope.Workspace, allow limiter) (*httptest.Server, *syncStore) {
	t.Helper()
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), caller)))
		})
	}
	ss := &syncStore{}
	svc := service.New(service.Deps{DB: fakeDB{}, Registries: &fakeStore{registries: regs}, Authority: authority(true),
		Sync: ss, Uses: struct{ api.ItemUses }{}, Fetch: service.Fetcher{Net: plainNet{}, GitHub: service.DefaultGitHub()},
		Log: slog.New(slog.DiscardHandler)})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, New(svc, nil, nil, func(context.Context) error { return nil }).WithRateLimit(allow, nil))
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s, ss
}

func TestAFailedSyncIs502WithTheClassifiedReason(t *testing.T) {
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "internal detail of the source", http.StatusInternalServerError)
	}))
	defer source.Close()
	id := uuid.NewString()
	ws, _ := scope.NewWorkspace(uuid.NewString(), "acme")
	s, ss := syncServer(t, map[string]domain.Registry{id: {ID: id, Name: "r", RegistryType: domain.TypeAgents,
		SourceType: "url", SourceURL: source.URL + "/i.json", Scope: "platform", IsActive: true}}, ws, true)
	status, body := call(t, s, http.MethodPost, "/registries/"+id+"/sync", ``)
	if status != http.StatusBadGateway || !strings.Contains(body, `"detail":"Sync failed: the source answered HTTP 500"`) {
		t.Fatalf("%d %s", status, body)
	}
	if len(ss.errors) != 1 || ss.errors[0] != "the source answered HTTP 500" {
		t.Fatalf("recorded %v", ss.errors)
	}
	status, _ = call(t, s, http.MethodPost, "/registries/"+uuid.NewString()+"/sync", ``)
	if status != http.StatusNotFound {
		t.Fatalf("missing: %d", status)
	}
}

func TestManagedRegistriesRefuseSyncAndWorkspaceSyncIsRateLimited(t *testing.T) {
	ws, _ := scope.NewWorkspace(uuid.NewString(), "acme")
	wsID := ws.ID()
	managed, own := uuid.NewString(), uuid.NewString()
	regs := map[string]domain.Registry{
		managed: {ID: managed, SourceType: "managed", Scope: "platform"},
		own:     {ID: own, SourceType: "url", Scope: "workspace", WorkspaceID: &wsID},
	}
	s, _ := syncServer(t, regs, ws, false)
	status, body := call(t, s, http.MethodPost, "/registries/"+managed+"/sync", ``)
	if status != http.StatusBadRequest || !strings.Contains(body, "Managed registry items are changed through the catalog item API") {
		t.Fatalf("%d %s", status, body)
	}
	req, _ := http.NewRequest(http.MethodPost, s.URL+"/v1/workspaces/acme/workspace-registries/"+own+"/sync?force=true", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusTooManyRequests || resp.Header.Get("Retry-After") != "42" {
		t.Fatalf("%d %s", resp.StatusCode, resp.Header.Get("Retry-After"))
	}
	status, _ = call(t, s, http.MethodPost, "/workspace-registries/"+managed+"/sync", ``)
	if status != http.StatusNotFound {
		t.Fatalf("another scope's registry: %d", status)
	}
	status, body = call(t, s, http.MethodPost, "/workspace-registries/"+own+"/sync?force=maybe", ``)
	if status != http.StatusUnprocessableEntity || !strings.Contains(body, `"loc":["query","force"]`) {
		t.Fatalf("%d %s", status, body)
	}
}

func TestSyncRoutesNeedTheirPorts(t *testing.T) {
	s := server(t, true, &fakeStore{registries: map[string]domain.Registry{}})
	for _, p := range []string{"/registries/" + uuid.NewString() + "/sync", "/workspace-registries/" + uuid.NewString() + "/sync"} {
		if status, _ := call(t, s, http.MethodPost, p, ``); status != http.StatusNotFound && status != http.StatusMethodNotAllowed {
			t.Fatalf("%s mounted without ports: %d", p, status)
		}
	}
}
