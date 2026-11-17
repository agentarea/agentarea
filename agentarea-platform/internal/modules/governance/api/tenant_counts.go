package api

import "context"

// TenantCounter counts tenant policies: analytics/pulse_repository.py's policies.
type TenantCounter interface {
	TenantCounts(ctx context.Context) (int, error)
}
