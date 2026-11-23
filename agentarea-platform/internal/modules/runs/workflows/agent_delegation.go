package workflows

import (
	"errors"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

const delegationStopped = "Stopped by the user while the delegated agent was running."

// delegation is one call handed to another agent: a local one runs as a child run, a
// remote one as a RemoteDelegationWorkflow.
type delegation struct {
	call    ToolCall
	message string
	local   *api.Delegate
	budget  money.Decimal
	remote  *api.RemoteAgentBinding
	req     ToolCallRequest

	childTaskID string
	res         AgentRunResult
	answer      RemoteDelegationResult
	err         error
	// content is the call's tool message once it settled.
	content string
	settled bool
}

func (r *agentRun) delegates(c ToolCall) bool {
	_, local := r.cfg.Delegates[c.Name]
	return local || r.cfg.Bindings[c.Name].Source == "remote_agent"
}

// delegateAll starts every delegation of a turn at once, each local one with an equal
// share of what the run has left, and answers them in the order they were made. Each
// result is announced as it arrives; only a stop or a failure to record ends the turn.
func (r *agentRun) delegateAll(ctx workflow.Context, calls []ToolCall) error {
	local := 0
	for _, c := range calls {
		if _, ok := r.cfg.Delegates[c.Name]; ok {
			local++
		}
	}
	var share money.Decimal
	if local > 0 {
		remaining := r.remaining()
		if remaining.Sign() <= 0 {
			return nonRetryable("no inference budget remains for agent delegation", ErrBudgetExceeded)
		}
		share = divInt(remaining, local)
	}
	var ds []*delegation
	for _, c := range calls {
		d, err := r.startDelegation(ctx, c, share)
		if err != nil {
			return err
		}
		if d != nil {
			ds = append(ds, d)
		}
	}
	if err := r.publish(ctx); err != nil || len(ds) == 0 {
		return err
	}
	finished := workflow.NewBufferedChannel(ctx, len(ds))
	for i, d := range ds {
		workflow.Go(ctx, func(ctx workflow.Context) {
			r.runDelegation(ctx, d)
			finished.Send(ctx, i)
		})
	}
	var first error
	answered := 0
	for range ds {
		var i int
		finished.Receive(ctx, &i)
		if err := r.settleDelegation(ctx, ds[i]); err != nil && first == nil {
			first = err
		}
		for ; answered < len(ds) && ds[answered].settled; answered++ {
			r.toolMessage(ds[answered].call, ds[answered].content)
		}
		if first == nil && ctx.Err() == nil {
			first = r.publish(ctx)
		}
	}
	return first
}

// startDelegation gates a call and announces it; nil when the gate refused it.
func (r *agentRun) startDelegation(ctx workflow.Context, c ToolCall, share money.Decimal) (*delegation, error) {
	allowed, granted, err := r.gate(ctx, c)
	if err != nil || !allowed {
		return nil, err
	}
	args := parseArgs(c)
	message, _ := args["message"].(string)
	d := &delegation{call: c, message: message}
	data := map[string]any{"tool_name": c.Name, "tool_call_id": c.ID, "iteration": r.iteration, "message": truncateRunes(message, 200)}
	if target, ok := r.cfg.Delegates[c.Name]; ok {
		d.local, d.budget = &target, share
		data["target_agent_id"], data["target_agent_name"] = target.AgentID, target.AgentName
	} else {
		b := r.cfg.Bindings[c.Name]
		d.remote = b.RemoteAgent
		if d.remote == nil {
			d.remote = &api.RemoteAgentBinding{}
		}
		d.req = ToolCallRequest{
			Principal: r.principal, TaskID: r.taskID, ExecutionID: r.executionID, ToolCallID: c.ID, ToolName: c.Name,
			Args: args, Binding: b, Policy: r.cfg.Policy, Counters: r.counters(), RunMetadata: r.metadata, PolicyApprovalGranted: granted,
		}
		data["target_agent_id"], data["target_agent_name"], data["remote"] = nil, d.remote.AgentName, true
	}
	r.emit(ctx, domain.EventDelegationStarted, data)
	return d, nil
}

func (r *agentRun) childOptions(ctx workflow.Context, id string) workflow.Context {
	return workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{
		WorkflowID: id, TaskQueue: r.queue, WorkflowExecutionTimeout: delegationTimeout,
		ParentClosePolicy: enumspb.PARENT_CLOSE_POLICY_TERMINATE, WaitForCancellation: true,
	})
}

// runDelegation waits for the delegated agent; it touches nothing the turn records.
func (r *agentRun) runDelegation(ctx workflow.Context, d *delegation) {
	c := d.call
	if d.local != nil {
		d.res, d.err = r.runChild(ctx, c, *d.local, d.message, d.budget, "delegation-"+r.executionID+"-"+c.ID, &d.childTaskID)
		return
	}
	req := RemoteDelegationRequest{Call: d.req, Deadline: r.remoteDeadline(ctx)}
	cctx := r.childOptions(ctx, "remote-delegation-"+r.executionID+"-"+c.ID)
	d.err = workflow.ExecuteChildWorkflow(cctx, api.WorkflowRemoteDelegation, req).Get(ctx, &d.answer)
}

// remoteDeadline is when a remote call stops waiting: the delegation limit, or sooner the
// last moment the run can still record its own end.
func (r *agentRun) remoteDeadline(ctx workflow.Context) time.Time {
	end := workflow.Now(ctx).UTC().Add(delegationTimeout - remoteDeadlineMargin)
	if hc := r.hardCap(ctx); hc != nil && hc.Before(end) {
		end = *hc
	}
	return end
}

func childStoppedAlone(ctx workflow.Context, err error) bool {
	_, child := errors.AsType[*temporal.ChildWorkflowExecutionError](err)
	return child && temporal.IsCanceledError(err) && ctx.Err() == nil
}

func (d *delegation) settle(content domain.Ordered) {
	d.content, d.settled = domain.PyDumps(content), true
}

func (r *agentRun) settleDelegation(ctx workflow.Context, d *delegation) error {
	if d.local != nil {
		return r.settleLocal(ctx, d)
	}
	return r.settleRemote(ctx, d)
}

// settleLocal hands back a local delegate's answer.
func (r *agentRun) settleLocal(ctx workflow.Context, d *delegation) error {
	c, target, res, err := d.call, *d.local, d.res, d.err
	if err == nil {
		envelope := domain.Ordered{{Key: "status", Value: "completed"}, {Key: "agent", Value: target.AgentName}, {Key: "task_id", Value: d.childTaskID}}
		if res.Success {
			envelope = append(envelope, domain.KV{Key: "final_response", Value: firstNonEmpty(res.FinalResponse, "(Agent completed without response)")})
		} else {
			envelope[0].Value = "failed"
			envelope = append(envelope, domain.KV{Key: "error", Value: firstNonEmpty(res.ErrorMessage, "(Agent failed without details)")})
		}
		envelope = append(envelope, domain.KV{Key: "iterations", Value: res.ReasoningIterations}, domain.KV{Key: "cost_usd", Value: floatOf(res.TotalCost)})
		d.settle(envelope)
		r.emit(ctx, domain.EventDelegationCompleted, map[string]any{
			"tool_name": c.Name, "tool_call_id": c.ID, "target_agent_id": target.AgentID, "target_agent_name": target.AgentName,
			"child_task_id": d.childTaskID, "success": res.Success, "iteration": r.iteration,
			"child_iterations": res.ReasoningIterations, "child_cost": floatOf(res.TotalCost),
		})
		if res.TotalCost.Sign() > 0 {
			r.delegatedCost = r.delegatedCost.Add(res.TotalCost)
			r.cost = r.cost.Add(res.TotalCost)
		}
		return nil
	}
	alone := childStoppedAlone(ctx, err)
	if (isCancellation(err) || ctx.Err() != nil) && !alone {
		var reserved *money.Decimal
		if d.childTaskID != "" {
			reserved = &d.budget
		}
		r.recordStoppedDelegation(ctx, d, target, reserved)
		return err
	}
	if d.childTaskID != "" {
		spent := d.budget
		if alone {
			var s DelegatedSpendResult
			req := DelegatedSpendRequest{Principal: r.principal, TaskID: d.childTaskID}
			if serr := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityDelegatedTaskSpend, "", 0), api.ActivityDelegatedTaskSpend, req).Get(ctx, &s); serr != nil {
				d.settle(domain.Ordered{{Key: "status", Value: "failed"}, {Key: "agent", Value: target.AgentName}, {Key: "error", Value: failureText(serr)}})
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
	d.settle(domain.Ordered{{Key: "status", Value: status}, {Key: "agent", Value: target.AgentName}, {Key: "error", Value: text}})
	data := map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "target_agent_id": target.AgentID, "target_agent_name": target.AgentName,
		"error": text, "iteration": r.iteration,
	}
	if alone {
		data["cancelled"] = true
	}
	r.emit(ctx, domain.EventDelegationFailed, data)
	return nil
}

// settleRemote hands back a remote delegate's answer, and charges what its send cost.
func (r *agentRun) settleRemote(ctx workflow.Context, d *delegation) error {
	c, name := d.call, d.remote.AgentName
	data := map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "target_agent_id": nil, "target_agent_name": name, "remote": true, "iteration": r.iteration,
	}
	if d.err == nil {
		a := d.answer.Answer
		r.chargeTool(a)
		if a.ServiceCost.Sign() > 0 {
			r.serviceCostUsed = r.serviceCostUsed.Add(a.ServiceCost)
			r.enforceAgentSpendCap()
		}
		envelope := domain.Ordered{{Key: "status", Value: "completed"}, {Key: "agent", Value: name}, {Key: "task_id", Value: nullable(d.answer.TaskID)}}
		if a.Success {
			envelope = append(envelope, domain.KV{Key: "final_response", Value: firstNonEmpty(a.Result, "(Agent completed without response)")})
		} else {
			envelope[0].Value = "failed"
			envelope = append(envelope, domain.KV{Key: "error", Value: firstNonEmpty(a.Error, a.Result, "(Agent failed without details)")})
		}
		d.settle(envelope)
		mergeInto(data, map[string]any{
			"remote_task_id": nullable(d.answer.TaskID), "success": a.Success, "execution_time": a.Duration.Seconds(),
			"service_cost": a.ServiceCost.String(), "payment": paymentValue(a.Payments),
		})
		r.emit(ctx, domain.EventDelegationCompleted, data)
		return nil
	}
	alone := childStoppedAlone(ctx, d.err)
	if (isCancellation(d.err) || ctx.Err() != nil) && !alone {
		d.settle(domain.Ordered{{Key: "status", Value: "cancelled"}, {Key: "agent", Value: name}, {Key: "task_id", Value: nil}, {Key: "error", Value: delegationStopped}})
		mergeInto(data, map[string]any{"cancelled": true, "error": delegationStopped})
		r.emit(ctx, domain.EventDelegationFailed, data)
		return d.err
	}
	text, status := failureText(d.err), "failed"
	if alone {
		text, status = "The remote delegation was stopped by a person before it finished.", "cancelled"
		data["cancelled"] = true
	}
	d.settle(domain.Ordered{{Key: "status", Value: status}, {Key: "agent", Value: name}, {Key: "error", Value: text}})
	data["error"] = text
	r.emit(ctx, domain.EventDelegationFailed, data)
	return nil
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
	var res AgentRunResult
	err := workflow.ExecuteChildWorkflow(r.childOptions(ctx, childID), api.WorkflowAgentExecution, child).Get(ctx, &res)
	return res, err
}

func (r *agentRun) recordStoppedDelegation(ctx workflow.Context, d *delegation, target api.Delegate, reserved *money.Decimal) {
	d.settle(domain.Ordered{
		{Key: "status", Value: "cancelled"}, {Key: "agent", Value: target.AgentName},
		{Key: "task_id", Value: nullable(d.childTaskID)}, {Key: "error", Value: delegationStopped},
	})
	var reservedText any
	if reserved != nil {
		r.delegatedCost = r.delegatedCost.Add(*reserved)
		r.cost = r.cost.Add(*reserved)
		reservedText = reserved.String()
	}
	r.emit(ctx, domain.EventDelegationFailed, map[string]any{
		"tool_name": d.call.Name, "tool_call_id": d.call.ID, "target_agent_id": target.AgentID, "target_agent_name": target.AgentName,
		"child_task_id": nullable(d.childTaskID), "cancelled": true, "error": delegationStopped, "reserved_cost": reservedText, "iteration": r.iteration,
	})
}
