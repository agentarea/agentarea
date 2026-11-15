package service

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

const (
	liveStateTimeout   = 3 * time.Second
	closedErrorTimeout = 5 * time.Second
)

// WorkflowStatus is TemporalWorkflowService.get_workflow_status's answer.
type WorkflowStatus struct {
	Status string
	// ExecutionStatus is "" when the answer carries none (an error or unknown).
	ExecutionStatus string
	Success         any
	Result          wirejson.Object
	FailureReason   any
	Error           string
	ErrorType       string
	StartTime       *time.Time
	EndTime         *time.Time
}

// workflowStatus maps Temporal's view of a run to the agent task's outcome
// (temporal_orchestrator.py get_workflow_status); a lookup failure is
// {"status": "error"} (temporal_workflow_service.py:65).
func (s *Surface) workflowStatus(ctx context.Context, workflowID string) WorkflowStatus {
	r, err := s.d.Executor.Status(ctx, workflowID)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to get workflow status", "workflow_id", workflowID, "error", err.Error())
		return WorkflowStatus{Status: "error", Success: false, Error: "Workflow status unavailable"}
	}
	var mapped string
	switch r.Status {
	case durable.StatusUnknown:
		if r.Error != "" {
			return WorkflowStatus{Status: "unknown", Success: false, Error: "Workflow not found"}
		}
		mapped = "running"
	case durable.StatusRunning:
		mapped = "running"
	case durable.StatusCompleted:
		mapped = "completed"
	case durable.StatusCancelled:
		mapped = "cancelled"
	case durable.StatusFailed, durable.StatusTerminated:
		mapped = "failed"
	default:
		mapped = "failed"
	}
	out := WorkflowStatus{Status: mapped, ExecutionStatus: mapped, StartTime: r.StartTime, EndTime: r.EndTime}
	switch mapped {
	case "completed":
		completedOutcome(&out, r.Result)
	case "failed", "cancelled":
		out.Success = false
		w, err := s.d.Executor.Wait(ctx, workflowID, closedErrorTimeout)
		if err != nil {
			s.d.Log.ErrorContext(ctx, "Failed to read the failure of a closed workflow", "workflow_id", workflowID, "error", err.Error())
		}
		text := strings.ToLower(w.Error)
		if strings.Contains(text, "insufficient balance") || strings.Contains(text, "no resource package") ||
			strings.Contains(text, "quota exceeded") {
			out.Status, out.ErrorType, out.Error = "blocked", "provider_quota_exceeded", "Provider quota exceeded"
		} else {
			out.Error = "Workflow execution failed"
		}
	}
	return out
}

func hasFinalResponse(v any) bool {
	s, ok := v.(string)
	return ok && strings.TrimSpace(s) != ""
}

func completedOutcome(out *WorkflowStatus, raw []byte) {
	var result wirejson.Object
	if len(raw) > 0 {
		if v, err := wirejson.Unmarshal(raw); err == nil {
			result, _ = v.(wirejson.Object)
		}
	}
	field := func(k string) any { v, _ := result.Get(k); return v }
	success := field("success")
	status, _ := field("status").(string)
	final := field("final_response")
	reason := field("failure_reason")
	errMsg := field("error_message")
	var outcome string
	switch {
	case status == "waiting_for_input" || status == "waiting_for_approval" || status == "waiting_for_continuation":
		outcome, success = status, nil
	case status == "blocked":
		outcome, success = "blocked", false
		if !truthy(reason) {
			reason = "blocked"
		}
	case status == "failed" || status == "cancelled" || success == false:
		outcome = "failed"
		if status == "cancelled" {
			outcome = "cancelled"
		}
		success = false
		if !truthy(reason) {
			reason = "task_unsuccessful"
		}
	case !hasFinalResponse(final):
		outcome, success = "failed", false
		if !truthy(reason) {
			reason = "missing_final_response"
		}
		if !truthy(errMsg) {
			errMsg = "Task ended without a final response"
		}
	default:
		outcome, success = "completed", true
	}
	metrics, ok := result.Get("execution_metrics")
	if !ok {
		metrics = wirejson.Object{}
	}
	out.Status, out.Success, out.FailureReason = outcome, success, reason
	if truthy(errMsg) {
		out.Error = pyStr(errMsg)
	}
	out.Result = wirejson.Object{
		{Key: "response", Value: final}, {Key: "execution_metrics", Value: metrics},
		{Key: "success", Value: success}, {Key: "status", Value: outcome}, {Key: "failure_reason", Value: reason},
	}
}

// liveState is get_workflow_live_state: the run's get_current_state, nil when unreadable.
func (s *Surface) liveState(ctx context.Context, workflowID string) map[string]any {
	qctx, cancel := context.WithTimeout(ctx, liveStateTimeout)
	defer cancel()
	var state map[string]any
	if err := s.d.Executor.Query(qctx, workflowID, api.QueryCurrentState, &state); err != nil {
		if !errors.Is(err, durable.ErrNotFound) {
			s.d.Log.WarnContext(ctx, "Failed to read live state of workflow", "workflow_id", workflowID, "error", err.Error())
		}
		return nil
	}
	return state
}

// errWorkflowNotFound is WorkflowNotFoundError.
var errWorkflowNotFound = errors.New("workflow not found")

// pendingEscalations is get_workflow_pending_escalations: a closed run waits on nothing.
func (s *Surface) pendingEscalations(ctx context.Context, workflowID string) ([]api.PendingEscalationView, error) {
	r, err := s.d.Executor.Status(ctx, workflowID)
	if err != nil {
		return nil, err
	}
	if r.Status == durable.StatusUnknown && r.Error != "" {
		return nil, errWorkflowNotFound
	}
	if r.Status != durable.StatusRunning {
		return []api.PendingEscalationView{}, nil
	}
	var out []api.PendingEscalationView
	if err := s.d.Executor.Query(ctx, workflowID, api.QueryPendingEscalation, &out); err != nil {
		if errors.Is(err, durable.ErrNotFound) {
			return nil, errWorkflowNotFound
		}
		return nil, err
	}
	if out == nil {
		out = []api.PendingEscalationView{}
	}
	return out, nil
}

// signal delivers a signal; false with the failure logged, as the
// orchestrator's pause/resume/a2ui wrappers answer.
func (s *Surface) signal(ctx context.Context, workflowID, name string, arg any) bool {
	if err := s.d.Executor.Signal(ctx, workflowID, name, arg); err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to signal workflow", "workflow_id", workflowID, "signal", name, "error", err.Error())
		return false
	}
	return true
}

// command is send_workflow_command: false when the run is not running, any
// other failure logged and false (temporal_workflow_service.py:134).
func (s *Surface) command(ctx context.Context, workflowID, command string, payload map[string]any) bool {
	err := s.d.Executor.Signal(ctx, workflowID, api.SignalWorkflowCommand, api.WorkflowCommandSignal{Command: command, Payload: payload})
	if err == nil {
		return true
	}
	if errors.Is(err, durable.ErrNotFound) {
		s.d.Log.InfoContext(ctx, "Workflow command not delivered: workflow is not running", "command", command, "workflow_id", workflowID)
		return false
	}
	s.d.Log.ErrorContext(ctx, "Failed to send workflow command", "command", command, "workflow_id", workflowID, "error", err.Error())
	return false
}
