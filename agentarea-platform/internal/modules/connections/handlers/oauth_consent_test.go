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

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// consentGate admits u1 into "acme" only.
type consentGate struct {
	authn.Gate
	acme scope.Workspace
}

func (g consentGate) EnterWorkspace(_ context.Context, p authn.Principal, ref string) (authn.Caller, error) {
	if p.UserID != "u1" || (ref != "acme" && ref != g.acme.ID()) {
		return authn.Caller{}, &scope.UnreachableError{Reference: ref}
	}
	return authn.Caller{Principal: p, Workspace: g.acme}, nil
}

func consentHarness(t *testing.T) (*httptest.Server, scope.Workspace, *map[string]any) {
	t.Helper()
	accepted := map[string]any{}
	hydra := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.Method + " " + r.URL.Path {
		case "GET /admin/oauth2/auth/requests/consent":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"subject": "u1", "requested_scope": []string{"openid", "offline_access"},
				"client": map[string]any{"client_id": "dcr-1", "client_name": "Cursor", "scope": "mcp offline_access openid", "redirect_uris": []string{"http://127.0.0.1:9/cb"}},
			})
		case "PUT /admin/oauth2/auth/requests/consent/accept":
			raw, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(raw, &accepted)
			_, _ = w.Write([]byte(`{"redirect_to":"https://hydra.example/next"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(hydra.Close)
	acme, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	w := &world{auths: map[uuid.UUID]domain.AuthConfig{}, conns: map[uuid.UUID]domain.Connection{}, secrets: map[string]string{}, allow: true, instances: map[uuid.UUID]bool{}}
	edge := Edge{
		Workspace: func(next http.Handler) http.Handler { return next },
		Admin:     func(context.Context) error { return nil },
		Gate:      consentGate{acme: acme},
		Authenticate: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
				kind := authn.CredentialKind(r.Header.Get("X-Kind"))
				p := authn.Principal{UserID: r.Header.Get("X-User"), Credential: &authn.Credential{Kind: kind, Granted: []string{authn.OAuthScopeAPI}}}
				next.ServeHTTP(rw, r.WithContext(authn.WithPrincipal(r.Context(), p)))
			})
		},
	}
	svc := service.New(service.Deps{
		DB: memDB{}, Auth: w, Links: worldLinks{w}, Connections: worldConns{w}, Instances: worldInstances{w: w},
		Secrets: worldSecrets{w}, Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return worldCatalog{} },
		Graph: worldGraph{w}, Out: oauthOut{}, KV: oauthKV{}, OAuthStore: oauthStore{},
		APIURL: "https://api.example", AppURL: "https://app.example",
		Config: service.Config{HydraURL: hydra.URL, HydraAdminURL: hydra.URL},
	})
	r := chi.NewRouter()
	Mount(r, httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError), edge, New(svc), Ports{})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s, acme, &accepted
}

func consentCall(t *testing.T, s *httptest.Server, method, path, body, user string, kind authn.CredentialKind) (int, string) {
	t.Helper()
	req, _ := http.NewRequest(method, s.URL+path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User", user)
	req.Header.Set("X-Kind", string(kind))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(raw)
}

func TestConsentRoutes(t *testing.T) {
	s, acme, accepted := consentHarness(t)

	status, body := consentCall(t, s, http.MethodGet, "/v1/oauth/consent?challenge=ch", "", "u1", authn.KindSession)
	if status != 200 || body != `{"client":{"client_id":"dcr-1","client_name":"Cursor","client_uri":"","logo_uri":"","redirect_uris":["http://127.0.0.1:9/cb"]},"redirect_uri":"http://127.0.0.1:9/cb","first_party":false,"access":"mcp","scopes":["mcp","openid","offline_access"]}` {
		t.Fatalf("%d %s", status, body)
	}
	for _, kind := range []authn.CredentialKind{authn.KindOAuth, authn.KindAPIKey, authn.KindTurn} {
		if status, body := consentCall(t, s, http.MethodGet, "/v1/oauth/consent?challenge=ch", "", "u1", kind); status != 403 || !strings.Contains(body, detailConsentNeedsSession) {
			t.Fatalf("%s read a consent: %d %s", kind, status, body)
		}
		if status, _ := consentCall(t, s, http.MethodPost, "/v1/oauth/consent", `{"challenge":"ch","action":"accept","workspaces":["acme"]}`, "u1", kind); status != 403 {
			t.Fatalf("%s accepted a consent: %d", kind, status)
		}
	}
	if status, _ := consentCall(t, s, http.MethodGet, "/v1/oauth/consent?challenge=ch", "", "u2", authn.KindSession); status != 403 {
		t.Fatalf("another user read the consent: %d", status)
	}

	for body, want := range map[string]int{
		`{"challenge":"ch","action":"accept"}`:                                 422,
		`{"challenge":"ch","action":"accept","workspaces":[]}`:                 422,
		`{"challenge":"ch","action":"accept","workspaces":"acme"}`:             422,
		`{"challenge":"ch","action":"accept","workspaces":[1]}`:                422,
		`{"challenge":"ch","action":"grant","workspaces":["acme"]}`:            422,
		`{"challenge":"ch","action":"accept","workspaces":["acme"],"x":1}`:     422,
		`{"challenge":"ch","action":"accept","workspaces":["acme","foreign"]}`: 403,
	} {
		if status, got := consentCall(t, s, http.MethodPost, "/v1/oauth/consent", body, "u1", authn.KindSession); status != want {
			t.Fatalf("%s: %d %s", body, status, got)
		}
	}
	if len(*accepted) != 0 {
		t.Fatalf("a refused decision reached Hydra: %v", *accepted)
	}

	status, body = consentCall(t, s, http.MethodPost, "/v1/oauth/consent", `{"challenge":"ch","action":"accept","workspaces":["acme","`+acme.ID()+`"]}`, "u1", authn.KindSession)
	if status != 200 || body != `{"redirect_to":"https://hydra.example/next"}` {
		t.Fatalf("%d %s", status, body)
	}
	session, _ := (*accepted)["session"].(map[string]any)
	token, _ := session["access_token"].(map[string]any)
	if ids, _ := token["workspace_ids"].([]any); len(ids) != 1 || ids[0] != acme.ID() {
		t.Fatalf("the workspace claim is %v, want the id of acme once", token["workspace_ids"])
	}
}
