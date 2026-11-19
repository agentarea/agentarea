package handlers

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

type oauthOut struct{}

func (oauthOut) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (oauthOut) Guard() *netguard.Guard                           { return nil }

type oauthKV map[string]string

func (k oauthKV) SetEx(_ context.Context, key, value string, _ time.Duration) error {
	k[key] = value
	return nil
}
func (k oauthKV) GetDel(_ context.Context, key string) (string, bool, error) {
	v, ok := k[key]
	delete(k, key)
	return v, ok, nil
}

type oauthStore struct{}

func (oauthStore) InsertOwnedAuth(context.Context, db.Session, uuid.UUID, string, domain.AuthConfigNew, string, uuid.UUID, time.Time) (domain.AuthConfig, error) {
	return domain.AuthConfig{}, nil
}
func (oauthStore) AttachConnectionAuth(context.Context, db.Session, uuid.UUID, uuid.UUID, time.Time) (bool, error) {
	return false, nil
}

type oauthGate struct{ authn.Gate }

// registerLimiter lets limit registrations through per identity, then refuses.
type registerLimiter struct {
	mu    sync.Mutex
	limit int
	taken map[string]int
}

func (l *registerLimiter) Take(_ context.Context, scope, identity string, limit int) (bool, int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if scope != httpx.OAuthRegisterScope || limit != httpx.OAuthRegisterLimit {
		return false, 0, nil
	}
	l.taken[identity]++
	return l.taken[identity] <= l.limit, 6, nil
}

// oauthHarness serves the OAuth routes against a fake Hydra; signedIn gates
// the finish route's authentication.
func oauthHarness(t *testing.T, signedIn bool) (*httptest.Server, oauthKV, *[]string) {
	t.Helper()
	return oauthHarnessLimited(t, signedIn, &registerLimiter{limit: 1 << 20, taken: map[string]int{}})
}

func oauthHarnessLimited(t *testing.T, signedIn bool, rate httpx.RateLimiter) (*httptest.Server, oauthKV, *[]string) {
	s, kv, hits, _ := oauthHarnessWithHydra(t, signedIn, rate, "https://api.example/oauth2/register")
	return s, kv, hits
}

// oauthHarnessWithHydra also returns Hydra's URL; registration is the
// registration endpoint its discovery advertises.
func oauthHarnessWithHydra(t *testing.T, signedIn bool, rate httpx.RateLimiter, registration string) (*httptest.Server, oauthKV, *[]string, string) {
	t.Helper()
	var hydraHits []string
	hydra := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hydraHits = append(hydraHits, r.Method+" "+r.URL.RequestURI())
		switch r.URL.Path {
		case "/.well-known/openid-configuration":
			base := "http://" + r.Host
			_ = json.NewEncoder(w).Encode(map[string]any{
				"issuer": base + "/", "authorization_endpoint": base + "/oauth2/auth",
				"token_endpoint": base + "/oauth2/token", "jwks_uri": base + "/.well-known/jwks.json",
				"registration_endpoint": registration, "scopes_supported": []string{"openid"},
			})
		case "/admin/clients":
			body, _ := io.ReadAll(r.Body)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write(body)
		default:
			w.Header().Set("X-Hydra", "1")
			w.Header().Set("Connection", "close")
			w.WriteHeader(http.StatusTeapot)
			_, _ = w.Write([]byte("hydra:" + r.URL.RequestURI()))
		}
	}))
	t.Cleanup(hydra.Close)

	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	w := &world{auths: map[uuid.UUID]domain.AuthConfig{}, conns: map[uuid.UUID]domain.Connection{}, secrets: map[string]string{}, allow: true, instances: map[uuid.UUID]bool{}}
	kv := oauthKV{}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	edge := Edge{
		Workspace: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(rw, r.WithContext(authn.WithCaller(r.Context(), caller)))
			})
		},
		Admin: func(context.Context) error { return nil },
		Gate:  oauthGate{},
		Authenticate: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
				if !signedIn {
					rw.WriteHeader(http.StatusUnauthorized)
					return
				}
				next.ServeHTTP(rw, r.WithContext(authn.WithPrincipal(r.Context(), caller.Principal)))
			})
		},
	}
	svc := service.New(service.Deps{
		DB: memDB{}, Auth: w, Links: worldLinks{w}, Connections: worldConns{w}, Instances: worldInstances{w: w},
		Secrets: worldSecrets{w}, Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return worldCatalog{} },
		Graph: worldGraph{w}, Out: oauthOut{}, KV: kv, OAuthStore: oauthStore{},
		APIURL: "https://api.example", AppURL: "https://app.example",
		Config: service.Config{HydraURL: hydra.URL, HydraAdminURL: hydra.URL, HydraBrowserURL: "https://auth.example", OAuthScopes: []string{"openid", "offline_access"}},
	})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, edge, New(svc).WithRateLimit(rate, slog.New(slog.DiscardHandler)), Ports{OpenAPI: true})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s, kv, &hydraHits, hydra.URL
}

func rawCall(t *testing.T, s *httptest.Server, method, path, body string) (*http.Response, string) {
	t.Helper()
	req, err := http.NewRequest(method, s.URL+path, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	client := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp, string(raw)
}

func TestOAuthConnectValidation(t *testing.T) {
	s, _, _ := oauthHarness(t, true)
	id := uuid.NewString()
	cases := []struct {
		method, path, body string
		status             int
		want               string
	}{
		{"GET", "/oauth/preflight", "", 422, "Pass exactly one of instance_id, server_id, catalog_item_id or openapi_connection_id."},
		{"GET", "/oauth/preflight?instance_id=" + id + "&server_id=" + id, "", 422, "Pass exactly one"},
		{"GET", "/oauth/preflight?instance_id=nope", "", 422, `"loc":["query","instance_id"]`},
		{"GET", "/oauth/preflight?instance_id=" + id, "", 503, "MCP server specs are not available"},
		{"POST", "/oauth/authorize", `{"instance_id":"` + id + `","bogus":1}`, 422, `"type":"extra_forbidden"`},
		{"POST", "/oauth/authorize", `{"instance_id":"` + id + `","credential_mode":"magic"}`, 422, `"type":"literal_error"`},
		{"POST", "/oauth/authorize", `{"instance_id":"` + id + `","scopes":[]}`, 422, `"type":"too_short"`},
		{"POST", "/oauth/authorize", `{}`, 422, "Value error, Pass exactly one of instance_id, catalog_item_id or openapi_connection_id."},
		{"POST", "/oauth/authorize", `{"instance_id":"` + id + `","client_id":"x"}`, 422, "Automatically chosen OAuth clients do not accept custom OAuth credentials."},
		{"POST", "/oauth/authorize", `{"instance_id":"` + id + `","credential_mode":"custom","client_id":"x"}`, 422, "Custom OAuth client secret must be entered"},
		{"POST", "/oauth/authorize", `{"instance_id":"` + id + `","credential_mode":"custom","client_secret":"x"}`, 422, "Custom OAuth client ID must be entered"},
		{"POST", "/oauth/authorize", `{"instance_id":"` + id + `"}`, 503, "MCP server specs are not available"},
	}
	for _, c := range cases {
		status, body := call(t, s, c.method, c.path, c.body)
		if status != c.status || !strings.Contains(body, c.want) {
			t.Errorf("%s %s %s: %d %s", c.method, c.path, c.body, status, body)
		}
	}
}

func TestOAuthCallbackAndFinish(t *testing.T) {
	s, kv, _ := oauthHarness(t, true)
	resp, _ := rawCall(t, s, "GET", "/v1/oauth/callback?state=gone&code=c", "")
	if resp.StatusCode != 400 {
		t.Fatalf("unknown state: %d", resp.StatusCode)
	}
	kv["oauth_state:st"] = `{"target_kind":"mcp_instance","connection_id":"i1","user_id":"owner","workspace_id":"w","workspace_slug":"acme"}`
	resp, _ = rawCall(t, s, "GET", "/v1/oauth/callback?state=st&code=c", "")
	loc := resp.Header.Get("Location")
	if resp.StatusCode != 302 || !strings.HasPrefix(loc, "https://app.example/oauth/finish?token=") {
		t.Fatalf("callback %d %s", resp.StatusCode, loc)
	}
	if status, body := call(t, s, "POST", "/../../oauth/finish", `{"token":"x"}`); status == 200 {
		t.Fatalf("finish under a workspace %d %s", status, body)
	}
	_, body := rawCall(t, s, "POST", "/v1/oauth/finish", `{"token":"","x":1}`)
	if !strings.Contains(body, `"string_too_short"`) || !strings.Contains(body, `"extra_forbidden"`) {
		t.Fatalf("finish validation %s", body)
	}
	resp, body = rawCall(t, s, "POST", "/v1/oauth/finish", `{"token":"unknown"}`)
	if resp.StatusCode != 400 || !strings.Contains(body, "Invalid or expired OAuth sign-in") {
		t.Fatalf("finish unknown %d %s", resp.StatusCode, body)
	}
	unauth, _, _ := oauthHarness(t, false)
	if resp, _ := rawCall(t, unauth, "POST", "/v1/oauth/finish", `{"token":"x"}`); resp.StatusCode != 401 {
		t.Fatalf("finish without a session %d", resp.StatusCode)
	}
}

// A Hydra that advertises its own registration endpoint is not described at all.
func TestOAuthASRefusesForeignRegistration(t *testing.T) {
	s, _, _, hydra := oauthHarnessWithHydra(t, true, &registerLimiter{limit: 1 << 20, taken: map[string]int{}}, "http://hydra.internal/oauth2/register")
	for _, path := range []string{"/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp/w/acme", "/.well-known/oauth-authorization-server"} {
		resp, body := rawCall(t, s, "GET", path, "")
		if resp.StatusCode != http.StatusBadGateway || strings.Contains(body, hydra) {
			t.Fatalf("%s: %d %s", path, resp.StatusCode, body)
		}
	}
}

func TestOAuthASShim(t *testing.T) {
	s, _, hits, hydra := oauthHarnessWithHydra(t, true, &registerLimiter{limit: 1 << 20, taken: map[string]int{}}, "https://api.example/oauth2/register")

	resp, body := rawCall(t, s, "GET", "/.well-known/oauth-protected-resource", "")
	if resp.StatusCode != 200 || body != `{"resource":"https://api.example/mcp","authorization_servers":["`+hydra+`/"],"scopes_supported":["openid","offline_access"],"bearer_methods_supported":["header"]}` {
		t.Fatalf("protected resource %d %s", resp.StatusCode, body)
	}
	if resp, _ := rawCall(t, s, "GET", "/.well-known/oauth-protected-resource/mcp/w/acme", ""); resp.StatusCode != 200 {
		t.Fatalf("workspace resource %d", resp.StatusCode)
	}
	if resp, body := rawCall(t, s, "GET", "/.well-known/oauth-protected-resource/admin", ""); resp.StatusCode != 404 || !strings.Contains(body, "Unknown protected resource") {
		t.Fatalf("unknown resource %d %s", resp.StatusCode, body)
	}

	_, body = rawCall(t, s, "GET", "/.well-known/oauth-authorization-server", "")
	var doc map[string]any
	if err := json.Unmarshal([]byte(body), &doc); err != nil {
		t.Fatal(err)
	}
	if doc["issuer"] != hydra+"/" || doc["token_endpoint"] != hydra+"/oauth2/token" ||
		doc["registration_endpoint"] != "https://api.example/oauth2/register" || doc["jwks_uri"] != hydra+"/.well-known/jwks.json" {
		t.Fatalf("AS metadata %s", body)
	}

	resp, _ = rawCall(t, s, "GET", "/oauth2/auth?client_id=c&state=s", "")
	if resp.StatusCode != 302 || resp.Header.Get("Location") != "https://auth.example/oauth2/auth?client_id=c&state=s" {
		t.Fatalf("auth redirect %d %s", resp.StatusCode, resp.Header.Get("Location"))
	}

	resp, body = rawCall(t, s, "POST", "/oauth2/register", `{"redirect_uris":["ftp://x"]}`)
	if resp.StatusCode != 400 || !strings.Contains(body, `"error":"invalid_redirect_uri"`) {
		t.Fatalf("register refusal %d %s", resp.StatusCode, body)
	}
	for _, uri := range []string{"https://*.evil.example/cb", "https://*/cb", "https://evil.example/cb#frag",
		"https://user:pass@evil.example/cb", "https://app.agentarea.example@evil.example/cb", "https:///cb"} {
		resp, body = rawCall(t, s, "POST", "/oauth2/register", `{"redirect_uris":["`+uri+`"]}`)
		if resp.StatusCode != 400 || !strings.Contains(body, `"error":"invalid_redirect_uri"`) {
			t.Fatalf("callback %s: %d %s", uri, resp.StatusCode, body)
		}
	}
	for _, uri := range []string{"https://claude.ai/api/mcp/auth_callback", "http://localhost:3118/callback",
		"http://127.0.0.1:50285/callback/mchcrPoY4sxk", "http://[::1]:8080/cb"} {
		if resp, body := rawCall(t, s, "POST", "/oauth2/register", `{"redirect_uris":["`+uri+`"]}`); resp.StatusCode != 201 {
			t.Fatalf("callback %s: %d %s", uri, resp.StatusCode, body)
		}
	}
	resp, body = rawCall(t, s, "POST", "/oauth2/register", `{"redirect_uris":["http://127.0.0.1:9/cb"],"scope":"openid"}`)
	if resp.StatusCode != 201 || !strings.Contains(body, `"audience":["https://api.example"]`) {
		t.Fatalf("register %d %s", resp.StatusCode, body)
	}
	// Python read an anonymous registration body of any size into memory.
	big := `{"client_name":"` + strings.Repeat("x", registerMaxBody) + `"}`
	if resp, body := rawCall(t, s, "POST", "/oauth2/register", big); resp.StatusCode != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized register %d %s", resp.StatusCode, body)
	}

	resp, body = rawCall(t, s, "POST", "/oauth2/token?x=1", "grant_type=refresh_token")
	if resp.StatusCode != http.StatusTeapot || body != "hydra:/oauth2/token?x=1" || resp.Header.Get("X-Hydra") != "1" {
		t.Fatalf("proxy %d %s", resp.StatusCode, body)
	}
	resp, body = rawCall(t, s, "GET", "/oauth2/a%2F..%2Fadmin", "")
	if resp.StatusCode != 400 || body != `{"error":"invalid_request","error_description":"invalid oauth2 path"}` {
		t.Fatalf("unsafe path %d %s", resp.StatusCode, body)
	}
	if resp, body := rawCall(t, s, "GET", "/.well-known/jwks.json", ""); resp.StatusCode != http.StatusTeapot || body != "hydra:/.well-known/jwks.json" {
		t.Fatalf("jwks %d %s", resp.StatusCode, body)
	}
	for _, h := range *hits {
		if strings.Contains(h, "admin/clients") && !strings.HasPrefix(h, "POST") {
			t.Fatalf("hydra admin hit %s", h)
		}
	}
}

// Anonymous client registration is limited per client address; the refusal
// is the edge's 429 with Retry-After, and Hydra is not asked.
func TestOAuthRegisterIsRateLimitedPerAddress(t *testing.T) {
	limiter := &registerLimiter{limit: 2, taken: map[string]int{}}
	s, _, hits := oauthHarnessLimited(t, true, limiter)
	reg := `{"redirect_uris":["https://claude.ai/api/mcp/auth_callback"]}`
	for range 2 {
		if resp, body := rawCall(t, s, "POST", "/oauth2/register", reg); resp.StatusCode != 201 {
			t.Fatalf("register %d %s", resp.StatusCode, body)
		}
	}
	before := len(*hits)
	resp, body := rawCall(t, s, "POST", "/oauth2/register", reg)
	if resp.StatusCode != http.StatusTooManyRequests || resp.Header.Get("Retry-After") != "6" || !strings.Contains(body, "Rate limit exceeded") {
		t.Fatalf("over the limit %d %q %s", resp.StatusCode, resp.Header.Get("Retry-After"), body)
	}
	if len(*hits) != before {
		t.Fatalf("a limited registration reached Hydra: %v", (*hits)[before:])
	}
	if len(limiter.taken) != 1 || limiter.taken["ip:127.0.0.1"] != 3 {
		t.Fatalf("buckets %v", limiter.taken)
	}
}
