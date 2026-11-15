package api

import (
	"context"
	"encoding/json"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// TaskDef is task_definitions_toolset._output.
type TaskDef struct {
	ID          string
	Name        string
	Description string
	AgentID     string
	// Parameters is the stored parameters object.
	Parameters json.RawMessage
	CreatedBy  string
	UpdatedAt  time.Time
}

// TaskDefs is what the platform MCP task_definitions toolset
// (tools/task_definitions_toolset.py) calls; refusals are errors whose text
// is what the toolset reports.
type TaskDefs interface {
	List(ctx context.Context, c authn.Caller, agentID *string, limit int) ([]TaskDef, error)
	// Get returns ErrNotFound for an unknown saved task.
	Get(ctx context.Context, c authn.Caller, definitionID string) (TaskDef, error)
	// Create takes a TaskDefinitionCreate document.
	Create(ctx context.Context, c authn.Caller, taskDefinitionCreate json.RawMessage) (TaskDef, error)
	// Run starts a run (created_via "mcp") and returns the TaskResponse body the runs module made.
	Run(ctx context.Context, c authn.Caller, definitionID string, parameters json.RawMessage) (any, error)
}
