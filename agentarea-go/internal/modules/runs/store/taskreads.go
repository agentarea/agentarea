package store

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// TaskCostText is a task result's own_cost and total_cost as stored, "" when absent.
type TaskCostText struct {
	OwnCost, TotalCost string
}

// UnfinishedRun is an unended task of an origin and its workflow id, "" when it never started.
type UnfinishedRun struct {
	TaskID, ExecutionID string
}

// TaskOriginRow is a task's origin and causation, "" for each one unset.
type TaskOriginRow struct {
	OriginType, OriginID, CausationID string
}

// TaskStatuses maps each id of a workspace task to its status.
func (Runs) TaskStatuses(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]string, error) {
	rows, err := New(s.Q()).TaskStatuses(ctx, TaskStatusesParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[string]string, len(rows))
	for _, r := range rows {
		out[r.ID.String()] = r.Status
	}
	return out, nil
}

// TaskCosts maps each id of a workspace task to the costs its result stores.
func (Runs) TaskCosts(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]TaskCostText, error) {
	rows, err := New(s.Q()).TaskCosts(ctx, TaskCostsParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[string]TaskCostText, len(rows))
	for _, r := range rows {
		out[r.ID.String()] = TaskCostText{OwnCost: r.OwnCost, TotalCost: r.TotalCost}
	}
	return out, nil
}

// UnfinishedRunsFrom is the origin's tasks whose stored status has not ended, oldest first.
func (Runs) UnfinishedRunsFrom(ctx context.Context, s db.Session, originType, originID string) ([]UnfinishedRun, error) {
	rows, err := New(s.Q()).UnfinishedRunsFrom(ctx, UnfinishedRunsFromParams{WorkspaceID: s.Workspace().ID(), OriginType: originType, OriginID: originID})
	if err != nil {
		return nil, err
	}
	out := make([]UnfinishedRun, len(rows))
	for i, r := range rows {
		out[i] = UnfinishedRun{TaskID: r.ID.String(), ExecutionID: r.ExecutionID.String}
	}
	return out, nil
}

// TaskOriginOf is a workspace task's origin; false when the workspace has no such task.
func (Runs) TaskOriginOf(ctx context.Context, s db.Session, id uuid.UUID) (TaskOriginRow, bool, error) {
	r, err := New(s.Q()).TaskOriginOf(ctx, TaskOriginOfParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return TaskOriginRow{}, false, nil
	}
	if err != nil {
		return TaskOriginRow{}, false, err
	}
	return TaskOriginRow{OriginType: r.OriginType.String, OriginID: r.OriginID.String, CausationID: r.CausationID.String}, true, nil
}
