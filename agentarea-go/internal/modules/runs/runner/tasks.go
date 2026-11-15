package runner

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/workflows"
)

// Tasks reads a runner's tasks and keeps their CLI sessions.
type Tasks interface {
	// Task returns store.ErrTaskNotFound when the workspace has no such task.
	Task(ctx context.Context, ws scope.Workspace, taskID string) (store.RunnerTask, error)
	KeepSession(ctx context.Context, ws scope.Workspace, taskID, sessionID string) error
}

// StoreTasks is Tasks over the runs store.
type StoreTasks struct {
	DB  db.Database
	Now func() time.Time
}

func (t StoreTasks) Task(ctx context.Context, ws scope.Workspace, taskID string) (store.RunnerTask, error) {
	sess, release, err := t.DB.Read(ctx, ws)
	if err != nil {
		return store.RunnerTask{}, err
	}
	defer release()
	return store.Runs{}.RunnerTask(ctx, sess, taskID)
}

func (t StoreTasks) KeepSession(ctx context.Context, ws scope.Workspace, taskID, sessionID string) error {
	now := time.Now
	if t.Now != nil {
		now = t.Now
	}
	return t.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		_, err := store.Runs{}.SetRunnerSession(ctx, sess, taskID, sessionID, now().UTC())
		return err
	})
}

// registrar registers a socket's turn activity on its worker.
type registrar func(w durable.Worker, turns workflows.RunnerTurns, exec durable.Executor)
