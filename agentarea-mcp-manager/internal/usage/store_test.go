package usage

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
)

func openTestStore(t *testing.T) *Store {
	t.Helper()
	dsn := os.Getenv("USAGE_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("USAGE_REQUIRE_DB") != "" {
			t.Fatal("USAGE_REQUIRE_DB is set but USAGE_TEST_DATABASE_URL is missing")
		}
		t.Skip("USAGE_TEST_DATABASE_URL not set; requires a migrated PostgreSQL database")
	}
	store, err := OpenStore(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store
}

func testEvent() Event {
	return Event{
		SchemaVersion: SchemaVersion,
		ID:            uuid.NewString(), Source: "usage-test", Kind: "runtime.sample",
		WorkspaceID: uuid.NewString(), ResourceKind: "mcp_runtime", ResourceID: uuid.NewString(),
		IncarnationID: uuid.NewString(), OccurredAt: time.Now().UTC(),
		Data: json.RawMessage(`{"cpu_usage_ns":18446744073709551615,"memory_usage_bytes":9007199254740993}`),
	}
}

func TestStoreReplayPreservesPrecisionAndRejectsCollision(t *testing.T) {
	store := openTestStore(t)
	ctx := context.Background()
	event := testEvent()
	if err := store.Record(ctx, event); err != nil {
		t.Fatal(err)
	}
	// JSON formatting is not immutable content, but the numeric value is.
	replay := event
	replay.Data = json.RawMessage(`{ "memory_usage_bytes": 9007199254740993, "cpu_usage_ns": 18446744073709551615 }`)
	if err := store.Record(ctx, replay); err != nil {
		t.Fatal(err)
	}
	var count, version int
	var cpu, memory, occurred string
	err := store.db.QueryRowContext(ctx, `SELECT count(*), min(data->>'cpu_usage_ns'),
		min(data->>'memory_usage_bytes'), min(occurred_at_source), min(schema_version)
		FROM resource_usage_events WHERE source=$1 AND event_id=$2`, event.Source, event.ID).
		Scan(&count, &cpu, &memory, &occurred, &version)
	if err != nil {
		t.Fatal(err)
	}
	if count != 1 || cpu != "18446744073709551615" || memory != "9007199254740993" || occurred != event.OccurredAt.Format(time.RFC3339Nano) {
		t.Fatalf("raw fact changed: count=%d cpu=%s memory=%s occurred=%s", count, cpu, memory, occurred)
	}
	if version != SchemaVersion {
		t.Fatalf("replayed fact schema version changed: %d", version)
	}
	collision := event
	collision.Data = json.RawMessage(`{"cpu_usage_ns":18446744073709551614,"memory_usage_bytes":9007199254740993}`)
	if err := store.Record(ctx, collision); !errors.Is(err, ErrIdentityCollision) {
		t.Fatalf("different counter under same identity: %v", err)
	}
	collision = event
	collision.WorkspaceID = uuid.NewString()
	if err := store.Record(ctx, collision); !errors.Is(err, ErrIdentityCollision) {
		t.Fatalf("different tenant under same identity: %v", err)
	}
	collision = event
	collision.OccurredAt = event.OccurredAt.Add(time.Nanosecond)
	if err := store.Record(ctx, collision); !errors.Is(err, ErrIdentityCollision) {
		t.Fatalf("different source timestamp under same identity: %v", err)
	}
}

func TestStoreRejectsReplayAcrossSchemaVersions(t *testing.T) {
	store := openTestStore(t)
	ctx := context.Background()
	event := testEvent()
	// A newer writer's history must not be accepted as a replay by this writer,
	// even if the envelope and payload happen to be identical.
	_, err := store.db.ExecContext(ctx, `INSERT INTO resource_usage_events
		(event_id,source,kind,workspace_id,resource_kind,resource_id,incarnation_id,task_id,occurred_at,occurred_at_source,data,schema_version)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12)`,
		event.ID, event.Source, event.Kind, event.WorkspaceID, event.ResourceKind,
		event.ResourceID, event.IncarnationID, event.TaskID, event.OccurredAt,
		event.OccurredAt.Format(time.RFC3339Nano), string(event.Data), SchemaVersion+1)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Record(ctx, event); !errors.Is(err, ErrIdentityCollision) {
		t.Fatalf("cross-version identity reuse accepted: %v", err)
	}
}

func TestRecordTxRollsBackWithOwner(t *testing.T) {
	store := openTestStore(t)
	ctx := context.Background()
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	event := testEvent()
	if err := RecordTx(ctx, tx, event); err != nil {
		t.Fatal(err)
	}
	if err := tx.Rollback(); err != nil {
		t.Fatal(err)
	}
	var sequence int64
	err = store.db.QueryRowContext(ctx, "SELECT sequence FROM resource_usage_events WHERE source=$1 AND event_id=$2", event.Source, event.ID).Scan(&sequence)
	if !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("rolled back fact became durable: sequence=%d err=%v", sequence, err)
	}
}

func TestOpenStoreRejectsMissingMigration(t *testing.T) {
	store := openTestStore(t)
	ctx := context.Background()
	// An isolated empty schema on one connection avoids touching migrated tables.
	conn, err := store.db.Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.ExecContext(ctx, "SET search_path TO pg_catalog"); err != nil {
		t.Fatal(err)
	}
	defer func() { _, _ = conn.ExecContext(ctx, "RESET search_path") }()
	if err := requireSchema(ctx, conn); err == nil {
		t.Fatal("unmigrated schema accepted")
	}
}
