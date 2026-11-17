package store

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
)

// TenantReads reads agents' tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context, day time.Time, workspaces []string) (api.TenantCounts, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return api.TenantCounts{}, err
	}
	defer release()
	var c api.TenantCounts
	if c.Agents, err = db.CountOne(ctx, q, `SELECT count(*) FROM agents WHERE workspace_id <> 'platform'`); err != nil {
		return c, err
	}
	if c.AgentsCreated24h, err = db.CountOne(ctx, q, `SELECT count(*) FROM agents
		WHERE workspace_id <> 'platform' AND created_at >= $1`, day.UTC()); err != nil {
		return c, err
	}
	if c.SkillsByItem, err = db.CountBy(ctx, q, `SELECT coalesce(registry_item_id::text, ''), count(*) FROM skills
		WHERE workspace_id <> 'platform' GROUP BY 1`); err != nil {
		return c, err
	}
	if c.ClientsByKind, err = db.CountBy(ctx, q, `SELECT kind, count(*) FROM clients
		WHERE workspace_id <> 'platform' GROUP BY 1`); err != nil {
		return c, err
	}
	if c.WithAgent, err = db.CountOne(ctx, q, `SELECT count(DISTINCT workspace_id) FROM agents
		WHERE workspace_id = ANY($1::text[])`, workspaces); err != nil {
		return c, err
	}
	return c, nil
}
