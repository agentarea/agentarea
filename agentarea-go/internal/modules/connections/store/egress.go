package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

// EgressBound is bound_instances: the session's workspace's MCP instances
// whose json_spec binds the exit.
func EgressBound(ctx context.Context, s db.Session, exitID string) ([]api.EgressBoundInstance, error) {
	rows, err := s.Q().Query(ctx, `SELECT id::text, name, transport FROM mcp_server_instances
		WHERE workspace_id = $1 AND json_spec->>'egress_exit' = $2`, s.Workspace().ID(), exitID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []api.EgressBoundInstance
	for rows.Next() {
		var i api.EgressBoundInstance
		if err := rows.Scan(&i.ID, &i.Name, &i.Transport); err != nil {
			return nil, err
		}
		out = append(out, i)
	}
	return out, rows.Err()
}
