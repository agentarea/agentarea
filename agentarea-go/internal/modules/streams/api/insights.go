package api

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// BrokenTrigger is a trigger that stopped working: NeedsNewOwner when whoever
// set it up can no longer run its agent, else it failed in a row (still
// active) or turned itself off at its threshold. LastExecutionAt is naive UTC.
type BrokenTrigger struct {
	ID                  string
	Name                string
	AgentID             string
	IsActive            bool
	NeedsNewOwner       bool
	ConsecutiveFailures int
	FailureThreshold    int
	LastExecutionAt     *time.Time
}

// CronTrigger is an active trigger with a cron schedule; Timezone nil is UTC.
type CronTrigger struct {
	ID             string
	Name           string
	AgentID        string
	CronExpression string
	Timezone       *string
}

// TriggerBoard is what the dashboard and the agent overview read of triggers.
type TriggerBoard interface {
	// BrokenTriggers is TriggerRepository.list_broken: most failures first, then by name.
	BrokenTriggers(ctx context.Context, ws scope.Workspace, limit int) ([]BrokenTrigger, error)
	// CronTriggers is the active cron triggers, of one agent when agentID is set.
	CronTriggers(ctx context.Context, ws scope.Workspace, agentID *string) ([]CronTrigger, error)
}
