package workflows

import (
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// Runner turns (runner_turn.py): a run of an agent on a client calls no model
// and no tool itself; each turn is one run_runner_turn_activity on the
// client's own queue.
const (
	runnerClientKey     = "runner_client_id"
	runnerLostType      = "RunnerLost"
	runnerResumeMessage = "You were paused. Continue from where you stopped."
	runnerRetryMessage  = "Your last turn ended before it finished. Do it again from where you stopped."
	runnerMaxAttempts   = 5
	runnerRetryDelay    = 5 * time.Second
	runnerStartTimeout  = 10 * time.Minute
	runnerTurnTimeout   = 12 * time.Hour
)

type runnerAsk struct{ escalationID, requestID string }

type runnerTool struct{ itemID, name string }

// runnerState is what the run keeps about its turns on a client's runner.
type runnerState struct {
	on           bool
	clientID     string
	turnKey      string
	actor        *RunnerActor
	updates      []RunnerTurnUpdate
	lastSeq      int64
	steering     []QueuedMessage
	heldBack     []QueuedMessage
	asks         []runnerAsk
	seenAsks     map[string]bool
	openTools    []runnerTool
	pausing      bool
	retryMessage *string
}

func (r *agentRun) adoptRunner() {
	v, ok := r.metadata[runnerClientKey]
	if !ok || v == nil {
		return
	}
	r.runner.on = true
	if s, isStr := v.(string); isStr {
		r.runner.clientID = s
	} else {
		r.runner.clientID = fmt.Sprint(v)
	}
}

func (r *agentRun) onRunnerUpdate(u RunnerTurnUpdate) {
	if r.runner.turnKey != "" && u.TurnKey == r.runner.turnKey {
		r.runner.updates = append(r.runner.updates, u)
	}
}

func senderActor(queued []QueuedMessage, fallback *RunnerActor) *RunnerActor {
	for i := len(queued) - 1; i >= 0; i-- {
		if s := queued[i].Sender; len(s) > 0 {
			return &RunnerActor{Type: s["type"], ID: s["id"]}
		}
	}
	return fallback
}

func joinContents(queued []QueuedMessage) string {
	parts := make([]string, len(queued))
	for i, m := range queued {
		parts[i] = m.Content
	}
	return strings.Join(parts, "\n\n")
}

// executeRunnerTurn sends the turn's message to the runner and waits for the CLI to answer it.
func (r *agentRun) executeRunnerTurn(ctx workflow.Context) error {
	queued := slices.Concat(r.runner.heldBack, r.messageQueue)
	r.runner.heldBack = nil
	r.messageQueue = nil
	if !r.conversationSeeded {
		if r.goal == nil {
			return nonRetryable("workflow goal is missing from execution state", ErrInvalidExecutionSnapshot)
		}
		queued = slices.Insert(queued, 0, QueuedMessage{ID: r.ids.uuid(), Content: r.goal.Description})
		r.conversationSeeded = true
	}
	if len(queued) == 0 && r.runner.retryMessage != nil {
		text := *r.runner.retryMessage
		r.runner.retryMessage = nil
		res, err := r.runRunnerTurn(ctx, text, nil)
		if err != nil {
			return err
		}
		return r.endRunnerTurn(ctx, res)
	}
	if len(queued) == 0 {
		return nonRetryable("A turn on a runner has no message to send; send the task a message instead", "RunnerTurnWithoutMessage")
	}
	for _, m := range queued {
		r.messages = append(r.messages, Message{Role: "user", Content: m.Content})
	}
	res, err := r.runRunnerTurn(ctx, joinContents(queued), senderActor(queued, nil))
	if err != nil {
		return err
	}
	return r.endRunnerTurn(ctx, res)
}

func (r *agentRun) endRunnerTurn(ctx workflow.Context, res RunnerTurnResult) error {
	r.settleRunnerTurn()
	if res.Status == "completed" {
		return r.completeRunnerTurn(ctx, res.Response)
	}
	fallback := "the CLI failed without saying why"
	if res.Status == "interrupted" {
		fallback = "The CLI's turn was interrupted"
	}
	return nonRetryable(firstNonEmpty(res.Error, fallback), "RunnerTurnFailed")
}

// runRunnerTurn is the turn's activity, scheduled again whenever its runner is lost.
func (r *agentRun) runRunnerTurn(ctx workflow.Context, text string, actor *RunnerActor) (RunnerTurnResult, error) {
	attempt := 0
	for {
		attempt++
		r.runner.turnKey = fmt.Sprintf("%d.%d", r.iteration, attempt)
		r.runner.lastSeq = 0
		r.runner.updates = nil
		r.runner.seenAsks = map[string]bool{}
		if err := r.publish(ctx); err != nil {
			return RunnerTurnResult{}, err
		}
		req := RunnerTurnRequest{
			TaskID: r.taskID, AgentID: r.principal.AgentID, WorkspaceID: r.principal.WorkspaceID,
			Iteration: r.iteration, TurnKey: r.runner.turnKey, Message: text, Actor: actor,
		}
		actx, cancel := workflow.WithCancel(ctx)
		fut := workflow.ExecuteActivity(activityCtx(actx, api.ActivityRunRunnerTurn, api.RunnerTaskQueue(r.runner.clientID), 0), api.ActivityRunRunnerTurn, req)
		var loopErr error
		for !fut.IsReady() {
			if loopErr = workflow.Await(ctx, func() bool { return fut.IsReady() || r.runnerHasWork() }); loopErr != nil {
				break
			}
			if loopErr = r.serveRunnerTurn(ctx, true); loopErr != nil {
				break
			}
		}
		if loopErr != nil {
			r.leaveRunnerTurn(ctx, cancel, fut, loopErr)
			return RunnerTurnResult{}, loopErr
		}
		var res RunnerTurnResult
		if err := fut.Get(ctx, &res); err != nil {
			if isCancellation(err) || ctx.Err() != nil {
				r.leaveRunnerTurn(ctx, cancel, fut, err)
				return RunnerTurnResult{}, err
			}
			lost := runnerLost(err)
			if serr := r.serveRunnerTurn(ctx, false); serr != nil {
				return RunnerTurnResult{}, serr
			}
			closing, expiring := "The turn ended before it finished.", "The turn ended before a decision."
			if lost {
				closing, expiring = "The runner was lost before it finished.", "The runner was lost before a decision."
			}
			if cerr := r.closeOpenRunnerTools(ctx, closing); cerr != nil {
				return RunnerTurnResult{}, cerr
			}
			if eerr := r.expireRunnerEscalations(ctx, expiring); eerr != nil {
				return RunnerTurnResult{}, eerr
			}
			if !lost {
				if reason := runnerTurnError(err); reason != nil {
					return RunnerTurnResult{}, reason
				}
				return RunnerTurnResult{}, err
			}
			if attempt >= runnerMaxAttempts {
				return RunnerTurnResult{}, nonRetryable(fmt.Sprintf("The runner was lost %d times during this turn", attempt), "RunnerTurnLost")
			}
			workflow.GetLogger(ctx).Warn("runner of the turn was lost; assigning it again", "turn_key", r.runner.turnKey)
			r.runner.heldBack = append(r.runner.heldBack, r.runner.steering...)
			r.runner.steering = nil
			if serr := workflow.Sleep(ctx, runnerRetryDelay); serr != nil {
				return RunnerTurnResult{}, serr
			}
			continue
		}
		if err := r.serveRunnerTurn(ctx, false); err != nil {
			return RunnerTurnResult{}, err
		}
		paused := r.runner.pausing && res.Status == "interrupted"
		r.runner.pausing = false
		closing, expiring := "The turn ended before it finished.", "The turn ended before a decision."
		switch {
		case paused:
			closing, expiring = "Paused before it finished.", "The run was paused before a decision."
		case res.Status == "interrupted":
			closing = "Stopped before it finished."
		}
		if err := r.closeOpenRunnerTools(ctx, closing); err != nil {
			return RunnerTurnResult{}, err
		}
		if err := r.expireRunnerEscalations(ctx, expiring); err != nil {
			return RunnerTurnResult{}, err
		}
		if !paused {
			r.runner.turnKey = ""
			return res, nil
		}
		if err := workflow.Await(ctx, func() bool { return !r.paused }); err != nil {
			return RunnerTurnResult{}, err
		}
		text, actor = r.runnerResumedTurn(actor)
	}
}

// leaveRunnerTurn: the run leaves a turn the CLI still works on; the
// activity stops the CLI's turn. On a stop, what the runner reported until
// then is recorded before the run closes.
func (r *agentRun) leaveRunnerTurn(ctx workflow.Context, cancel workflow.CancelFunc, fut workflow.Future, cause error) {
	cancel()
	dctx, _ := workflow.NewDisconnectedContext(ctx)
	if err := fut.Get(dctx, nil); err != nil && !isCancellation(err) {
		workflow.GetLogger(ctx).Warn("runner turn ended with an error while it was stopped", "turn_key", r.runner.turnKey, "error", err)
	}
	if isCancellation(cause) || ctx.Err() != nil {
		if err := r.serveRunnerTurn(dctx, false); err != nil {
			workflow.GetLogger(ctx).Warn("runner turn reports could not be recorded", "error", err)
		}
		if err := r.closeOpenRunnerTools(dctx, "Stopped before it finished."); err != nil {
			workflow.GetLogger(ctx).Warn("open runner tools could not be closed", "error", err)
		}
	}
	r.runner.turnKey = ""
	r.runner.updates = nil
}

func runnerLost(err error) bool {
	if t, ok := errors.AsType[*temporal.TimeoutError](err); ok {
		return t.TimeoutType() == enumspb.TIMEOUT_TYPE_HEARTBEAT
	}
	return appErrorType(err) == runnerLostType
}

// runnerTurnError is why a turn timed out, in words a person can act on.
func runnerTurnError(err error) error {
	t, ok := errors.AsType[*temporal.TimeoutError](err)
	if !ok {
		return nil
	}
	switch t.TimeoutType() {
	case enumspb.TIMEOUT_TYPE_SCHEDULE_TO_START:
		return nonRetryable(fmt.Sprintf("No runner of the agent's client took the turn within %d minutes; "+
			"start the client's runner and send the task a message", int(runnerStartTimeout.Minutes())), "RunnerOffline")
	case enumspb.TIMEOUT_TYPE_START_TO_CLOSE:
		return nonRetryable(fmt.Sprintf("The CLI's turn ran longer than %d hours", int(runnerTurnTimeout.Hours())), "RunnerTurnTimedOut")
	case enumspb.TIMEOUT_TYPE_UNSPECIFIED, enumspb.TIMEOUT_TYPE_SCHEDULE_TO_CLOSE, enumspb.TIMEOUT_TYPE_HEARTBEAT:
		return nil
	default:
		return nil
	}
}

func (r *agentRun) runnerHasWork() bool {
	if r.runner.pausing {
		return len(r.runner.updates) > 0
	}
	answered := false
	for _, a := range r.runner.asks {
		if e := r.escalations[a.escalationID]; e != nil && e.Resolved {
			answered = true
			break
		}
	}
	return len(r.runner.updates) > 0 || len(r.messageQueue) > 0 || answered || r.paused
}

// runnerResumedTurn is what the turn after a resume sends: the messages since the pause, else a nudge.
func (r *agentRun) runnerResumedTurn(actor *RunnerActor) (string, *RunnerActor) {
	queued := slices.Concat(r.runner.heldBack, r.runner.steering, r.messageQueue)
	r.runner.heldBack, r.runner.steering, r.messageQueue = nil, nil, nil
	if len(queued) == 0 {
		return runnerResumeMessage, actor
	}
	for _, m := range queued {
		r.messages = append(r.messages, Message{Role: "user", Content: m.Content})
	}
	return joinContents(queued), senderActor(queued, actor)
}

// serveRunnerTurn records what the runner reported, and sends it the messages and answers since.
func (r *agentRun) serveRunnerTurn(ctx workflow.Context, deliver bool) error {
	updates := r.runner.updates
	r.runner.updates = nil
	for _, u := range updates {
		if u.TurnKey != r.runner.turnKey {
			continue
		}
		if u.Actor != nil {
			r.runner.actor = u.Actor
		}
		for _, e := range u.Events {
			if e.Seq <= r.runner.lastSeq {
				continue
			}
			r.runner.lastSeq = e.Seq
			r.recordRunnerEvent(ctx, e)
		}
		for _, ask := range u.Approvals {
			if err := r.openRunnerEscalation(ctx, ask); err != nil {
				return err
			}
		}
		for _, s := range u.Steers {
			r.settleSteer(s)
		}
	}
	if deliver && r.paused && !r.runner.pausing {
		r.runner.pausing = true
		if err := r.deliverToRunner(ctx, DeliverToRunnerRequest{Kind: "pause"}); err != nil {
			return err
		}
	}
	if deliver && !r.runner.pausing {
		for len(r.messageQueue) > 0 {
			m := r.messageQueue[0]
			r.messageQueue = r.messageQueue[1:]
			r.runner.steering = append(r.runner.steering, m)
			if err := r.deliverToRunner(ctx, DeliverToRunnerRequest{Kind: "steer", MessageID: m.ID, Text: m.Content}); err != nil {
				return err
			}
		}
		for _, a := range slices.Clone(r.runner.asks) {
			if e := r.escalations[a.escalationID]; e != nil && e.Resolved {
				if err := r.answerRunnerEscalation(ctx, a.escalationID, e); err != nil {
					return err
				}
			}
		}
	}
	return r.publish(ctx)
}

func (r *agentRun) runnerActorData() any {
	if r.runner.actor == nil {
		return nil
	}
	return map[string]any{"type": r.runner.actor.Type, "id": r.runner.actor.ID}
}

func (r *agentRun) recordRunnerEvent(ctx workflow.Context, e RunnerTurnEvent) {
	switch e.Kind {
	case "message":
		r.emit(ctx, domain.EventLLMCompleted, map[string]any{
			"role": "assistant", "content": e.Text, "thinking": "", "cost": "0", "iteration": r.iteration,
			"item_id": e.ItemID, "model_name": firstNonEmpty(e.Model, "runner"),
		})
	case "tool.call":
		if i := slices.IndexFunc(r.runner.openTools, func(t runnerTool) bool { return t.itemID == e.ItemID }); i >= 0 {
			r.runner.openTools[i].name = e.Name
		} else {
			r.runner.openTools = append(r.runner.openTools, runnerTool{itemID: e.ItemID, name: e.Name})
		}
		r.emit(ctx, domain.EventToolCall, map[string]any{
			"tool_name": nullable(e.Name), "tool_call_id": e.ItemID, "arguments": domain.SanitizeToolEventValue(e.Arguments, ""),
			"iteration": r.iteration, "actor": r.runnerActorData(),
		})
	default:
		r.runner.openTools = slices.DeleteFunc(r.runner.openTools, func(t runnerTool) bool { return t.itemID == e.ItemID })
		var exit any
		if e.ExitCode != nil {
			exit = *e.ExitCode
		}
		r.emit(ctx, domain.EventToolResult, map[string]any{
			"tool_name": nullable(e.Name), "tool_call_id": e.ItemID, "result": e.Output, "success": e.Success != nil && *e.Success,
			"exit_code": exit, "source": "runner", "iteration": r.iteration,
		})
	}
}

// closeOpenRunnerTools gives each command the turn left running a result.
func (r *agentRun) closeOpenRunnerTools(ctx workflow.Context, reason string) error {
	if len(r.runner.openTools) == 0 {
		return nil
	}
	for _, t := range r.runner.openTools {
		r.emit(ctx, domain.EventToolResult, map[string]any{
			"tool_name": nullable(t.name), "tool_call_id": t.itemID, "result": reason, "success": false,
			"source": "runner", "iteration": r.iteration,
		})
	}
	r.runner.openTools = nil
	return r.publish(ctx)
}

func (r *agentRun) settleSteer(s RunnerSteerOutcome) {
	i := slices.IndexFunc(r.runner.steering, func(m QueuedMessage) bool { return m.ID == s.MessageID })
	if i < 0 {
		return
	}
	m := r.runner.steering[i]
	r.runner.steering = slices.Delete(r.runner.steering, i, i+1)
	if s.Accepted {
		r.messages = append(r.messages, Message{Role: "user", Content: m.Content})
	} else {
		r.runner.heldBack = append(r.runner.heldBack, m)
	}
}

// openRunnerEscalation: the CLI waits for a person, an escalation of the run as a tool's would be.
func (r *agentRun) openRunnerEscalation(ctx workflow.Context, ask RunnerApprovalAsk) error {
	if r.runner.seenAsks[ask.RequestID] {
		return nil
	}
	r.runner.seenAsks[ask.RequestID] = true
	id := r.ids.uuid()
	esc := &Escalation{
		EscalationID: id, ToolCallID: firstNonEmpty(ask.ItemID, ask.RequestID), ToolName: ask.ToolName, ToolArgs: ask.Arguments,
		Approvers: domain.ApproversForTool(r.cfg.Policy, ask.ToolName, nil),
	}
	r.escalations[id] = esc
	r.escalationOrder = append(r.escalationOrder, id)
	r.runner.asks = append(r.runner.asks, runnerAsk{escalationID: id, requestID: ask.RequestID})
	r.status = StatusWaitingForApproval
	if err := r.persistStatus(ctx, r.statusOnly("waiting_for_approval")); err != nil {
		return err
	}
	msg := "The CLI asks to run '" + ask.ToolName + "'"
	if ask.Reason != "" {
		msg += ": " + ask.Reason
	}
	r.emit(ctx, domain.EventApprovalRequested, map[string]any{
		"escalation_id": id, "tool_name": ask.ToolName, "tool_call_id": esc.ToolCallID, "iteration": r.iteration,
		"arguments": domain.SanitizeToolEventValue(ask.Arguments, ""), "approvers": orEmpty(esc.Approvers),
		"actor": r.runnerActorData(), "message": msg,
	})
	return nil
}

func (r *agentRun) dropEscalation(id string) *Escalation {
	e := r.escalations[id]
	delete(r.escalations, id)
	r.escalationOrder = slices.DeleteFunc(r.escalationOrder, func(s string) bool { return s == id })
	return e
}

func (r *agentRun) dropRunnerAsk(id string) string {
	i := slices.IndexFunc(r.runner.asks, func(a runnerAsk) bool { return a.escalationID == id })
	if i < 0 {
		return ""
	}
	req := r.runner.asks[i].requestID
	r.runner.asks = slices.Delete(r.runner.asks, i, i+1)
	return req
}

func (r *agentRun) answerRunnerEscalation(ctx workflow.Context, id string, esc *Escalation) error {
	requestID := r.dropRunnerAsk(id)
	r.dropEscalation(id)
	r.emit(ctx, domain.EventApprovalDecided, map[string]any{
		"escalation_id": id, "tool_name": esc.ToolName, "tool_call_id": esc.ToolCallID, "iteration": r.iteration,
		"approved": esc.Approved, "approved_by": nullable(esc.ApprovedBy), "comment": nullable(esc.Comment),
	})
	approved := esc.Approved
	if err := r.deliverToRunner(ctx, DeliverToRunnerRequest{Kind: "decision", RequestID: requestID, Approved: &approved}); err != nil {
		return err
	}
	if len(r.escalations) == 0 {
		r.status = StatusExecuting
		return r.persistStatus(ctx, r.statusOnly("running"))
	}
	return nil
}

// expireRunnerEscalations closes the escalations of a turn that ended before anyone answered them.
func (r *agentRun) expireRunnerEscalations(ctx workflow.Context, reason string) error {
	if len(r.runner.asks) == 0 {
		return nil
	}
	for _, a := range slices.Clone(r.runner.asks) {
		r.dropRunnerAsk(a.escalationID)
		esc := r.dropEscalation(a.escalationID)
		if esc == nil || esc.Resolved {
			continue
		}
		r.emit(ctx, domain.EventApprovalDecided, map[string]any{
			"escalation_id": a.escalationID, "tool_name": esc.ToolName, "tool_call_id": esc.ToolCallID, "iteration": r.iteration,
			"approved": false, "approved_by": nil, "comment": reason,
		})
	}
	if len(r.escalations) == 0 {
		r.status = StatusExecuting
		return r.persistStatus(ctx, r.statusOnly("running"))
	}
	return nil
}

// settleRunnerTurn: messages the turn never took wait for the next one.
func (r *agentRun) settleRunnerTurn() {
	r.runner.heldBack = append(r.runner.heldBack, r.runner.steering...)
	r.runner.steering = nil
	r.messageQueue = slices.Concat(r.runner.heldBack, r.messageQueue)
	r.runner.heldBack = nil
}

func (r *agentRun) completeRunnerTurn(ctx workflow.Context, response string) error {
	r.success = true
	r.finalResponse = response
	r.status = StatusCompleted
	r.failureReason = ""
	r.errorMessage = ""
	r.awaitingInput = true
	r.completedStatus = &TaskStatus{Status: "completed", Response: response}
	window, ok := r.followUpWindow()
	if !ok {
		r.awaitingInput = false
		return nil
	}
	r.emit(ctx, domain.EventTaskAwaitingFollowUp, map[string]any{
		"state": "awaiting_follow_up", "timeout_seconds": int(window.Seconds()), "final_response": response,
	})
	return nil
}

func (r *agentRun) deliverToRunner(ctx workflow.Context, req DeliverToRunnerRequest) error {
	req.ClientID, req.TaskID, req.TurnKey = r.runner.clientID, r.taskID, r.runner.turnKey
	return workflow.ExecuteActivity(activityCtx(ctx, api.ActivityDeliverToRunner, "", 0), api.ActivityDeliverToRunner, req).Get(ctx, nil)
}
