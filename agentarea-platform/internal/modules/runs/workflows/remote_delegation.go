package workflows

import (
	"fmt"
	"time"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

const (
	remotePollFirst = 2 * time.Second
	remotePollMax   = 30 * time.Second
	// remotePollsPerRun bounds one run's history; the wait then continues as new.
	remotePollsPerRun = 200
	// remotePollFailures is how many reads in a row may fail before the call does.
	remotePollFailures = 5
	// remoteDeadlineMargin leaves the child time to stop the task and answer before its own timeout.
	remoteDeadlineMargin = 5 * time.Minute
)

// RemoteDelegationWorkflow is one call of a remote A2A delegate: the message sent through
// the tool activity, then the task it started waited for with durable timers and read on a
// backoff, until it ends, the deadline passes or the run stops it. A remote_task_update
// signal for the task reads it at once.
func RemoteDelegationWorkflow(ctx workflow.Context, req RemoteDelegationRequest) (RemoteDelegationResult, error) {
	st := req.State
	if st == nil {
		started := workflow.Now(ctx).UTC()
		sent, err := sendRemote(ctx, req.Call)
		if err != nil || sent.RemoteTask == nil {
			return RemoteDelegationResult{Answer: sent}, err
		}
		st = &RemoteDelegationState{Sent: sent, Task: *sent.RemoteTask, Started: started, Delay: remotePollFirst}
	}
	return waitRemote(ctx, req, st)
}

func remoteActivity(ctx workflow.Context, name, id string) workflow.Context {
	ctx = activityCtx(ctx, name, "", 0)
	opts := workflow.GetActivityOptions(ctx)
	opts.ActivityID = id
	return workflow.WithActivityOptions(ctx, opts)
}

// sendRemote is the call's tool activity; a refusal or a failure is the call's answer.
func sendRemote(ctx workflow.Context, call ToolCallRequest) (ToolCallResult, error) {
	var res ToolCallResult
	err := workflow.ExecuteActivity(remoteActivity(ctx, api.ActivityExecuteTool, call.ToolCallID+"-send"), api.ActivityExecuteTool, call).Get(ctx, &res)
	switch {
	case err == nil:
		return res, nil
	case isCancellation(err) || ctx.Err() != nil:
		return ToolCallResult{}, err
	}
	if typ, reason, _, ok := governanceVerdict(err); ok {
		if typ == ErrGovernanceDenied {
			return ToolCallResult{Error: "Tool call denied by policy: " + reason}, nil
		}
		return ToolCallResult{Error: "Tool call needs a person's approval, which a remote delegation cannot ask for: " + reason}, nil
	}
	return ToolCallResult{Error: "Tool execution failed: " + failureText(err)}, nil
}

func taskRequest(req RemoteDelegationRequest, st *RemoteDelegationState) RemoteTaskRequest {
	c := req.Call
	return RemoteTaskRequest{
		Principal: c.Principal, TaskID: c.TaskID, ExecutionID: c.ExecutionID, ToolCallID: c.ToolCallID, ToolName: c.ToolName,
		Binding: c.Binding, Task: st.Task,
	}
}

func waitRemote(ctx workflow.Context, req RemoteDelegationRequest, st *RemoteDelegationState) (RemoteDelegationResult, error) {
	updates := workflow.GetSignalChannel(ctx, api.SignalRemoteTaskUpdate)
	logger := workflow.GetLogger(ctx)
	for {
		now := workflow.Now(ctx)
		if !now.Before(req.Deadline) {
			cancelRemote(ctx, req, st)
			agent := ""
			if b := req.Call.Binding.RemoteAgent; b != nil {
				agent = b.AgentName
			}
			msg := fmt.Sprintf("'%s' is still working on task %s; no result within the delegation time limit", agent, st.Task.TaskID)
			return st.answer(ctx, ToolCallResult{Error: msg, Source: "builtin"}), nil
		}
		tctx, stopTimer := workflow.WithCancel(ctx)
		due := false
		sel := workflow.NewSelector(ctx)
		sel.AddFuture(workflow.NewTimer(tctx, min(st.Delay, req.Deadline.Sub(now))), func(workflow.Future) { due = true })
		sel.AddReceive(updates, func(c workflow.ReceiveChannel, _ bool) {
			var u api.RemoteTaskUpdate
			c.Receive(ctx, &u)
			due = u.TaskID == st.Task.TaskID
		})
		sel.Select(ctx)
		stopTimer()
		if ctx.Err() != nil {
			return stopRemote(ctx, req, st)
		}
		if !due {
			continue
		}
		var res ToolCallResult
		st.Reads++
		id := fmt.Sprintf("%s-get-%d", req.Call.ToolCallID, st.Reads)
		err := workflow.ExecuteActivity(remoteActivity(ctx, api.ActivityGetRemoteTask, id), api.ActivityGetRemoteTask, taskRequest(req, st)).Get(ctx, &res)
		switch {
		case err != nil && (isCancellation(err) || ctx.Err() != nil):
			return stopRemote(ctx, req, st)
		case err != nil:
			st.Failures++
			logger.Warn("reading a remote delegate's task failed", "task", st.Task.TaskID, "failures", st.Failures, "error", err)
			if st.Failures >= remotePollFailures {
				cancelRemote(ctx, req, st)
				return st.answer(ctx, ToolCallResult{Error: "Tool execution failed: " + failureText(err), Source: "builtin"}), nil
			}
		case res.RemoteTask == nil:
			return st.answer(ctx, res), nil
		default:
			st.Polls++
			st.Failures = 0
		}
		st.Delay = min(st.Delay*2, remotePollMax)
		if st.Failures == 0 && st.Polls%remotePollsPerRun == 0 {
			next := req
			next.State = st
			return RemoteDelegationResult{}, workflow.NewContinueAsNewError(ctx, api.WorkflowRemoteDelegation, next)
		}
	}
}

// answer is the call's answer: what the task ended with, carrying what the send cost.
func (st *RemoteDelegationState) answer(ctx workflow.Context, got ToolCallResult) RemoteDelegationResult {
	out := st.Sent
	out.Success, out.Result, out.Error, out.Images, out.RemoteTask = got.Success, got.Result, got.Error, got.Images, nil
	out.Duration = workflow.Now(ctx).UTC().Sub(st.Started)
	return RemoteDelegationResult{Answer: out, TaskID: st.Task.TaskID}
}

// stopRemote asks the delegate to stop the task once the run stopped this call.
func stopRemote(ctx workflow.Context, req RemoteDelegationRequest, st *RemoteDelegationState) (RemoteDelegationResult, error) {
	dctx, _ := workflow.NewDisconnectedContext(ctx)
	cancelRemote(dctx, req, st)
	return RemoteDelegationResult{TaskID: st.Task.TaskID}, ctx.Err()
}

func cancelRemote(ctx workflow.Context, req RemoteDelegationRequest, st *RemoteDelegationState) {
	id := req.Call.ToolCallID + "-cancel"
	if err := workflow.ExecuteActivity(remoteActivity(ctx, api.ActivityCancelRemoteTask, id), api.ActivityCancelRemoteTask, taskRequest(req, st)).Get(ctx, nil); err != nil {
		workflow.GetLogger(ctx).Warn("stopping a remote delegate's task failed", "task", st.Task.TaskID, "error", err)
	}
}
