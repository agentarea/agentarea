package api

import (
	"context"
	"time"
)

// NewWorkspace is a workspace and when it was created.
type NewWorkspace struct {
	ID        string
	CreatedAt time.Time
}

// TenantCounts are identity's counts over every tenant workspace; the platform workspace is no
// tenant's.
type TenantCounts struct {
	Workspaces int
	// Users are the workspace members and owners, each once.
	Users int
	// WorkspacesByMembers is how many workspaces have each number of distinct members.
	WorkspacesByMembers map[int]int
	// NewPersonal are the personal workspaces created at or after since.
	NewPersonal []NewWorkspace
}

// TenantCounter is analytics/pulse_repository.py's workspaces total, _users, _workspace_sizes and _activation.
type TenantCounter interface {
	TenantCounts(ctx context.Context, since time.Time) (TenantCounts, error)
}
