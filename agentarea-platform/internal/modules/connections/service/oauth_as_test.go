package service

import (
	"context"
	"net/http"
	"net/http/httptest"
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
		_, _ = w.Write([]byte(`{"issuer":"` + base + `","registration_endpoint":"` + base + `/oauth2/register","token_endpoint":"` + base + `/oauth2/token"}`))
	}))
	t.Cleanup(hydra.Close)
	f := newOAuthFixture(t, nil, Config{HydraURL: hydra.URL, OAuthScopes: []string{"openid"}})

	if _, err := f.svc.AuthorizationServerMetadata(ctx); err == nil {
		t.Fatal("metadata while Hydra is down")
	}
	f.svc.ProtectedResource(ctx, "mcp")
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
	doc := f.svc.ProtectedResource(ctx, "mcp")
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
