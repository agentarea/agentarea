package api

import (
	"context"
	"time"
)

// TenantCounts are agents' counts over every tenant workspace.
type TenantCounts struct {
	Agents, AgentsCreated24h int
	// SkillsByItem are skills by the catalog item they were installed from; "" is none.
	SkillsByItem map[string]int
	// ClientsByKind are registered clients by kind.
	ClientsByKind map[string]int
	// WithAgent is how many of the given workspaces have an agent.
	WithAgent int
}

// TenantCounter is analytics/pulse_repository.py's agents, skills, clients and _activation's with_agent.
type TenantCounter interface {
	TenantCounts(ctx context.Context, day time.Time, workspaces []string) (TenantCounts, error)
}
