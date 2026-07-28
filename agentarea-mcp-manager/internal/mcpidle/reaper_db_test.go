package mcpidle

import (
	"context"
	"database/sql"
	"os"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// These tests run the reaper's real SQL against a real database carrying the
// schema alembic produces. That combination is the point: every defect this
// package has had lived in the SQL and was invisible to the unit tests above.
// The first version of the reaper filtered on a `status` column that had been
// dropped from mcp_server_instances a year earlier, so every sweep failed with
// `column "status" does not exist` and was swallowed as a warning — a hand-built
// table in a Go test would have carried whatever column the test author
// imagined, and would have happily passed.
//
// So the schema must come from the migrations, not from this file. CI runs these
// in the migrations gate, where a fresh database has just been migrated to head.
// Locally:
//
//	docker run -d --name pg -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test \
//	  -e POSTGRES_DB=mcpidle -p 55433:5432 postgres:18
//	cd agentarea-platform/apps/api && POSTGRES_HOST=localhost POSTGRES_PORT=55433 \
//	  POSTGRES_USER=test POSTGRES_PASSWORD=test POSTGRES_DB=mcpidle uv run alembic upgrade head
//	MCPIDLE_TEST_DATABASE_URL=postgres://test:test@localhost:55433/mcpidle?sslmode=disable \
//	  go test ./internal/mcpidle/...

const testDSNEnv = "MCPIDLE_TEST_DATABASE_URL"

func openTestDB(t *testing.T) *sql.DB {
	t.Helper()

	dsn := os.Getenv(testDSNEnv)
	if dsn == "" {
		t.Skipf("%s not set; skipping schema-backed reaper tests", testDSNEnv)
	}

	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("opening test database: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	if err := db.PingContext(context.Background()); err != nil {
		t.Fatalf("connecting to test database: %v", err)
	}
	return db
}

// insertInstance adds one row and removes it when the test ends. Columns are
// written positionally against the migrated schema, so a rename or a type change
// fails here rather than silently changing what the reaper matches.
func insertInstance(t *testing.T, db *sql.DB, id, name, jsonSpec, verificationStatus string, lastUsed *time.Time) {
	t.Helper()

	verification := `{"schema_version":1,"status":"` + verificationStatus + `","at":null,"error":null}`
	_, err := db.ExecContext(context.Background(), `
		INSERT INTO mcp_server_instances
			(id, server_spec_id, name, json_spec, workspace_id, created_by, verification, last_used_at)
		VALUES ($1::uuid, 'spec', $2, $3::json, 'ws', 'user', $4::jsonb, $5)
	`, id, name, jsonSpec, verification, lastUsed)
	if err != nil {
		t.Fatalf("inserting instance %s: %v", name, err)
	}

	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM mcp_server_instances WHERE id = $1::uuid`, id)
	})
}

func ago(d time.Duration) *time.Time {
	at := time.Now().Add(-d)
	return &at
}

// TestReaperSQLSelectsOnlyIdleServerlessInstances pins the whole selection
// matrix. Each non-selected row is a distinct way the reaper could destroy
// something it should not have touched.
func TestReaperSQLSelectsOnlyIdleServerlessInstances(t *testing.T) {
	db := openTestDB(t)

	const (
		idleSrvls  = "11111111-1111-4111-8111-000000000001"
		busySrvls  = "11111111-1111-4111-8111-000000000002"
		neverUsed  = "11111111-1111-4111-8111-000000000003"
		idleEager  = "11111111-1111-4111-8111-000000000004"
		unverified = "11111111-1111-4111-8111-000000000005"
		failed     = "11111111-1111-4111-8111-000000000006"
	)
	lazy, eager := `{"lazy_provisioning":true}`, `{}`

	insertInstance(t, db, idleSrvls, "idle-serverless", lazy, "succeeded", ago(30*time.Minute))
	insertInstance(t, db, busySrvls, "busy-serverless", lazy, "succeeded", ago(time.Minute))
	insertInstance(t, db, neverUsed, "never-called", lazy, "succeeded", nil)
	insertInstance(t, db, idleEager, "idle-eager", eager, "succeeded", ago(30*time.Minute))
	insertInstance(t, db, unverified, "idle-unprovisioned", lazy, "never_attempted", ago(30*time.Minute))
	insertInstance(t, db, failed, "idle-failed", lazy, "failed", ago(30*time.Minute))

	reaper := newTestReaper(&fakeBackend{})
	idle, err := reaper.findIdle(context.Background(), db, 10*time.Minute)
	if err != nil {
		t.Fatalf("findIdle against the migrated schema: %v", err)
	}

	selected := make(map[string]bool, len(idle))
	for _, inst := range idle {
		selected[inst.id] = true
	}

	if !selected[idleSrvls] {
		t.Error("an idle serverless instance was not selected; nothing would ever be reclaimed")
	}
	for _, c := range []struct {
		id, why string
	}{
		{busySrvls, "an instance called a minute ago is in use; stopping it breaks a live session"},
		{neverUsed, "no recorded use means not yet observed, not idle — this is every row predating last_used_at"},
		{idleEager, "an eagerly-provisioned instance was asked to stay up"},
		{unverified, "already unprovisioned; selecting it would re-sweep it every tick"},
		{failed, "not running, so there is nothing to stop"},
	} {
		if selected[c.id] {
			t.Errorf("selected an instance it must not touch: %s", c.why)
		}
	}
}

// TestReleaseSQLMakesTheInstanceProvisionableAgain covers the defect that made
// the first reaper leave instances down permanently: stopping the workload
// without resetting verification left the row claiming 'succeeded', so the next
// call skipped provisioning and dispatched to an endpoint that was gone.
func TestReleaseSQLMakesTheInstanceProvisionableAgain(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	const id = "22222222-2222-4222-8222-000000000001"
	insertInstance(t, db, id, "released", `{"lazy_provisioning":true}`, "succeeded", ago(30*time.Minute))

	if _, err := db.ExecContext(ctx, releaseSQL, id); err != nil {
		t.Fatalf("releasing instance: %v", err)
	}

	var status string
	if err := db.QueryRowContext(ctx,
		`SELECT verification->>'status' FROM mcp_server_instances WHERE id = $1::uuid`, id,
	).Scan(&status); err != nil {
		t.Fatalf("reading verification: %v", err)
	}
	if status != "never_attempted" {
		t.Errorf("released instance has status %q; it must be never_attempted so the next call starts it", status)
	}

	// And it must drop out of the sweep, or every tick would try to stop a
	// workload that is already gone.
	reaper := newTestReaper(&fakeBackend{})
	idle, err := reaper.findIdle(ctx, db, 10*time.Minute)
	if err != nil {
		t.Fatalf("findIdle after release: %v", err)
	}
	for _, inst := range idle {
		if inst.id == id {
			t.Error("a released instance is still selected; it would be swept again every tick")
		}
	}
}

// TestReleaseSQLDoesNotClobberAnInFlightVerification covers the race the
// compare-and-set exists for: a call arriving between the sweep's select and its
// release starts provisioning, and that state must win.
func TestReleaseSQLDoesNotClobberAnInFlightVerification(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	const id = "33333333-3333-4333-8333-000000000001"
	insertInstance(t, db, id, "racing", `{"lazy_provisioning":true}`, "in_progress", ago(30*time.Minute))

	result, err := db.ExecContext(ctx, releaseSQL, id)
	if err != nil {
		t.Fatalf("releasing instance: %v", err)
	}
	affected, err := result.RowsAffected()
	if err != nil {
		t.Fatalf("reading rows affected: %v", err)
	}
	if affected != 0 {
		t.Errorf("release overwrote an in-flight verification (%d rows); the caller's state must win", affected)
	}
}

// TestSweepLockExcludesASecondReplica proves the property the advisory lock is
// there for. mcpManager.replicaCount is an operator knob, and two replicas
// sweeping at once race to delete the same workloads.
func TestSweepLockExcludesASecondReplica(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()
	logger := newTestReaper(&fakeBackend{}).logger

	first, acquired, err := acquireSweepLock(ctx, db, logger)
	if err != nil {
		t.Fatalf("first replica taking the sweep lock: %v", err)
	}
	if !acquired {
		t.Fatal("first replica could not take the sweep lock")
	}

	// A distinct pool, because the lock is session-scoped: reusing the same
	// *sql.DB could hand back the connection that already holds it and report a
	// false exclusion.
	second := openTestDB(t)
	lock, acquired, err := acquireSweepLock(ctx, second, logger)
	if err != nil {
		t.Fatalf("second replica probing the sweep lock: %v", err)
	}
	if acquired {
		lock.release(ctx)
		t.Error("two replicas hold the sweep lock at once; they would race to stop the same instances")
	}

	first.release(ctx)

	// Once the holder is done, the next replica must be able to sweep — a lock
	// that is never released would stop reclamation entirely.
	lock, acquired, err = acquireSweepLock(ctx, second, logger)
	if err != nil {
		t.Fatalf("second replica taking the released lock: %v", err)
	}
	if !acquired {
		t.Fatal("the sweep lock was not released; reclamation would stop permanently")
	}
	lock.release(ctx)
}
