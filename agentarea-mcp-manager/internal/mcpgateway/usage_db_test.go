package mcpgateway

import (
	"context"
	"database/sql"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/google/uuid"
)

func lifecycleFacts(t *testing.T, db *sql.DB, instanceID, kind string) []int64 {
	t.Helper()
	rows, err := db.Query(`SELECT (data->>'generation')::bigint FROM resource_usage_events WHERE source='mcp-gateway' AND resource_id=$1 AND kind=$2 ORDER BY sequence`, instanceID, kind)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var generations []int64
	for rows.Next() {
		var generation int64
		if err := rows.Scan(&generation); err != nil {
			t.Fatal(err)
		}
		generations = append(generations, generation)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	return generations
}

func TestLifecycleUsagePreservesGenerationsAcrossWarmRequestsAndReaping(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuid.NewString()
	seedInstance(t, db, instanceID, "docker")
	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM resource_usage_events WHERE resource_id=$1 AND source='mcp-gateway'`, instanceID)
	})
	for range 4 {
		requestID := uuid.NewString()
		if err := repository.WithInstanceLock(ctx, instanceID, func(ctx context.Context) error {
			if err := repository.MarkStarting(ctx, instanceID); err != nil {
				return err
			}
			return repository.MarkReadyAndBeginRequest(ctx, instanceID, requestID, time.Minute)
		}); err != nil {
			t.Fatal(err)
		}
		if err := repository.FinishRequest(ctx, instanceID, requestID); err != nil {
			t.Fatal(err)
		}
	}
	for _, kind := range []string{"mcp.runtime.starting", "mcp.runtime.ready"} {
		if generations := lifecycleFacts(t, db, instanceID, kind); len(generations) != 1 || generations[0] != 1 {
			t.Fatalf("warm %s generations = %v", kind, generations)
		}
	}
	if _, err := db.Exec(`UPDATE mcp_runtime_instances SET last_used_at=now()-interval '2 hours' WHERE instance_id=$1::uuid`, instanceID); err != nil {
		t.Fatal(err)
	}
	removed, err := repository.ReapIfIdle(ctx, instanceID, time.Minute, func(context.Context, *models.MCPServerInstance) error { return nil })
	if err != nil || !removed {
		t.Fatalf("reaped=%v err=%v", removed, err)
	}
	if generations := lifecycleFacts(t, db, instanceID, "mcp.runtime.retired"); len(generations) != 1 || generations[0] != 1 {
		t.Fatalf("reaper retirement = %v", generations)
	}
	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if generations := lifecycleFacts(t, db, instanceID, "mcp.runtime.starting"); len(generations) != 2 || generations[1] != 2 {
		t.Fatalf("restart generations = %v", generations)
	}
	if _, err := db.Exec(`DELETE FROM mcp_server_instances WHERE id=$1::uuid`, instanceID); err != nil {
		t.Fatal(err)
	}
	if generations := lifecycleFacts(t, db, instanceID, "mcp.runtime.retired"); len(generations) != 1 {
		t.Fatal("deleting desired state erased historical usage")
	}
}

func TestLifecycleUsageRollsBackReadyFactWhenAdmissionFails(t *testing.T) {
	repository := openRepository(t)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuid.NewString()
	seedInstance(t, db, instanceID, "docker")
	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM resource_usage_events WHERE resource_id=$1 AND source='mcp-gateway'`, instanceID)
	})
	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if err := repository.MarkReadyAndBeginRequest(ctx, instanceID, "invalid-uuid", time.Minute); err == nil {
		t.Fatal("invalid request was admitted")
	}
	if state := runtimeState(t, db, instanceID); state != "starting" {
		t.Fatalf("failed admission changed state to %s", state)
	}
	if generations := lifecycleFacts(t, db, instanceID, "mcp.runtime.ready"); len(generations) != 0 {
		t.Fatalf("rolled-back admission recorded ready: %v", generations)
	}
}
