package api

import "context"

// TenantCounter counts tenant provider configs by provider spec id: analytics/pulse_repository.py's llm_providers.
type TenantCounter interface {
	TenantCounts(ctx context.Context) (map[string]int, error)
}
