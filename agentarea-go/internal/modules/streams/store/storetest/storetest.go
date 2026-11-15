// Package storetest holds the test doubles streams' tests share: a database
// over a real Postgres pool, and fakes for the graph, agents and scheduler ports.
package storetest

import (
	"context"
	"errors"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

// Pool opens the test Postgres named by AGENTAREA_TEST_POSTGRES_URL with the
// core schema migrated, or skips the test when it is not set.
func Pool(t testing.TB) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_TEST_POSTGRES_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_TEST_POSTGRES_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

// Workspace inserts a workspace and returns it bound to a fresh id.
func Workspace(t testing.TB, pool *pgxpool.Pool) scope.Workspace {
	t.Helper()
	id := uuid.NewString()
	slug := "ws-" + id[:8]
	if _, err := pool.Exec(context.Background(),
		`INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, slug); err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(id, slug)
	if err != nil {
		t.Fatal(err)
	}
	return ws
}

// Caller is the workspace caller of user in ws, placed in a context.
func Caller(ctx context.Context, ws scope.Workspace, user string) (context.Context, authn.Caller) {
	c := authn.Caller{Principal: authn.Principal{UserID: user}, Workspace: ws}
	return authn.WithCaller(ctx, c), c
}

// DB is kernel/db.Database over a pgx pool: reads on the pool, writes in a transaction.
type DB struct{ Pool *pgxpool.Pool }

var _ db.Database = DB{}

// Read returns a session on the pool.
func (d DB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, d.Pool), func() {}, nil
}

// Write runs fn in one transaction.
func (d DB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	tx, err := d.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	if err := fn(ctx, db.NewTxSession(ws, tx)); err != nil {
		_ = tx.Rollback(ctx)
		return err
	}
	return tx.Commit(ctx)
}

// Global reaches workspace-less reads and writes on the pool.
func (d DB) Global() db.Global { return global{d.Pool} }

type global struct{ pool *pgxpool.Pool }

func (g global) Read(context.Context) (db.Querier, func(), error) { return g.pool, func() {}, nil }

func (g global) Write(ctx context.Context, fn func(context.Context, db.Querier) error) error {
	return fn(ctx, g.pool)
}

var errUnused = errors.New("streamstest: not used by these tests")

// Lock is not used by streams' tests.
func (DB) Lock(context.Context, db.LockKey, func(context.Context, db.Querier) error) error {
	return errUnused
}

// TryLock is not used by streams' tests.
func (DB) TryLock(context.Context, db.LockKey, func(context.Context, db.Querier) error) (bool, error) {
	return false, errUnused
}

// TrySessionLock is not used by streams' tests.
func (DB) TrySessionLock(context.Context, db.LockKey, func(context.Context, db.Querier) error) (bool, error) {
	return false, errUnused
}

// Ping always succeeds.
func (d DB) Ping(ctx context.Context) error { return d.Pool.Ping(ctx) }

// Close does nothing; the test owns the pool.
func (DB) Close() {}

// Graph is an authz.Graph that allows what Allow lists and records what it is asked to write.
type Graph struct {
	mu       sync.Mutex
	Allow    map[string]bool
	AllowAll bool
	// Readable is what ListObjects lists under AllowAll.
	Readable []string
	Writes   []authz.Tuple
}

var _ authz.Graph = (*Graph)(nil)

// Grant allows subject the relation on resource id (a resource:<id> object).
func (g *Graph) Grant(subject, relation, resourceID string) {
	if g.Allow == nil {
		g.Allow = map[string]bool{}
	}
	g.Allow[subject+"|"+relation+"|"+resourceID] = true
}

// Check answers from Allow.
func (g *Graph) Check(_ context.Context, subject, relation, objectType, objectID string) (bool, error) {
	if g.AllowAll {
		return true, nil
	}
	return g.Allow[subject+"|"+relation+"|"+objectID], nil
}

// BatchCheck answers each item with Check.
func (g *Graph) BatchCheck(ctx context.Context, items []authz.CheckItem) ([]bool, error) {
	out := make([]bool, len(items))
	for i, it := range items {
		ok, err := g.Check(ctx, it.Subject, it.Relation, it.ObjectType, it.ObjectID)
		if err != nil {
			return nil, err
		}
		out[i] = ok
	}
	return out, nil
}

// ListObjects lists the resource ids Allow grants subject the relation on (Readable when AllowAll).
func (g *Graph) ListObjects(_ context.Context, subject, relation, _ string) ([]string, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.AllowAll {
		return append([]string(nil), g.Readable...), nil
	}
	var out []string
	for k, ok := range g.Allow {
		parts := strings.SplitN(k, "|", 3)
		if ok && parts[0] == subject && parts[1] == relation {
			out = append(out, parts[2])
		}
	}
	return out, nil
}

// Read returns nothing.
func (*Graph) Read(context.Context, authz.Query) ([]authz.Tuple, error) { return nil, nil }

// Write records the tuples.
func (g *Graph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.Writes = append(g.Writes, writes...)
	return nil
}

// Agents knows the agent ids in Known.
type Agents struct{ Known map[string]bool }

// AgentExists reports whether id is known.
func (a Agents) AgentExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	return a.Known[id], nil
}

// Schedules is an in-memory durable.Scheduler.
type Schedules struct {
	mu        sync.Mutex
	Items     map[string]durable.Schedule
	EnsureErr error
}

var _ durable.Scheduler = (*Schedules)(nil)

// Ensure stores s.
func (f *Schedules) Ensure(_ context.Context, s durable.Schedule) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.EnsureErr != nil {
		return f.EnsureErr
	}
	if f.Items == nil {
		f.Items = map[string]durable.Schedule{}
	}
	f.Items[s.ID] = s
	return nil
}

// Describe returns the stored schedule as its info, durable.ErrNotFound when absent.
func (f *Schedules) Describe(_ context.Context, id string) (durable.ScheduleInfo, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	s, ok := f.Items[id]
	if !ok {
		return durable.ScheduleInfo{}, durable.ErrNotFound
	}
	return durable.ScheduleInfo{ID: s.ID, Workflow: s.Workflow, WorkflowID: s.WorkflowID, TaskQueue: s.TaskQueue,
		Cron: s.Cron, TimeZone: s.TimeZone, CatchupWindow: s.CatchupWindow, Paused: s.Paused}, nil
}

// Delete removes the schedule, durable.ErrNotFound when absent.
func (f *Schedules) Delete(_ context.Context, id string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if _, ok := f.Items[id]; !ok {
		return durable.ErrNotFound
	}
	delete(f.Items, id)
	return nil
}
