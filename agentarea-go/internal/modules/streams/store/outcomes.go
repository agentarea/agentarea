package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// ErrFiringNotRecorded is a task's end that arrived before the firing that started it was recorded.
var ErrFiringNotRecorded = errors.New("no firing names the task yet")

// LockTrigger locks the trigger's row until commit; false when it is gone.
func (Router) LockTrigger(ctx context.Context, s db.Session, triggerID uuid.UUID) (bool, error) {
	_, err := New(s.Q()).LockTrigger(ctx, LockTriggerParams{ID: triggerID, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// ResetFailures sets the trigger's consecutive failures back to 0.
func (Router) ResetFailures(ctx context.Context, s db.Session, triggerID uuid.UUID, at time.Time) error {
	return New(s.Q()).ResetTriggerFailures(ctx, ResetTriggerFailuresParams{At: naive(at), ID: triggerID, WorkspaceID: s.Workspace().ID()})
}

// MarkRunFailed marks the latest firing that started the task failed; false when it is not a
// success (already marked, or never one). ErrFiringNotRecorded when no firing names the task.
func (Router) MarkRunFailed(ctx context.Context, s db.Session, triggerID, taskID uuid.UUID, reason *string, at time.Time) (bool, error) {
	q := New(s.Q())
	latest, err := q.LatestFiringOfTask(ctx, LatestFiringOfTaskParams{
		TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true}, TaskID: uuid.NullUUID{UUID: taskID, Valid: true},
		WorkspaceID: s.Workspace().ID(),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("trigger %s, task %s: %w", triggerID, taskID, ErrFiringNotRecorded)
	}
	if err != nil {
		return false, err
	}
	if latest.Status != "success" {
		return false, nil
	}
	return true, q.MarkFiringFailed(ctx, MarkFiringFailedParams{ErrorMessage: text(reason), At: naive(at), ID: latest.ID, WorkspaceID: s.Workspace().ID()})
}
