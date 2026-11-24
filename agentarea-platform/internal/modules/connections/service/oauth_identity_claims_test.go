package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
)

func kratosWith(t *testing.T, identities map[string]any) string {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id, ok := identities[strings.TrimPrefix(r.URL.Path, "/admin/identities/")]
		if !ok {
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(id)
	}))
	t.Cleanup(srv.Close)
	return srv.URL
}

func TestIdentityClaimsFollowTheGrantedScopes(t *testing.T) {
	ann := map[string]any{
		"traits": map[string]any{
			"email": "Ann@Example.com", "name": map[string]any{"first": "Ann", "last": "Lee"},
			"username": "ann", "picture": "https://cdn.example/ann.png",
		},
		"verifiable_addresses": []any{map[string]any{"value": "ann@example.com", "via": "email", "verified": true}},
	}
	unverified := map[string]any{"traits": ann["traits"], "verifiable_addresses": []any{map[string]any{"value": "ann@example.com", "via": "email", "verified": false}}}
	bare := map[string]any{"traits": map[string]any{"email": "b@example.com", "name": map[string]any{"first": " ", "last": ""}}}
	svc := newOAuthFixture(t, nil, Config{KratosAdminURL: kratosWith(t, map[string]any{"ann": ann, "unverified": unverified, "bare": bare})}).svc
	cases := []struct {
		user   string
		scopes []string
		want   map[string]any
	}{
		{"ann", []string{"openid", "email"}, map[string]any{"email": "Ann@Example.com", "email_verified": true}},
		{"ann", []string{"openid", "profile"}, map[string]any{
			"name": "Ann Lee", "given_name": "Ann", "family_name": "Lee",
			"preferred_username": "ann", "picture": "https://cdn.example/ann.png",
		}},
		{"ann", []string{"openid", "offline_access"}, map[string]any{}},
		{"unverified", []string{"email"}, map[string]any{"email": "Ann@Example.com", "email_verified": false}},
		{"bare", []string{"email", "profile"}, map[string]any{"email": "b@example.com", "email_verified": false}},
	}
	for _, c := range cases {
		got, err := svc.identityClaims(context.Background(), c.user, c.scopes)
		if err != nil || !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s %v: %v %v", c.user, c.scopes, got, err)
		}
	}
	if _, err := svc.identityClaims(context.Background(), "nobody", []string{"email"}); err == nil {
		t.Fatal("an identity Kratos does not have gave claims")
	}
}

func TestAcceptConsentPutsIdentityClaimsInTheIDToken(t *testing.T) {
	ctx := context.Background()
	svc, h := consentFixture(t, "agentarea-desktop", "api openid offline_access offline email profile", []any{"openid", "email"})
	svc.d.Config.KratosAdminURL = kratosWith(t, map[string]any{"u1": map[string]any{
		"traits": map[string]any{"email": "u1@example.com"},
	}})
	if _, err := svc.AcceptConsent(ctx, "u1", "ch-1", nil); err != nil {
		t.Fatal(err)
	}
	accept := h.bodies["PUT /admin/oauth2/auth/requests/consent/accept"].(map[string]any)
	want := map[string]any{"id_token": map[string]any{"email": "u1@example.com", "email_verified": false}}
	if !reflect.DeepEqual(accept["session"], want) || !reflect.DeepEqual(accept["grant_scope"], []any{"api", "openid", "email"}) {
		t.Fatalf("accept body %v", accept)
	}
}
