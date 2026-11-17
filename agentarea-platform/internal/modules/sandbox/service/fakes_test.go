package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/service/servicetest"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

// memEvents is artifact_events in memory, newest last.
type memEvents struct {
	mu  sync.Mutex
	evs map[string][]domain.ArtifactEvent
}

func (m *memEvents) Insert(_ context.Context, s db.Session, e domain.ArtifactEvent) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.evs == nil {
		m.evs = map[string][]domain.ArtifactEvent{}
	}
	k := s.Workspace().ID() + "|" + e.Path
	m.evs[k] = append(m.evs[k], e)
	return nil
}

func (m *memEvents) History(_ context.Context, s db.Session, path string) ([]domain.ArtifactEvent, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	src := m.evs[s.Workspace().ID()+"|"+path]
	out := make([]domain.ArtifactEvent, len(src))
	for i, e := range src {
		out[len(src)-1-i] = e
	}
	return out, nil
}

func (m *memEvents) Rename(_ context.Context, s db.Session, source, destination string, _ time.Time) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	from, to := s.Workspace().ID()+"|"+source, s.Workspace().ID()+"|"+destination
	for _, e := range m.evs[from] {
		e.Path = destination
		m.evs[to] = append(m.evs[to], e)
	}
	delete(m.evs, from)
	return nil
}

func (m *memEvents) seed(wsID string, e domain.ArtifactEvent) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.evs == nil {
		m.evs = map[string][]domain.ArtifactEvent{}
	}
	m.evs[wsID+"|"+e.Path] = append(m.evs[wsID+"|"+e.Path], e)
}

func (m *memEvents) actions(wsID, path string) []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []string
	for _, e := range m.evs[wsID+"|"+path] {
		out = append(out, e.Action)
	}
	return out
}

type projectIDs []string

func (p projectIDs) IDs(context.Context, scope.Workspace) ([]string, error) { return p, nil }

const (
	wsID  = "11111111-1111-1111-1111-111111111111"
	user1 = "user-1"
)

type fixture struct {
	svc    *Service
	store  *servicetest.MemStore
	events *memEvents
	ws     scope.Workspace
}

func newFixture(t *testing.T, d Deps) fixture {
	t.Helper()
	ws, err := scope.NewWorkspace(wsID, "acme")
	if err != nil {
		t.Fatal(err)
	}
	st := servicetest.NewMemStore()
	ev := &memEvents{}
	d.DB, d.Blob, d.Events = fakeDB{}, st, ev
	if d.Projects == nil {
		d.Projects = projectIDs{"p1"}
	}
	if d.Bucket == "" {
		d.Bucket = "artifacts"
	}
	n := 0
	d.NewHex = func() string { n++; return strings.Repeat("0", 31) + strconv.Itoa(n%10) }
	var tick time.Duration
	d.Now = func() time.Time {
		t := time.Date(2026, 11, 12, 9, 30, 15, 123456000, time.UTC).Add(tick)
		tick += time.Millisecond
		return t
	}
	return fixture{svc: New(d), store: st, events: ev, ws: ws}
}

func sha(data string) string {
	s := sha256.Sum256([]byte(data))
	return hex.EncodeToString(s[:])
}

func (f fixture) put(t *testing.T, path, data string) {
	t.Helper()
	if _, err := f.svc.Artifacts().Put(context.Background(), wsID, path, []byte(data), "", nil); err != nil {
		t.Fatalf("put %s: %v", path, err)
	}
}

func httpStatus(t *testing.T, err error) int {
	t.Helper()
	var he *HTTPError
	if !errors.As(err, &he) {
		t.Fatalf("want HTTPError, got %v", err)
	}
	return he.Status
}

func blobOpts(ct string) blob.PutOptions { return blob.PutOptions{ContentType: ct} }
