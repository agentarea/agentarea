package store

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
)

// TenantReads reads identity's tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context, since time.Time) (api.TenantCounts, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return api.TenantCounts{}, err
	}
	defer release()
	var c api.TenantCounts
	if c.Workspaces, err = db.CountOne(ctx, q, `SELECT count(*) FROM workspaces WHERE id <> 'platform'`); err != nil {
		return c, err
	}
	if c.Users, err = db.CountOne(ctx, q, `SELECT count(*) FROM (
		SELECT user_id FROM workspace_memberships WHERE workspace_id <> 'platform'
		UNION SELECT owner_user_id FROM workspaces WHERE id <> 'platform') AS u`); err != nil {
		return c, err
	}
	sizes, err := q.Query(ctx, `SELECT n, count(*) FROM (SELECT count(DISTINCT m.user_id) AS n FROM workspaces w
			LEFT JOIN workspace_memberships m ON m.workspace_id = w.id
			WHERE w.id <> 'platform' GROUP BY w.id) AS s
		GROUP BY n`)
	if err != nil {
		return c, err
	}
	c.WorkspacesByMembers = map[int]int{}
	for sizes.Next() {
		var members, workspaces int
		if err := sizes.Scan(&members, &workspaces); err != nil {
			sizes.Close()
			return c, err
		}
		c.WorkspacesByMembers[members] = workspaces
	}
	sizes.Close()
	if err := sizes.Err(); err != nil {
		return c, err
	}
	rows, err := q.Query(ctx, `SELECT id, created_at FROM workspaces
		WHERE id = owner_user_id AND id <> 'platform' AND created_at >= $1`, since.UTC())
	if err != nil {
		return c, err
	}
	defer rows.Close()
	for rows.Next() {
		var w api.NewWorkspace
		if err := rows.Scan(&w.ID, &w.CreatedAt); err != nil {
			return c, err
		}
		c.NewPersonal = append(c.NewPersonal, w)
	}
	return c, rows.Err()
}
