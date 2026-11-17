package api

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Tasks starts runs for other modules (TaskService.route_or_submit_task): a
// trigger firing, a channel message, a saved task definition.
type Tasks interface {
	// Submit routes a session follow-up into the live task it continues, or
	// stores the task under its resolved policy and starts its workflow.
	Submit(ctx context.Context, ws scope.Workspace, req TaskRequest) (TaskSubmitted, error)
}

// TaskRequest is a run to start. UserID is whom it acts for; Metadata is
// merged under the governance keys the run writes (created_via defaults to
// "api"); Parameters carry trigger_id, session, trigger_event and the rest.
type TaskRequest struct {
	TaskID                string
	AgentID               string
	Description           string
	Parameters            map[string]any
	UserID                string
	RequiresHumanApproval bool
	Metadata              map[string]any
	Provenance            TaskProvenance
	ScheduledAt           *time.Time
	// Claim, when set, makes a routed follow-up go out at most once per delivery.
	Claim FollowUpClaim
}

// TaskProvenance is why a task exists (TaskProvenance).
type TaskProvenance struct {
	OriginType, OriginID           string
	CorrelationID, CausationID     string
	ParentTaskID, TaskDefinitionID string
	SourceIdentity                 string
	Depth                          int
}

// FollowUpClaim records, before the signal, that a delivery goes to taskID;
// false when an earlier attempt already did. Release withdraws a claim whose
// signal did not go out.
type FollowUpClaim interface {
	Claim(ctx context.Context, taskID string) (bool, error)
	Release(ctx context.Context) error
}

// TaskSubmitted is the task the request landed in; Routed when a live task
// of its session took it as a follow-up.
type TaskSubmitted struct {
	TaskID      string
	Status      string
	ExecutionID string
	Routed      bool
}

// Refusals Submit returns, wrapped with Python's text.
var (
	ErrAgentNotFound      = errors.New("agent not found")
	ErrAgentArchived      = errors.New("agent archived")
	ErrModelNotConfigured = errors.New("agent model is not configured")
	ErrTaskPolicyRejected = errors.New("task policy rejected")
	ErrSpendCapReached    = errors.New("monthly spend cap reached")
	ErrTaskDispatchFailed = errors.New("task dispatch failed")
)
