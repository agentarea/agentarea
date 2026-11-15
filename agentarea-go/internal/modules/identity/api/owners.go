package api

import "context"

// WorkspaceOwners reads who owns a workspace (workspaces.owner_user_id).
type WorkspaceOwners interface {
	// Owner is the owner's user id; false when no such workspace exists.
	Owner(ctx context.Context, workspaceID string) (string, bool, error)
}
