package authn

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"
	"time"

	port "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
)

type fakeStore struct {
	mu         sync.Mutex
	keys       map[string]APIKey
	workspaces []Workspace
	uses       map[string]int
	stamps     map[string]time.Time
	writeErr   error
	dbErr      error
}

func newFakeStore() *fakeStore {
	return &fakeStore{keys: map[string]APIKey{}, uses: map[string]int{}, stamps: map[string]time.Time{}}
}

func (s *fakeStore) APIKeyByHash(_ context.Context, h string) (APIKey, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.dbErr != nil {
		return APIKey{}, false, s.dbErr
	}
	k, ok := s.keys[h]
	return k, ok, nil
}

func (s *fakeStore) RecordAPIKeyUse(_ context.Context, id string, uses int, at time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.writeErr != nil {
		return s.writeErr
	}
	s.uses[id] += uses
	s.stamps[id] = at
	return nil
}

func (s *fakeStore) WorkspaceByID(_ context.Context, id string) (Workspace, bool, error) {
	if s.dbErr != nil {
		return Workspace{}, false, s.dbErr
	}
	for _, w := range s.workspaces {
		if w.ID == id {
			return w, true, nil
		}
	}
	return Workspace{}, false, nil
}

func (s *fakeStore) WorkspaceBySlug(_ context.Context, slug string) (Workspace, bool, error) {
	for _, w := range s.workspaces {
		if w.Slug == slug {
			return w, true, nil
		}
	}
	return Workspace{}, false, nil
}

func (s *fakeStore) OwnedOrNamed(_ context.Context, userID, slug, id string) ([]Workspace, error) {
	if s.dbErr != nil {
		return nil, s.dbErr
	}
	var out []Workspace
	for _, w := range s.workspaces {
		if w.OwnerUserID == userID || (slug != "" && w.Slug == slug) || (id != "" && w.ID == id) {
			out = append(out, w)
		}
	}
	return out, nil
}

// fakeGraph holds Workspace#members tuples as "ws|User:id".
type fakeGraph struct {
	members map[string]bool
	err     error
	checks  int
}

func (g *fakeGraph) Check(_ context.Context, subject, relation, objectType, objectID string) (bool, error) {
	g.checks++
	if g.err != nil {
		return false, g.err
	}
	if relation != "members" || objectType != "Workspace" {
		return false, errors.New("unexpected check")
	}
	return g.members[objectID+"|"+subject], nil
}

func (g *fakeGraph) Read(_ context.Context, q authz.Query) ([]authz.Tuple, error) {
	if g.err != nil {
		return nil, g.err
	}
	var out []authz.Tuple
	for k := range g.members {
		ws, user, _ := cutPipe(k)
		t := authz.Tuple{User: user, Relation: "members", Object: "Workspace:" + ws}
		if q.Matches(t) {
			out = append(out, t)
		}
	}
	return out, nil
}

func cutPipe(s string) (string, string, bool) {
	for i := range len(s) {
		if s[i] == '|' {
			return s[:i], s[i+1:], true
		}
	}
	return s, "", false
}

type fakeLive struct {
	alive map[string]bool
	err   error
}

func (l *fakeLive) Begin(context.Context, string, time.Duration) error { return nil }
func (l *fakeLive) Renew(context.Context, string, time.Duration) error { return nil }
func (l *fakeLive) End(context.Context, string) error                  { return nil }
func (l *fakeLive) Alive(_ context.Context, id string) (bool, error) {
	return l.alive[id], l.err
}

type golden struct {
	Issuer    string          `json:"issuer"`
	Audience  string          `json:"audience"`
	HydraJWKS json.RawMessage `json:"hydra_jwks"`
	Scenarios []scenario      `json:"scenarios"`
	Tokens    map[string]string
	Results   map[string]map[string]outcome `json:"results"`
	Turn      goldenTurn                    `json:"turn"`
	APIKeys   []goldenKey                   `json:"api_keys"`
}

type scenario struct {
	Name          string   `json:"name"`
	JWKSB64       string   `json:"jwks_b64"`
	HydraAudience string   `json:"hydra_audience"`
	Tokens        []string `json:"tokens"`
}

type outcome struct {
	Status          int    `json:"status"`
	UserID          string `json:"user_id"`
	Email           string `json:"email"`
	Kind            string `json:"kind"`
	Detail          string `json:"detail"`
	WWWAuthenticate string `json:"www_authenticate"`
	Raised          string `json:"raised"`
}

type goldenClaims struct {
	TurnID      string `json:"turn_id"`
	TaskID      string `json:"task_id"`
	WorkspaceID string `json:"workspace_id"`
	ClientID    string `json:"client_id"`
	ActorType   string `json:"actor_type"`
	ActorID     string `json:"actor_id"`
	OnBehalfOf  string `json:"on_behalf_of"`
	Raised      string `json:"raised"`
}

func (c goldenClaims) port() port.TurnClaims {
	return port.TurnClaims{
		TurnID: c.TurnID, TaskID: c.TaskID, WorkspaceID: c.WorkspaceID, ClientID: c.ClientID,
		ActorType: port.SubjectKind(c.ActorType), ActorID: c.ActorID, OnBehalfOf: c.OnBehalfOf,
	}
}

type goldenTurn struct {
	Secret   string `json:"secret"`
	IssuedAt int64  `json:"issued_at"`
	Issue    []struct {
		Claims goldenClaims `json:"claims"`
		TTL    int64        `json:"ttl"`
		Token  string       `json:"token"`
	} `json:"issue"`
	Cases   map[string]string        `json:"cases"`
	Decoded map[string]*goldenClaims `json:"decoded"`
	IsTurn  map[string]bool          `json:"is_turn"`
}

type goldenKey struct {
	Token  string `json:"token"`
	Prefix string `json:"prefix"`
	Hash   string `json:"hash"`
}

// loadGolden reads what the Python auth code produced
// (testdata/python_golden.json, made by running the Python code offline).
func loadGolden(t *testing.T) golden {
	t.Helper()
	raw, err := os.ReadFile("testdata/python_golden.json")
	if err != nil {
		t.Fatal(err)
	}
	var g golden
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	return g
}

// jwksServer serves body as Hydra's JWKS and counts fetches.
func jwksServer(t *testing.T, body func() []byte) (*httptest.Server, *int) {
	t.Helper()
	var mu sync.Mutex
	fetches := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/.well-known/jwks.json" {
			http.NotFound(w, r)
			return
		}
		mu.Lock()
		fetches++
		mu.Unlock()
		b := body()
		if b == nil {
			http.Error(w, "down", http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(b)
	}))
	t.Cleanup(srv.Close)
	return srv, &fetches
}

func quietLog() *slog.Logger {
	return slog.New(slog.NewTextHandler(discard{}, &slog.HandlerOptions{Level: slog.LevelError + 1}))
}

type discard struct{}

func (discard) Write(p []byte) (int, error) { return len(p), nil }

func newTestGate(t *testing.T, cfg Config, d Deps) *Gate {
	t.Helper()
	if d.Store == nil {
		d.Store = newFakeStore()
	}
	if d.Graph == nil {
		d.Graph = &fakeGraph{members: map[string]bool{}}
	}
	if d.Log == nil {
		d.Log = quietLog()
	}
	if cfg.APIURL == "" {
		cfg.APIURL = "http://localhost:8000"
	}
	if cfg.HydraURL == "" {
		cfg.HydraURL = "http://127.0.0.1:9"
	}
	g, err := New(cfg, d)
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func asRefusal(err error) (*port.Error, bool) {
	var e *port.Error
	ok := errors.As(err, &e)
	return e, ok
}
