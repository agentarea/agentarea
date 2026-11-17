package store

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// DeclareEgressExit upserts a platform exit in the session's workspace; an unchanged one is not touched.
func DeclareEgressExit(ctx context.Context, s db.Session, e api.DeclaredEgressExit, createdBy string, now time.Time) error {
	_, err := s.Q().Exec(ctx, `INSERT INTO egress_exits (id, name, description, via, remote_dns, allow_plaintext_credentials,
		managed_by, workspace_id, created_by, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, false, 'platform', $6, $7, $8, $8)
		ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, via = EXCLUDED.via,
			remote_dns = EXCLUDED.remote_dns, updated_at = EXCLUDED.updated_at
		WHERE egress_exits.workspace_id = EXCLUDED.workspace_id AND
			(egress_exits.name, egress_exits.description, egress_exits.via, egress_exits.remote_dns)
			IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.description, EXCLUDED.via, EXCLUDED.remote_dns)`,
		e.ID, e.Name, e.Description, e.Via, e.RemoteDNS, s.Workspace().ID(), createdBy, now.UTC().Truncate(time.Microsecond))
	return err
}
