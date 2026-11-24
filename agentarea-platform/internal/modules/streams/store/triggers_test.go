package store_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

func cron(agent string) domain.Trigger {
	expr, tz := "0 9 * * *", "UTC"
	return domain.Trigger{Name: "daily", AgentID: agent, Type: domain.TypeCron, IsActive: true,
		TaskParameters: map[string]any{"text": "go"}, Conditions: map[string]any{}, FailureThreshold: 5,
		CronExpression: &expr, Timezone: &tz, CreatedBy: "u1"}
}

func TestTriggerRowsRoundTrip(t *testing.T) {
	ctx := context.Background()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	s := db.NewSession(ws, pool)
	var st store.Triggers
	now := time.Now().UTC().Truncate(time.Microsecond)

	id := uuid.New()
	agent := uuid.New().String()
	tr := cron(agent)
	if err := st.Insert(ctx, s, id, tr, now); err != nil {
		t.Fatal(err)
	}
	got, ok, err := st.Get(ctx, s, id)
	if err != nil || !ok {
		t.Fatalf("get = %v %v", ok, err)
	}
	if got.Name != "daily" || got.AgentID != agent || got.TaskParameters["text"] != "go" || !got.IsActive {
		t.Fatalf("round trip = %+v", got)
	}

	list, err := st.List(ctx, s, store.Filter{Limit: 10, ActiveOnly: true})
	if err != nil || len(list) != 1 {
		t.Fatalf("list = %d %v", len(list), err)
	}
	other := db.NewSession(storetest.Workspace(t, pool), pool)
	if rest, _ := st.List(ctx, other, store.Filter{Limit: 10}); len(rest) != 0 {
		t.Fatal("list leaked across workspaces")
	}

	execID, _, err := st.RecordExecution(ctx, s, id, store.Execution{Status: "success", ExecutionTime: 1500 * time.Millisecond,
		TriggerData: map[string]any{"source": "cron"}}, now)
	if err != nil || execID == uuid.Nil {
		t.Fatalf("record = %v %v", execID, err)
	}
	execs, err := st.Executions(ctx, s, id, 10)
	if err != nil || len(execs) != 1 || execs[0].ExecutionTimeMs != 1500 {
		t.Fatalf("executions = %+v %v", execs, err)
	}

	if err := st.MarkExecuted(ctx, s, id, now, true); err != nil {
		t.Fatal(err)
	}
	if ok, err := st.Delete(ctx, s, id); err != nil || !ok {
		t.Fatalf("delete = %v %v", ok, err)
	}
	if _, ok, _ := st.Get(ctx, s, id); ok {
		t.Fatal("row survived delete")
	}
}
