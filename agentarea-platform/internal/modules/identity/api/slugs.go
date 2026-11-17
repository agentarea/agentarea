package api

import (
	"context"
	"errors"
)

// ErrWorkspaceNotFound: no workspace has the id.
var ErrWorkspaceNotFound = errors.New("workspace not found")

// WorkspaceSlugs is workspace_slug_for: the URL slug of a workspace by its id.
type WorkspaceSlugs interface {
	// Slug returns ErrWorkspaceNotFound when no such workspace exists.
	Slug(ctx context.Context, workspaceID string) (string, error)
}
