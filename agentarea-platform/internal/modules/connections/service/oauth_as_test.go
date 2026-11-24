package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// Hydra's discovery document is fetched once for every anonymous metadata
// request within its TTL; a failed fetch is not remembered.
func TestHydraDiscoveryIsCachedBriefly(t *testing.T) {
	ctx := context.Background()
	var hits atomic.Int32
	var down atomic.Bool
	down.Store(true)
	hydra := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/.well-known/openid-configuration" {
			http.NotFound(w, r)
			return
		}
		hits.Add(1)
		if down.Load() {
			http.Error(w, "down", http.StatusServiceUnavailable)
			return
		}
		base := "http://" + r.Host
		_, _ = w.Write([]byte(`{"issuer":"` + base + `","registration_endpoint":"https://api.example/oauth2/register","token_endpoint":"` + base + `/oauth2/token"}`))
	}))
	t.Cleanup(hydra.Close)
	f := newOAuthFixture(t, nil, Config{HydraURL: hydra.URL, OAuthScopes: []string{"openid"}})

	if _, err := f.svc.AuthorizationServerMetadata(ctx); err == nil {
		t.Fatal("metadata while Hydra is down")
	}
	if _, err := f.svc.ProtectedResource(ctx, "mcp"); err == nil {
		t.Fatal("protected resource while Hydra is down")
	}
	if n := hits.Load(); n != 2 {
		t.Fatalf("a failed discovery was cached: %d fetches", n)
	}

	down.Store(false)
	if _, err := f.svc.AuthorizationServerMetadata(ctx); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for range 8 {
		wg.Go(func() {
			if _, err := f.svc.AuthorizationServerMetadata(ctx); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	doc, err := f.svc.ProtectedResource(ctx, "mcp")
	if err != nil {
		t.Fatal(err)
	}
	if as, _ := doc.Get("authorization_servers"); as.([]any)[0] != hydra.URL {
		t.Fatalf("protected resource %v", doc)
	}
	if n := hits.Load(); n != 3 {
		t.Fatalf("%d fetches for requests within the TTL, want 1 more", n-2)
	}

	f.now = f.now.Add(5*time.Minute + time.Second)
	if _, err := f.svc.AuthorizationServerMetadata(ctx); err != nil {
		t.Fatal(err)
	}
	if n := hits.Load(); n != 4 {
		t.Fatalf("an expired discovery was not refetched: %d fetches", n)
	}
}

func hydraServing(t *testing.T, doc func(base string) map[string]any) string {
	t.Helper()
	hydra := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/.well-known/openid-configuration" {
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(doc("http://" + r.Host))
	}))
	t.Cleanup(hydra.Close)
	return hydra.URL
}

// One issuer: the API serves Hydra's metadata unchanged, and its protected
// resources name Hydra as their authorization server.
func TestAuthorizationServerIsHydraUnchanged(t *testing.T) {
	ctx := context.Background()
	hydra := hydraServing(t, func(base string) map[string]any {
		return map[string]any{
			"issuer": base + "/", "authorization_endpoint": base + "/oauth2/auth", "token_endpoint": base + "/oauth2/token",
			"jwks_uri": base + "/.well-known/jwks.json", "userinfo_endpoint": base + "/userinfo",
			"registration_endpoint": "https://api.example/oauth2/register",
		}
	})
	f := newOAuthFixture(t, nil, Config{HydraURL: hydra, OAuthScopes: []string{"openid"}})

	doc, err := f.svc.AuthorizationServerMetadata(ctx)
	if err != nil {
		t.Fatal(err)
	}
	got, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	want, _ := json.Marshal(map[string]any{
		"issuer": hydra + "/", "authorization_endpoint": hydra + "/oauth2/auth", "token_endpoint": hydra + "/oauth2/token",
		"jwks_uri": hydra + "/.well-known/jwks.json", "userinfo_endpoint": hydra + "/userinfo",
		"registration_endpoint": "https://api.example/oauth2/register",
	})
	var gotMap, wantMap map[string]any
	_ = json.Unmarshal(got, &gotMap)
	_ = json.Unmarshal(want, &wantMap)
	if len(gotMap) != len(wantMap) {
		t.Fatalf("metadata %s, want %s", got, want)
	}
	for k, v := range wantMap {
		if gotMap[k] != v {
			t.Fatalf("metadata %s, want %s", got, want)
		}
	}
	doc.Set("issuer", "changed")
	again, err := f.svc.AuthorizationServerMetadata(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if issuer, _ := again.Get("issuer"); issuer != hydra+"/" {
		t.Fatalf("a caller's change reached the cached discovery document: issuer %v", issuer)
	}
	pr, err := f.svc.ProtectedResource(ctx, "mcp/w/acme")
	if err != nil {
		t.Fatal(err)
	}
	if as, _ := pr.Get("authorization_servers"); len(as.([]any)) != 1 || as.([]any)[0] != hydra+"/" {
		t.Fatalf("authorization_servers %v, want the issuer as Hydra names it", as)
	}
	if res, _ := pr.Get("resource"); res != "https://api.example/mcp/w/acme" {
		t.Fatalf("resource %v", res)
	}
}

// A Hydra that advertises any registration endpoint but this API's sends
// every client to a registration that does not exist: refuse to describe it.
func TestAuthorizationServerRequiresOurRegistration(t *testing.T) {
	ctx := context.Background()
	for name, doc := range map[string]func(base string) map[string]any{
		"hydra's own": func(base string) map[string]any {
			return map[string]any{"issuer": base, "registration_endpoint": base + "/oauth2/register"}
		},
		"none": func(base string) map[string]any { return map[string]any{"issuer": base} },
		"no issuer": func(string) map[string]any {
			return map[string]any{"registration_endpoint": "https://api.example/oauth2/register"}
		},
	} {
		t.Run(name, func(t *testing.T) {
			f := newOAuthFixture(t, nil, Config{HydraURL: hydraServing(t, doc), OAuthScopes: []string{"openid"}})
			_, err := f.svc.AuthorizationServerMetadata(ctx)
			if err == nil {
				t.Fatal("metadata for a misconfigured Hydra")
			}
			if _, prErr := f.svc.ProtectedResource(ctx, "mcp"); prErr == nil {
				t.Fatal("protected resource for a misconfigured Hydra")
			}
			if name != "no issuer" && !strings.Contains(err.Error(), "client_registration_url") {
				t.Fatalf("error does not say how to fix it: %v", err)
			}
		})
	}
}
