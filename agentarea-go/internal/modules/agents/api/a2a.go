package api

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// Refusals A2ARuns.Start returns.
var (
	ErrA2AModelNotConfigured = errors.New("agent model is not configured")
	ErrA2ASpendCap           = errors.New("monthly spend cap reached")
	ErrA2ARejected           = errors.New("task rejected")
)

// A2ATask is a task as the A2A methods read it.
type A2ATask struct {
	ID, AgentID, CreatedBy, Status string
	// Result is nil or a wirejson.Object.
	Result     any
	Error      *string
	Metadata   wirejson.Object
	Parameters wirejson.Object
	UpdatedAt  time.Time
}

// A2AStart is a run an A2A message starts for the caller in ctx.
type A2AStart struct {
	AgentID, Description string
	Metadata             map[string]any
	// Source is the provenance origin id and source identity.
	Source                string
	RequiresHumanApproval bool
}

// A2ARuns is what the A2A task methods need of runs. Every call acts for the
// caller authn.WithCaller put in ctx.
type A2ARuns interface {
	// Start permits the caller to invoke the agent unless an agent key
	// confined to it made the call, stores the task and starts its workflow.
	Start(ctx context.Context, in A2AStart) (taskID string, err error)
	// Task reads a task of the caller's workspace; live settles a closed run's outcome.
	Task(ctx context.Context, taskID string, live bool) (A2ATask, bool, error)
	// MayAct is nil when the caller started the task or administers the
	// workspace, else an HTTP 403.
	MayAct(ctx context.Context, t A2ATask) error
	// Cancel is false when the task has ended or its workflow could not be cancelled.
	Cancel(ctx context.Context, taskID string) (bool, error)
	// AgentTasks is a page of the agent's tasks, newest first, and their count.
	AgentTasks(ctx context.Context, agentID string, limit, offset int) ([]A2ATask, int64, error)
	// SetParameters replaces the task's parameters.
	SetParameters(ctx context.Context, taskID string, params wirejson.Object) error
	// Follow calls emit with each event of the task's feed until the feed
	// ends or emit fails; fromNow skips what the log already holds.
	Follow(ctx context.Context, t A2ATask, fromNow bool, emit func(eventType string, data wirejson.Object) error) error
}
