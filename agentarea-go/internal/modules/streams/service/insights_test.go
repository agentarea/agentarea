package service_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
)

func TestTriggerBoard(t *testing.T) {
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx := context.Background()
	agent, other := uuid.NewString(), uuid.NewString()
	insert := func(name, agentID string, active bool, failures int, cron, tz any, needsOwner any) string {
		id := uuid.NewString()
		if _, err := pool.Exec(ctx, `INSERT INTO triggers (id, name, description, agent_id, trigger_type, is_active, task_parameters, conditions,
			failure_threshold, consecutive_failures, cron_expression, timezone, workspace_id, created_by, needs_new_owner_at, last_execution_at)
			VALUES ($1, $2, '', $3, 'cron', $4, '{}', '{}', 3, $5, $6, $7, $8, 'u', $9, now())`,
			id, name, agentID, active, failures, cron, tz, ws.ID(), needsOwner); err != nil {
			t.Fatal(err)
		}
		return id
	}
	healthy := insert("healthy", agent, true, 0, "0 9 * * *", "Europe/Berlin", nil)
	failing := insert("failing", agent, true, 1, "0 * * * *", nil, nil)
	stopped := insert("stopped", other, false, 3, "0 * * * *", nil, nil)
	insert("paused", other, false, 0, "0 * * * *", nil, nil)
	orphan := insert("orphan", other, true, 0, nil, nil, time.Now().UTC())

	b := service.TriggerBoard{DB: storetest.DB{Pool: pool}}
	broken, err := b.BrokenTriggers(ctx, ws, 20)
	if err != nil || len(broken) != 3 || broken[0].ID != stopped || broken[1].ID != failing || broken[2].ID != orphan || !broken[2].NeedsNewOwner {
		t.Fatalf("broken: %+v %v", broken, err)
	}
	if broken[0].LastExecutionAt == nil || broken[0].FailureThreshold != 3 {
		t.Fatalf("broken row: %+v", broken[0])
	}
	crons, err := b.CronTriggers(ctx, ws, nil)
	if err != nil || len(crons) != 2 {
		t.Fatalf("crons: %+v %v", crons, err)
	}
	mine, err := b.CronTriggers(ctx, ws, &agent)
	if err != nil || len(mine) != 2 {
		t.Fatalf("agent crons: %+v %v", mine, err)
	}
	for _, c := range mine {
		if c.ID == healthy && (c.Timezone == nil || *c.Timezone != "Europe/Berlin") {
			t.Fatalf("timezone %+v", c)
		}
	}
	bad := "nope"
	if none, err := b.CronTriggers(ctx, ws, &bad); err != nil || len(none) != 0 {
		t.Fatalf("a non-uuid agent: %+v %v", none, err)
	}
}
