package store

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// LocateClient is the workspace of the client among workspaces, across
// workspaces (locate_workspace).
func LocateClient(ctx context.Context, q db.Querier, id uuid.UUID, workspaces []string) (string, bool, error) {
	ws, err := New(q).LocateClient(ctx, LocateClientParams{ID: id, Workspaces: workspaces})
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return ws, true, nil
}
