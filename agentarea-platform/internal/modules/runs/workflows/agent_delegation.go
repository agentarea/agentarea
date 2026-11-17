package workflows

import (
	"errors"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// delegateAll starts every delegation of a turn at once, each with an equal
// share of what the run has left.
func (r *agentRun) delegateAll(ctx workflow.Context, calls []ToolCall) error {
	remaining := r.remaining()
	if remaining.Sign() <= 0 {
		return nonRetryable("no inference budget remains for agent delegation", ErrBudgetExceeded)
	}
	share := divInt(remaining, len(calls))
	if len(calls) == 1 {
		return r.delegate(ctx, calls[0], share)
	}
	wg := workflow.NewWaitGroup(ctx)
	errs := make([]error, len(calls))
	for i, c := range calls {
		wg.Add(1)
		workflow.Go(ctx, func(ctx workflow.Context) {
			defer wg.Done()
			errs[i] = r.delegate(ctx, c, share)
		})
	}
	wg.Wait(ctx)
	for _, err := range errs {
		if err != nil {
			return err
		}
	}
	return nil
}

func childStoppedAlone(ctx workflow.Context, err error) bool {
	_, child := errors.AsType[*temporal.ChildWorkflowExecutionError](err)
	return child && temporal.IsCanceledError(err) && ctx.Err() == nil
}

// delegate runs another agent as a child workflow and hands its answer back.
func (r *agentRun) delegate(ctx workflow.Context, c ToolCall, budget money.Decimal) error {
	allowed, _, err := r.gate(ctx, c)
	if err != nil || !allowed {
		return err
	}
	target := r.cfg.Delegates[c.Name]
	message, _ := parseArgs(c)["message"].(string)
	r.emit(ctx, domain.EventDelegationStarted, map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "target_agent_id": target.AgentID, "target_agent_name": target.AgentName,
		"iteration": r.iteration, "message": truncateRunes(message, 200),
	})
	if err := r.publish(ctx); err != nil {
		return err
	}
	childID := "delegation-" + r.executionID + "-" + c.ID
	childTaskID := ""
	res, err := r.runChild(ctx, c, target, message, budget, childID, &childTaskID)
	if err == nil {
		envelope := domain.Ordered{{Key: "status", Value: "completed"}, {Key: "agent", Value: target.AgentName}, {Key: "task_id", Value: childTaskID}}
		if res.Success {
			envelope = append(envelope, domain.KV{Key: "final_response", Value: firstNonEmpty(res.FinalResponse, "(Agent completed without response)")})
		} else {
			envelope[0].Value = "failed"
			envelope = append(envelope, domain.KV{Key: "error", Value: firstNonEmpty(res.ErrorMessage, "(Agent failed without details)")})
		}
		envelope = append(envelope, domain.KV{Key: "iterations", Value: res.ReasoningIterations}, domain.KV{Key: "cost_usd", Value: floatOf(res.TotalCost)})
		r.toolMessage(c, domain.PyDumps(envelope))
		r.emit(ctx, domain.EventDelegationCompleted, map[string]any{
			"tool_name": c.Name, "tool_call_id": c.ID, "target_agent_id": target.AgentID, "target_agent_name": target.AgentName,
			"child_task_id": childTaskID, "success": res.Success, "iteration": r.iteration,
			"child_iterations": res.ReasoningIterations, "child_cost": floatOf(res.TotalCost),
		})
		if perr := r.publish(ctx); perr != nil {
			return perr
		}
		if res.TotalCost.Sign() > 0 {
			r.delegatedCost = r.delegatedCost.Add(res.TotalCost)
			r.cost = r.cost.Add(res.TotalCost)
		}
		return nil
	}
	alone := childStoppedAlone(ctx, err)
	if (isCancellation(err) || ctx.Err() != nil) && !alone {
		var reserved *money.Decimal
		if childTaskID != "" {
			reserved = &budget
		}
		r.recordStoppedDelegation(ctx, c, target, childTaskID, reserved)
		return err
	}
	if childTaskID != "" {
		spent := budget
		if alone {
			var s DelegatedSpendResult
			req := DelegatedSpendRequest{Principal: r.principal, TaskID: childTaskID}
			if serr := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityDelegatedTaskSpend, "", 0), api.ActivityDelegatedTaskSpend, req).Get(ctx, &s); serr != nil {
				return serr
			}
			spent = s.Spent
		}
		r.delegatedCost = r.delegatedCost.Add(spent)
		r.cost = r.cost.Add(spent)
	}
	text, status := failureText(err), "failed"
	if alone {
		text, status = "The delegated agent's run was stopped by a person before it finished.", "cancelled"
	}
	r.toolMessage(c, domain.PyDumps(domain.Ordered{{Key: "status", Value: status}, {Key: "agent", Value: target.AgentName}, {Key: "error", Value: text}}))
	data := map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "target_agent_id": target.AgentID, "target_agent_name": target.AgentName,
		"error": text, "iteration": r.iteration,
	}
	if alone {
		data["cancelled"] = true
	}
	r.emit(ctx, domain.EventDelegationFailed, data)
	return r.publish(ctx)
}

func (r *agentRun) runChild(ctx workflow.Context, c ToolCall, target api.Delegate, message string, budget money.Decimal, childID string, childTaskID *string) (AgentRunResult, error) {
	req := CreateDelegationTaskRequest{
		Principal: r.principal, ParentTaskID: r.taskID, TargetAgentID: target.AgentID, TargetAgentName: target.AgentName,
		Message: message, ParentPolicy: r.cfg.Policy, RunBudget: &budget, ExecutionID: childID,
	}
	var created CreateDelegationTaskResult
	if err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityCreateDelegationTask, "", 0), api.ActivityCreateDelegationTask, req).Get(ctx, &created); err != nil {
		return AgentRunResult{}, err
	}
	if created.Status != "created" || created.TaskID == "" {
		return AgentRunResult{}, temporal.NewApplicationError("Failed to create delegation task: "+created.Error, "ApplicationError")
	}
	*childTaskID = created.TaskID
	child := AgentRunRequest{
		TaskID: created.TaskID, AgentID: target.AgentID, UserID: r.principal.UserID, WorkspaceID: r.principal.WorkspaceID,
		TaskQuery: message, Policy: created.Policy,
		WorkflowMetadata: map[string]any{
			"source": "agent_delegation", "parent_execution_id": r.executionID,
			"parent_agent_id": r.principal.AgentID, "parent_task_id": r.taskID,
		},
	}
	cctx := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{
		WorkflowID: childID, TaskQueue: r.queue, WorkflowExecutionTimeout: delegationTimeout,
		ParentClosePolicy: enumspb.PARENT_CLOSE_POLICY_TERMINATE, WaitForCancellation: true,
	})
	var res AgentRunResult
	err := workflow.ExecuteChildWorkflow(cctx, api.WorkflowAgentExecution, child).Get(ctx, &res)
	return res, err
}

func (r *agentRun) recordStoppedDelegation(ctx workflow.Context, c ToolCall, target api.Delegate, childTaskID string, reserved *money.Decimal) {
	const stopped = "Stopped by the user while the delegated agent was running."
	r.toolMessage(c, domain.PyDumps(domain.Ordered{
		{Key: "status", Value: "cancelled"}, {Key: "agent", Value: target.AgentName},
		{Key: "task_id", Value: nullable(childTaskID)}, {Key: "error", Value: stopped},
	}))
	var reservedText any
	if reserved != nil {
		r.delegatedCost = r.delegatedCost.Add(*reserved)
		r.cost = r.cost.Add(*reserved)
		reservedText = reserved.String()
	}
	r.emit(ctx, domain.EventDelegationFailed, map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "target_agent_id": target.AgentID, "target_agent_name": target.AgentName,
		"child_task_id": nullable(childTaskID), "cancelled": true, "error": stopped, "reserved_cost": reservedText, "iteration": r.iteration,
	})
}
