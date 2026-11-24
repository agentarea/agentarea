package service

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

var _ api.ClientToolCalls = (*Service)(nil)

// RunClientCall is run_tool_call past the policy for a call through the client gateway
// (/mcp/clients, /v1/mcp/{id}): priced, held and capped like a run's call, its lines carry the
// client. A call of a runner's turn is also judged by its run's policy and capped by the run's
// budget, as a call the run makes itself is, and its lines carry the task.
func (s *Service) RunClientCall(ctx context.Context, ws scope.Workspace, call api.ClientToolCall, h api.ClientCallHooks) (string, error) {
	p := Principal{WorkspaceID: ws.ID(), UserID: call.UserID}
	in := ToolCall{ToolName: call.ToolName, Args: call.Args, Binding: call.Binding, ToolCallID: uuid.NewString(), ClientID: call.ClientID}
	var refusal string
	if call.TaskID != "" {
		agentID, policy, known, err := s.turnRun(ctx, ws, call.TaskID)
		if err != nil {
			return "", err
		}
		p.AgentID, in.TaskID, in.Policy, in.PolicyApprovalGranted = agentID, call.TaskID, policy, call.Approved
		if refusal = runPolicyRefusal(in); !known {
			refusal = "the run this turn acts in is gone or has no policy to hold the call to"
		}
	}
	var conn *connection
	var err error
	if refusal == "" {
		if conn, refusal, err = s.callConnection(ctx, ws, in); err != nil {
			return "", err
		}
	}
	var b before
	if refusal == "" {
		b, refusal = s.beforeCall(ctx, p, in, conn)
	}
	if refusal == "" {
		var pending *pendingCost
		if b.converted {
			pending = &pendingCost{amount: b.amount, currency: b.currency}
		}
		if refusal, err = s.toolSpendRefusal(ctx, ws, p, in, conn, pending); err != nil {
			s.voidHold(ctx, b.holdID, "the spend gate failed")
			return "", err
		}
		if refusal != "" {
			s.voidHold(ctx, b.holdID, "refused by a spend cap")
		}
	}
	if err := h.Audit(ctx, refusal); err != nil {
		s.voidHold(ctx, b.holdID, "the call was not audited")
		return "", err
	}
	if refusal != "" {
		return refusal, nil
	}
	answer, err := h.Invoke(ctx)
	if err != nil {
		s.voidHold(ctx, b.holdID, "the call raised")
		return "", err
	}
	if !answer.Success {
		s.voidHold(ctx, b.holdID, "the call failed")
	}
	out := ToolOutput{Success: answer.Success, MeteredBody: answer.Body, MeteredMeta: answer.Meta, VendorCost: answer.VendorCost}
	usages := s.meter(ctx, in, conn, out, b)
	if len(usages) == 0 {
		return "", nil
	}
	inserted, err := s.ledger(ctx, ws, p, in, conn, usages)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "client tool call ran but its cost lines were not recorded", "call", callRef(in), "error", err)
		return "", nil
	}
	if inserted < len(usages) && answer.Success {
		s.voidHold(ctx, b.holdID, "the call's line was already recorded")
	}
	return "", nil
}

// turnRun is the agent and effective policy of the run a runner's turn acts in; known is false
// for a run that is gone or was stored without one.
func (s *Service) turnRun(ctx context.Context, ws scope.Workspace, taskID string) (agentID string, policy api.Policy, known bool, err error) {
	var t store.RunnerTask
	err = s.readSession(ctx, ws, func(tx db.Session) error {
		var err error
		t, err = s.store.RunnerTask(ctx, tx, taskID)
		return err
	})
	if errors.Is(err, store.ErrTaskNotFound) {
		return "", api.Policy{}, false, nil
	}
	if err != nil {
		return "", api.Policy{}, false, err
	}
	raw, err := json.Marshal(t.Metadata["governance_snapshot"])
	if err != nil {
		return "", api.Policy{}, false, err
	}
	var snap struct {
		EffectivePolicy *api.Policy `json:"effective_policy"`
	}
	if err := json.Unmarshal(raw, &snap); err != nil || snap.EffectivePolicy == nil {
		return t.AgentID, api.Policy{}, false, nil
	}
	return t.AgentID, *snap.EffectivePolicy, true, nil
}

// runPolicyRefusal is why the run's policy refuses the call, as executeTool refuses it.
func runPolicyRefusal(in ToolCall) string {
	action, reason := domain.DecideToolPolicy(in.Policy, in.ToolName, toolNamesOf(in.Binding))
	switch {
	case action == domain.ToolDeny:
		return reason
	case action == domain.ToolRequireApproval && !in.PolicyApprovalGranted:
		return reason + "; the run's policy holds it for a person's approval"
	}
	return ""
}
