package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// specsPort is a present catalog port; the tests here never reach it.
type specsPort struct{ service.Specs }

// instanceHarness serves the routes with the specs port present.
func instanceHarness(t *testing.T, admin bool, seed func(*world)) (*httptest.Server, *world) {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	w := &world{auths: map[uuid.UUID]domain.AuthConfig{}, conns: map[uuid.UUID]domain.Connection{}, secrets: map[string]string{}, allow: true, instances: map[uuid.UUID]bool{}}
	if seed != nil {
		seed(w)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	edge := Edge{
		Workspace: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(rw, r.WithContext(authn.WithCaller(r.Context(), caller)))
			})
		},
		Admin: func(context.Context) error {
			if admin {
				return nil
			}
			return httpx.HTTPError(http.StatusForbidden, authz.NotAdminDetail)
		},
	}
	svc := service.New(service.Deps{
		DB: memDB{}, Auth: w, Links: worldLinks{w}, Connections: worldConns{w}, Instances: worldInstances{w: w},
		Secrets: worldSecrets{w}, Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return worldCatalog{} },
		Graph: worldGraph{w}, Specs: specsPort{},
	})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, edge, New(svc), Ports{})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s, w
}

func TestInstanceRoutesMountOnlyWithTheirPorts(t *testing.T) {
	s, _ := harness(t, true, nil)
	for _, p := range []string{"/mcp-server-instances/", "/mcp-server-instances/with-spec", "/mcp-server-instances/check"} {
		if code, _ := call(t, s, http.MethodPost, p, `{}`); code != http.StatusNotFound && code != http.StatusMethodNotAllowed {
			t.Errorf("POST %s without its port: %d", p, code)
		}
	}
	id := uuid.NewString()
	for _, p := range []string{"/mcp-server-instances/health/containers", "/mcp-server-instances/tool-policies", "/mcp-server-instances/" + id + "/consumers"} {
		if code, _ := call(t, s, http.MethodGet, p, ""); code == http.StatusOK {
			t.Errorf("GET %s served without its port", p)
		}
	}
}

func TestCreateInstanceBodyErrorsAre422(t *testing.T) {
	s, _ := instanceHarness(t, false, nil)
	code, body := call(t, s, http.MethodPost, "/mcp-server-instances/", `{"server_spec_id":"nope","extra":1}`)
	if code != http.StatusUnprocessableEntity {
		t.Fatalf("%d %s", code, body)
	}
	for _, want := range []string{`"loc":["body","name"]`, `"loc":["body","server_spec_id"]`, `"loc":["body","extra"]`} {
		if !strings.Contains(body, want) {
			t.Errorf("missing %s in %s", want, body)
		}
	}
}

func TestPatchChecksPermissionBeforeTheBody(t *testing.T) {
	id := uuid.New()
	s, w := harness(t, false, func(w *world) { w.instances[id] = true })
	w.allow = false
	code, body := call(t, s, http.MethodPatch, "/mcp-server-instances/"+id.String(), `{"name":null}`)
	if code == http.StatusUnprocessableEntity || code == http.StatusOK {
		t.Fatalf("a denied caller saw body validation: %d %s", code, body)
	}
	w.allow = true
	code, body = call(t, s, http.MethodPatch, "/mcp-server-instances/"+id.String(), `{"name":null}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, "may be omitted, but not set to null") {
		t.Fatalf("null name: %d %s", code, body)
	}
}

func TestInstanceAdminRoutesRefuseMembers(t *testing.T) {
	id := uuid.New()
	s, _ := harness(t, false, func(w *world) { w.instances[id] = true })
	for _, p := range []string{"/environment", "/oauth-links"} {
		if code, _ := call(t, s, http.MethodGet, "/mcp-server-instances/"+id.String()+p, ""); code != http.StatusForbidden {
			t.Errorf("%s for a member: %d", p, code)
		}
	}
}

func TestOAuthLinkIs501AndTestAuthNeedsAnAuthConfig(t *testing.T) {
	id := uuid.New()
	s, _ := harness(t, false, func(w *world) { w.instances[id] = true })
	code, body := call(t, s, http.MethodPost, "/mcp-server-instances/"+id.String()+"/oauth-link", `{}`)
	if code != http.StatusNotImplemented || !strings.Contains(body, "/v1/mcp-oauth-links") {
		t.Fatalf("oauth-link: %d %s", code, body)
	}
	code, body = call(t, s, http.MethodPost, "/mcp-server-instances/"+id.String()+"/test-auth", "")
	if code != http.StatusBadRequest || !strings.Contains(body, "No auth config attached to this MCP instance") {
		t.Fatalf("test-auth: %d %s", code, body)
	}
	missing := uuid.NewString()
	if code, _ := call(t, s, http.MethodPost, "/mcp-server-instances/"+missing+"/test-auth", ""); code != http.StatusNotFound {
		t.Fatalf("test-auth on a missing instance: %d", code)
	}
}

func TestInstanceErrorShapes(t *testing.T) {
	e, ok := instanceError(&domain.SpecInvalid{Errors: []string{"a", "b"}})
	if !ok || e.Status != http.StatusUnprocessableEntity {
		t.Fatalf("spec invalid: %+v", e)
	}
	raw, err := json.Marshal(e.Extensions)
	if err != nil || !strings.Contains(string(raw), `"errors":["a","b"]`) {
		t.Fatalf("errors extension: %s %v", raw, err)
	}
	e, _ = instanceError(&service.RuntimeRetirementError{Conflict: true, Msg: "busy"})
	if e.Status != http.StatusConflict || e.Header.Get("Retry-After") != "1" {
		t.Fatalf("conflict: %+v", e)
	}
	e, _ = instanceError(&service.RuntimeRetirementError{Msg: "down"})
	if e.Status != http.StatusServiceUnavailable {
		t.Fatalf("unavailable: %+v", e)
	}
	if _, ok := instanceError(errors.New("x")); ok {
		t.Fatal("a plain error is not an instance error")
	}
}

func TestCreatedIs202ForContainers(t *testing.T) {
	for transport, want := range map[string]int{domain.TransportURL: http.StatusCreated, domain.TransportDocker: http.StatusAccepted, domain.TransportCommand: http.StatusAccepted} {
		v := service.InstanceView{Instance: domain.Instance{ID: uuid.NewString(), Transport: transport, JSONSpec: map[string]any{}}}
		if got := created(v).status; got != want {
			t.Errorf("%s: %d, want %d", transport, got, want)
		}
	}
}
