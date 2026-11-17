package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
)

// TenantReads reads models' tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context) (map[string]int, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return db.CountBy(ctx, q, `SELECT provider_spec_id::text, count(*) FROM provider_configs
		WHERE workspace_id <> 'platform' GROUP BY 1`)
}
