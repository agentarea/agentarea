package store

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// TenantReads reads runs' tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context, w api.Windows, workspaces []string) (api.TenantCounts, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return api.TenantCounts{}, err
	}
	defer release()
	var c api.TenantCounts
	day, week, month := w.Day.UTC(), w.Week.UTC(), w.Month.UTC()
	for _, a := range []struct {
		n     *int
		who   string
		since time.Time
	}{{&c.ActiveWorkspaces7d, "workspace_id", week}, {&c.ActiveWorkspaces30d, "workspace_id", month},
		{&c.ActiveUsers7d, "created_by", week}, {&c.ActiveUsers30d, "created_by", month}} {
		if *a.n, err = db.CountOne(ctx, q, `SELECT count(DISTINCT `+a.who+`) FROM tasks
			WHERE workspace_id <> 'platform' AND created_at >= $1`, a.since); err != nil {
			return c, err
		}
	}
	for _, g := range []struct {
		out *map[string]int
		key string
		and string
	}{{&c.ByStatus, "status", ""}, {&c.ByOrigin, "coalesce(origin_type, 'unknown')", ""},
		{&c.FailedByReason, "coalesce(result ->> 'failure_reason', 'unknown')", " AND status = 'failed'"}} {
		if *g.out, err = db.CountBy(ctx, q, `SELECT `+g.key+`, count(*) FROM tasks
			WHERE workspace_id <> 'platform' AND created_at >= $1`+g.and+` GROUP BY 1`, day); err != nil {
			return c, err
		}
	}
	if err := q.QueryRow(ctx, `SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM completed_at - started_at))
		FROM tasks WHERE workspace_id <> 'platform' AND completed_at >= $1 AND started_at IS NOT NULL`, day).Scan(&c.MedianDurationSeconds); err != nil {
		return c, err
	}
	c.FirstCompleted = map[string]time.Time{}
	if len(workspaces) == 0 {
		return c, nil
	}
	rows, err := q.Query(ctx, `SELECT workspace_id, min(completed_at) FROM tasks
		WHERE workspace_id = ANY($1::text[]) AND status = 'completed' AND completed_at IS NOT NULL
		GROUP BY workspace_id`, workspaces)
	if err != nil {
		return c, err
	}
	defer rows.Close()
	for rows.Next() {
		var ws string
		var at time.Time
		if err := rows.Scan(&ws, &at); err != nil {
			return c, err
		}
		c.FirstCompleted[ws] = at
	}
	return c, rows.Err()
}
