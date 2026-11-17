package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

// TenantReads reads streams' tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context) (map[string]int, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return db.CountBy(ctx, q, `SELECT trigger_type, count(*) FROM triggers
		WHERE workspace_id <> 'platform' AND is_active GROUP BY 1`)
}
