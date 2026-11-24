package workflows

import (
	"errors"
	"sort"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// AgentWorkflow registers AgentExecutionWorkflow.
func AgentWorkflow() durable.Workflow {
	return durable.Workflow{Name: api.WorkflowAgentExecution, Fn: AgentExecutionWorkflow}
}

// AgentExecutionWorkflow runs one agent task: initialize, the turn loop, finalize.
func AgentExecutionWorkflow(ctx workflow.Context, req AgentRunRequest) (AgentRunResult, error) {
	r := newAgentRun()
	info := workflow.GetInfo(ctx)
	r.ids = newIDs(info.WorkflowExecution.ID, info.WorkflowExecution.RunID)
	r.queue = info.TaskQueueName
	r.conversationSeeded = req.Resume != nil
	if err := r.registerHandlers(ctx); err != nil {
		return AgentRunResult{}, err
	}
	res, err := r.run(ctx, req)
	if err == nil {
		return res, nil
	}
	if _, can := errors.AsType[*workflow.ContinueAsNewError](err); can {
		return AgentRunResult{}, err
	}
	if isCancellation(err) || ctx.Err() != nil {
		r.finalizeCancellation(ctx)
		return AgentRunResult{}, err
	}
	r.handleWorkflowError(ctx, err)
	return AgentRunResult{}, err
}

func (r *agentRun) run(ctx workflow.Context, req AgentRunRequest) (AgentRunResult, error) {
	if err := r.initialize(ctx, req); err != nil {
		return AgentRunResult{}, err
	}
	if err := r.mainLoop(ctx); err != nil {
		return AgentRunResult{}, err
	}
	return r.finalize(ctx)
}

func (r *agentRun) registerHandlers(ctx workflow.Context) error {
	workflow.Go(ctx, func(ctx workflow.Context) {
		pause := workflow.GetSignalChannel(ctx, api.SignalPause)
		resume := workflow.GetSignalChannel(ctx, api.SignalResume)
		a2ui := workflow.GetSignalChannel(ctx, api.SignalA2UIAction)
		resolve := workflow.GetSignalChannel(ctx, api.SignalResolveEscalation)
		command := workflow.GetSignalChannel(ctx, api.SignalWorkflowCommand)
		runner := workflow.GetSignalChannel(ctx, api.SignalRunnerTurnUpdate)
		for {
			sel := workflow.NewSelector(ctx)
			sel.AddReceive(pause, func(c workflow.ReceiveChannel, _ bool) {
				var s api.PauseSignal
				c.Receive(ctx, &s)
				r.onPause(ctx, s.Reason)
			})
			sel.AddReceive(resume, func(c workflow.ReceiveChannel, _ bool) {
				var s api.PauseSignal
				c.Receive(ctx, &s)
				r.onResume(ctx, s.Reason)
			})
			sel.AddReceive(a2ui, func(c workflow.ReceiveChannel, _ bool) {
				var action map[string]any
				c.Receive(ctx, &action)
				r.onA2UIAction(ctx, action)
			})
			sel.AddReceive(resolve, func(c workflow.ReceiveChannel, _ bool) {
				var s api.ResolveEscalationSignal
				c.Receive(ctx, &s)
				r.onResolveEscalation(ctx, s)
			})
			sel.AddReceive(command, func(c workflow.ReceiveChannel, _ bool) {
				var s api.WorkflowCommandSignal
				c.Receive(ctx, &s)
				r.onCommand(ctx, s)
			})
			sel.AddReceive(runner, func(c workflow.ReceiveChannel, _ bool) {
				var u RunnerTurnUpdate
				c.Receive(ctx, &u)
				r.onRunnerUpdate(u)
			})
			sel.Select(ctx)
		}
	})
	if err := workflow.SetQueryHandler(ctx, api.QueryPendingEscalation, r.queryPendingEscalations); err != nil {
		return err
	}
	if err := workflow.SetQueryHandler(ctx, api.QueryCurrentState, r.queryCurrentState); err != nil {
		return err
	}
	return workflow.SetUpdateHandler(ctx, api.UpdateContinueExecution, r.onContinueExecution)
}

func (r *agentRun) onPause(ctx workflow.Context, reason string) {
	if reason == "" {
		reason = "Paused by user"
	}
	r.paused = true
	r.pauseReason = reason
	r.wakeWait = true
	if r.ids != nil && r.taskID != "" {
		r.emit(ctx, domain.EventExecutionPaused, map[string]any{"reason": reason, "iteration": r.iteration})
	}
}

func (r *agentRun) onResume(ctx workflow.Context, reason string) {
	if reason == "" {
		reason = "Resumed by user"
	}
	if r.waitingForOutage {
		r.retryOutageNow = true
		if !r.paused {
			return
		}
	}
	if !r.paused {
		return
	}
	r.paused = false
	r.pauseReason = ""
	if r.taskID != "" {
		r.emit(ctx, domain.EventExecutionResumed, map[string]any{"reason": reason, "iteration": r.iteration})
	}
}

func (r *agentRun) onA2UIAction(ctx workflow.Context, action map[string]any) {
	surfaceID, _ := action["surface_id"].(string)
	actions := r.a2uiSurfaces[surfaceID]
	name, _ := action["name"].(string)
	componentID, _ := action["source_component_id"].(string)
	known := false
	for _, v := range actions {
		if v == name {
			known = true
		}
	}
	if !r.a2uiAvailable() || !known || (componentID != "" && actions[componentID] != name) {
		return
	}
	if len(r.inputRequests) > 0 {
		for _, id := range r.inputOrder {
			pending := r.inputRequests[id]
			if pending == nil || pending.SurfaceID != surfaceID || pending.Resolved {
				continue
			}
			for _, q := range pending.Questions {
				if q["type"] == "secret" {
					return
				}
			}
			if context, ok := action["context"].(map[string]any); ok {
				answers := map[string]any{}
				for k, v := range context {
					answers[k] = v
				}
				for _, q := range pending.Questions {
					qid, _ := q["id"].(string)
					if list, isList := answers[qid].([]any); q["type"] == "select" && isList && len(list) == 1 {
						if s, isStr := list[0].(string); isStr {
							answers[qid] = s
						}
					}
				}
				r.submitUserInput(ctx, map[string]any{"input_request_id": id, "answers": answers})
			}
			return
		}
		return
	}
	if len(r.a2uiQueue) >= 50 {
		r.a2uiQueue = r.a2uiQueue[1:]
	}
	r.a2uiQueue = append(r.a2uiQueue, action)
}

func (r *agentRun) onResolveEscalation(ctx workflow.Context, s api.ResolveEscalationSignal) {
	esc, ok := r.escalations[s.EscalationID]
	if !ok {
		return
	}
	if !domain.CallerCanApprove(esc.Approvers, s.ResolvedBy) {
		workflow.GetLogger(ctx).Warn("unauthorized escalation resolution ignored", "escalation_id", s.EscalationID, "resolved_by", s.ResolvedBy)
		return
	}
	esc.Resolved = true
	esc.Approved = s.Approved
	esc.ApprovedBy = s.ResolvedBy
	esc.Comment = s.Comment
	if !s.Approved {
		esc.DenyComment = s.Comment
	}
}

func (r *agentRun) queryPendingEscalations() ([]api.PendingEscalationView, error) {
	out := []api.PendingEscalationView{}
	for _, id := range r.escalationOrder {
		e := r.escalations[id]
		if e == nil || e.Resolved {
			continue
		}
		out = append(out, api.PendingEscalationView{EscalationID: e.EscalationID, ToolName: e.ToolName, ToolCallID: e.ToolCallID, ToolArgs: e.ToolArgs, Approvers: e.Approvers})
	}
	return out, nil
}

func (r *agentRun) queryCurrentState() (map[string]any, error) {
	escalations := map[string]any{}
	for id, e := range r.escalations {
		escalations[id] = map[string]any{"tool_name": e.ToolName, "tool_call_id": e.ToolCallID, "resolved": e.Resolved}
	}
	inputs := map[string]any{}
	for id, p := range r.inputRequests {
		qs := p.Questions
		if qs == nil {
			qs = []map[string]any{}
		}
		inputs[id] = map[string]any{"resolved": p.Resolved, "questions": qs}
	}
	cost, remaining := "0", "0"
	if r.configuredBudget() {
		cost, remaining = r.cost.String(), r.remaining().String()
	}
	var context any
	if r.contextWindow > 0 {
		context = r.contextStatus()
	}
	return map[string]any{
		"status": r.status, "current_iteration": r.iteration, "success": r.success,
		"effective_policy": r.cfg.Policy, "cost": cost, "budget_remaining": remaining,
		"paused": r.paused, "pause_reason": r.pauseReason, "blocked_reason": nullable(r.blockedReason),
		"validation_state": r.validationState, "validation_repair_attempts": r.validationRepairs,
		"waiting_for_continuation": r.waitingContinuation, "continuation_failure_reason": nullable(r.continuationReason),
		"continuation_message": nullable(r.continuationMessage), "continuation_count": r.continuationCount,
		"waiting_for_infrastructure": r.waitingForOutage, "infrastructure_reason": nullable(r.outageReason),
		"pending_escalations": escalations, "pending_input_requests": inputs, "context": context,
	}, nil
}

func (r *agentRun) configuredBudget() bool { return r.budgetLimit.Sign() > 0 }

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// finalizeCancellation ends a stopped run under a disconnected context:
// pending decisions are denied, stopped calls answered, the status stored.
func (r *agentRun) finalizeCancellation(ctx workflow.Context) {
	dctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	r.inputRequests = map[string]*InputRequest{}
	r.inputOrder = nil
	for _, e := range r.escalations {
		if !e.Resolved {
			e.Resolved = true
			e.Approved = false
			e.DenyComment = "The run was stopped before a decision."
		}
	}
	r.awaitingInput = false
	r.status = StatusCancelled
	if !r.success {
		r.failureReason = "cancelled"
		r.errorMessage = "Task cancelled"
	}
	if r.taskID == "" || r.ids == nil {
		return
	}
	r.answerStoppedToolCalls()
	if _, err := r.finalize(dctx); err != nil {
		workflow.GetLogger(ctx).Error("finalizing a stopped run failed", "error", err)
	}
	r.stoppedToolCalls = nil
	r.stoppedModelCall = false
}

// finalize stores the run's outcome and its terminal events.
func (r *agentRun) finalize(ctx workflow.Context) (AgentRunResult, error) {
	cancelled := r.status == StatusCancelled
	settling := cancelled && (len(r.stoppedToolCalls) > 0 || r.stoppedModelCall)
	if (r.completionPublished || r.success) && r.finalResponse != "" && trimmed(r.finalResponse) != "" {
		r.status = StatusCompleted
		r.success = true
	} else {
		switch {
		case r.completionPublished || r.success:
			r.failureReason = "missing_final_response"
			r.errorMessage = "Task ended without a final response"
		case r.status == StatusBlocked:
			r.failureReason = firstNonEmpty(r.failureReason, "blocked")
			r.errorMessage = firstNonEmpty(r.errorMessage, r.blockedReason)
		case r.failureReason == "":
			r.failureReason = "task_unsuccessful"
			r.errorMessage = firstNonEmpty(r.errorMessage, "Task did not complete")
		}
		r.success = false
		if r.status != StatusBlocked && r.status != StatusCancelled {
			r.status = StatusFailed
		}
	}
	if !r.completionPublished {
		eventType := domain.EventTaskFailed
		switch {
		case r.status == StatusCancelled:
			eventType = domain.EventTaskCancelled
		case r.success:
			eventType = domain.EventTaskCompleted
		}
		data := map[string]any{
			"success": r.success, "iterations_completed": r.iteration, "total_cost": r.cost.String(),
			"tokens_used": r.tokensUsed, "final_response": nullable(r.finalResponse), "status": r.status,
			"failure_reason": nullable(r.failureReason), "error": nullable(r.errorMessage),
			"blocked_reason": nullable(r.blockedReason), "blocked": r.status == StatusBlocked,
			"validation_state": r.validationState,
		}
		if settling {
			data["execution_status"] = "settling"
		}
		r.emit(ctx, eventType, data)
		if err := r.publish(ctx); err != nil {
			return AgentRunResult{}, err
		}
	}
	final := StatusFailed
	switch {
	case r.success:
		final = StatusCompleted
	case r.status == StatusBlocked:
		final = StatusBlocked
	case r.status == StatusCancelled:
		final = StatusCancelled
	}
	r.keepQueuedMessages()
	var resume *ResumeSnapshot
	if final != StatusBlocked && !r.isDelegationChild() && r.resumable() {
		resume = r.resumeSnapshot(len(r.messages))
	}
	st := TaskStatus{
		Status: final, ValidationState: r.validationState, TotalCost: ptr(r.cost), OwnCost: ptr(r.ownCost()),
		TokensUsed: ptr(r.tokensUsed), Resume: resume,
	}
	if r.finalResponse != "" {
		st.Response = r.finalResponse
	}
	st.ErrorMessage = r.errorMessage
	if st.ErrorMessage == "" && final == StatusBlocked {
		st.ErrorMessage = r.blockedReason
	}
	if !r.success {
		st.FailureReason = r.failureReason
	}
	if err := r.persistStatus(ctx, st); err != nil {
		return AgentRunResult{}, err
	}
	if !settling {
		r.emit(ctx, domain.EventExecutionFinished, map[string]any{
			"status": r.status, "execution_status": map[bool]string{true: "cancelled", false: "completed"}[cancelled],
			"success": r.success, "final_response": nullable(r.finalResponse), "failure_reason": nullable(r.failureReason),
			"blocked": r.status == StatusBlocked, "blocked_reason": nullable(r.blockedReason),
		})
		if err := r.publish(ctx); err != nil {
			return AgentRunResult{}, err
		}
	}
	return AgentRunResult{
		TaskID: r.taskID, AgentID: r.principal.AgentID, Success: r.success, Status: r.status,
		ValidationState: r.validationState, FinalResponse: r.finalResponse, FailureReason: r.failureReason,
		ErrorMessage: r.errorMessage, TotalCost: r.cost, ReasoningIterations: r.iteration, TotalToolCalls: r.toolCallsUsed,
	}, nil
}

// handleWorkflowError records task.failed and the failed (or blocked) status.
func (r *agentRun) handleWorkflowError(ctx workflow.Context, cause error) {
	if r.ids == nil || r.taskID == "" {
		return
	}
	dctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	blocked := r.status == StatusBlocked
	data := map[string]any{
		"error": userFacingError(cause), "error_type": userFacingErrorType(cause),
		"failure_reason": nullable(failureCause(cause)), "error_detail": errorDetail(cause),
		"iterations_completed": r.iteration, "total_cost": r.cost.String(), "tokens_used": r.tokensUsed,
		"status": r.status, "blocked_reason": nullable(r.blockedReason),
	}
	if blocked {
		data["blocked"] = true
		data["retryable"] = false
	}
	r.emit(dctx, domain.EventTaskFailed, data)
	if err := r.publish(dctx); err != nil {
		workflow.GetLogger(ctx).Error("recording task.failed failed", "error", err)
	}
	status := StatusFailed
	if blocked {
		status = StatusBlocked
	}
	var resume *ResumeSnapshot
	if status == StatusFailed && !r.isDelegationChild() {
		r.answerUnansweredToolCalls("Not executed: the run failed before this call ran.")
		r.keepQueuedMessages()
		if r.resumable() {
			resume = r.resumeSnapshot(len(r.messages))
		}
	} else {
		r.keepQueuedMessages()
	}
	st := TaskStatus{
		Status: status, ErrorMessage: firstNonEmpty(r.blockedReason, extractErrorDetails(cause)),
		FailureReason: firstNonEmpty(failureCause(cause), r.failureReason), TokensUsed: ptr(r.tokensUsed), Resume: resume,
	}
	if r.configuredBudget() {
		st.TotalCost, st.OwnCost = ptr(r.cost), ptr(r.ownCost())
	}
	if err := r.persistStatus(dctx, st); err != nil {
		workflow.GetLogger(ctx).Error("recording the failed status failed", "error", err)
	}
}

func trimmed(s string) string {
	for len(s) > 0 && (s[0] == ' ' || s[0] == '\n' || s[0] == '\t' || s[0] == '\r') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == ' ' || s[len(s)-1] == '\n' || s[len(s)-1] == '\t' || s[len(s)-1] == '\r') {
		s = s[:len(s)-1]
	}
	return s
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func appErr(err error) *temporal.ApplicationError {
	a, _ := errors.AsType[*temporal.ApplicationError](err)
	return a
}
