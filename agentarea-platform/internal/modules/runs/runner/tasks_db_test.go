package runner

import (
	"context"
	"log/slog"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

func openTasksDB(t *testing.T) db.Database {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pass, _ := u.User.Password()
	pools, err := db.Open(context.Background(), db.Config{
		Host: u.Hostname(), Port: port, Name: strings.TrimPrefix(u.Path, "/"), User: u.User.Username(), Password: pass,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 4, PoolTimeout: 10 * time.Second,
	}, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

func TestLostOutputsAreKeptOnTheTaskUntilTaken(t *testing.T) {
	d := openTasksDB(t)
	wsID, taskID := uuid.NewString(), uuid.NewString()
	ws, err := scope.NewWorkspace(wsID, "")
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err := d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		if _, err := s.Q().Exec(ctx, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, wsID, "ws-"+wsID[:8]); err != nil {
			return err
		}
		return store.Runs{}.CreateTask(ctx, s, store.NewTask{ID: taskID, AgentID: uuid.NewString(), Description: "d", Status: "running",
			CreatedBy: "u1", Metadata: map[string]any{runnerClientKey: "client-1"}}, time.Now())
	}); err != nil {
		t.Fatal(err)
	}
	tasks := StoreTasks{DB: d}
	for _, note := range []string{"outputs/deck.pptx (sandbox expired)", "outputs/x.png (store down)"} {
		if err := tasks.NoteLostOutput(ctx, ws, taskID, note); err != nil {
			t.Fatal(err)
		}
	}
	lost, err := tasks.TakeLostOutputs(ctx, ws, taskID)
	if err != nil || len(lost) != 2 || lost[0] != "outputs/deck.pptx (sandbox expired)" || lost[1] != "outputs/x.png (store down)" {
		t.Fatalf("taken %v %v", lost, err)
	}
	if again, err := tasks.TakeLostOutputs(ctx, ws, taskID); err != nil || len(again) != 0 {
		t.Fatalf("taken twice %v %v", again, err)
	}
	task, err := tasks.Task(ctx, ws, taskID)
	if err != nil || task.Metadata[runnerClientKey] != "client-1" {
		t.Fatalf("the task's other metadata changed: %v %v", task.Metadata, err)
	}
}
