package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// DelegationInput asks for a child task of a run (task_state.py create_delegation_task_activity).
type DelegationInput struct {
	ParentTaskID    string
	TargetAgentID   string
	TargetAgentName string
	Message         string
	ParentPolicy    api.Policy
	RunBudget       *money.Decimal
	ExecutionID     string
}

// DelegationOutput: Status created with TaskID and Policy, or failed with Error.
// RunnerClientID is the client whose runner runs the child's turns, if any.
type DelegationOutput struct {
	Status         string
	TaskID         string
	Policy         api.Policy
	Error          string
	RunnerClientID string
}

// runnerClientKey names, in task metadata, the client whose runner runs the task's turns.
const runnerClientKey = "runner_client_id"

// CreateDelegationTask stores the child task with the parent's policy as
// upper bound and the allotted run budget; the parent starts it as a child
// workflow. A delegate that cannot run is reported, not raised.
func (s *Service) CreateDelegationTask(ctx context.Context, p Principal, in DelegationInput) (DelegationOutput, error) {
	ws, err := workspace(p)
	if err != nil {
		return DelegationOutput{}, err
	}
	if in.RunBudget == nil {
		return DelegationOutput{}, nonRetryable("ValueError", "delegation request is missing its allocated run budget", nil)
	}
	if s.d.Agents == nil || s.d.Policies == nil || s.d.Audit == nil {
		return DelegationOutput{}, errors.New("delegation needs the agent definitions, the policy resolver and the audit writer")
	}
	failed := func(err error) (DelegationOutput, error) {
		return DelegationOutput{Status: "failed", Error: err.Error()}, nil
	}
	def, agent, err := s.agent(ctx, p, in.TargetAgentID)
	switch {
	case errors.Is(err, ErrNotFound) || errors.Is(err, ErrRefused):
		return failed(fmt.Errorf("agent %s cannot be delegated to: %w", in.TargetAgentID, err))
	case err != nil:
		return DelegationOutput{}, err
	case def.Archived:
		return failed(fmt.Errorf("agent %s is archived", in.TargetAgentID))
	case def.ClientID == "" && agent.ModelID == "":
		return failed(fmt.Errorf("agent %s has no model configured", in.TargetAgentID))
	}
	taskID := uuid.NewString()
	policy, snapshot, err := s.d.Policies.Delegation(ctx, governanceapi.RunPrincipal{Workspace: ws, UserID: p.UserID, AgentID: p.AgentID}, governanceapi.DelegationRequest{
		TargetAgentID: in.TargetAgentID, UpperBound: fromRunPolicy(in.ParentPolicy), RunBudget: *in.RunBudget,
	})
	if errors.Is(err, governanceapi.ErrPolicyRefused) {
		return failed(err)
	}
	if err != nil {
		return DelegationOutput{}, err
	}
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		parent, err := s.store.Origin(ctx, tx, in.ParentTaskID)
		if err != nil {
			return err
		}
		meta := map[string]any{
			"created_via": "agent_delegation", "parent_agent_id": p.AgentID, "parent_task_id": in.ParentTaskID,
			"agent_name": agent.Name, "requires_human_approval": false, "governance_snapshot": snapshot,
		}
		if def.ClientID != "" {
			meta[runnerClientKey] = def.ClientID
		}
		if err := s.store.CreateTask(ctx, tx, store.NewTask{
			ID: taskID, AgentID: in.TargetAgentID, Description: "Delegated task to " + in.TargetAgentName,
			Parameters: map[string]any{"source": "agent_delegation", "parent_agent_id": p.AgentID, "parent_task_id": in.ParentTaskID},
			Status:     "submitted", ExecutionID: in.ExecutionID, Metadata: jsonValue(meta), CreatedBy: p.UserID,
			OriginType: "agent", OriginID: in.ParentTaskID, CausationID: in.ParentTaskID, ParentTaskID: in.ParentTaskID,
			SourceIdentity: parent.SourceIdentity,
		}, s.now()); err != nil {
			return err
		}
		return s.d.Audit.RecordOnce(ctx, tx, taskCreated(taskID, p.UserID, nil))
	})
	if err != nil {
		return DelegationOutput{}, taskNotFound(err)
	}
	s.d.Log.InfoContext(ctx, "created delegation task", "task_id", taskID, "agent", in.TargetAgentName)
	return DelegationOutput{Status: "created", TaskID: taskID, Policy: toRunPolicy(policy), RunnerClientID: def.ClientID}, nil
}
