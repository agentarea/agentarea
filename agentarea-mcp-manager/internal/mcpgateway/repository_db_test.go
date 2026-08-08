package mcpgateway

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/agentarea/mcp-manager/internal/models"
)

// These tests run the gateway's real SQL against a real database carrying the
// schema alembic produces. That combination is the point: the lifecycle rules
// this package enforces — one cold start at a time, a workload that survives
// while a request holds a lease, a reaper that only takes idle instances — live
// entirely in SQL and are invisible to the stubbed unit tests next door. A
// hand-built table in a Go test would carry whatever columns the test author
// imagined and would happily pass while production failed.
//
// So the schema must come from the migrations, not from this file. CI runs
// these in the migrations gate, where a fresh database has just been migrated
// to head. Locally:
//
//	docker run -d --name pg -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test \
//	  -e POSTGRES_DB=mcpgateway -p 55433:5432 postgres:18
//	cd agentarea-platform/apps/api && POSTGRES_HOST=localhost POSTGRES_PORT=55433 \
//	  POSTGRES_USER=test POSTGRES_PASSWORD=test POSTGRES_DB=mcpgateway uv run alembic upgrade head
//	MCP_GATEWAY_TEST_DATABASE_URL=postgres://test:test@localhost:55433/mcpgateway?sslmode=disable \
//	  go test ./internal/mcpgateway/...

const (
	testDSNEnv = "MCP_GATEWAY_TEST_DATABASE_URL"
	// requireDBEnv turns a skip into a failure. Set by the CI job that provides
	// the migrated database, so a DSN that fails to reach the test surfaces as a
	// red build instead of a green one that checked nothing.
	requireDBEnv = "MCP_GATEWAY_REQUIRE_DB"
)

func testDSN(t *testing.T) string {
	t.Helper()
	dsn := os.Getenv(testDSNEnv)
	if dsn != "" {
		return dsn
	}
	// Skipping is right on a developer's machine, and in the Go CI job, which
	// runs `go test ./...` with no database on purpose. It is wrong in the job
	// that stands one up: there a silent skip reports "ok" for the only check
	// that ever exercises this SQL against a real schema.
	if os.Getenv(requireDBEnv) != "" {
		t.Fatalf("%s is set but %s is empty: the schema-backed gateway tests were meant to run here, not skip",
			requireDBEnv, testDSNEnv)
	}
	t.Skipf("%s not set; skipping schema-backed MCP gateway lifecycle tests", testDSNEnv)
	return ""
}

// openRepository goes through the production constructor so its schema
// precondition is exercised too: a database missing the runtime tables must be
// refused at startup rather than discovered on the first request.
func openRepository(t *testing.T) *SQLRepository {
	t.Helper()
	repository, err := OpenSQLRepository(context.Background(), testDSN(t))
	if err != nil {
		t.Fatalf("OpenSQLRepository() against the migrated schema: %v", err)
	}
	t.Cleanup(func() { _ = repository.Close() })
	return repository
}

func openRawDB(t *testing.T) *sql.DB {
	t.Helper()
	db, err := sql.Open("pgx", testDSN(t))
	if err != nil {
		t.Fatalf("opening test database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := db.PingContext(context.Background()); err != nil {
		t.Fatalf("connecting to test database: %v", err)
	}
	return db
}

// seedInstance writes one desired-state instance and its server spec against the
// migrated schema, so a rename or type change fails here rather than silently
// changing what the gateway matches.
func seedInstance(t *testing.T, db *sql.DB, instanceID, specKind string) {
	t.Helper()
	ctx := context.Background()
	serverID := instanceID

	// mcp_servers has a unique (workspace_id, slug); derive it from the whole id
	// so seeding several instances in one test cannot collide.
	unique := "gw-" + strings.ReplaceAll(instanceID, "-", "")

	var dockerImage, remoteURL any
	var command any
	switch specKind {
	case "docker":
		dockerImage = "ghcr.io/example/mcp:1"
	case "command":
		command = `["mcp-server","--stdio"]`
	case "url":
		remoteURL = "https://remote.example/mcp"
	default:
		t.Fatalf("unknown spec kind %q", specKind)
	}

	if _, err := db.ExecContext(ctx, `
INSERT INTO mcp_servers
  (id, name, slug, description, version, tags, status, is_public, env_schema,
   docker_image_url, remote_url, cmd, json_spec, workspace_id, created_by)
VALUES
  ($1::uuid, $2, $2, 'schema-backed gateway test', '1.0.0', '[]'::json, 'active', false, '[]'::json,
   $3, $4, $5::json, '{}'::jsonb, 'ws-test', 'user-test')
`, serverID, unique, dockerImage, remoteURL, command); err != nil {
		t.Fatalf("inserting server spec: %v", err)
	}

	if _, err := db.ExecContext(ctx, `
INSERT INTO mcp_server_instances
  (id, server_spec_id, name, description, json_spec, verification, network_scope, workspace_id, created_by)
VALUES
  ($1::uuid, $2, $3, NULL, '{}'::json,
   '{"schema_version":1,"status":"succeeded","at":null,"error":null}'::json,
   'private', 'ws-test', 'user-test')
`, instanceID, serverID, unique); err != nil {
		t.Fatalf("inserting instance: %v", err)
	}

	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM mcp_runtime_request_leases WHERE instance_id = $1::uuid`, instanceID)
		_, _ = db.Exec(`DELETE FROM mcp_runtime_instances WHERE instance_id = $1::uuid`, instanceID)
		_, _ = db.Exec(`DELETE FROM mcp_server_instances WHERE id = $1::uuid`, instanceID)
		_, _ = db.Exec(`DELETE FROM mcp_servers WHERE id = $1::uuid`, serverID)
	})
}

func runtimeState(t *testing.T, db *sql.DB, instanceID string) string {
	t.Helper()
	var state string
	err := db.QueryRowContext(context.Background(),
		`SELECT state FROM mcp_runtime_instances WHERE instance_id = $1::uuid`, instanceID).Scan(&state)
	if errors.Is(err, sql.ErrNoRows) {
		return ""
	}
	if err != nil {
		t.Fatalf("reading runtime state: %v", err)
	}
	return state
}

func liveLeases(t *testing.T, db *sql.DB, instanceID string) int {
	t.Helper()
	var count int
	if err := db.QueryRowContext(context.Background(),
		`SELECT count(*) FROM mcp_runtime_request_leases WHERE instance_id = $1::uuid AND expires_at > now()`,
		instanceID).Scan(&count); err != nil {
		t.Fatalf("counting live leases: %v", err)
	}
	return count
}

func uuidAt(prefix string, n int) string {
	return fmt.Sprintf("%s-%04d-4000-8000-%012d", prefix, n, n)
}

// TestSchemaDropsCallerMaintainedLastUsed pins the migration's intent: liveness
// moved into control-plane-owned runtime tables, so no caller can be expected
// to report use on the desired-state row.
func TestSchemaDropsCallerMaintainedLastUsed(t *testing.T) {
	db := openRawDB(t)
	var present bool
	if err := db.QueryRowContext(context.Background(), `
SELECT EXISTS(
  SELECT 1 FROM information_schema.columns
  WHERE table_name='mcp_server_instances' AND column_name='last_used_at'
)`).Scan(&present); err != nil {
		t.Fatal(err)
	}
	if present {
		t.Error("mcp_server_instances.last_used_at still exists; callers would again be expected to report use")
	}
	for _, table := range []string{"mcp_runtime_instances", "mcp_runtime_request_leases"} {
		var exists bool
		if err := db.QueryRowContext(context.Background(),
			`SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=$1)`, table).Scan(&exists); err != nil {
			t.Fatal(err)
		}
		if !exists {
			t.Errorf("%s is missing; the gateway has nowhere to record runtime state", table)
		}
	}
	// The production constructor must accept exactly this schema.
	openRepository(t)
}

// TestAdvisoryLockSerializesInstanceLifecycle covers the invariant the whole
// cold-start path rests on: two managers acting on one instance must not be
// inside the lifecycle section at the same time, or both would create a
// workload.
func TestAdvisoryLockSerializesInstanceLifecycle(t *testing.T) {
	repository := openRepository(t)
	instanceID := uuidAt("aaaaaaaa", 1)

	firstInside := make(chan struct{})
	releaseFirst := make(chan struct{})
	var mu sync.Mutex
	inside := 0
	maxInside := 0

	enter := func() {
		mu.Lock()
		inside++
		if inside > maxInside {
			maxInside = inside
		}
		mu.Unlock()
	}
	leave := func() {
		mu.Lock()
		inside--
		mu.Unlock()
	}

	firstDone := make(chan error, 1)
	go func() {
		firstDone <- repository.WithInstanceLock(context.Background(), instanceID, func(context.Context) error {
			enter()
			close(firstInside)
			<-releaseFirst
			leave()
			return nil
		})
	}()
	<-firstInside

	secondEntered := make(chan struct{})
	secondDone := make(chan error, 1)
	go func() {
		secondDone <- repository.WithInstanceLock(context.Background(), instanceID, func(context.Context) error {
			enter()
			close(secondEntered)
			leave()
			return nil
		})
	}()

	select {
	case <-secondEntered:
		t.Fatal("a second lifecycle holder entered while the first still held the advisory lock")
	case <-time.After(300 * time.Millisecond):
	}

	close(releaseFirst)
	if err := <-firstDone; err != nil {
		t.Fatalf("first lifecycle section: %v", err)
	}
	if err := <-secondDone; err != nil {
		t.Fatalf("second lifecycle section: %v", err)
	}
	if maxInside != 1 {
		t.Fatalf("%d lifecycle holders overlapped; cold start is not serialized", maxInside)
	}
}

// TestConcurrentColdStartCreatesOneWorkload is the behaviour the advisory lock
// exists for, exercised through the same calls the gateway makes.
func TestConcurrentColdStartCreatesOneWorkload(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	instanceID := uuidAt("aaaaaaaa", 2)
	seedInstance(t, db, instanceID, "docker")

	const callers = 6
	var creates int
	var mu sync.Mutex
	var wait sync.WaitGroup
	errs := make(chan error, callers)

	for i := range callers {
		wait.Add(1)
		go func(index int) {
			defer wait.Done()
			errs <- repository.WithInstanceLock(context.Background(), instanceID, func(lockCtx context.Context) error {
				if runtimeState(t, db, instanceID) == "ready" {
					return nil
				}
				if err := repository.MarkStarting(lockCtx, instanceID); err != nil {
					return err
				}
				mu.Lock()
				creates++
				mu.Unlock()
				return repository.MarkReadyAndBeginRequest(lockCtx, instanceID, uuidAt("bbbbbbbb", index), time.Minute)
			})
		}(i)
	}
	wait.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatalf("cold start caller: %v", err)
		}
	}

	mu.Lock()
	defer mu.Unlock()
	if creates != 1 {
		t.Fatalf("workload created %d times under concurrent demand; want exactly 1", creates)
	}
	if got := runtimeState(t, db, instanceID); got != "ready" {
		t.Fatalf("runtime state = %q, want ready", got)
	}
}

func TestRequestLeaseInsertHeartbeatAndFinalize(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 3)
	requestID := uuidAt("bbbbbbbb", 3)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if err := repository.MarkReadyAndBeginRequest(ctx, instanceID, requestID, 2*time.Second); err != nil {
		t.Fatalf("MarkReadyAndBeginRequest() error = %v", err)
	}
	if liveLeases(t, db, instanceID) != 1 {
		t.Fatal("admitting a request did not register a lease")
	}

	var firstExpiry time.Time
	if err := db.QueryRowContext(ctx,
		`SELECT expires_at FROM mcp_runtime_request_leases WHERE request_id=$1::uuid`, requestID).Scan(&firstExpiry); err != nil {
		t.Fatal(err)
	}
	if err := repository.HeartbeatRequest(ctx, requestID, time.Hour); err != nil {
		t.Fatalf("HeartbeatRequest() error = %v", err)
	}
	var extendedExpiry time.Time
	if err := db.QueryRowContext(ctx,
		`SELECT expires_at FROM mcp_runtime_request_leases WHERE request_id=$1::uuid`, requestID).Scan(&extendedExpiry); err != nil {
		t.Fatal(err)
	}
	if !extendedExpiry.After(firstExpiry) {
		t.Fatalf("heartbeat did not extend the lease: %s -> %s", firstExpiry, extendedExpiry)
	}

	if err := repository.FinishRequest(ctx, instanceID, requestID); err != nil {
		t.Fatalf("FinishRequest() error = %v", err)
	}
	if liveLeases(t, db, instanceID) != 0 {
		t.Fatal("finishing a request left its lease behind")
	}
	// A lost or replayed finalization must not silently succeed.
	if err := repository.FinishRequest(ctx, instanceID, requestID); err == nil {
		t.Fatal("finalizing an already-finished request unexpectedly succeeded")
	}
	if err := repository.HeartbeatRequest(ctx, requestID, time.Minute); err == nil {
		t.Fatal("heartbeating a finished lease unexpectedly succeeded")
	}
}

// TestIdleSelectionAndExpiredLeaseCleanup pins the whole selection matrix. Each
// non-selected row is a distinct way the reaper could take down something that
// is still in use.
func TestIdleSelectionAndExpiredLeaseCleanup(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()

	idle := uuidAt("aaaaaaaa", 10)
	recent := uuidAt("aaaaaaaa", 11)
	leased := uuidAt("aaaaaaaa", 12)
	expired := uuidAt("aaaaaaaa", 13)
	remote := uuidAt("aaaaaaaa", 14)
	for _, id := range []string{idle, recent, leased, expired} {
		seedInstance(t, db, id, "docker")
	}
	seedInstance(t, db, remote, "url")

	for _, id := range []string{idle, recent, leased, expired, remote} {
		if err := repository.MarkStarting(ctx, id); err != nil {
			t.Fatal(err)
		}
		if _, err := db.ExecContext(ctx,
			`UPDATE mcp_runtime_instances SET state='ready' WHERE instance_id=$1::uuid`, id); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := db.ExecContext(ctx, `
UPDATE mcp_runtime_instances SET last_used_at = now() - interval '1 hour'
WHERE instance_id = ANY($1::uuid[])`, "{"+idle+","+leased+","+expired+","+remote+"}"); err != nil {
		t.Fatal(err)
	}

	if _, err := db.ExecContext(ctx,
		`INSERT INTO mcp_runtime_request_leases(request_id, instance_id, expires_at) VALUES ($1::uuid, $2::uuid, now() + interval '1 hour')`,
		uuidAt("bbbbbbbb", 12), leased); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx,
		`INSERT INTO mcp_runtime_request_leases(request_id, instance_id, expires_at) VALUES ($1::uuid, $2::uuid, now() - interval '1 minute')`,
		uuidAt("bbbbbbbb", 13), expired); err != nil {
		t.Fatal(err)
	}

	candidates, err := repository.IdleCandidates(ctx, 10*time.Minute)
	if err != nil {
		t.Fatalf("IdleCandidates() error = %v", err)
	}
	selected := map[string]bool{}
	for _, id := range candidates {
		selected[id] = true
	}

	if !selected[idle] {
		t.Error("an idle container-backed instance was not selected; nothing would ever be reclaimed")
	}
	if !selected[expired] {
		t.Error("an instance whose only lease had expired was not selected; a crashed proxy would pin it forever")
	}
	for _, c := range []struct{ id, why string }{
		{recent, "an instance used moments ago is in use; reaping it breaks a live session"},
		{leased, "a live request lease means a request is still in flight"},
		{remote, "URL-type MCP servers have no workload to reap"},
	} {
		if selected[c.id] {
			t.Errorf("selected an instance it must not touch: %s", c.why)
		}
	}
	if liveLeases(t, db, expired) != 0 {
		t.Error("the expired lease was not cleaned up")
	}
	if liveLeases(t, db, leased) != 1 {
		t.Error("cleanup removed a live lease")
	}
}

// TestReaperIsFencedByLiveRequestLease covers the race the whole lease table
// exists for: a request admitted between the sweep's selection and its
// teardown must keep the workload alive.
func TestReaperIsFencedByLiveRequestLease(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 20)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if err := repository.MarkReadyAndBeginRequest(ctx, instanceID, uuidAt("bbbbbbbb", 20), time.Hour); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx,
		`UPDATE mcp_runtime_instances SET last_used_at = now() - interval '1 hour' WHERE instance_id=$1::uuid`,
		instanceID); err != nil {
		t.Fatal(err)
	}

	removed, err := repository.ReapIfIdle(ctx, instanceID, time.Minute, func(context.Context, *models.MCPServerInstance) error {
		t.Error("the reaper tore down a workload that still held a live request lease")
		return nil
	})
	if err != nil {
		t.Fatalf("ReapIfIdle() error = %v", err)
	}
	if removed {
		t.Fatal("ReapIfIdle() reported a removal despite a live request lease")
	}
	if got := runtimeState(t, db, instanceID); got != "ready" {
		t.Fatalf("runtime state = %q, want the instance left ready", got)
	}
}

func TestReaperRemovesTrulyIdleInstanceAndMarksItDormant(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 21)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	requestID := uuidAt("bbbbbbbb", 21)
	if err := repository.MarkReadyAndBeginRequest(ctx, instanceID, requestID, time.Minute); err != nil {
		t.Fatal(err)
	}
	if err := repository.FinishRequest(ctx, instanceID, requestID); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx,
		`UPDATE mcp_runtime_instances SET last_used_at = now() - interval '1 hour' WHERE instance_id=$1::uuid`,
		instanceID); err != nil {
		t.Fatal(err)
	}

	removals := 0
	removed, err := repository.ReapIfIdle(ctx, instanceID, time.Minute, func(_ context.Context, instance *models.MCPServerInstance) error {
		removals++
		if instance.InstanceID != instanceID {
			t.Errorf("reaper removed %s, want %s", instance.InstanceID, instanceID)
		}
		return nil
	})
	if err != nil || !removed || removals != 1 {
		t.Fatalf("ReapIfIdle() removed=%v removals=%d err=%v", removed, removals, err)
	}
	if got := runtimeState(t, db, instanceID); got != "dormant" {
		t.Fatalf("runtime state = %q, want dormant so the next request cold-starts it", got)
	}
}

// TestReaperFailureLeavesInstanceReady keeps a failed teardown from parking the
// instance in a state no request can recover from.
func TestReaperFailureLeavesInstanceReady(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 22)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx,
		`UPDATE mcp_runtime_instances SET state='ready', last_used_at = now() - interval '1 hour' WHERE instance_id=$1::uuid`,
		instanceID); err != nil {
		t.Fatal(err)
	}

	removed, err := repository.ReapIfIdle(ctx, instanceID, time.Minute, func(context.Context, *models.MCPServerInstance) error {
		return errors.New("data plane unreachable")
	})
	if err == nil || removed {
		t.Fatalf("ReapIfIdle() removed=%v err=%v, want the failure surfaced", removed, err)
	}
	if got := runtimeState(t, db, instanceID); got != "ready" {
		t.Fatalf("runtime state = %q, want ready after a failed teardown", got)
	}
}

// TestDeletionIsRefusedWhileARequestIsInFlight is the synchronous-delete
// contract: desired state may only be removed once the data plane is free.
func TestDeletionIsRefusedWhileARequestIsInFlight(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 30)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	requestID := uuidAt("bbbbbbbb", 30)
	if err := repository.MarkReadyAndBeginRequest(ctx, instanceID, requestID, time.Hour); err != nil {
		t.Fatal(err)
	}

	err := repository.RetireForDeletion(ctx, instanceID, func(context.Context, *models.MCPServerInstance) error {
		t.Error("deletion tore down a workload that was still serving a request")
		return nil
	})
	if !errors.Is(err, ErrInstanceBusy) {
		t.Fatalf("RetireForDeletion() error = %v, want ErrInstanceBusy", err)
	}

	if err := repository.FinishRequest(ctx, instanceID, requestID); err != nil {
		t.Fatal(err)
	}
	removals := 0
	if err := repository.RetireForDeletion(ctx, instanceID, func(context.Context, *models.MCPServerInstance) error {
		removals++
		return nil
	}); err != nil {
		t.Fatalf("RetireForDeletion() after the request finished: %v", err)
	}
	if removals != 1 {
		t.Fatalf("workload removals = %d, want 1", removals)
	}
	if got := runtimeState(t, db, instanceID); got != "dormant" {
		t.Fatalf("runtime state = %q, want dormant", got)
	}

	// A retried delete after the workload is already gone must still succeed,
	// so a lost HTTP response can be replayed safely.
	if err := repository.RetireForDeletion(ctx, instanceID, func(context.Context, *models.MCPServerInstance) error {
		removals++
		return nil
	}); err != nil {
		t.Fatalf("repeated RetireForDeletion(): %v", err)
	}
}

// TestLifecycleLockIsReleasedWhenTheConnectionGoesAway covers lock loss: an
// advisory lock is connection-scoped, so a manager that dies mid-lifecycle must
// not leave the instance permanently unstartable.
func TestLifecycleLockIsReleasedWhenTheConnectionGoesAway(t *testing.T) {
	dsn := testDSN(t)
	instanceID := uuidAt("aaaaaaaa", 40)

	doomed, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := doomed.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.ExecContext(context.Background(),
		`SELECT pg_advisory_lock(hashtextextended($1, 0))`, instanceID); err != nil {
		t.Fatal(err)
	}

	repository := openRepository(t)
	blocked, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	if err := repository.WithInstanceLock(blocked, instanceID, func(context.Context) error {
		t.Error("acquired the lifecycle lock while another connection held it")
		return nil
	}); err == nil {
		t.Fatal("lifecycle lock acquisition unexpectedly succeeded while held elsewhere")
	}

	// Dropping the holder's connection must free the lock for the next manager.
	_ = conn.Close()
	_ = doomed.Close()

	acquired, cancelAcquire := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancelAcquire()
	entered := false
	if err := repository.WithInstanceLock(acquired, instanceID, func(context.Context) error {
		entered = true
		return nil
	}); err != nil {
		t.Fatalf("WithInstanceLock() after the holder disconnected: %v", err)
	}
	if !entered {
		t.Fatal("the lifecycle section never ran after the previous holder disconnected")
	}
}

// TestStrandedColdStartIsStillReclaimable covers the reachability hole: a
// workload created but never marked ready — because the process died, or its
// own cleanup failed — used to sit outside the reaper's 'ready'-only filter
// forever, running and billable until someone happened to call that instance.
func TestStrandedColdStartIsStillReclaimable(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()

	for _, stranded := range []struct{ id, state string }{
		{uuidAt("aaaaaaaa", 50), "starting"},
		{uuidAt("aaaaaaaa", 51), "failed"},
	} {
		t.Run(stranded.state, func(t *testing.T) {
			seedInstance(t, db, stranded.id, "docker")
			if err := repository.MarkStarting(ctx, stranded.id); err != nil {
				t.Fatal(err)
			}
			if _, err := db.ExecContext(ctx,
				`UPDATE mcp_runtime_instances SET state=$2, updated_at = now() - interval '1 hour' WHERE instance_id=$1::uuid`,
				stranded.id, stranded.state); err != nil {
				t.Fatal(err)
			}

			candidates, err := repository.IdleCandidates(ctx, time.Minute)
			if err != nil {
				t.Fatal(err)
			}
			if !slices.Contains(candidates, stranded.id) {
				t.Fatalf("a workload stranded in %q was not reclaimable; it would run forever", stranded.state)
			}

			removals := 0
			removed, err := repository.ReapIfIdle(ctx, stranded.id, time.Minute, func(context.Context, *models.MCPServerInstance) error {
				removals++
				return nil
			})
			if err != nil || !removed || removals != 1 {
				t.Fatalf("ReapIfIdle() removed=%v removals=%d err=%v", removed, removals, err)
			}
			if got := runtimeState(t, db, stranded.id); got != "dormant" {
				t.Fatalf("runtime state = %q, want dormant", got)
			}
		})
	}
}

// TestFreshColdStartIsNotReclaimedWhileStarting keeps the widened selection from
// reaping an activation that is still legitimately in progress.
func TestFreshColdStartIsNotReclaimedWhileStarting(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 52)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	candidates, err := repository.IdleCandidates(ctx, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if slices.Contains(candidates, instanceID) {
		t.Fatal("an in-progress cold start was selected for reaping")
	}
}

// TestFailedReapRestoresTheStateItFound keeps a failed teardown from claiming a
// stranded start is serving requests.
func TestFailedReapRestoresTheStateItFound(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 53)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx,
		`UPDATE mcp_runtime_instances SET state='failed', updated_at = now() - interval '1 hour' WHERE instance_id=$1::uuid`,
		instanceID); err != nil {
		t.Fatal(err)
	}

	if _, err := repository.ReapIfIdle(ctx, instanceID, time.Minute, func(context.Context, *models.MCPServerInstance) error {
		return errors.New("data plane unreachable")
	}); err == nil {
		t.Fatal("a failed teardown reported success")
	}
	if got := runtimeState(t, db, instanceID); got != "failed" {
		t.Fatalf("runtime state = %q, want the original 'failed' restored, not a fabricated 'ready'", got)
	}
}

// TestWarmRequestKeepsInstanceReadyAndGeneration pins that a warm call does not
// churn runtime state: it must not report a serving instance as starting, and
// generation must count workload generations rather than requests.
func TestWarmRequestKeepsInstanceReadyAndGeneration(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuidAt("aaaaaaaa", 54)
	seedInstance(t, db, instanceID, "docker")

	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	requestID := uuidAt("bbbbbbbb", 54)
	if err := repository.MarkReadyAndBeginRequest(ctx, instanceID, requestID, time.Minute); err != nil {
		t.Fatal(err)
	}
	if err := repository.FinishRequest(ctx, instanceID, requestID); err != nil {
		t.Fatal(err)
	}

	var generationAfterColdStart int64
	if err := db.QueryRowContext(ctx,
		`SELECT generation FROM mcp_runtime_instances WHERE instance_id=$1::uuid`, instanceID).Scan(&generationAfterColdStart); err != nil {
		t.Fatal(err)
	}

	for range 3 {
		if err := repository.MarkStarting(ctx, instanceID); err != nil {
			t.Fatal(err)
		}
		if got := runtimeState(t, db, instanceID); got != "ready" {
			t.Fatalf("a warm request moved a serving instance to %q", got)
		}
	}

	var generationAfterWarmCalls int64
	if err := db.QueryRowContext(ctx,
		`SELECT generation FROM mcp_runtime_instances WHERE instance_id=$1::uuid`, instanceID).Scan(&generationAfterWarmCalls); err != nil {
		t.Fatal(err)
	}
	if generationAfterWarmCalls != generationAfterColdStart {
		t.Fatalf("generation moved %d -> %d across warm requests; it counts requests, not workload generations",
			generationAfterColdStart, generationAfterWarmCalls)
	}
}
