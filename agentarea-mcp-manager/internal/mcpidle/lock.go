package mcpidle

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
)

// sweepLockKey identifies the reaper's advisory lock.
//
// A literal rather than a hash of a name so the value is stable across builds
// and greppable when someone finds it held in pg_locks. Chosen to not collide
// with any other advisory lock in the platform.
const sweepLockKey int64 = 0x6D63705F69646C65 // "mcp_idle"

// sweepLock is a held advisory lock, pinned to the connection that took it.
type sweepLock struct {
	conn   *sql.Conn
	logger *slog.Logger
}

// acquireSweepLock takes a cluster-wide advisory lock for one sweep.
//
// mcpManager.replicaCount is an operator knob, so more than one manager can be
// running. Every replica would otherwise select the same idle rows and race to
// delete the same workloads: the losers log failures for work that already
// succeeded, and an instance provisioned between one replica's select and
// another's delete can be torn down immediately after coming up. Serialising
// the sweep is cheaper and clearer than making every step idempotent.
//
// The lock is session-scoped and pinned to a dedicated connection, so a manager
// that crashes mid-sweep releases it when its connection closes — there is no
// stuck lock to clear by hand.
//
// A second return of false means another replica is sweeping; that is the
// normal, non-error outcome and the caller should simply skip this tick.
func acquireSweepLock(ctx context.Context, db *sql.DB, logger *slog.Logger) (*sweepLock, bool, error) {
	conn, err := db.Conn(ctx)
	if err != nil {
		return nil, false, fmt.Errorf("acquiring connection for sweep lock: %w", err)
	}

	var acquired bool
	if err := conn.QueryRowContext(ctx, "SELECT pg_try_advisory_lock($1)", sweepLockKey).Scan(&acquired); err != nil {
		conn.Close()
		return nil, false, fmt.Errorf("taking sweep lock: %w", err)
	}
	if !acquired {
		conn.Close()
		return nil, false, nil
	}

	return &sweepLock{conn: conn, logger: logger}, true, nil
}

// release drops the advisory lock and returns the connection to the pool.
func (l *sweepLock) release(ctx context.Context) {
	if _, err := l.conn.ExecContext(ctx, "SELECT pg_advisory_unlock($1)", sweepLockKey); err != nil {
		// Closing the connection ends the session, which drops the lock anyway;
		// log it because a failure here usually means the database went away
		// mid-sweep and the rest of the sweep's results are suspect.
		l.logger.Warn("Failed to release MCP idle sweep lock", slog.String("error", err.Error()))
	}
	l.conn.Close()
}
