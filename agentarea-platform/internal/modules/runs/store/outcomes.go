package store

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// OutcomeTaskOf reads the task a task event names; false when the workspace has none.
func (Runs) OutcomeTaskOf(ctx context.Context, s db.Session, id uuid.UUID) (OutcomeTaskRow, bool, error) {
	r, err := New(s.Q()).OutcomeTask(ctx, OutcomeTaskParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return OutcomeTaskRow{}, false, nil
	}
	return r, err == nil, err
}
