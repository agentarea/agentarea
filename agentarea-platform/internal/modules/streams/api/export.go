package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ExportTrigger is a trigger as the workspace config export reads it.
type ExportTrigger struct {
	ID, Name, TriggerType, AgentID string
	Conditions                     map[string]any
	TaskParameters                 map[string]any
	// CronExpression and Timezone are empty when the trigger has none.
	CronExpression, Timezone string
	IsActive                 bool
}

// TriggerExports lists the workspace's triggers for the workspace config export.
type TriggerExports interface {
	ExportTriggers(ctx context.Context, ws scope.Workspace) ([]ExportTrigger, error)
}
