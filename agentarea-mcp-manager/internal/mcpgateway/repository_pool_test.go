package mcpgateway

import (
	"context"
	"database/sql"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// The lifecycle lock is held on a pooled connection for the whole cold start,
// and the work it guards — LoadInstance, MarkStarting, MarkReadyAndBeginRequest
// — needs a second connection from that same bounded pool. That combination
// deadlocked production on 2026-08-27: one instance failed to become ready, its
// caller retried every 10s against a 5m start, and within minutes every
// connection in the pool was parked inside pg_advisory_lock. The one caller
// holding the lock could never obtain its second connection, so it timed out at
// the deadline and handed the lock to a waiter with no budget left. No cold
// start ever ran again — for any instance, because the pool is shared even
// though the lock is per instance.
//
// These tests reproduce that shape with a small pool. They need advisory locks
// and a connection pool, not the runtime tables, so they build the repository
// directly instead of going through OpenSQLRepository's schema probe.
func poolTestRepository(t *testing.T, maxOpenConns int) (*SQLRepository, *sql.DB) {
	t.Helper()
	db, err := sql.Open("pgx", testDSN(t))
	if err != nil {
		t.Fatalf("opening test database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	db.SetMaxOpenConns(maxOpenConns)
	if err := db.PingContext(context.Background()); err != nil {
		t.Fatalf("connecting to test database: %v", err)
	}
	return &SQLRepository{db: db}, db
}

func TestWithInstanceLockLetsTheLockHolderReachTheDatabase(t *testing.T) {
	const (
		poolSize = 4
		callers  = 8
	)
	repository, db := poolTestRepository(t, poolSize)

	// More callers than connections, all demanding the same instance: the shape
	// a retrying client produces against a slow cold start.
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	var completed atomic.Int32
	var wg sync.WaitGroup
	for range callers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			err := repository.WithInstanceLock(ctx, "pool-starvation-instance", func(lockCtx context.Context) error {
				// The second pooled connection the real callback takes.
				var one int
				if err := db.QueryRowContext(lockCtx, `SELECT 1`).Scan(&one); err != nil {
					return err
				}
				// Stand in for a cold start that outlives the caller's patience.
				time.Sleep(300 * time.Millisecond)
				return nil
			})
			if err == nil {
				completed.Add(1)
			}
		}()
	}
	wg.Wait()

	if completed.Load() == 0 {
		t.Fatal("no caller completed its critical section: the lock holder starved waiting for a connection every other caller was holding")
	}
}
