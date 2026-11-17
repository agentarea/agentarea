package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// UndispatchedTask is a task left pending with no workflow, in its workspace.
type UndispatchedTask struct {
	ID          string
	WorkspaceID string
	Owner       string
}

// FindUndispatched lists pending tasks with no execution created in
// [horizon, staleBefore), oldest first, trigger tasks left out. It reads every
// workspace, so it takes the global querier (find_undispatched_tasks, unscoped).
func FindUndispatched(ctx context.Context, q db.Querier, staleBefore, horizon time.Time, limit int) ([]UndispatchedTask, error) {
	rows, err := New(q).UndispatchedTasks(ctx, UndispatchedTasksParams{StaleBefore: naive(staleBefore), Horizon: naive(horizon), MaxRows: int32(limit)})
	if err != nil {
		return nil, err
	}
	out := make([]UndispatchedTask, len(rows))
	for i, r := range rows {
		out[i] = UndispatchedTask{ID: r.ID.String(), WorkspaceID: r.WorkspaceID, Owner: r.CreatedBy}
	}
	return out, nil
}

// StoredTask is a task row as a launch reads it.
type StoredTask struct {
	ID          string
	AgentID     string
	Description string
	Parameters  map[string]any
	Status      string
	ExecutionID string
	Metadata    map[string]any
	CreatedBy   string
	ScheduledAt *time.Time
}

// objectOf is a JSON column read as Python reads it into a dict: anything
// that is not an object is empty.
func objectOf(raw []byte) map[string]any {
	var m map[string]any
	if len(raw) == 0 || json.Unmarshal(raw, &m) != nil || m == nil {
		return map[string]any{}
	}
	return m
}

// TaskToLaunch reads the task a launch starts; ErrTaskNotFound when the workspace has none.
func (Runs) TaskToLaunch(ctx context.Context, s db.Session, taskID string) (StoredTask, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return StoredTask{}, err
	}
	row, err := New(s.Q()).TaskToLaunch(ctx, TaskToLaunchParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return StoredTask{}, fmt.Errorf("task %s: %w", taskID, ErrTaskNotFound)
	}
	if err != nil {
		return StoredTask{}, err
	}
	t := StoredTask{
		ID: row.ID.String(), AgentID: row.AgentID.String(), Description: row.Description,
		Parameters: objectOf(row.Parameters), Status: row.Status, ExecutionID: row.ExecutionID.String,
		Metadata: objectOf(row.TaskMetadata), CreatedBy: row.CreatedBy,
	}
	if row.ScheduledAt.Valid {
		at := row.ScheduledAt.Time.UTC()
		t.ScheduledAt = &at
	}
	return t, nil
}

// MarkLaunched records a started workflow: status running (started_at
// stamped once) or scheduled, and its execution id; false when the task is gone.
func (Runs) MarkLaunched(ctx context.Context, s db.Session, taskID, status, executionID string, now time.Time) (bool, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).MarkTaskLaunched(ctx, MarkTaskLaunchedParams{
		Status: status, ExecutionID: executionID, Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID(),
	})
	return n > 0, err
}
