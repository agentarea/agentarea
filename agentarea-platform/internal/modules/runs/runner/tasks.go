package runner

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/workflows"
)

// Tasks reads a runner's tasks and keeps their CLI sessions.
type Tasks interface {
	// Task returns store.ErrTaskNotFound when the workspace has no such task.
	Task(ctx context.Context, ws scope.Workspace, taskID string) (store.RunnerTask, error)
	KeepSession(ctx context.Context, ws scope.Workspace, taskID, sessionID string) error
	// NoteLostOutput keeps, on the task, an output of its runner that did not reach it;
	// TakeLostOutputs returns those kept since the last take and forgets them.
	NoteLostOutput(ctx context.Context, ws scope.Workspace, taskID, note string) error
	TakeLostOutputs(ctx context.Context, ws scope.Workspace, taskID string) ([]string, error)
}

// lostOutputsKey names, in task metadata, the runner outputs that did not reach the task.
const lostOutputsKey = "runner_lost_outputs"

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

func (t StoreTasks) NoteLostOutput(ctx context.Context, ws scope.Workspace, taskID, note string) error {
	return t.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		task, err := store.Runs{}.RunnerTask(ctx, sess, taskID)
		if err != nil {
			return err
		}
		lost, _ := task.Metadata[lostOutputsKey].([]any)
		_, err = store.Runs{}.MergeMetadata(ctx, sess, taskID, map[string]any{lostOutputsKey: append(lost, note)}, t.now())
		return err
	})
}

func (t StoreTasks) TakeLostOutputs(ctx context.Context, ws scope.Workspace, taskID string) ([]string, error) {
	var out []string
	err := t.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		task, err := store.Runs{}.RunnerTask(ctx, sess, taskID)
		if err != nil {
			return err
		}
		lost, _ := task.Metadata[lostOutputsKey].([]any)
		if len(lost) == 0 {
			return nil
		}
		for _, l := range lost {
			if s, ok := l.(string); ok {
				out = append(out, s)
			}
		}
		_, err = store.Runs{}.MergeMetadata(ctx, sess, taskID, map[string]any{lostOutputsKey: []any{}}, t.now())
		return err
	})
	return out, err
}

func (t StoreTasks) now() time.Time {
	if t.Now != nil {
		return t.Now().UTC()
	}
	return time.Now().UTC()
}

// registrar registers a socket's turn activity on its worker.
type registrar func(w durable.Worker, turns workflows.RunnerTurns, exec durable.Executor)
