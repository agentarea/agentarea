package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

type oaCounts struct {
	mu  sync.Mutex
	got []string
}

func (c *oaCounts) Count(name string, labels map[string]string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.got = append(c.got, name+" "+labels["provider"]+" "+labels["outcome"])
}

func (c *oaCounts) take() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := c.got
	c.got = nil
	return out
}

func wantCounts(t *testing.T, c *oaCounts, want ...string) {
	t.Helper()
	if got := c.take(); !slices.Equal(got, want) {
		t.Fatalf("counts %q, want %q", got, want)
	}
}

func TestOAuthProviderNamesOnlyPublicIssuersOfAPlatformApp(t *testing.T) {
	s := New(Deps{Stamps: NewStamps(), Verdicts: NewVerdicts(), Config: Config{OAuthApps: []OAuthApp{
		{Issuer: "https://github.com"}, {Issuer: "https://idp.internal.example"},
	}}})
	for issuer, want := range map[string]string{
		"https://github.com":           "github.com",
		"https://GitHub.com/":          "custom",
		"https://github.com/":          "github.com",
		"https://idp.internal.example": "custom",
		"https://slack.com":            "custom",
		"":                             "custom",
	} {
		if got := s.oauthProvider(issuer); got != want {
			t.Errorf("%q: %q, want %q", issuer, got, want)
		}
	}
	for code, want := range map[string]string{"access_denied": "access_denied", "invalid_grant": "invalid_grant", "Boom!": "other"} {
		if got := oauthErrorLabel(code); got != want {
			t.Errorf("%q: %q, want %q", code, got, want)
		}
	}
}

func TestConnectCountsStartAndSuccess(t *testing.T) {
	for status, want := range map[int]string{200: "succeeded", 400: "failed:token_exchange_failed"} {
		connectOnce(t, status, want)
	}
}

func connectOnce(t *testing.T, status int, want string) {
	t.Helper()
	p := newOAuthProvider(t)
	p.token = func(url.Values, *http.Request) (int, map[string]any) {
		if status != 200 {
			return status, map[string]any{"error": "invalid_grant"}
		}
		return 200, map[string]any{"access_token": "at"}
	}
	f := newOAuthFixture(t, p, Config{})
	item, conn := uuid.New(), uuid.New()
	itemID := item.String()
	f.items[item] = CatalogAPIItem{ID: item, Name: "Acme", Spec: map[string]any{
		"base_url": p.srv.URL + "/api",
		"oauth": map[string]any{"provider_key": "acme", "authorization_url": p.srv.URL + "/authorize",
			"token_url": p.srv.URL + "/token", "scopes": []any{"read"}},
	}}
	f.conns.rows[conn] = domain.Connection{ID: conn.String(), RegistryItemID: &itemID}
	ctx := context.Background()
	cid, sec := "cid", "csec"
	loc, _, err := f.svc.OAuthAuthorize(ctx, f.caller, AuthorizeRequest{
		Target: OAuthTarget{OpenAPIConnectionID: &conn}, Mode: "custom", Custom: CustomOAuthApp{ClientID: &cid, ClientSecret: &sec},
	})
	if err != nil {
		t.Fatal(err)
	}
	wantCounts(t, f.counts, "oauth_connect custom started")
	u, _ := url.Parse(loc)
	back, err := f.svc.OAuthReceive(ctx, u.Query().Get("state"), "code-1", "", "")
	if err != nil {
		t.Fatal(err)
	}
	enter := func(context.Context, string) (authn.Caller, error) { return f.caller, nil }
	if _, err := f.svc.OAuthFinish(ctx, f.caller.Principal, strings.TrimPrefix(back, "https://app.example/oauth/finish?token="), enter); err != nil {
		t.Fatal(err)
	}
	wantCounts(t, f.counts, "oauth_connect custom "+want)
}

func TestConnectFailuresAreCounted(t *testing.T) {
	p := newOAuthProvider(t)
	p.dcr = false
	f := newOAuthFixture(t, p, Config{})
	ctx := context.Background()
	id := f.urlInstance(p)
	if _, _, err := f.svc.OAuthAuthorize(ctx, f.caller, AuthorizeRequest{Target: OAuthTarget{InstanceID: &id}, Mode: "auto"}); err == nil {
		t.Fatal("authorize without an app succeeded")
	}
	wantCounts(t, f.counts, "oauth_connect custom failed:oauth_app_required")

	_, _ = f.svc.OAuthReceive(ctx, "", "", "access_denied", "")
	_, _ = f.svc.OAuthReceive(ctx, "nope", "c", "", "")
	flow, _ := json.Marshal(oauthState{TargetKind: kindMCPInstance, ConnectionID: "i1", WorkspaceSlug: "acme"})
	f.kv.m["oauth_state:s"] = string(flow)
	_, _ = f.svc.OAuthReceive(ctx, "s", "", "Boom!", "")
	f.kv.m["oauth_state:s"] = string(flow)
	_, _ = f.svc.OAuthReceive(ctx, "s", "", "", "")
	gone, _ := json.Marshal(oauthState{TargetKind: kindMCPInstance, ConnectionID: "i1"})
	f.kv.m["oauth_state:g"] = string(gone)
	_, _ = f.svc.OAuthReceive(ctx, "g", "", "access_denied", "")
	wantCounts(t, f.counts, "oauth_connect unknown failed:access_denied", "oauth_connect unknown failed:invalid_state",
		"oauth_connect unknown failed:other", "oauth_connect unknown failed:missing_code", "oauth_connect unknown failed:workspace_gone")

	returned, _ := json.Marshal(returnedFlow{Flow: oauthState{UserID: "owner", WorkspaceID: f.caller.Workspace.ID(),
		AuthConfigID: uuid.NewString(), ConnectionID: uuid.NewString()}, Code: "c"})
	f.kv.m["oauth_returned:t"] = string(returned)
	_, _ = f.svc.OAuthFinish(ctx, authn.Principal{UserID: "intruder"}, "t", nil)
	_, _ = f.svc.OAuthFinish(ctx, f.caller.Principal, "t", nil)
	f.kv.m["oauth_returned:t"] = string(returned)
	enter := func(context.Context, string) (authn.Caller, error) { return f.caller, nil }
	_, _ = f.svc.OAuthFinish(ctx, f.caller.Principal, "t", enter)
	wantCounts(t, f.counts, "oauth_connect unknown failed:other_user", "oauth_connect unknown failed:invalid_state",
		"oauth_connect unknown failed:connection_gone")
}
