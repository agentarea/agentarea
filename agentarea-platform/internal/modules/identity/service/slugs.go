package service

import (
	"context"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// WorkspaceRows reads a workspace row by id.
type WorkspaceRows interface {
	GetWorkspace(ctx context.Context, q db.Querier, id string) (domain.Workspace, bool, error)
}

// WorkspaceSlugs implements api.WorkspaceSlugs over the read pool.
type WorkspaceSlugs struct {
	DB    db.Database
	Store WorkspaceRows
}

var _ api.WorkspaceSlugs = WorkspaceSlugs{}

// Slug is workspace_slug_for.
func (w WorkspaceSlugs) Slug(ctx context.Context, workspaceID string) (string, error) {
	q, release, err := w.DB.Global().Read(ctx)
	if err != nil {
		return "", err
	}
	defer release()
	ws, ok, err := w.Store.GetWorkspace(ctx, q, workspaceID)
	if err != nil {
		return "", err
	}
	if !ok {
		return "", fmt.Errorf("workspace %s: %w", workspaceID, api.ErrWorkspaceNotFound)
	}
	return ws.Slug, nil
}
