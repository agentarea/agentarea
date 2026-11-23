package service

import (
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"

	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// fakeGitHub is the GitHub REST API a GitHub App's connections talk to:
// the user's installations of the app and the installation tokens it mints.
type fakeGitHub struct {
	srv    *httptest.Server
	key    *rsa.PrivateKey
	appID  string
	now    func() time.Time
	mu     sync.Mutex
	bodies []string
	mints  atomic.Int32
	// installations the user token "ghu" reaches, by id: account login and the app they belong to.
	installations map[int64][2]string
	repos         map[int64][]string
}

func newFakeGitHub(t *testing.T, now func() time.Time) *fakeGitHub {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	g := &fakeGitHub{key: key, appID: "42", now: now,
		installations: map[int64][2]string{7: {"acme", "42"}, 8: {"octo", "42"}, 9: {"other-app-org", "99"}},
		repos:         map[int64][]string{7: {"api", "web"}, 8: {"dots"}},
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /user/installations", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer ghu" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		var list []map[string]any
		for id, v := range g.installations {
			list = append(list, map[string]any{"id": id, "app_id": json.Number(v[1]), "repository_selection": "selected",
				"account": map[string]any{"login": v[0], "type": "Organization"}})
		}
		page, _ := strconv.Atoi(r.URL.Query().Get("page"))
		if page > 1 {
			list = nil
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"total_count": len(g.installations), "installations": list})
	})
	mux.HandleFunc("GET /user/installations/{id}/repositories", func(w http.ResponseWriter, r *http.Request) {
		id, _ := strconv.ParseInt(r.PathValue("id"), 10, 64)
		if r.Header.Get("Authorization") != "Bearer ghu" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		names, ok := g.repos[id]
		if !ok {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		// One repository per page: the listing must follow the pages.
		page, _ := strconv.Atoi(r.URL.Query().Get("page"))
		var list []map[string]any
		if page >= 1 && page <= len(names) {
			n := names[page-1]
			list = append(list, map[string]any{"name": n, "full_name": g.installations[id][0] + "/" + n, "private": true})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"total_count": len(names), "repositories": list})
	})
	mux.HandleFunc("POST /app/installations/{id}/access_tokens", func(w http.ResponseWriter, r *http.Request) {
		if err := g.verifyJWT(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")); err != nil {
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = io.WriteString(w, err.Error())
			return
		}
		body, _ := io.ReadAll(r.Body)
		g.mu.Lock()
		g.bodies = append(g.bodies, string(body))
		g.mu.Unlock()
		n := g.mints.Add(1)
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"token": fmt.Sprintf("ghs_%s_%d", r.PathValue("id"), n), "expires_at": g.now().Add(time.Hour).Format(time.RFC3339),
		})
	})
	g.srv = httptest.NewTLSServer(mux)
	t.Cleanup(g.srv.Close)
	return g
}

func (g *fakeGitHub) verifyJWT(tok string) error {
	parts := strings.Split(tok, ".")
	if len(parts) != 3 {
		return errors.New("not a JWT")
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return err
	}
	sum := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	if err := rsa.VerifyPKCS1v15(&g.key.PublicKey, crypto.SHA256, sum[:], sig); err != nil {
		return err
	}
	var h struct{ Alg, Typ string }
	raw, _ := base64.RawURLEncoding.DecodeString(parts[0])
	if json.Unmarshal(raw, &h) != nil || h.Alg != "RS256" {
		return errors.New("header " + string(raw))
	}
	var c struct {
		Iat, Exp int64
		Iss      json.Number
	}
	raw, _ = base64.RawURLEncoding.DecodeString(parts[1])
	if err := json.Unmarshal(raw, &c); err != nil {
		return err
	}
	now := g.now().Unix()
	if c.Iss.String() != g.appID || c.Iat > now || c.Exp <= now || c.Exp-c.Iat > 600 {
		return errors.New("claims " + string(raw))
	}
	return nil
}

func (g *fakeGitHub) app() OAuthApp {
	return OAuthApp{Issuer: "https://gh", ClientID: "pid", ClientSecret: "psec", TokenEndpoint: g.srv.URL + "/token",
		ResourceOrigins: []string{"https://mcp.gh"}, AppID: json.Number(g.appID), APIURL: g.srv.URL, InstallationKey: g.key}
}

type installFixture struct {
	*oauthFixture
	gh     *fakeGitHub
	instID uuid.UUID
	authID uuid.UUID
}

// newInstallFixture is an MCP instance signed in through a GitHub App with
// installation tokens: its user token is "ghu".
func newInstallFixture(t *testing.T, mints bool) *installFixture {
	t.Helper()
	var f *oauthFixture
	gh := newFakeGitHub(t, func() time.Time { return f.now })
	app := gh.app()
	if !mints {
		app.InstallationKey = nil
	}
	f = newOAuthFixture(t, &oauthProvider{srv: gh.srv}, Config{OAuthApps: []OAuthApp{app}})
	inst := uuid.New()
	f.specs.rows["spec-1"] = catalogapi.MCPSpec{ID: "spec-1", JSONSpec: map[string]any{}}
	auth := f.oauthConfig(t, map[string]any{"credential_mode": "managed", "platform_oauth_issuer": "https://gh", "token_url": gh.srv.URL + "/token"},
		map[string]any{"access_token": "ghu", "refresh_token": "ghr", "expires_at": float64(f.now.Unix() + 8*3600)})
	a := auth.String()
	f.inst.rows[inst] = domain.Instance{ID: inst.String(), ServerSpecID: "spec-1", Transport: domain.TransportURL,
		JSONSpec: map[string]any{"endpoint_url": "https://mcp.gh/mcp"}, AuthConfigID: &a}
	return &installFixture{oauthFixture: f, gh: gh, instID: inst, authID: auth}
}

func (f *installFixture) target() OAuthTarget { return OAuthTarget{InstanceID: &f.instID} }

func (f *installFixture) header(t *testing.T, force bool) string {
	t.Helper()
	h, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, f.authID, "https://mcp.gh/mcp", force)
	if err != nil {
		t.Fatal(err)
	}
	return h["Authorization"]
}

func oauthStatus(err error) int {
	var oe *OAuthError
	if errors.As(err, &oe) {
		return oe.Status
	}
	return 0
}

func TestAppJWT(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	gh := newFakeGitHub(t, func() time.Time { return now })
	app := gh.app()
	tok, err := appJWT(&app, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := gh.verifyJWT(tok); err != nil {
		t.Fatalf("jwt %s: %v", tok, err)
	}
	other, _ := rsa.GenerateKey(rand.Reader, 2048)
	app.InstallationKey = other
	tok, _ = appJWT(&app, now)
	if gh.verifyJWT(tok) == nil {
		t.Fatal("a JWT signed with another key verified")
	}
}

func TestListInstallationsOfTheApp(t *testing.T) {
	f := newInstallFixture(t, true)
	ctx := context.Background()
	got, err := f.svc.OAuthInstallations(ctx, f.caller, f.target())
	if err != nil {
		t.Fatal(err)
	}
	var accounts []string
	for _, i := range got {
		accounts = append(accounts, fmt.Sprint(i.ID, i.Account, i.AccountType, i.RepositorySelection))
	}
	if strings.Join(accounts, ",") != "7acmeOrganizationselected,8octoOrganizationselected" {
		t.Fatalf("installations %v: want only the app's own, sorted", accounts)
	}
	repos, err := f.svc.OAuthInstallationRepositories(ctx, f.caller, f.target(), 7)
	if err != nil || len(repos) != 2 || repos[0].Name != "api" || repos[1].FullName != "acme/web" || !repos[1].Private {
		t.Fatalf("repositories %+v err %v", repos, err)
	}
	if _, err := f.svc.OAuthInstallationRepositories(ctx, f.caller, f.target(), 9); oauthStatus(err) != 404 {
		t.Fatalf("another app's installation: err %v, want 404", err)
	}
}

func TestInstallationsNeedAnAppThatMintsThem(t *testing.T) {
	f := newInstallFixture(t, false)
	ctx := context.Background()
	if _, err := f.svc.OAuthInstallations(ctx, f.caller, f.target()); oauthStatus(err) != 409 {
		t.Fatalf("err %v, want 409", err)
	}
	pf, err := f.svc.OAuthPreflight(ctx, f.caller, f.target())
	if err != nil || pf.InstallationBindingAvailable || pf.InstallationBinding != nil {
		t.Fatalf("preflight %+v err %v", pf, err)
	}
}

func TestBindRefusesWhatTheUserCannotReach(t *testing.T) {
	f := newInstallFixture(t, true)
	ctx := context.Background()
	for _, req := range []InstallationBindingRequest{
		{InstallationID: 9},
		{InstallationID: 12345},
		{InstallationID: 7, Repositories: []string{"api", "dots"}},
		{InstallationID: 7, Repositories: []string{"acme/api"}},
	} {
		if _, err := f.svc.BindOAuthInstallation(ctx, f.caller, f.target(), &req); oauthStatus(err) != 422 {
			t.Fatalf("bind %+v: err %v, want 422", req, err)
		}
		if _, ok := f.auth.rows[f.authID].Config["installation_id"]; ok {
			t.Fatalf("bind %+v was stored", req)
		}
	}
	if f.gh.mints.Load() != 0 {
		t.Fatal("a refused bind minted a token")
	}
}

func TestBoundConnectionSendsAnInstallationToken(t *testing.T) {
	f := newInstallFixture(t, true)
	ctx := context.Background()
	if h := f.header(t, false); h != "Bearer ghu" {
		t.Fatalf("unbound: %q, want the user token", h)
	}
	b, err := f.svc.BindOAuthInstallation(ctx, f.caller, f.target(), &InstallationBindingRequest{InstallationID: 7, Repositories: []string{"web", "web"}})
	if err != nil || b == nil || b.InstallationID != 7 || b.Account != "acme" || strings.Join(b.Repositories, ",") != "web" {
		t.Fatalf("binding %+v err %v", b, err)
	}
	pf, err := f.svc.OAuthPreflight(ctx, f.caller, f.target())
	if err != nil || !pf.InstallationBindingAvailable || pf.InstallationBinding == nil || pf.InstallationBinding.Account != "acme" {
		t.Fatalf("preflight %+v err %v", pf, err)
	}

	var wg sync.WaitGroup
	for range 8 {
		wg.Add(1)
		go func() { defer wg.Done(); f.header(t, false) }()
	}
	wg.Wait()
	if h := f.header(t, false); h != "Bearer ghs_7_1" || f.gh.mints.Load() != 1 {
		t.Fatalf("header %q after %d mints, want one cached token", h, f.gh.mints.Load())
	}
	if f.gh.bodies[0] != `{"repositories":["web"]}` {
		t.Fatalf("mint body %q", f.gh.bodies[0])
	}

	f.now = f.now.Add(50 * time.Minute)
	if h := f.header(t, false); h != "Bearer ghs_7_1" {
		t.Fatalf("still valid: %q", h)
	}
	f.now = f.now.Add(6 * time.Minute)
	if h := f.header(t, false); h != "Bearer ghs_7_2" {
		t.Fatalf("near expiry: %q, want a fresh token", h)
	}
	if h := f.header(t, true); h != "Bearer ghs_7_3" {
		t.Fatalf("forced: %q, want a fresh token", h)
	}

	if _, err := f.svc.BindOAuthInstallation(ctx, f.caller, f.target(), &InstallationBindingRequest{InstallationID: 8}); err != nil {
		t.Fatal(err)
	}
	if h := f.header(t, false); h != "Bearer ghs_8_4" || f.gh.bodies[3] != "" {
		t.Fatalf("all repositories: header %q body %q, want no body", h, f.gh.bodies[3])
	}

	if b, err := f.svc.BindOAuthInstallation(ctx, f.caller, f.target(), nil); err != nil || b != nil {
		t.Fatalf("clear: %+v %v", b, err)
	}
	if h := f.header(t, false); h != "Bearer ghu" {
		t.Fatalf("cleared: %q, want the user token", h)
	}
	if _, err := f.svc.AuthHeaders(ctx, f.caller.Workspace, f.authID, "https://evil/mcp", false); err == nil {
		t.Fatal("resource_origins no longer enforced")
	}
}

// A binding outlives the user's access to the installation only until the
// next token: each mint checks the installation is still theirs.
func TestBoundConnectionStopsWhenTheUserLosesTheInstallation(t *testing.T) {
	f := newInstallFixture(t, true)
	ctx := context.Background()
	if _, err := f.svc.BindOAuthInstallation(ctx, f.caller, f.target(), &InstallationBindingRequest{InstallationID: 7}); err != nil {
		t.Fatal(err)
	}
	f.header(t, false)
	delete(f.gh.installations, 7)
	f.now = f.now.Add(time.Hour)
	var ra *domain.ReauthRequired
	if _, err := f.svc.AuthHeaders(ctx, f.caller.Workspace, f.authID, "https://mcp.gh/mcp", false); !errors.As(err, &ra) {
		t.Fatalf("err %v, want ReauthRequired", err)
	}
}

// A bound connection whose app can no longer mint installation tokens fails
// rather than send the broader user token.
func TestBindingWithoutTheAppFailsClosed(t *testing.T) {
	f := newInstallFixture(t, true)
	if _, err := f.svc.BindOAuthInstallation(context.Background(), f.caller, f.target(), &InstallationBindingRequest{InstallationID: 7}); err != nil {
		t.Fatal(err)
	}
	f.svc.d.Config.OAuthApps[0].InstallationKey = nil
	if _, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, f.authID, "https://mcp.gh/mcp", false); err == nil {
		t.Fatal("a bound connection fell back to the user token")
	}
}

// Signing in again keeps the connection on its installation.
func TestReconnectKeepsTheBinding(t *testing.T) {
	cfg := map[string]any{}
	carryInstallationBinding(&domain.AuthConfig{Config: map[string]any{"credential_mode": "managed", "platform_oauth_issuer": "https://gh",
		"installation_id": int64(7), "installation_account": "acme", "installation_repositories": []any{"web"}}}, "https://gh", cfg)
	if cfg["installation_id"] != int64(7) || cfg["installation_account"] != "acme" || len(domain.StringList(cfg["installation_repositories"])) != 1 {
		t.Fatalf("carried %v", cfg)
	}
	other := map[string]any{}
	carryInstallationBinding(&domain.AuthConfig{Config: map[string]any{"credential_mode": "managed", "platform_oauth_issuer": "https://other",
		"installation_id": int64(7)}}, "https://gh", other)
	if len(other) != 0 {
		t.Fatalf("carried across apps: %v", other)
	}
}
