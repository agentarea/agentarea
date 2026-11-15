package store

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func openPool(t *testing.T) *pgxpool.Pool {
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

func workspace(t *testing.T, pool *pgxpool.Pool) db.Session {
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
	return db.NewSession(ws, pool)
}

func newTask(t *testing.T, s db.Session) TaskRef {
	t.Helper()
	var r Runs
	id := uuid.NewString()
	if err := r.CreateTask(context.Background(), s, NewTask{
		ID: id, AgentID: uuid.NewString(), Description: "d", Status: "running", CreatedBy: "user-1",
		Metadata: map[string]any{"a": 1.0}, OriginType: "agent",
	}, time.Now()); err != nil {
		t.Fatal(err)
	}
	task, err := r.Task(context.Background(), s, id)
	if err != nil {
		t.Fatal(err)
	}
	return task
}

func TestTaskLogIsIdempotentAndScoped(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var r Runs
	task := newTask(t, s)
	if task.CorrelationID != task.ID {
		t.Fatalf("correlation %q, want the task id", task.CorrelationID)
	}
	if _, err := r.Task(ctx, other, task.ID); !errors.Is(err, ErrTaskNotFound) {
		t.Fatalf("another workspace reads the task: %v", err)
	}
	rows := []domain.Entry{
		{Seq: 0, EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "system", Content: "sys"},
		{Seq: 1, EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "user", Content: "hi\x00there"},
		{Seq: 2, EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "assistant", Content: "",
			ToolCalls: []domain.ToolCall{{ID: "c1", Name: "t", Arguments: `{"x":1}`}}},
		{Seq: 3, EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "tool", Content: "ok", ToolCallID: "c1", Name: "t"},
		{Seq: 4, EventID: uuid.NewString(), Kind: domain.KindEvent, Name: domain.EventToolResult, Meta: map[string]any{"k": "v"}},
	}
	for range 2 {
		for _, e := range rows {
			if err := r.InsertEntry(ctx, s, task, e, "user-1"); err != nil {
				t.Fatal(err)
			}
		}
	}
	var n int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM task_conversation_entries WHERE task_id = $1`, task.ID).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != len(rows) {
		t.Fatalf("%d rows after a retried insert, want %d", n, len(rows))
	}
	window, err := r.Window(ctx, s, task.ID, 4)
	if err != nil {
		t.Fatal(err)
	}
	if len(window) != 4 || window[1].Content != "hi�there" || len(window[2].ToolCalls) != 1 || window[2].ToolCalls[0].Arguments != `{"x":1}` {
		t.Fatalf("window %+v", window)
	}
	feed, err := r.LatestFeed(ctx, s, task.ID, []string{domain.EventToolResult}, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(feed) != 1 || feed[0].Seq != 4 {
		t.Fatalf("feed %+v", feed)
	}
}

func TestOutcomeKeepsResultOrderAndMergesMetadata(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var r Runs
	task := newTask(t, s)
	cost := "0.5"
	o := domain.OutcomeOf(domain.StatusUpdate{Status: "completed", Response: "done", ValidationState: "passed", TotalCost: &cost, OwnCost: &cost})
	ok, err := r.SetOutcome(ctx, s, task.ID, o, time.Now())
	if err != nil || !ok {
		t.Fatalf("set outcome %v %v", ok, err)
	}
	if _, err := r.MergeMetadata(ctx, s, task.ID, map[string]any{"agent_config_hash": "v2:x"}, time.Now()); err != nil {
		t.Fatal(err)
	}
	var result, meta, status string
	var completed *time.Time
	if err := pool.QueryRow(ctx, `SELECT result::text, task_metadata::text, status, completed_at FROM tasks WHERE id = $1`, task.ID).
		Scan(&result, &meta, &status, &completed); err != nil {
		t.Fatal(err)
	}
	if want := `{"response": "done", "validation_state": "passed", "total_cost": "0.5", "own_cost": "0.5"}`; result != want {
		t.Fatalf("result %s\nwant   %s", result, want)
	}
	if status != "completed" || completed == nil {
		t.Fatalf("status %s completed_at %v", status, completed)
	}
	if meta != `{"a": 1, "failure_reason": null, "agent_config_hash": "v2:x"}` {
		t.Fatalf("metadata %s", meta)
	}
}

func TestCostLinesOncePerEventAndSummedByScope(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var r Runs
	task := newTask(t, s)
	agent := uuid.NewString()
	conn, tool := "conn-1", "search"
	line := func(category, amount string, subjectID, name *string) domain.CostLine {
		return domain.CostLine{
			EventID: uuid.NewString(), Category: category, TaskID: task.ID, AgentID: agent, SubjectType: domain.SubjectTool,
			SubjectID: subjectID, SubjectName: name, Amount: amount, Currency: "USD", Source: "rate", Payer: "workspace",
			OccurredAt: time.Now().UTC(),
		}
	}
	model := line(domain.CostModel, "1.25", nil, nil)
	model.SubjectType = domain.SubjectModelInstance
	service := line(domain.CostService, "0.75", &conn, &tool)
	for range 2 {
		for _, l := range []domain.CostLine{model, service} {
			if _, err := r.InsertCostLine(ctx, s, l, "user-1", task); err != nil {
				t.Fatal(err)
			}
		}
	}
	since := time.Now().Add(-time.Hour)
	for _, c := range []struct {
		scope SpendScope
		want  string
	}{
		{SpendScope{}, "2"},
		{SpendScope{AgentID: agent}, "2"},
		{SpendScope{TaskID: task.ID, Category: domain.CostModel}, "1.25"},
		{SpendScope{ConnectionID: conn}, "0.75"},
		{SpendScope{ConnectionID: conn, Tool: "other"}, "0"},
		{SpendScope{AgentID: uuid.NewString()}, "0"},
	} {
		raw, err := r.SumSpendSince(ctx, s, since, "USD", c.scope)
		if err != nil {
			t.Fatal(err)
		}
		got, err := money.Parse(raw)
		if err != nil {
			t.Fatal(err)
		}
		if !got.Equal(money.MustParse(c.want)) {
			t.Fatalf("%+v: spent %s, want %s", c.scope, got, c.want)
		}
	}
	if got, _ := r.SumSpendSince(ctx, s, since, "EUR", SpendScope{}); !money.MustParse(got).IsZero() {
		t.Fatalf("EUR spent %s", got)
	}
}

func TestTaskEventsOncePerID(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var r Runs
	task := newTask(t, s)
	e := domain.StoredEvent{ID: uuid.NewString(), Type: domain.EventLLMCompleted, Timestamp: time.Now(), Data: map[string]any{"cost": "0.1"}}
	for range 2 {
		if err := r.InsertTaskEvent(ctx, s, task.ID, e, "user-1", time.Now()); err != nil {
			t.Fatal(err)
		}
	}
	var n int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM task_events WHERE task_id = $1`, task.ID).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Fatalf("%d task events, want 1", n)
	}
}
