package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

var _ api.ClientToolCalls = (*Service)(nil)

// RunClientCall is run_tool_call past the policy for a call outside a run (/mcp/clients,
// /v1/mcp/{id}): priced, held and capped like a run's call, its lines carry the client and no task.
func (s *Service) RunClientCall(ctx context.Context, ws scope.Workspace, call api.ClientToolCall, h api.ClientCallHooks) (string, error) {
	p := Principal{WorkspaceID: ws.ID(), UserID: call.UserID}
	in := ToolCall{ToolName: call.ToolName, Args: call.Args, Binding: call.Binding, ToolCallID: uuid.NewString(), ClientID: call.ClientID}
	conn, refusal, err := s.callConnection(ctx, ws, in)
	if err != nil {
		return "", err
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
