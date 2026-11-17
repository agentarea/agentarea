package service

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// oaDB runs closures without a database; Lock serializes per key as the
// advisory lock does.
type oaDB struct {
	db.Database
	mu    sync.Mutex
	locks map[string]*sync.Mutex
}

func (*oaDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (*oaDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

func (d *oaDB) Lock(ctx context.Context, key db.LockKey, fn func(context.Context, db.Querier) error) error {
	d.mu.Lock()
	if d.locks == nil {
		d.locks = map[string]*sync.Mutex{}
	}
	m, ok := d.locks[key.String()]
	if !ok {
		m = &sync.Mutex{}
		d.locks[key.String()] = m
	}
	d.mu.Unlock()
	m.Lock()
	defer m.Unlock()
	return fn(ctx, nil)
}

type oaSecrets struct {
	mu     sync.Mutex
	values map[string]string
}

func (s *oaSecrets) Manager(db.Session, string) ksecrets.Manager { return oaManager{s} }

type oaManager struct{ s *oaSecrets }

func (m oaManager) Get(_ context.Context, name string) (string, error) {
	m.s.mu.Lock()
	defer m.s.mu.Unlock()
	v, ok := m.s.values[name]
	if !ok {
		return "", ksecrets.ErrNotFound
	}
	return v, nil
}
func (m oaManager) Set(_ context.Context, name, value string) error {
	m.s.mu.Lock()
	defer m.s.mu.Unlock()
	m.s.values[name] = value
	return nil
}
func (m oaManager) Delete(_ context.Context, name string) (bool, error) {
	m.s.mu.Lock()
	defer m.s.mu.Unlock()
	_, ok := m.s.values[name]
	delete(m.s.values, name)
	return ok, nil
}
func (m oaManager) Has(ctx context.Context, name string) (bool, error) {
	_, err := m.Get(ctx, name)
	return err == nil, nil
}
func (m oaManager) ExternalRef(string) (string, bool) { return "", false }

type oaAuth struct {
	AuthStore
	mu   sync.Mutex
	rows map[uuid.UUID]domain.AuthConfig
}

func (a *oaAuth) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.AuthConfig, bool, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, ok := a.rows[id]
	return r, ok, nil
}
func (a *oaAuth) SetSecretKey(_ context.Context, _ db.Session, id uuid.UUID, key string, _ time.Time) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	r := a.rows[id]
	r.SecretKey = &key
	a.rows[id] = r
	return nil
}
func (a *oaAuth) Update(_ context.Context, _ db.Session, id uuid.UUID, _, _ *string, cfg map[string]any, _ time.Time) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	r := a.rows[id]
	if cfg != nil {
		r.Config = cfg
	}
	a.rows[id] = r
	return nil
}

func (a *oaAuth) InsertOwnedAuth(_ context.Context, _ db.Session, id uuid.UUID, by string, n domain.AuthConfigNew, kind string, owner uuid.UUID, _ time.Time) (domain.AuthConfig, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	o := owner.String()
	r := domain.AuthConfig{ID: id.String(), CreatedBy: by, Name: n.Name, AuthType: n.AuthType, Config: n.Config}
	if kind == kindMCPInstance {
		r.MCPInstanceID = &o
	} else {
		r.OpenAPIConnID = &o
	}
	a.rows[id] = r
	return r, nil
}

type oaOAuthStore struct {
	*oaAuth
	attached map[uuid.UUID]uuid.UUID
}

func (s *oaOAuthStore) AttachConnectionAuth(_ context.Context, _ db.Session, conn, auth uuid.UUID, _ time.Time) (bool, error) {
	s.attached[conn] = auth
	return true, nil
}

type oaOut struct{ rt http.RoundTripper }

func (o oaOut) Transport(netguard.Destination) http.RoundTripper { return o.rt }
func (oaOut) Guard() *netguard.Guard                             { return nil }

type oaKV struct {
	mu sync.Mutex
	m  map[string]string
}

func (k *oaKV) SetEx(_ context.Context, key, value string, _ time.Duration) error {
	k.mu.Lock()
	defer k.mu.Unlock()
	k.m[key] = value
	return nil
}
func (k *oaKV) GetDel(_ context.Context, key string) (string, bool, error) {
	k.mu.Lock()
	defer k.mu.Unlock()
	v, ok := k.m[key]
	delete(k.m, key)
	return v, ok, nil
}

type oaInstances struct {
	InstanceStore
	rows     map[uuid.UUID]domain.Instance
	attached map[uuid.UUID]uuid.UUID
}

func (i *oaInstances) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	r, ok := i.rows[id]
	return r, ok, nil
}
func (i *oaInstances) SetAuthConfig(_ context.Context, _ db.Session, id uuid.UUID, a *uuid.UUID, _ time.Time) (bool, error) {
	i.attached[id] = *a
	return true, nil
}

type oaSpecs struct {
	catalogapi.MCPSpecs
	rows map[string]catalogapi.MCPSpec
}

func (s oaSpecs) Get(_ context.Context, _ scope.Workspace, id string, _ catalogapi.MCPSpecGet) (catalogapi.MCPSpec, bool, error) {
	r, ok := s.rows[id]
	return r, ok, nil
}

type oaConns struct {
	ConnectionStore
	rows map[uuid.UUID]domain.Connection
}

func (c oaConns) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	r, ok := c.rows[id]
	return r, ok, nil
}

type oaItems map[uuid.UUID]CatalogAPIItem

func (m oaItems) CatalogAPIItem(_ context.Context, _ scope.Workspace, id uuid.UUID) (CatalogAPIItem, error) {
	it, ok := m[id]
	if !ok {
		return it, &domain.NotFound{Msg: "Catalog connection not found"}
	}
	return it, nil
}

type oaGraph struct{}

func (oaGraph) Check(context.Context, string, string, string, string) (bool, error) { return true, nil }
func (oaGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error)            { return nil, nil }

// oauthProvider is an MCP server, its authorization server and token endpoint.
type oauthProvider struct {
	srv      *httptest.Server
	dcr      bool
	token    func(form url.Values, r *http.Request) (int, map[string]any)
	tokens   atomic.Int32
	register atomic.Int32
}

func newOAuthProvider(t *testing.T) *oauthProvider {
	p := &oauthProvider{dcr: true}
	mux := http.NewServeMux()
	mux.HandleFunc("/mcp", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("WWW-Authenticate", `Bearer resource_metadata="`+p.srv.URL+`/.well-known/oauth-protected-resource/mcp"`)
		w.WriteHeader(http.StatusUnauthorized)
	})
	mux.HandleFunc("/.well-known/oauth-protected-resource/mcp", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"resource": p.srv.URL + "/mcp", "authorization_servers": []string{p.srv.URL},
			"scopes_supported": []string{"read", "write"},
		})
	})
	mux.HandleFunc("/.well-known/oauth-authorization-server", func(w http.ResponseWriter, _ *http.Request) {
		doc := map[string]any{
			"issuer": p.srv.URL, "authorization_endpoint": p.srv.URL + "/authorize",
			"token_endpoint": p.srv.URL + "/token", "scopes_supported": []string{"read", "offline_access"},
		}
		if p.dcr {
			doc["registration_endpoint"] = p.srv.URL + "/register"
		}
		_ = json.NewEncoder(w).Encode(doc)
	})
	mux.HandleFunc("/register", func(w http.ResponseWriter, _ *http.Request) {
		p.register.Add(1)
		_ = json.NewEncoder(w).Encode(map[string]any{"client_id": "dyn-1"})
	})
	mux.HandleFunc("/token", func(w http.ResponseWriter, r *http.Request) {
		p.tokens.Add(1)
		_ = r.ParseForm()
		status, body := p.token(r.PostForm, r)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(body)
	})
	p.srv = httptest.NewTLSServer(mux)
	t.Cleanup(p.srv.Close)
	return p
}

type oauthFixture struct {
	svc     *Service
	auth    *oaAuth
	store   *oaOAuthStore
	secrets *oaSecrets
	kv      *oaKV
	inst    *oaInstances
	conns   oaConns
	items   oaItems
	specs   oaSpecs
	caller  authn.Caller
	now     time.Time
	counts  *oaCounts
}

func newOAuthFixture(t *testing.T, p *oauthProvider, cfg Config) *oauthFixture {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	auth := &oaAuth{rows: map[uuid.UUID]domain.AuthConfig{}}
	f := &oauthFixture{
		auth: auth, store: &oaOAuthStore{oaAuth: auth, attached: map[uuid.UUID]uuid.UUID{}},
		secrets: &oaSecrets{values: map[string]string{}}, kv: &oaKV{m: map[string]string{}},
		inst:  &oaInstances{rows: map[uuid.UUID]domain.Instance{}, attached: map[uuid.UUID]uuid.UUID{}},
		conns: oaConns{rows: map[uuid.UUID]domain.Connection{}}, items: oaItems{},
		specs:  oaSpecs{rows: map[string]catalogapi.MCPSpec{}},
		caller: authn.Caller{Principal: authn.Principal{UserID: "owner", AccessibleWorkspaces: []string{ws.ID()}}, Workspace: ws},
		now:    time.Unix(1_700_000_000, 0).UTC(),
		counts: &oaCounts{},
	}
	rt := http.DefaultTransport
	if p != nil {
		rt = p.srv.Client().Transport
	}
	f.svc = New(Deps{
		DB: &oaDB{}, Auth: auth, Instances: f.inst, Connections: f.conns, Secrets: f.secrets,
		Catalog: func(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return &memCatalog{} },
		Graph:   oaGraph{}, Specs: f.specs, Out: oaOut{rt}, KV: f.kv, OAuthStore: f.store, CatalogItems: f.items,
		Config: cfg, APIURL: "https://api.example", AppURL: "https://app.example",
		Now: func() time.Time { return f.now }, Counter: f.counts,
	})
	return f
}

func (f *oauthFixture) oauthConfig(t *testing.T, cfg map[string]any, creds map[string]any) uuid.UUID {
	t.Helper()
	id := uuid.New()
	key := domain.SecretKeyFor(id.String())
	raw, _ := json.Marshal(creds)
	f.secrets.values[key] = string(raw)
	f.auth.rows[id] = domain.AuthConfig{ID: id.String(), CreatedBy: "owner", AuthType: "oauth2", Config: cfg, SecretKey: &key}
	return id
}

func (f *oauthFixture) stored(t *testing.T, id uuid.UUID) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal([]byte(f.secrets.values[domain.SecretKeyFor(id.String())]), &m); err != nil {
		t.Fatal(err)
	}
	return m
}

// Concurrent requests with an expired token spend the refresh token once:
// the rest wait for the lock and use the renewed token.
func TestRefreshRotationIsSerialized(t *testing.T) {
	p := newOAuthProvider(t)
	var mu sync.Mutex
	valid := "r1"
	p.token = func(form url.Values, _ *http.Request) (int, map[string]any) {
		mu.Lock()
		defer mu.Unlock()
		if form.Get("grant_type") != "refresh_token" || form.Get("refresh_token") != valid {
			return 400, map[string]any{"error": "invalid_grant"}
		}
		time.Sleep(20 * time.Millisecond)
		valid = "r2"
		return 200, map[string]any{"access_token": "a2", "refresh_token": "r2", "expires_in": 3600}
	}
	f := newOAuthFixture(t, p, Config{})
	id := f.oauthConfig(t, map[string]any{"token_url": p.srv.URL + "/token", "client_id": "cid"},
		map[string]any{"access_token": "a1", "refresh_token": "r1", "expires_at": float64(f.now.Unix() - 10)})

	var wg sync.WaitGroup
	errs := make(chan error, 8)
	for range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			h, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, id, p.srv.URL+"/mcp", false)
			if err == nil && h["Authorization"] != "Bearer a2" {
				err = errors.New("got " + h["Authorization"])
			}
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	if n := p.tokens.Load(); n != 1 {
		t.Fatalf("token endpoint called %d times, want 1", n)
	}
	if got := f.stored(t, id)["refresh_token"]; got != "r2" {
		t.Fatalf("stored refresh token = %v, want the rotated r2", got)
	}
}

func TestRefreshOutcomes(t *testing.T) {
	cases := []struct {
		name   string
		creds  map[string]any
		status int
		body   map[string]any
		reauth bool
	}{
		{"rejected grant", map[string]any{"refresh_token": "r"}, 400, map[string]any{"error": "invalid_grant"}, true},
		{"200 with an error", map[string]any{"refresh_token": "r"}, 200, map[string]any{"error": "bad_refresh_token"}, true},
		{"nothing to renew with", map[string]any{"access_token": ""}, 200, nil, true},
		{"client credentials", map[string]any{"client_secret": "s"}, 200, map[string]any{"access_token": "cc"}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := newOAuthProvider(t)
			var form url.Values
			p.token = func(f url.Values, _ *http.Request) (int, map[string]any) { form = f; return c.status, c.body }
			f := newOAuthFixture(t, p, Config{})
			id := f.oauthConfig(t, map[string]any{"token_url": p.srv.URL + "/token", "client_id": "cid", "scopes": []any{"a", "b"}}, c.creds)
			h, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, id, p.srv.URL+"/mcp", true)
			var ra *domain.ReauthRequired
			if c.reauth {
				if !errors.As(err, &ra) {
					t.Fatalf("err = %v, want ReauthRequired", err)
				}
				return
			}
			if err != nil || h["Authorization"] != "Bearer cc" {
				t.Fatalf("headers %v err %v", h, err)
			}
			if form.Get("grant_type") != "client_credentials" || form.Get("scope") != "a b" || form.Get("client_secret") != "s" {
				t.Fatalf("form = %v", form)
			}
		})
	}
}

func TestRefreshClientSecretBasic(t *testing.T) {
	p := newOAuthProvider(t)
	p.token = func(form url.Values, r *http.Request) (int, map[string]any) {
		u, pw, ok := r.BasicAuth()
		if !ok || u != "cid" || pw != "sec" || form.Get("client_secret") != "" || r.Header.Get("Accept") != "application/json" {
			return 401, nil
		}
		return 200, map[string]any{"access_token": "b1"}
	}
	f := newOAuthFixture(t, p, Config{})
	id := f.oauthConfig(t, map[string]any{"token_url": p.srv.URL + "/token", "client_id": "cid", "client_auth_method": "client_secret_basic", "authorization_scheme": "OAuth"},
		map[string]any{"refresh_token": "r", "client_secret": "sec"})
	h, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, id, "https://x", false)
	if err != nil || h["Authorization"] != "OAuth b1" {
		t.Fatalf("headers %v err %v", h, err)
	}
	if _, ok := f.stored(t, id)["expires_at"]; ok {
		t.Fatal("a token without expires_in keeps no expiry")
	}
}

func TestManagedCredentialsStayWithTheirOrigins(t *testing.T) {
	p := newOAuthProvider(t)
	p.token = func(url.Values, *http.Request) (int, map[string]any) { return 200, map[string]any{"access_token": "m"} }
	app := OAuthApp{Issuer: "https://gh", ClientID: "pid", ClientSecret: "psec", TokenEndpoint: p.srv.URL + "/token", ResourceOrigins: []string{"https://api.gh"}}
	f := newOAuthFixture(t, p, Config{OAuthApps: []OAuthApp{app}})
	id := f.oauthConfig(t, map[string]any{"token_url": "https://evil/token", "credential_mode": "managed", "platform_oauth_issuer": "https://gh"},
		map[string]any{"refresh_token": "r"})
	var inv *domain.Invalid
	if _, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, id, "https://evil/mcp", false); !errors.As(err, &inv) {
		t.Fatalf("err = %v, want Invalid", err)
	}
	h, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, id, "https://api.gh/mcp", false)
	if err != nil || h["Authorization"] != "Bearer m" {
		t.Fatalf("headers %v err %v", h, err)
	}
}

func TestStaticHeaders(t *testing.T) {
	f := newOAuthFixture(t, nil, Config{})
	key := func(id uuid.UUID, v string) *string {
		k := domain.SecretKeyFor(id.String())
		f.secrets.values[k] = v
		return &k
	}
	api, bearer, empty := uuid.New(), uuid.New(), uuid.New()
	f.auth.rows[api] = domain.AuthConfig{ID: api.String(), AuthType: "api_key", Config: map[string]any{"header_name": "X-K"}, SecretKey: key(api, `{"header_value":"v"}`)}
	f.auth.rows[bearer] = domain.AuthConfig{ID: bearer.String(), AuthType: "bearer", Config: map[string]any{}, SecretKey: key(bearer, `{"token":"t"}`)}
	f.auth.rows[empty] = domain.AuthConfig{ID: empty.String(), AuthType: "bearer", Config: map[string]any{}}
	ctx, ws := context.Background(), f.caller.Workspace
	if h, _ := f.svc.AuthHeaders(ctx, ws, api, "https://x", false); h["X-K"] != "v" {
		t.Fatalf("api key headers %v", h)
	}
	if h, _ := f.svc.AuthHeaders(ctx, ws, bearer, "https://x", false); h["Authorization"] != "Bearer t" {
		t.Fatalf("bearer headers %v", h)
	}
	var inv *domain.Invalid
	if _, err := f.svc.AuthHeaders(ctx, ws, empty, "https://x", false); !errors.As(err, &inv) {
		t.Fatalf("empty bearer err = %v", err)
	}
	if _, err := f.svc.AuthHeaders(ctx, ws, uuid.New(), "https://x", false); !errors.As(err, &inv) {
		t.Fatalf("unknown config err = %v", err)
	}
}

func (f *oauthFixture) urlInstance(p *oauthProvider) uuid.UUID {
	id := uuid.New()
	f.specs.rows["spec-1"] = catalogapi.MCPSpec{ID: "spec-1", JSONSpec: map[string]any{}}
	f.inst.rows[id] = domain.Instance{ID: id.String(), ServerSpecID: "spec-1", Transport: domain.TransportURL,
		JSONSpec: map[string]any{"endpoint_url": p.srv.URL + "/mcp"}}
	return id
}

func TestPreflightAndAuthorizeDynamic(t *testing.T) {
	p := newOAuthProvider(t)
	f := newOAuthFixture(t, p, Config{})
	id := f.urlInstance(p)
	ctx := context.Background()
	pf, err := f.svc.OAuthPreflight(ctx, f.caller, OAuthTarget{InstanceID: &id})
	if err != nil {
		t.Fatal(err)
	}
	if pf.Status != "ready" || *pf.CredentialSource != "dynamic" || *pf.Issuer != p.srv.URL || strings.Join(pf.Scopes, ",") != "read,write" {
		t.Fatalf("preflight = %+v", pf)
	}
	loc, conn, err := f.svc.OAuthAuthorize(ctx, f.caller, AuthorizeRequest{Target: OAuthTarget{InstanceID: &id}, Mode: "auto"})
	if err != nil {
		t.Fatal(err)
	}
	u, _ := url.Parse(loc)
	q := u.Query()
	if conn != id || q.Get("client_id") != "dyn-1" || q.Get("scope") != "read write offline_access" ||
		q.Get("resource") != p.srv.URL+"/mcp" || q.Get("code_challenge_method") != "S256" ||
		q.Get("redirect_uri") != "https://api.example/v1/oauth/callback" || p.register.Load() != 1 {
		t.Fatalf("authorize url %s", loc)
	}
	if _, ok := f.kv.m["oauth_state:"+q.Get("state")]; !ok {
		t.Fatal("no state stored")
	}
	var minted domain.AuthConfig
	for _, a := range f.auth.rows {
		minted = a
	}
	if minted.MCPInstanceID == nil || *minted.MCPInstanceID != id.String() || minted.Config["credential_mode"] != "dynamic" || minted.Name != "mcp-oauth-"+id.String()[:8] {
		t.Fatalf("minted = %+v", minted)
	}
}

func TestPreflightWithoutDCRNeedsAnApp(t *testing.T) {
	p := newOAuthProvider(t)
	p.dcr = false
	f := newOAuthFixture(t, p, Config{})
	id := f.urlInstance(p)
	pf, err := f.svc.OAuthPreflight(context.Background(), f.caller, OAuthTarget{InstanceID: &id})
	if err != nil || pf.Status != "oauth_app_required" || !strings.Contains(pf.Detail, "Dynamic Client Registration") {
		t.Fatalf("preflight %+v err %v", pf, err)
	}
	_, _, err = f.svc.OAuthAuthorize(context.Background(), f.caller, AuthorizeRequest{Target: OAuthTarget{InstanceID: &id}, Mode: "auto"})
	var oe *OAuthError
	if !errors.As(err, &oe) || oe.Code != "oauth_app_required" || oe.Issuer == nil || *oe.Issuer != p.srv.URL {
		t.Fatalf("authorize err = %v", err)
	}
}

func TestPreflightUnsupportedIsAnAnswer(t *testing.T) {
	f := newOAuthFixture(t, nil, Config{})
	id := uuid.New()
	f.specs.rows["s"] = catalogapi.MCPSpec{ID: "s"}
	f.inst.rows[id] = domain.Instance{ID: id.String(), ServerSpecID: "s", Transport: domain.TransportDocker}
	pf, err := f.svc.OAuthPreflight(context.Background(), f.caller, OAuthTarget{InstanceID: &id})
	if err != nil || pf.Status != "unsupported" || !strings.Contains(pf.Detail, "No remote URL") {
		t.Fatalf("preflight %+v err %v", pf, err)
	}
}

// The full catalog reconnect: authorize with a custom app, the callback
// parks the code, the starter finishes and the connection is signed in.
func TestConnectRoundTrip(t *testing.T) {
	p := newOAuthProvider(t)
	var exchange url.Values
	p.token = func(form url.Values, _ *http.Request) (int, map[string]any) {
		exchange = form
		return 200, map[string]any{"access_token": "at", "refresh_token": "rt", "expires_in": 60, "scope": "read"}
	}
	f := newOAuthFixture(t, p, Config{})
	item, conn := uuid.New(), uuid.New()
	itemID := item.String()
	f.items[item] = CatalogAPIItem{ID: item, Name: "Acme", Spec: map[string]any{
		"base_url": p.srv.URL + "/api",
		"oauth": map[string]any{"provider_key": "acme", "authorization_url": p.srv.URL + "/authorize",
			"token_url": p.srv.URL + "/token", "scopes": []any{"read", "write"}},
	}}
	f.conns.rows[conn] = domain.Connection{ID: conn.String(), RegistryItemID: &itemID}
	ctx := context.Background()
	cid, sec := "cid", "csec"
	loc, _, err := f.svc.OAuthAuthorize(ctx, f.caller, AuthorizeRequest{
		Target: OAuthTarget{OpenAPIConnectionID: &conn}, Mode: "custom",
		Custom: CustomOAuthApp{ClientID: &cid, ClientSecret: &sec}, Scopes: []string{"read"}, ScopesSet: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	u, _ := url.Parse(loc)
	if u.Query().Get("scope") != "read" || u.Query().Get("client_id") != "cid" {
		t.Fatalf("authorize url %s", loc)
	}
	state := u.Query().Get("state")
	back, err := f.svc.OAuthReceive(ctx, state, "code-1", "", "")
	if err != nil || !strings.HasPrefix(back, "https://app.example/oauth/finish?token=") {
		t.Fatalf("receive %q err %v", back, err)
	}
	if _, err := f.svc.OAuthReceive(ctx, state, "code-1", "", ""); err == nil {
		t.Fatal("a replayed callback was accepted")
	}
	token := strings.TrimPrefix(back, "https://app.example/oauth/finish?token=")
	enter := func(context.Context, string) (authn.Caller, error) { return f.caller, nil }
	done, err := f.svc.OAuthFinish(ctx, f.caller.Principal, token, enter)
	if err != nil {
		t.Fatal(err)
	}
	want := "https://app.example/w/acme/connections/openapi/" + conn.String() + "/settings?oauth=success"
	if done != want {
		t.Fatalf("finish = %q, want %q", done, want)
	}
	if exchange.Get("grant_type") != "authorization_code" || exchange.Get("code") != "code-1" ||
		exchange.Get("code_verifier") == "" || exchange.Get("client_secret") != "csec" {
		t.Fatalf("exchange form %v", exchange)
	}
	authID, ok := f.store.attached[conn]
	if !ok {
		t.Fatal("credential not attached")
	}
	creds := f.stored(t, authID)
	if creds["access_token"] != "at" || creds["refresh_token"] != "rt" || creds["client_secret"] != "csec" {
		t.Fatalf("stored %v", creds)
	}
}

func TestAuthorizeCatalogItemCreatesAPendingConnection(t *testing.T) {
	p := newOAuthProvider(t)
	f := newOAuthFixture(t, p, Config{})
	conns := &writesStore{rows: map[uuid.UUID]domain.Connection{}}
	graph := &writesGraph{personal: map[string]bool{}, owners: map[string]bool{}, allowed: map[string]bool{}}
	f.svc.d.OpenAPIWrites, f.svc.d.Graph, f.svc.d.Out = conns, graph, newWritesOut(t, true)
	item := uuid.New()
	desc := "Acme API"
	f.items[item] = CatalogAPIItem{ID: item, Name: "Acme", Description: &desc, Spec: map[string]any{
		"base_url":     p.srv.URL + "/api",
		"spec_content": map[string]any{"openapi": "3.0.0", "info": map[string]any{"title": "A", "version": "1"}, "paths": map[string]any{}},
		"oauth": map[string]any{"provider_key": "acme", "authorization_url": p.srv.URL + "/authorize",
			"token_url": p.srv.URL + "/token", "scopes": []any{"read"}},
	}}
	cid, sec := "cid", "csec"
	loc, connID, err := f.svc.OAuthAuthorize(context.Background(), f.caller, AuthorizeRequest{
		Target: OAuthTarget{CatalogItemID: &item}, Mode: "custom", Custom: CustomOAuthApp{ClientID: &cid, ClientSecret: &sec},
	})
	if err != nil {
		t.Fatal(err)
	}
	conn, ok := conns.rows[connID]
	if !ok {
		t.Fatalf("no connection %s in %v", connID, conns.rows)
	}
	if conn.Name != "Acme" || conn.Description == nil || *conn.Description != desc || conn.BaseURL != p.srv.URL+"/api" ||
		conn.Status != "pending" || conn.SpecContent == nil || !reflect.DeepEqual(conn.AllowedAuthOrigins, []string{p.srv.URL}) {
		t.Fatalf("connection %+v", conn)
	}
	if !graph.owners[connID.String()] || !graph.personal[connID.String()] {
		t.Fatal("the connection was not granted to its creator")
	}
	var minted *domain.AuthConfig
	for _, a := range f.auth.rows {
		if a.OpenAPIConnID != nil && *a.OpenAPIConnID == connID.String() {
			minted = &a
		}
	}
	if minted == nil || minted.Name != "acme-"+connID.String()[:8] {
		t.Fatalf("auth config %+v", f.auth.rows)
	}
	u, _ := url.Parse(loc)
	raw := f.kv.m["oauth_state:"+u.Query().Get("state")]
	var st oauthState
	if err := json.Unmarshal([]byte(raw), &st); err != nil || st.TargetKind != kindOpenAPIConnection || st.ConnectionID != connID.String() {
		t.Fatalf("state %s %v", raw, err)
	}
}

func TestFinishRefusesSomeoneElse(t *testing.T) {
	f := newOAuthFixture(t, nil, Config{})
	raw, _ := json.Marshal(returnedFlow{Flow: oauthState{UserID: "owner", WorkspaceID: f.caller.Workspace.ID()}, Code: "c"})
	f.kv.m["oauth_returned:t"] = string(raw)
	other := authn.Principal{UserID: "intruder", AccessibleWorkspaces: []string{f.caller.Workspace.ID()}}
	_, err := f.svc.OAuthFinish(context.Background(), other, "t", nil)
	var oe *OAuthError
	if !errors.As(err, &oe) || oe.Status != 403 {
		t.Fatalf("err = %v", err)
	}
	if _, err := f.svc.OAuthFinish(context.Background(), f.caller.Principal, "t", nil); err == nil {
		t.Fatal("a refused finish could be retried")
	}
}

func TestReceiveErrors(t *testing.T) {
	f := newOAuthFixture(t, nil, Config{})
	ctx := context.Background()
	loc, err := f.svc.OAuthReceive(ctx, "", "", "access_denied", "")
	if err != nil || loc != "https://app.example/?oauth=error&reason=access_denied" {
		t.Fatalf("no state %q %v", loc, err)
	}
	var oe *OAuthError
	if _, err := f.svc.OAuthReceive(ctx, "nope", "c", "", ""); !errors.As(err, &oe) || oe.Status != 400 {
		t.Fatalf("bad state err %v", err)
	}
	raw, _ := json.Marshal(oauthState{TargetKind: kindMCPInstance, ConnectionID: "i1", WorkspaceSlug: "acme",
		ReturnTo: "https://app.example/w/acme/connect/i1?x=1"})
	f.kv.m["oauth_state:s"] = string(raw)
	loc, err = f.svc.OAuthReceive(ctx, "s", "", "access_denied", "User said no")
	if err != nil || loc != "https://app.example/w/acme/connect/i1?oauth=error&reason=User+said+no" {
		t.Fatalf("provider error %q %v", loc, err)
	}
}

func TestRegistrationShaping(t *testing.T) {
	f := newOAuthFixture(t, nil, Config{OAuthScopes: []string{"openid", "offline_access", "offline"}})
	reg, err := f.svc.Registration([]byte(`{"client_id":"mine","redirect_uris":["http://localhost:3000/cb"],"grant_types":["client_credentials","refresh_token"],"scope":null,"jwks_uri":"https://x"}`))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := reg["client_id"]; ok {
		t.Fatal("client_id forwarded")
	}
	if _, ok := reg["jwks_uri"]; ok {
		t.Fatal("jwks_uri forwarded")
	}
	if g := reg["grant_types"].([]any); len(g) != 1 || g[0] != "refresh_token" {
		t.Fatalf("grant_types %v", g)
	}
	if reg["scope"] != "offline offline_access openid" || reg["skip_consent"] != false {
		t.Fatalf("registration %v", reg)
	}
	for _, body := range []string{`null`, `{"redirect_uris":["ftp://x"]}`, `{"redirect_uris":["https://x"],"grant_types":["implicit"]}`, `{"redirect_uris":["https://x"],"scope":"admin"}`} {
		var refusal *DCRRefusal
		if _, err := f.svc.Registration([]byte(body)); !errors.As(err, &refusal) {
			t.Fatalf("%s: err = %v", body, err)
		}
	}
}

func TestProtectedResourcePaths(t *testing.T) {
	for path, want := range map[string]bool{
		"mcp": true, "client-mcp": true, "mcp/w/acme": true, "mcp/clients/" + uuid.NewString(): true,
		"mcp/clients/x": false, "other": false, "mcp/w/" + strings.Repeat("a", 121): false,
	} {
		if IsProtectedResource(path) != want {
			t.Fatalf("%s: want %v", path, want)
		}
	}
	for path, want := range map[string]bool{"token": true, "sessions/logout": true, "../admin": false, "a/../b": false, "": false, "x?y": false} {
		if SafeOAuth2Path(path) != want {
			t.Fatalf("%q: want %v", path, want)
		}
	}
}

// A platform-managed config starts without stored credentials; the token
// its client_credentials grant earns is recorded and reused.
func TestClientCredentialsTokenIsKept(t *testing.T) {
	p := newOAuthProvider(t)
	p.token = func(url.Values, *http.Request) (int, map[string]any) {
		return 200, map[string]any{"access_token": "cc", "expires_in": 3600}
	}
	app := OAuthApp{Issuer: "https://gh", ClientID: "pid", ClientSecret: "psec", TokenEndpoint: p.srv.URL + "/token", ResourceOrigins: []string{"https://api.gh"}}
	f := newOAuthFixture(t, p, Config{OAuthApps: []OAuthApp{app}})
	id := uuid.New()
	f.auth.rows[id] = domain.AuthConfig{ID: id.String(), AuthType: "oauth2", Config: map[string]any{"credential_mode": "managed", "platform_oauth_issuer": "https://gh"}}
	for range 2 {
		if h, err := f.svc.AuthHeaders(context.Background(), f.caller.Workspace, id, "https://api.gh/mcp", false); err != nil || h["Authorization"] != "Bearer cc" {
			t.Fatalf("headers %v err %v", h, err)
		}
	}
	if n := p.tokens.Load(); n != 1 {
		t.Fatalf("token endpoint called %d times, want 1", n)
	}
	if f.auth.rows[id].SecretKey == nil {
		t.Fatal("secret_key not recorded")
	}
}
