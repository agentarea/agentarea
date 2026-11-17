package store

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// NamedInstance is an MCP server instance carrying a name, as binding reads it.
type NamedInstance struct {
	ID        uuid.UUID
	CreatedBy string
	ManagedBy *string
}

// MCPInstancesNamed are the instances visible to the session's workspace named name, newest first.
func (Lookup) MCPInstancesNamed(ctx context.Context, s db.Session, name string) ([]NamedInstance, error) {
	rows, err := New(s.Q()).MCPInstancesNamed(ctx, MCPInstancesNamedParams{Name: name, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]NamedInstance, len(rows))
	for i, r := range rows {
		out[i] = NamedInstance{ID: r.ID, CreatedBy: r.CreatedBy, ManagedBy: fromText(r.ManagedBy)}
	}
	return out, nil
}
