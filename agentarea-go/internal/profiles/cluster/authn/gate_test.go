package authn

import (
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"math/big"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	port "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

const (
	testIssuer   = "http://kratos.test:4433"
	testAudience = "agentarea-api"
	testSecret   = "test-turn-secret-0123456789abcdefghijk"
	challenge    = `Bearer resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource"`
)

func b64url(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }

func jwtWith(t *testing.T, header, claims map[string]any, sign func(input []byte) []byte) string {
	t.Helper()
	h, _ := json.Marshal(header)
	c, _ := json.Marshal(claims)
	input := b64url(h) + "." + b64url(c)
	return input + "." + b64url(sign([]byte(input)))
}

func signES256(t *testing.T, key *ecdsa.PrivateKey, kid string, claims map[string]any) string {
	return jwtWith(t, map[string]any{"alg": "ES256", "kid": kid, "typ": "JWT"}, claims, func(in []byte) []byte {
		d := sha256.Sum256(in)
		r, s, err := ecdsa.Sign(rand.Reader, key, d[:])
		if err != nil {
			t.Fatal(err)
		}
		out := make([]byte, 64)
		r.FillBytes(out[:32])
		s.FillBytes(out[32:])
		return out
	})
}

func signRS256(t *testing.T, key *rsa.PrivateKey, kid string, claims map[string]any) string {
	return jwtWith(t, map[string]any{"alg": "RS256", "kid": kid, "typ": "JWT"}, claims, func(in []byte) []byte {
		d := sha256.Sum256(in)
		sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, d[:])
		if err != nil {
			t.Fatal(err)
		}
		return sig
	})
}

func ecJWKS(t *testing.T, key *ecdsa.PrivateKey, kid string) string {
	t.Helper()
	pt, err := key.PublicKey.Bytes()
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(map[string]any{"keys": []any{map[string]any{
		"kty": "EC", "crv": "P-256", "kid": kid, "x": b64url(pt[1:33]), "y": b64url(pt[33:]),
	}}})
	return string(b)
}

func rsaJWKS(keys map[string]*rsa.PrivateKey) []byte {
	var list []any
	for kid, k := range keys {
		list = append(list, map[string]any{
			"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
			"n": b64url(k.N.Bytes()), "e": b64url(big.NewInt(int64(k.E)).Bytes()),
		})
	}
	b, _ := json.Marshal(map[string]any{"keys": list})
	return b
}

func sessionClaims(sub string) map[string]any {
	now := time.Now().Unix()
	return map[string]any{"sub": sub, "aud": testAudience, "iss": testIssuer, "iat": now - 10, "exp": now + 600, "email": sub + "@example.com"}
}

// world is a user u1 owning ws-own (slug own), member of ws-joined (slug
// joined), not of ws-foreign (owned by u9); u1's personal workspace is u1.
type world struct {
	store   *fakeStore
	graph   *fakeGraph
	live    *fakeLive
	gate    *Gate
	turns   *TurnTokens
	kratos  *ecdsa.PrivateKey
	now     time.Time
	nowFunc func() time.Time
	mu      sync.Mutex
}

const personalUUID = "0b7c1d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e"

func newWorld(t *testing.T) *world {
	t.Helper()
	w := &world{
		store: newFakeStore(),
		graph: &fakeGraph{members: map[string]bool{"ws-joined|User:u1": true}},
		live:  &fakeLive{alive: map[string]bool{}},
		now:   time.Now(),
	}
	w.nowFunc = func() time.Time { w.mu.Lock(); defer w.mu.Unlock(); return w.now }
	w.store.workspaces = []Workspace{
		{ID: "ws-own", Slug: "own", OwnerUserID: "u1"},
		{ID: "ws-joined", Slug: "joined", OwnerUserID: "u2"},
		{ID: "ws-foreign", Slug: "foreign", OwnerUserID: "u9"},
		{ID: personalUUID, Slug: "u9-personal", OwnerUserID: personalUUID},
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	w.kratos = key
	w.gate = newTestGate(t, Config{
		JWKSB64: ecJWKS(t, key, "k1"), Issuer: testIssuer, Audience: testAudience, GatewaySecret: testSecret,
	}, Deps{Store: w.store, Graph: w.graph, LiveTurns: w.live, Now: w.nowFunc})
	w.turns, err = NewTurnTokens(testSecret, w.nowFunc)
	if err != nil {
		t.Fatal(err)
	}
	return w
}

func (w *world) advance(d time.Duration) { w.mu.Lock(); w.now = w.now.Add(d); w.mu.Unlock() }

func (w *world) session(t *testing.T, sub string) string {
	return signES256(t, w.kratos, "k1", sessionClaims(sub))
}

// key stores an API key and returns its token.
func (w *world) key(t *testing.T, k APIKey) string {
	t.Helper()
	token, _, hash, err := port.NewAPIKey()
	if err != nil {
		t.Fatal(err)
	}
	if k.ID == "" {
		k.ID = "key-" + hash[:8]
	}
	w.store.keys[hash] = k
	return token
}

func (w *world) turn(t *testing.T, c port.TurnClaims, alive bool) string {
	t.Helper()
	token, err := w.turns.Issue(c, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	w.live.alive[c.TurnID] = alive
	return token
}

func wantRefusal(t *testing.T, err error, status int, detail string) {
	t.Helper()
	r, ok := asRefusal(err)
	if !ok {
		t.Fatalf("want %d %q, got %v", status, detail, err)
	}
	if r.Status != status || r.Detail != detail {
		t.Fatalf("want %d %q, got %d %q", status, detail, r.Status, r.Detail)
	}
	if status == http.StatusUnauthorized && r.WWWAuthenticate != challenge {
		t.Fatalf("401 without the RFC 9728 challenge: %q", r.WWWAuthenticate)
	}
	if status != http.StatusUnauthorized && r.WWWAuthenticate != "" {
		t.Fatalf("%d carries a challenge", status)
	}
}

func TestBearerTokenReadsOnlyTheAuthorizationHeaderAsHTTPBearer(t *testing.T) {
	for _, tc := range []struct {
		header string
		token  string
		ok     bool
	}{
		{"Bearer abc", "abc", true},
		{"bearer abc", "abc", true},
		{"BEARER   abc  ", "abc", true},
		{"Bearer \x85abc\xa0", "abc", true},
		{"Basic abc", "", false},
		{"Bearer", "", false},
		{"Bearer    ", "", false},
		{"", "", false},
		{"Bearerabc", "", false},
	} {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		if tc.header != "" {
			r.Header.Set("Authorization", tc.header)
		}
		r.Header.Set("X-Workspace", "ws-own")
		r.AddCookie(&http.Cookie{Name: "ory_kratos_session", Value: "abc"})
		token, ok := port.BearerToken(r)
		if token != tc.token || ok != tc.ok {
			t.Errorf("%q: got %q %v", tc.header, token, ok)
		}
	}
}

func TestAuthenticateWithoutCredentialsIs401WithChallenge(t *testing.T) {
	w := newWorld(t)
	r := httptest.NewRequest(http.MethodGet, "/v1/workspaces", nil)
	r.AddCookie(&http.Cookie{Name: "ory_kratos_session", Value: "session-cookie"})
	_, err := w.gate.Authenticate(context.Background(), r)
	wantRefusal(t, err, 401, port.DetailMissingCredentials)
	if !errors.Is(err, port.ErrUnauthenticated) {
		t.Fatal("401 does not match ErrUnauthenticated")
	}
}

func TestKratosSessionIsAUserWithEveryScopeAndNoWorkspace(t *testing.T) {
	w := newWorld(t)
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set("Authorization", "Bearer "+w.session(t, "u1"))
	p, err := w.gate.Authenticate(context.Background(), r)
	if err != nil {
		t.Fatal(err)
	}
	if p.UserID != "u1" || p.Email != "u1@example.com" || p.Credential.Kind != port.KindSession ||
		!p.Credential.Grants(port.ScopeCredentials) || !p.Credential.Grants(port.ScopeWorkspaces) {
		t.Fatalf("%+v %+v", p, p.Credential)
	}
	if p.BoundWorkspaceID != "" || p.AccessibleWorkspaces != nil {
		t.Fatal("authentication selected a workspace")
	}
}

func TestAPIKeys(t *testing.T) {
	ctx := context.Background()
	past := time.Now().UTC().Add(-time.Minute)
	future := time.Now().UTC().Add(time.Hour)
	for _, tc := range []struct {
		name   string
		key    APIKey
		graph  error
		ok     bool
		detail string
	}{
		{name: "owner of the workspace", key: APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true}, ok: true},
		{name: "personal workspace", key: APIKey{WorkspaceID: "u1", CreatedBy: "u1", IsActive: true}, ok: true},
		{name: "graph member", key: APIKey{WorkspaceID: "ws-joined", CreatedBy: "u1", IsActive: true}, ok: true},
		{name: "unexpired", key: APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true, ExpiresAt: &future}, ok: true},
		{name: "revoked", key: APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: false}},
		{name: "expired", key: APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true, ExpiresAt: &past}},
		{name: "creator left the workspace", key: APIKey{WorkspaceID: "ws-foreign", CreatedBy: "u1", IsActive: true}},
		{name: "graph down denies a member", key: APIKey{WorkspaceID: "ws-joined", CreatedBy: "u1", IsActive: true}, graph: errors.New("fga down")},
		{name: "graph down keeps an owner", key: APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true}, graph: errors.New("fga down"), ok: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			w := newWorld(t)
			w.graph.err = tc.graph
			token := w.key(t, tc.key)
			p, err := w.gate.Verify(ctx, token)
			if !tc.ok {
				wantRefusal(t, err, 401, port.DetailInvalidAPIKey)
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if p.UserID != "u1" || p.BoundWorkspaceID != tc.key.WorkspaceID || p.Credential.Kind != port.KindAPIKey ||
				p.Credential.KeyID == "" || len(p.Credential.Scopes()) != 0 {
				t.Fatalf("%+v %+v", p, p.Credential)
			}
		})
	}
	t.Run("unknown key", func(t *testing.T) {
		w := newWorld(t)
		_, err := w.gate.Verify(ctx, "aat_nobody")
		wantRefusal(t, err, 401, port.DetailInvalidAPIKey)
	})
	t.Run("an aat_ string never reaches Kratos", func(t *testing.T) {
		w := newWorld(t)
		_, err := w.gate.Verify(ctx, "aat_"+w.session(t, "u1"))
		wantRefusal(t, err, 401, port.DetailInvalidAPIKey)
	})
	t.Run("database failure is internal, not a refusal", func(t *testing.T) {
		w := newWorld(t)
		w.store.dbErr = errors.New("db down")
		_, err := w.gate.Verify(ctx, "aat_x")
		if _, refused := asRefusal(err); err == nil || refused {
			t.Fatalf("got %v", err)
		}
	})
}

func TestAPIKeyNarrowsReachToItsWorkspaceAndAdministersOnlyThere(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	p, err := w.gate.Verify(ctx, w.key(t, APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true}))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.gate.Caller(ctx, p, port.Route{WorkspaceRef: "joined", HasWorkspaceRef: true}); err == nil {
		t.Fatal("a key reached a workspace it was not issued for")
	} else {
		wantRefusal(t, err, 403, port.DetailNotAMember)
	}
	c, err := w.gate.Caller(ctx, p, port.Route{WorkspaceRef: "own", HasWorkspaceRef: true})
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(c.AccessibleWorkspaces, []string{"ws-own"}) || !slices.Equal(c.AdminWorkspaces, []string{"ws-own"}) {
		t.Fatalf("%v %v", c.AccessibleWorkspaces, c.AdminWorkspaces)
	}
	if err := port.EnsureScope(c.Principal, port.ScopeCredentials, "create API keys"); err == nil {
		t.Fatal("an API key holds the credentials scope")
	}
}

func TestAPIKeyUsesAreWrittenAtMostOncePerInterval(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	token := w.key(t, APIKey{ID: "k1", WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true})
	hash := port.HashAPIKey(token)
	if _, err := w.gate.Verify(ctx, token); err != nil {
		t.Fatal(err)
	}
	if w.store.uses["k1"] != 1 {
		t.Fatalf("first use not written: %v", w.store.uses)
	}
	stamp := w.store.stamps["k1"]
	k := w.store.keys[hash]
	k.LastAccessedAt = &stamp
	w.store.keys[hash] = k
	for range 3 {
		w.advance(10 * time.Second)
		if _, err := w.gate.Verify(ctx, token); err != nil {
			t.Fatal(err)
		}
	}
	if w.store.uses["k1"] != 1 {
		t.Fatalf("written within the interval: %v", w.store.uses)
	}
	w.advance(time.Minute)
	w.store.writeErr = errors.New("db busy")
	if _, err := w.gate.Verify(ctx, token); err != nil {
		t.Fatalf("a failed use write failed the request: %v", err)
	}
	w.store.writeErr = nil
	if _, err := w.gate.Verify(ctx, token); err != nil {
		t.Fatal(err)
	}
	if w.store.uses["k1"] != 1+5 {
		t.Fatalf("uses lost: %v", w.store.uses)
	}
}

func TestAgentKeyReachesOnlyItsAgentOverA2A(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	p, err := w.gate.Verify(ctx, w.key(t, APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true, AgentID: "agent-1"}))
	if err != nil {
		t.Fatal(err)
	}
	if p.BoundAgentID != "agent-1" {
		t.Fatal("agent not bound")
	}
	_, err = w.gate.Principal(ctx, p)
	wantRefusal(t, err, 403, port.DetailAgentKeyRefused)

	for name, route := range map[string]port.Route{
		"workspace path":     {WorkspaceRef: "own", HasWorkspaceRef: true, Binding: &port.Binding{WorkspaceID: "ws-own", WorkspaceSlug: "own", AgentID: "agent-1"}},
		"no binding":         {},
		"another agent":      {Binding: &port.Binding{WorkspaceID: "ws-own", WorkspaceSlug: "own", AgentID: "agent-2"}},
		"another workspace":  {Binding: &port.Binding{WorkspaceID: "ws-joined", WorkspaceSlug: "joined", AgentID: "agent-1"}},
		"bound for a client": {Binding: &port.Binding{WorkspaceID: "ws-own", WorkspaceSlug: "own", ClientID: "c-1"}},
	} {
		_, err := w.gate.Caller(ctx, p, route)
		if r, ok := asRefusal(err); !ok || r.Status != 403 || r.Detail != port.DetailAgentKeyRefused {
			t.Errorf("%s: %v", name, err)
		}
	}
	c, err := w.gate.Caller(ctx, p, port.Route{Binding: &port.Binding{WorkspaceID: "ws-own", WorkspaceSlug: "own", AgentID: "agent-1"}})
	if err != nil {
		t.Fatal(err)
	}
	if c.Workspace.ID() != "ws-own" || !slices.Equal(c.AccessibleWorkspaces, []string{"ws-own"}) || len(c.AdminWorkspaces) != 0 || c.AdminWorkspaces == nil {
		t.Fatalf("%+v", c)
	}
	opt, err := w.gate.Optional(ctx, w.key(t, APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true, AgentID: "agent-1"}), false)
	if err != nil || opt == nil || len(opt.AccessibleWorkspaces) != 0 || opt.AccessibleWorkspaces == nil {
		t.Fatalf("A2A edge: %+v %v", opt, err)
	}
}

func TestRunnerKeyReachesOnlyItsClientsRunnerRoutes(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	token := w.key(t, APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true, ClientID: "c-1"})
	p, err := w.gate.Verify(ctx, token)
	if err != nil {
		t.Fatal(err)
	}
	_, err = w.gate.Principal(ctx, p)
	wantRefusal(t, err, 403, port.DetailRunnerKeyRefused)
	if opt, err := w.gate.Optional(ctx, token, true); opt != nil || err != nil {
		t.Fatal("an optional edge admitted a runner key")
	}
	_, err = w.gate.Caller(ctx, p, port.Route{WorkspaceRef: "own", HasWorkspaceRef: true})
	wantRefusal(t, err, 403, port.DetailRunnerKeyRefused)
	c, err := w.gate.Caller(ctx, p, port.Route{Binding: &port.Binding{WorkspaceID: "ws-own", WorkspaceSlug: "own", ClientID: "c-1"}})
	if err != nil || c.Workspace.ID() != "ws-own" {
		t.Fatalf("%v %v", c, err)
	}

	runner, err := w.gate.RunnerKey(ctx, token)
	if err != nil || runner == nil || runner.BoundClientID != "c-1" {
		t.Fatalf("%v %v", runner, err)
	}
	ws, _ := scope.NewWorkspace("ws-own", "own")
	if c, err := w.gate.EnterAsRunner(*runner, ws); err != nil || c.Workspace.ID() != "ws-own" || len(c.AdminWorkspaces) != 0 {
		t.Fatalf("%v %v", c, err)
	}
	other, _ := scope.NewWorkspace("ws-joined", "joined")
	_, err = w.gate.EnterAsRunner(*runner, other)
	wantRefusal(t, err, 403, port.DetailRunnerKeyRefused)

	plain := w.key(t, APIKey{WorkspaceID: "ws-own", CreatedBy: "u1", IsActive: true})
	for _, tok := range []string{plain, w.session(t, "u1"), "aat_unknown", ""} {
		if p, err := w.gate.RunnerKey(ctx, tok); p != nil || err != nil {
			t.Fatalf("runner socket admitted %q: %v %v", tok, p, err)
		}
	}
}

func turnClaims(actor port.SubjectKind, actorID, obo, ws string) port.TurnClaims {
	return port.TurnClaims{
		TurnID: "turn-" + actorID, TaskID: "task-1", WorkspaceID: ws, ClientID: "c-1",
		ActorType: actor, ActorID: actorID, OnBehalfOf: obo,
	}
}

func TestTurnTokens(t *testing.T) {
	ctx := context.Background()
	for _, tc := range []struct {
		name    string
		claims  port.TurnClaims
		alive   bool
		mutate  func(string) string
		advance time.Duration
		ok      bool
		user    string
		subject string
	}{
		{name: "user turn", claims: turnClaims(port.SubjectUser, "u1", "u1", "ws-own"), alive: true, ok: true, user: "u1", subject: "User:u1"},
		{name: "agent turn acts as the agent under its person", claims: turnClaims(port.SubjectAgent, "agent-1", "u1", "ws-joined"), alive: true, ok: true, user: "u1", subject: "Agent:agent-1"},
		{name: "ended turn", claims: turnClaims(port.SubjectUser, "u1", "u1", "ws-own")},
		{name: "expired", claims: turnClaims(port.SubjectUser, "u1", "u1", "ws-own"), alive: true, advance: 2 * time.Hour},
		{name: "wrong signature", claims: turnClaims(port.SubjectUser, "u1", "u1", "ws-own"), alive: true, mutate: func(s string) string {
			i := strings.LastIndexByte(s, '.')
			return s[:i+1] + b64url(make([]byte, 32))
		}},
		{name: "person left the workspace", claims: turnClaims(port.SubjectUser, "u1", "u1", "ws-foreign"), alive: true},
		{name: "agent's person left the workspace", claims: turnClaims(port.SubjectAgent, "agent-1", "u1", "ws-foreign"), alive: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			w := newWorld(t)
			token := w.turn(t, tc.claims, tc.alive)
			if tc.mutate != nil {
				token = tc.mutate(token)
			}
			w.advance(tc.advance)
			p, err := w.gate.Verify(ctx, token)
			if !tc.ok {
				wantRefusal(t, err, 401, port.DetailTurnEnded)
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if p.UserID != tc.user || p.GraphSubject() != tc.subject || p.BoundTaskID != "task-1" ||
				p.TurnClientID != "c-1" || p.BoundWorkspaceID != tc.claims.WorkspaceID ||
				p.Credential.Kind != port.KindTurn || p.Credential.KeyID != tc.claims.TurnID || len(p.Credential.Scopes()) != 0 {
				t.Fatalf("%+v %+v", p, p.Credential)
			}
		})
	}
	t.Run("live-turn store failure is internal", func(t *testing.T) {
		w := newWorld(t)
		token := w.turn(t, turnClaims(port.SubjectUser, "u1", "u1", "ws-own"), true)
		w.live.err = errors.New("redis down")
		_, err := w.gate.Verify(ctx, token)
		if _, refused := asRefusal(err); err == nil || refused {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("no gateway secret: a turn token is an internal error", func(t *testing.T) {
		w := newWorld(t)
		token := w.turn(t, turnClaims(port.SubjectUser, "u1", "u1", "ws-own"), true)
		gate := newTestGate(t, Config{Issuer: testIssuer, Audience: testAudience}, Deps{Store: w.store, Graph: w.graph})
		_, err := gate.Verify(ctx, token)
		if _, refused := asRefusal(err); err == nil || refused {
			t.Fatalf("got %v", err)
		}
	})
}

func TestTurnTokenReachesOnlyItsTasksMarkedRoutes(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	token := w.turn(t, turnClaims(port.SubjectAgent, "agent-1", "u1", "ws-own"), true)
	p, err := w.gate.Verify(ctx, token)
	if err != nil {
		t.Fatal(err)
	}
	_, err = w.gate.Principal(ctx, p)
	wantRefusal(t, err, 403, port.DetailTurnTokenRefused)
	if opt, err := w.gate.Optional(ctx, token, false); opt != nil || err != nil {
		t.Fatal("an edge that does not admit turns admitted one")
	}
	opt, err := w.gate.Optional(ctx, token, true)
	if err != nil || opt == nil || !slices.Equal(opt.AccessibleWorkspaces, []string{"ws-own"}) || len(opt.AdminWorkspaces) != 0 {
		t.Fatalf("client MCP edge: %+v %v", opt, err)
	}

	for name, route := range map[string]port.Route{
		"unmarked route": {WorkspaceRef: "own", HasWorkspaceRef: true, TaskID: "task-1"},
		"another task":   {WorkspaceRef: "own", HasWorkspaceRef: true, AdmitsTurnToken: true, TaskID: "task-2"},
		"no task":        {WorkspaceRef: "own", HasWorkspaceRef: true, AdmitsTurnToken: true},
	} {
		_, err := w.gate.Caller(ctx, p, route)
		if r, ok := asRefusal(err); !ok || r.Status != 403 || r.Detail != port.DetailTurnTokenRefused {
			t.Errorf("%s: %v", name, err)
		}
	}
	_, err = w.gate.Caller(ctx, p, port.Route{WorkspaceRef: "joined", HasWorkspaceRef: true, AdmitsTurnToken: true, TaskID: "task-1"})
	wantRefusal(t, err, 403, port.DetailNotAMember)
	c, err := w.gate.Caller(ctx, p, port.Route{WorkspaceRef: "own", HasWorkspaceRef: true, AdmitsTurnToken: true, TaskID: "task-1"})
	if err != nil {
		t.Fatal(err)
	}
	if c.Workspace.ID() != "ws-own" || c.Workspace.Slug() != "own" || c.GraphSubject() != "Agent:agent-1" || len(c.AdminWorkspaces) != 0 {
		t.Fatalf("%+v", c)
	}
}

func TestSessionWorkspaceSelection(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	p, err := w.gate.Verify(ctx, w.session(t, "u1"))
	if err != nil {
		t.Fatal(err)
	}
	resolved, err := w.gate.Principal(ctx, p)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(resolved.AccessibleWorkspaces, []string{"ws-joined", "ws-own"}) || !slices.Equal(resolved.AdminWorkspaces, []string{"ws-own"}) {
		t.Fatalf("reach %v admin %v", resolved.AccessibleWorkspaces, resolved.AdminWorkspaces)
	}
	for _, tc := range []struct {
		ref    string
		ws     string
		status int
		detail string
	}{
		{ref: "own", ws: "ws-own"},
		{ref: "joined", ws: "ws-joined"},
		{ref: "foreign", status: 403, detail: port.DetailNotAMember},
		{ref: "nowhere", status: 403, detail: port.DetailNotAMember},
		{ref: "Own", status: 422, detail: port.DetailMalformedWorkspace},
		{ref: "own-", status: 422, detail: port.DetailMalformedWorkspace},
		{ref: personalUUID, status: 403, detail: port.DetailNotAMember},
		{ref: "u9-personal", status: 403, detail: port.DetailNotAMember},
	} {
		c, err := w.gate.Caller(ctx, p, port.Route{WorkspaceRef: tc.ref, HasWorkspaceRef: true})
		if tc.status != 0 {
			if r, ok := asRefusal(err); !ok || r.Status != tc.status || r.Detail != tc.detail {
				t.Errorf("%s: %v", tc.ref, err)
			}
			continue
		}
		if err != nil || c.Workspace.ID() != tc.ws || c.Workspace.Slug() != tc.ref {
			t.Errorf("%s: %v %v", tc.ref, c, err)
		}
	}
	if _, err := w.gate.Caller(ctx, p, port.Route{}); !errors.Is(err, port.ErrWorkspaceNotSelected) {
		t.Fatalf("no workspace: %v", err)
	}
	c, err := w.gate.Caller(ctx, p, port.Route{Binding: &port.Binding{WorkspaceID: "ws-joined", WorkspaceSlug: "joined"}})
	if err != nil || c.Workspace.ID() != "ws-joined" {
		t.Fatalf("bound: %v %v", c, err)
	}
	_, err = w.gate.Caller(ctx, p, port.Route{Binding: &port.Binding{WorkspaceID: "ws-foreign", WorkspaceSlug: "foreign"}})
	wantRefusal(t, err, 403, port.DetailNotAMember)
}

func TestPersonalWorkspaceIsReachedByIDOnly(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	p, err := w.gate.Verify(ctx, w.session(t, personalUUID))
	if err != nil {
		t.Fatal(err)
	}
	c, err := w.gate.Caller(ctx, p, port.Route{WorkspaceRef: personalUUID, HasWorkspaceRef: true})
	if err != nil || c.Workspace.ID() != personalUUID || !slices.Contains(c.AdminWorkspaces, personalUUID) {
		t.Fatalf("%v %v", c, err)
	}
	c, err = w.gate.EnterWorkspace(ctx, p, strings.ToUpper(personalUUID))
	if c.Workspace.ID() != "" || err == nil {
		t.Fatalf("an upper-case id matched by id: %v", c)
	}
	c, err = w.gate.EnterWorkspace(ctx, p, "u9-personal")
	if err != nil || c.Workspace.ID() != personalUUID {
		t.Fatalf("by slug: %v %v", c, err)
	}
	var unreachable *scope.UnreachableError
	if _, err := w.gate.EnterWorkspace(ctx, p, "own"); !errors.As(err, &unreachable) {
		t.Fatalf("foreign by slug: %v", err)
	}
	if _, err := w.gate.EnterWorkspace(ctx, p, "nowhere"); !errors.As(err, &unreachable) || unreachable.Reference != "nowhere" {
		t.Fatalf("unknown: %v", err)
	}
}

func TestGraphOutageNarrowsReachToOwnedWorkspaces(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	w.graph.err = errors.New("fga down")
	p, err := w.gate.Verify(ctx, w.session(t, "u1"))
	if err != nil {
		t.Fatal(err)
	}
	resolved, err := w.gate.Principal(ctx, p)
	if err != nil || !slices.Equal(resolved.AccessibleWorkspaces, []string{"ws-own"}) {
		t.Fatalf("%v %v", resolved.AccessibleWorkspaces, err)
	}
	w.store.dbErr = errors.New("db down")
	if _, err := w.gate.Principal(ctx, p); err == nil {
		t.Fatal("a database failure read as no workspace")
	} else if _, refused := asRefusal(err); refused {
		t.Fatal("a database failure was answered as a refusal")
	}
}

type reachFunc func(ctx context.Context, p port.Principal) ([]string, error)

func (f reachFunc) AccessibleWorkspaces(ctx context.Context, p port.Principal) ([]string, error) {
	return f(ctx, p)
}

func TestExtensionReachComesFirstAndIsNarrowedForKeys(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	gate := newTestGate(t, Config{JWKSB64: ecJWKS(t, w.kratos, "k1"), Issuer: testIssuer, Audience: testAudience}, Deps{
		Store: w.store, Graph: w.graph,
		Reach: reachFunc(func(context.Context, port.Principal) ([]string, error) { return []string{"ws-ext", "ws-own"}, nil }),
	})
	p, _ := gate.Verify(ctx, w.session(t, "u1"))
	resolved, err := gate.Principal(ctx, p)
	if err != nil || !slices.Equal(resolved.AccessibleWorkspaces, []string{"ws-ext", "ws-own", "ws-joined"}) {
		t.Fatalf("%v %v", resolved.AccessibleWorkspaces, err)
	}
	keyP, err := gate.Verify(ctx, w.key(t, APIKey{WorkspaceID: "ws-joined", CreatedBy: "u1", IsActive: true}))
	if err != nil {
		t.Fatal(err)
	}
	resolved, err = gate.Principal(ctx, keyP)
	if err != nil || !slices.Equal(resolved.AccessibleWorkspaces, []string{"ws-joined"}) || len(resolved.AdminWorkspaces) != 0 {
		t.Fatalf("%v %v %v", resolved.AccessibleWorkspaces, resolved.AdminWorkspaces, err)
	}
}

func TestOptionalReadsRefusalsAsNobody(t *testing.T) {
	w := newWorld(t)
	ctx := context.Background()
	for _, tok := range []string{"", "garbage", "aat_unknown"} {
		if p, err := w.gate.Optional(ctx, tok, true); p != nil || err != nil {
			t.Fatalf("%q: %v %v", tok, p, err)
		}
	}
	p, err := w.gate.Optional(ctx, w.session(t, "u1"), false)
	if err != nil || p == nil || len(p.AccessibleWorkspaces) != 2 {
		t.Fatalf("%v %v", p, err)
	}
}

func TestHydraTokens(t *testing.T) {
	ctx := context.Background()
	k1, _ := rsa.GenerateKey(rand.Reader, 2048)
	k2, _ := rsa.GenerateKey(rand.Reader, 2048)
	var mu sync.Mutex
	served := map[string]*rsa.PrivateKey{"h1": k1}
	down := false
	srv, fetches := jwksServer(t, func() []byte {
		mu.Lock()
		defer mu.Unlock()
		if down {
			return nil
		}
		return rsaJWKS(served)
	})
	w := newWorld(t)
	gate := newTestGate(t, Config{
		JWKSB64: ecJWKS(t, w.kratos, "k1"), Issuer: testIssuer, Audience: testAudience,
		HydraURL: srv.URL, HydraAudience: "mcp",
	}, Deps{Store: w.store, Graph: w.graph, Now: w.nowFunc})
	claims := func(sub string) map[string]any {
		now := w.nowFunc().Unix()
		return map[string]any{"sub": sub, "aud": "mcp", "iss": srv.URL, "iat": now, "exp": now + 600, "client_id": "cli", "workspace_id": "ws-foreign"}
	}

	p, err := gate.Verify(ctx, signRS256(t, k1, "h1", claims("u1")))
	if err != nil || p.UserID != "u1" || p.Credential.Kind != port.KindOAuth || p.Email != "" || p.BoundWorkspaceID != "" ||
		!p.Credential.Grants(port.ScopeWorkspaces) {
		t.Fatalf("%+v %v", p, err)
	}
	if _, err := gate.Caller(ctx, p, port.Route{WorkspaceRef: "foreign", HasWorkspaceRef: true}); err == nil {
		t.Fatal("a workspace claim in an OAuth token selected a workspace")
	}

	mu.Lock()
	served["h2"] = k2
	mu.Unlock()
	token2 := signRS256(t, k2, "h2", claims("u1"))
	_, err = gate.Verify(ctx, token2)
	wantRefusal(t, err, 401, "Key not found in JWKS")
	w.advance(31 * time.Second)
	if _, err := gate.Verify(ctx, token2); err != nil {
		t.Fatalf("a rotated-in key was not fetched after the cooldown: %v", err)
	}

	mu.Lock()
	delete(served, "h1")
	mu.Unlock()
	w.advance(301 * time.Second)
	_, err = gate.Verify(ctx, signRS256(t, k1, "h1", claims("u1")))
	wantRefusal(t, err, 401, "Key not found in JWKS")

	mu.Lock()
	down = true
	mu.Unlock()
	w.advance(301 * time.Second)
	before := *fetches
	_, err = gate.Verify(ctx, token2)
	wantRefusal(t, err, 401, "Key not found in JWKS")
	if *fetches == before {
		t.Fatal("an expired JWKS was not refetched")
	}
}

func TestHydraUnreachableLeavesKratosVerdictAndKratosFailureIs500(t *testing.T) {
	ctx := context.Background()
	w := newWorld(t)
	gate := newTestGate(t, Config{Issuer: testIssuer, Audience: testAudience, HydraAudience: "mcp"}, Deps{Store: w.store, Graph: w.graph})
	_, err := gate.Verify(ctx, w.session(t, "u1"))
	wantRefusal(t, err, 500, port.DetailAuthInternal)
	if p, err := gate.Optional(ctx, w.session(t, "u1"), false); p != nil || err != nil {
		t.Fatal("the optional edge did not read Python's 500 HTTPException as nobody")
	}
}

func TestNonHTTPHydraURLFailsAtLoadNotPerRequest(t *testing.T) {
	for _, u := range []string{"ftp://hydra", "file:///etc/passwd", "hydra:4444", ""} {
		if u != "" {
			l := config.FromMap(map[string]string{"AGENTAREA_AUTH_HYDRA_URL": u})
			LoadConfig(l)
			if l.Err() == nil {
				t.Errorf("LoadConfig accepted %q", u)
			}
		}
		if _, err := New(Config{HydraURL: u}, Deps{Store: newFakeStore(), Graph: &fakeGraph{}}); err == nil {
			t.Errorf("New accepted %q", u)
		}
	}
	for _, u := range []string{"http://hydra:4444", "HTTPS://hydra.example"} {
		l := config.FromMap(map[string]string{"AGENTAREA_AUTH_HYDRA_URL": u})
		LoadConfig(l)
		if err := l.Err(); err != nil {
			t.Errorf("%s: %v", u, err)
		}
	}
	l := config.FromMap(nil)
	if LoadConfig(l); l.Err() != nil {
		t.Errorf("the default: %v", l.Err())
	}
}

func hydraGate(t *testing.T, w *world, srv *httptest.Server) *Gate {
	return newTestGate(t, Config{
		JWKSB64: ecJWKS(t, w.kratos, "k1"), Issuer: testIssuer, Audience: testAudience,
		HydraURL: srv.URL, HydraAudience: "mcp",
	}, Deps{Store: w.store, Graph: w.graph, Now: w.nowFunc})
}

func hydraClaims(w *world, srv *httptest.Server) map[string]any {
	now := w.nowFunc().Unix()
	return map[string]any{"sub": "u1", "aud": "mcp", "iss": srv.URL, "iat": now, "exp": now + 600, "client_id": "cli"}
}

// A token whose header does not parse names no key: Hydra's JWKS is not asked.
func TestHydraParsesTheHeaderBeforeFetching(t *testing.T) {
	ctx := context.Background()
	k1, _ := rsa.GenerateKey(rand.Reader, 2048)
	srv, fetches := jwksServer(t, func() []byte { return rsaJWKS(map[string]*rsa.PrivateKey{"h1": k1}) })
	w := newWorld(t)
	gate := hydraGate(t, w, srv)
	for _, token := range []string{"garbage", "a.b.c", "eyJhbGciOiJSUzI1NiJ9", base64.RawURLEncoding.EncodeToString([]byte("not json")) + ".e30.sig"} {
		if _, err := gate.Verify(ctx, token); err == nil {
			t.Fatalf("accepted %q", token)
		}
	}
	if *fetches != 0 {
		t.Fatalf("%d JWKS fetches for tokens with no readable header", *fetches)
	}
	if _, err := gate.Verify(ctx, signRS256(t, k1, "h1", hydraClaims(w, srv))); err != nil {
		t.Fatal(err)
	}
	if *fetches != 1 {
		t.Errorf("fetches %d", *fetches)
	}
}

func TestHydraCachesAFailedFetchForTheCooldown(t *testing.T) {
	ctx := context.Background()
	k1, _ := rsa.GenerateKey(rand.Reader, 2048)
	srv, fetches := jwksServer(t, func() []byte { return nil })
	w := newWorld(t)
	gate := hydraGate(t, w, srv)
	token := signRS256(t, k1, "h1", hydraClaims(w, srv))
	for range 5 {
		_, err := gate.Verify(ctx, token)
		wantRefusal(t, err, 401, "Key not found in JWKS")
	}
	if *fetches != 1 {
		t.Fatalf("a down JWKS was fetched %d times within the cooldown", *fetches)
	}
	w.advance(31 * time.Second)
	_, _ = gate.Verify(ctx, token)
	if *fetches != 2 {
		t.Errorf("not retried after the cooldown: %d", *fetches)
	}
}

// A slow JWKS refresh holds no lock: a token whose key is cached verifies
// meanwhile, and concurrent refreshes share one fetch.
func TestHydraFetchesOutsideTheLockOnce(t *testing.T) {
	ctx := context.Background()
	k1, _ := rsa.GenerateKey(rand.Reader, 2048)
	k2, _ := rsa.GenerateKey(rand.Reader, 2048)
	var mu sync.Mutex
	served := map[string]*rsa.PrivateKey{"h1": k1}
	var hold chan struct{}
	arrived := make(chan struct{}, 8)
	srv, fetches := jwksServer(t, func() []byte {
		mu.Lock()
		h := hold
		body := rsaJWKS(served)
		mu.Unlock()
		if h != nil {
			arrived <- struct{}{}
			<-h
		}
		return body
	})
	w := newWorld(t)
	gate := hydraGate(t, w, srv)
	known := signRS256(t, k1, "h1", hydraClaims(w, srv))
	if _, err := gate.Verify(ctx, known); err != nil {
		t.Fatal(err)
	}

	release := make(chan struct{})
	mu.Lock()
	hold = release
	served["h2"] = k2
	mu.Unlock()
	w.advance(31 * time.Second)
	rotated := signRS256(t, k2, "h2", hydraClaims(w, srv))
	var wg sync.WaitGroup
	errs := make([]error, 3)
	for i := range errs {
		wg.Go(func() { _, errs[i] = gate.Verify(ctx, rotated) })
	}
	select {
	case <-arrived:
	case <-time.After(5 * time.Second):
		t.Fatal("no refresh reached the JWKS")
	}

	done := make(chan error, 1)
	go func() { _, err := gate.Verify(ctx, known); done <- err }()
	select {
	case err := <-done:
		if err != nil {
			t.Errorf("cached key: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Error("a cached key waited for a JWKS fetch")
	}
	close(release)
	wg.Wait()
	for i, err := range errs {
		if err != nil {
			t.Errorf("refresh %d: %v", i, err)
		}
	}
	if *fetches != 2 {
		t.Errorf("concurrent refreshes made %d fetches in all, want 2", *fetches)
	}
}

// Hydra signs only with its own issuer; a token naming another, or none, is
// not one Hydra issued for this deployment.
func TestHydraRequiresHydrasIssuer(t *testing.T) {
	ctx := context.Background()
	k1, _ := rsa.GenerateKey(rand.Reader, 2048)
	srv, _ := jwksServer(t, func() []byte { return rsaJWKS(map[string]*rsa.PrivateKey{"h1": k1}) })
	w := newWorld(t)
	gate := hydraGate(t, w, srv)
	claims := hydraClaims(w, srv)
	if _, err := gate.Verify(ctx, signRS256(t, k1, "h1", claims)); err != nil {
		t.Fatal(err)
	}
	for _, iss := range []any{"https://other-hydra.example", srv.URL + "/", "", 42, nil} {
		claims["iss"] = iss
		_, err := gate.Verify(ctx, signRS256(t, k1, "h1", claims))
		wantRefusal(t, err, 401, detailHydraIssuer)
	}
	delete(claims, "iss")
	_, err := gate.Verify(ctx, signRS256(t, k1, "h1", claims))
	wantRefusal(t, err, 401, detailHydraIssuer)
}

// The issuer comes from Hydra's discovery document: without one the JWKS is
// not trusted and the token is judged as Kratos's (401, not 500).
func TestHydraWithoutDiscoveryIsUnavailable(t *testing.T) {
	ctx := context.Background()
	k1, _ := rsa.GenerateKey(rand.Reader, 2048)
	for name, discovery := range map[string]func(http.ResponseWriter){
		"down":      func(w http.ResponseWriter) { http.Error(w, "down", http.StatusServiceUnavailable) },
		"no issuer": func(w http.ResponseWriter) { _, _ = w.Write([]byte(`{"jwks_uri":"x"}`)) },
		"empty":     func(w http.ResponseWriter) { _, _ = w.Write([]byte(`{"issuer":""}`)) },
	} {
		t.Run(name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
				switch r.URL.Path {
				case "/.well-known/openid-configuration":
					discovery(rw)
				case "/.well-known/jwks.json":
					_, _ = rw.Write(rsaJWKS(map[string]*rsa.PrivateKey{"h1": k1}))
				default:
					http.NotFound(rw, r)
				}
			}))
			t.Cleanup(srv.Close)
			w := newWorld(t)
			gate := hydraGate(t, w, srv)
			_, err := gate.Verify(ctx, signRS256(t, k1, "h1", hydraClaims(w, srv)))
			wantRefusal(t, err, 401, "Key not found in JWKS")
		})
	}
}

func TestNewRefusesTurnTokensWithoutLiveTurns(t *testing.T) {
	_, err := New(Config{GatewaySecret: testSecret}, Deps{Store: newFakeStore(), Graph: &fakeGraph{}})
	if err == nil {
		t.Fatal("turn tokens without a live-turn store")
	}
	if _, err := NewTurnTokens("short", nil); err == nil {
		t.Fatal("short secret")
	}
}
