package service

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"testing"
)

func TestConsentGrantFollowsTheClientNotItsRequest(t *testing.T) {
	cases := []struct {
		client    string
		requested []string
		access    string
		scopes    []string
	}{
		{"dcr-1", []string{"openid", "offline_access"}, "mcp", []string{"mcp", "openid", "offline_access"}},
		{"dcr-1", []string{"api", "credentials", "offline"}, "mcp", []string{"mcp", "offline"}},
		{"dcr-1", nil, "mcp", []string{"mcp"}},
		{"https://client.example/meta.json", []string{"mcp", "mcp"}, "mcp", []string{"mcp"}},
		{"agentarea-cli", []string{"openid", "offline_access"}, "api", []string{"api", "openid", "offline_access"}},
		{"agentarea-desktop", []string{"mcp"}, "api", []string{"api"}},
	}
	for _, c := range cases {
		access, scopes := ConsentGrant(c.client, c.requested)
		if access != c.access || !reflect.DeepEqual(scopes, c.scopes) {
			t.Errorf("%s %v: %s %v", c.client, c.requested, access, scopes)
		}
	}
}

type fakeHydraAdmin struct {
	mu      sync.Mutex
	request map[string]any
	gone    bool
	calls   []string
	bodies  map[string]any
}

func (h *fakeHydraAdmin) serve(t *testing.T) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h.mu.Lock()
		defer h.mu.Unlock()
		key := r.Method + " " + r.URL.Path
		h.calls = append(h.calls, key)
		raw, _ := io.ReadAll(r.Body)
		if len(raw) > 0 {
			var v any
			_ = json.Unmarshal(raw, &v)
			h.bodies[key] = v
		}
		if r.URL.Path != "/admin/clients/"+h.request["client"].(map[string]any)["client_id"].(string) && r.URL.Query().Get("consent_challenge") != "ch-1" {
			http.NotFound(w, r)
			return
		}
		switch {
		case h.gone:
			w.WriteHeader(http.StatusGone)
		case key == "GET /admin/oauth2/auth/requests/consent":
			_ = json.NewEncoder(w).Encode(h.request)
		case strings.HasPrefix(key, "PUT /admin/oauth2/auth/requests/consent/"):
			_, _ = w.Write([]byte(`{"redirect_to":"https://hydra.example/oauth2/auth?consent_verifier=v"}`))
		case strings.HasPrefix(key, "PATCH /admin/clients/"):
			_, _ = w.Write([]byte(`{}`))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func consentFixture(t *testing.T, clientID, clientScope string, requested []any) (*Service, *fakeHydraAdmin) {
	h := &fakeHydraAdmin{bodies: map[string]any{}, request: map[string]any{
		"subject": "u1", "requested_scope": requested, "requested_access_token_audience": []any{},
		"client": map[string]any{"client_id": clientID, "client_name": "Cursor", "scope": clientScope, "audience": []any{"https://api.example"},
			"redirect_uris": []any{"http://127.0.0.1:9/cb"}},
	}}
	srv := h.serve(t)
	return newOAuthFixture(t, nil, Config{HydraAdminURL: srv.URL}).svc, h
}

func TestAcceptConsentBindsAThirdPartyToOneWorkspace(t *testing.T) {
	ctx := context.Background()
	svc, h := consentFixture(t, "dcr-1", "offline offline_access openid", []any{"openid", "offline_access", "api"})

	view, err := svc.Consent(ctx, "u1", "ch-1")
	if err != nil || view.Access != "mcp" || view.FirstParty || view.Client.Name != "Cursor" || view.Client.Scope != "" ||
		view.RedirectURI != "http://127.0.0.1:9/cb" {
		t.Fatalf("%+v %v", view, err)
	}
	h.request["request_url"] = "https://hydra.example/oauth2/auth?client_id=dcr-1&redirect_uri=https%3A%2F%2Fevil.example%2Fcb"
	if view, _ := svc.Consent(ctx, "u1", "ch-1"); view.RedirectURI != "https://evil.example/cb" {
		t.Fatalf("the requested redirect_uri was not read: %q", view.RedirectURI)
	}
	if _, err := svc.AcceptConsent(ctx, "u1", "ch-1", nil); !errors.Is(err, ErrConsentNeedsWorkspace) {
		t.Fatalf("accepted without a workspace: %v", err)
	}
	to, err := svc.AcceptConsent(ctx, "u1", "ch-1", []string{"ws-1", "ws-2"})
	if err != nil || !strings.Contains(to, "consent_verifier") {
		t.Fatalf("%q %v", to, err)
	}
	patch := h.bodies["PATCH /admin/clients/dcr-1"]
	want := []any{map[string]any{"op": "replace", "path": "/scope", "value": "offline offline_access openid mcp"}}
	if !reflect.DeepEqual(patch, want) {
		t.Fatalf("client scope patch %v", patch)
	}
	accept := h.bodies["PUT /admin/oauth2/auth/requests/consent/accept"].(map[string]any)
	if !reflect.DeepEqual(accept["grant_scope"], []any{"mcp", "openid", "offline_access"}) ||
		!reflect.DeepEqual(accept["grant_access_token_audience"], []any{"https://api.example"}) ||
		!reflect.DeepEqual(accept["session"], map[string]any{"access_token": map[string]any{"workspace_ids": []any{"ws-1", "ws-2"}}}) ||
		accept["remember"] != false {
		t.Fatalf("accept body %v", accept)
	}
}

func TestAcceptConsentGivesAFirstPartyTheAccount(t *testing.T) {
	ctx := context.Background()
	svc, h := consentFixture(t, "agentarea-cli", "api offline_access openid", []any{"openid", "offline_access"})
	if _, err := svc.AcceptConsent(ctx, "u1", "ch-1", []string{"ws-ignored"}); err != nil {
		t.Fatal(err)
	}
	accept := h.bodies["PUT /admin/oauth2/auth/requests/consent/accept"].(map[string]any)
	if !reflect.DeepEqual(accept["grant_scope"], []any{"api", "openid", "offline_access"}) || accept["session"] != nil {
		t.Fatalf("accept body %v", accept)
	}
	for _, c := range h.calls {
		if strings.HasPrefix(c, "PATCH") {
			t.Fatalf("a client already allowed its grant was patched: %v", h.calls)
		}
	}
}

func TestConsentBelongsToItsSubject(t *testing.T) {
	ctx := context.Background()
	svc, h := consentFixture(t, "dcr-1", "mcp openid", []any{"openid"})
	if _, err := svc.Consent(ctx, "u2", "ch-1"); !errors.Is(err, ErrConsentNotYours) {
		t.Fatalf("another user read the consent: %v", err)
	}
	if _, err := svc.AcceptConsent(ctx, "u2", "ch-1", []string{"ws-1"}); !errors.Is(err, ErrConsentNotYours) {
		t.Fatalf("another user accepted: %v", err)
	}
	if _, err := svc.RejectConsent(ctx, "", "ch-1"); !errors.Is(err, ErrConsentNotYours) {
		t.Fatalf("nobody rejected: %v", err)
	}
	for _, c := range h.calls {
		if c != "GET /admin/oauth2/auth/requests/consent" {
			t.Fatalf("a refused consent reached Hydra: %v", h.calls)
		}
	}
	if _, err := svc.Consent(ctx, "u1", "other"); !errors.Is(err, ErrConsentNotFound) {
		t.Fatalf("unknown challenge: %v", err)
	}
	h.gone = true
	if _, err := svc.AcceptConsent(ctx, "u1", "ch-1", []string{"ws-1"}); !errors.Is(err, ErrConsentNotFound) {
		t.Fatalf("used challenge: %v", err)
	}
}

func TestRejectConsent(t *testing.T) {
	svc, h := consentFixture(t, "dcr-1", "mcp", []any{"openid"})
	to, err := svc.RejectConsent(context.Background(), "u1", "ch-1")
	if err != nil || to == "" {
		t.Fatalf("%q %v", to, err)
	}
	body := h.bodies["PUT /admin/oauth2/auth/requests/consent/reject"].(map[string]any)
	if body["error"] != "access_denied" {
		t.Fatalf("%v", body)
	}
}

func TestEnsureFirstPartyClientsCreatesThenRewrites(t *testing.T) {
	var mu sync.Mutex
	stored := map[string]map[string]any{}
	var calls []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		calls = append(calls, r.Method+" "+r.URL.Path)
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		id := strings.TrimPrefix(r.URL.Path, "/admin/clients/")
		switch {
		case r.Method == http.MethodPut && stored[id] == nil:
			w.WriteHeader(http.StatusNotFound)
		case r.Method == http.MethodPut:
			stored[id] = body
		case r.Method == http.MethodPost && r.URL.Path == "/admin/clients":
			stored[body["client_id"].(string)] = body
			w.WriteHeader(http.StatusCreated)
		default:
			w.WriteHeader(http.StatusBadRequest)
		}
	}))
	t.Cleanup(srv.Close)
	ctx := context.Background()
	if err := EnsureFirstPartyClients(ctx, srv.Client(), srv.URL+"/", "https://api.example"); err != nil {
		t.Fatal(err)
	}
	if err := EnsureFirstPartyClients(ctx, srv.Client(), srv.URL, "https://api.example"); err != nil {
		t.Fatal(err)
	}
	want := []string{
		"PUT /admin/clients/agentarea-cli", "POST /admin/clients", "PUT /admin/clients/agentarea-desktop", "POST /admin/clients",
		"PUT /admin/clients/agentarea-cli", "PUT /admin/clients/agentarea-desktop",
	}
	if !reflect.DeepEqual(calls, want) {
		t.Fatalf("calls %v", calls)
	}
	cli := stored["agentarea-cli"]
	if cli["scope"] != "api openid offline_access offline email profile" || cli["token_endpoint_auth_method"] != "none" ||
		!reflect.DeepEqual(cli["audience"], []any{"https://api.example"}) || cli["skip_consent"] != false ||
		!reflect.DeepEqual(cli["redirect_uris"], []any{"http://127.0.0.1/callback"}) {
		t.Fatalf("cli client %v", cli)
	}

	failing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusInternalServerError) }))
	t.Cleanup(failing.Close)
	if err := EnsureFirstPartyClients(ctx, failing.Client(), failing.URL, "https://api.example"); err == nil {
		t.Fatal("a Hydra failure passed")
	}
}
