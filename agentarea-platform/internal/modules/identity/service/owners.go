package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
)

// WorkspaceOwners implements api.WorkspaceOwners over the read pool.
type WorkspaceOwners struct {
	DB    db.Database
	Store WorkspaceRows
}

var _ api.WorkspaceOwners = WorkspaceOwners{}

// Owner implements api.WorkspaceOwners.
func (w WorkspaceOwners) Owner(ctx context.Context, workspaceID string) (string, bool, error) {
	q, release, err := w.DB.Global().Read(ctx)
	if err != nil {
		return "", false, err
	}
	defer release()
	ws, ok, err := w.Store.GetWorkspace(ctx, q, workspaceID)
	if err != nil || !ok {
		return "", false, err
	}
	return ws.OwnerUserID, true, nil
}
