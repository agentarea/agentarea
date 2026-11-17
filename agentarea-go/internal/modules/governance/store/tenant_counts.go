package store

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// TenantReads reads governance's tenant counts (analytics/pulse_repository.py).
type TenantReads struct{ DB db.Database }

var _ api.TenantCounter = TenantReads{}

// TenantCounts implements api.TenantCounter.
func (p TenantReads) TenantCounts(ctx context.Context) (int, error) {
	q, release, err := p.DB.Global().Read(ctx)
	if err != nil {
		return 0, err
	}
	defer release()
	return db.CountOne(ctx, q, `SELECT count(*) FROM policies WHERE workspace_id <> 'platform'`)
}
