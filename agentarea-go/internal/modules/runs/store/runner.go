package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// RunnerTask is a task as its runner's turns and file uploads read it.
type RunnerTask struct {
	ID             string
	AgentID        string
	Parameters     map[string]any
	Metadata       map[string]any
	CreatedBy      string
	SourceIdentity string
}

// RunnerTask reads the session workspace's task; ErrTaskNotFound when it has none.
func (Runs) RunnerTask(ctx context.Context, s db.Session, taskID string) (RunnerTask, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return RunnerTask{}, err
	}
	row, err := New(s.Q()).RunnerTask(ctx, RunnerTaskParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return RunnerTask{}, fmt.Errorf("task %s: %w", taskID, ErrTaskNotFound)
	}
	if err != nil {
		return RunnerTask{}, err
	}
	return RunnerTask{
		ID: row.ID.String(), AgentID: row.AgentID.String(), Parameters: objectOf(row.Parameters),
		Metadata: objectOf(row.TaskMetadata), CreatedBy: row.CreatedBy, SourceIdentity: row.SourceIdentity.String,
	}, nil
}

// SetRunnerSession keeps the CLI's session id in the task's metadata; false
// when the task is gone or already has it.
func (Runs) SetRunnerSession(ctx context.Context, s db.Session, taskID, sessionID string, now time.Time) (bool, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).SetRunnerSession(ctx, SetRunnerSessionParams{
		SessionID: sessionID, Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID(),
	})
	return n > 0, err
}
