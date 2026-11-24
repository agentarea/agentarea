// Package api is what other modules may import from governance: identifiers and the
// interfaces governance implements for them. Nothing else of governance is importable
// (rule 1).
//
// Policy is the resolved policy a run carries (EffectivePolicy); the tool
// decision point (DecideToolPolicy) and the gates (CheckGates) are pure
// functions of it, so every plane evaluates the same rules the same way.
package api

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// AuditRecord is one audit row written under a caller-chosen id
// (AuditService.record_once). A run's event rows are ResourceType "task",
// ResourceID the task's id. ActorID is required.
type AuditRecord struct {
	EventID      string
	Action       string
	ResourceType string
	ResourceID   string
	ActorType    string
	ActorID      string
	Metadata     map[string]any
}

// AuditWriter writes audit rows inside the caller's transaction; a repeat of
// an event id is a no-op, so a retried writer never doubles the trail.
type AuditWriter interface {
	RecordOnce(ctx context.Context, tx db.Session, rec AuditRecord) error
}

// RunPrincipal is who a run acts for: its workspace, the person who started
// it (empty for a schedule or an event) and its agent.
type RunPrincipal struct {
	Workspace scope.Workspace
	UserID    string
	AgentID   string
}

// Budgets reads the spend caps set now (model_spend_caps.current_budget with
// no run budget): the workspace, agent and user layers resolved again. Nil:
// no budget set.
type Budgets interface {
	CurrentBudget(ctx context.Context, p RunPrincipal) (*Budget, error)
}

// ErrPolicyRefused wraps a PolicyValidationError: a lower layer loosened a
// higher one, or the runtime contract is incomplete. Its text is Python's.
var ErrPolicyRefused = errors.New("policy refused")

// DelegationRequest is a delegated task's policy question: its own layers
// under the parent's effective policy, with the run budget it was allotted.
type DelegationRequest struct {
	TargetAgentID string
	UpperBound    Policy
	RunBudget     money.Decimal
}

// RunPolicies resolves the policy a run starts with.
type RunPolicies interface {
	// Resolve is GovernancePolicyResolver.resolve over the workspace, agent,
	// user and task layers; ErrPolicyRefused when they do not tighten.
	Resolve(ctx context.Context, p RunPrincipal, taskPolicy *Policy) (Policy, error)
	// Delegation is create_task_with_policy's policy half for a delegated
	// task: the resolved policy and the governance_snapshot metadata.
	Delegation(ctx context.Context, p RunPrincipal, req DelegationRequest) (Policy, Snapshot, error)
	// Task is start_run's and create_task_with_policy's policy half for a run
	// a caller starts: the resolved policy and the governance_snapshot metadata.
	Task(ctx context.Context, p RunPrincipal, req TaskRequest) (Policy, Snapshot, error)
}

// TaskRequest is what a caller asked of a run's policy: its task policy, the
// execution block's max_model_turns (nil without one), parameters.max_iterations
// as sent (nil when absent or null) and requires_human_approval.
type TaskRequest struct {
	TaskPolicy            *Policy
	ExecutionTurns        *int64
	MaxIterations         any
	RequiresHumanApproval bool
}

// DeclaredEgressExit is a platform exit leaving through a hop of the egress proxy's own
// configuration; it holds no credentials.
type DeclaredEgressExit struct {
	ID          uuid.UUID
	Name        string
	Description *string
	Via         string
	RemoteDNS   bool
}

// EgressExitDeclarations is what the operator writes of egress exits; idempotent.
type EgressExitDeclarations interface {
	DeclareEgressExit(ctx context.Context, e DeclaredEgressExit) error
}
