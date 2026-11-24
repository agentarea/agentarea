package store

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

//go:generate sqlc generate

// Lookup reads MCP server instances visible to the session's workspace.
type Lookup struct{}

func (Lookup) MCPInstanceExists(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	return New(s.Q()).MCPInstanceExists(ctx, MCPInstanceExistsParams{WorkspaceID: s.Workspace().ID(), ID: id})
}

func (Lookup) MCPInstanceNames(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]string, error) {
	rows, err := New(s.Q()).MCPInstanceNames(ctx, MCPInstanceNamesParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]string, len(rows))
	for _, r := range rows {
		out[r.ID] = r.Name
	}
	return out, nil
}

// Managed is what the lookups answer per row: the row's managed_by, nil when
// the workspace owns it.
type Managed map[uuid.UUID]*string

// MCPInstanceFlags maps each id the session sees to its managed_by.
func (Lookup) MCPInstanceFlags(ctx context.Context, s db.Session, ids []uuid.UUID) (Managed, error) {
	rows, err := New(s.Q()).MCPInstanceFlags(ctx, MCPInstanceFlagsParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := Managed{}
	for _, r := range rows {
		out[r.ID] = fromText(r.ManagedBy)
	}
	return out, nil
}

// OpenAPIConnectionFlags maps each id the session sees to its managed_by.
func (Lookup) OpenAPIConnectionFlags(ctx context.Context, s db.Session, ids []uuid.UUID) (Managed, error) {
	rows, err := New(s.Q()).OpenAPIConnectionFlags(ctx, OpenAPIConnectionFlagsParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := Managed{}
	for _, r := range rows {
		out[r.ID] = fromText(r.ManagedBy)
	}
	return out, nil
}

// OpenAPIConnectionNames maps each id the session sees to its name.
func (Lookup) OpenAPIConnectionNames(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]string, error) {
	rows, err := New(s.Q()).OpenAPIConnectionNames(ctx, OpenAPIConnectionNamesParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]string, len(rows))
	for _, r := range rows {
		out[r.ID] = r.Name
	}
	return out, nil
}
