package api

import "context"

// TenantCounter counts active tenant triggers by type: analytics/pulse_repository.py's triggers_active.
type TenantCounter interface {
	TenantCounts(ctx context.Context) (map[string]int, error)
}
