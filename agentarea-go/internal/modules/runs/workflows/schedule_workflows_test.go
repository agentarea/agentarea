package workflows

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

func register(env *testsuite.TestWorkflowEnvironment, name string, fn any) {
	env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
}

func TestReconcilerReturnsStarted(t *testing.T) {
	var s testsuite.WorkflowTestSuite
	env := s.NewTestWorkflowEnvironment()
	attempts := 0
	register(env, api.ActivityStartUndispatchedTasks, func(context.Context) (StartUndispatchedResult, error) {
		attempts++
		return StartUndispatchedResult{Started: 3}, nil
	})
	env.ExecuteWorkflow(UndispatchedTaskReconcilerWorkflow)
	var n int
	if err := env.GetWorkflowResult(&n); err != nil || n != 3 || attempts != 1 {
		t.Fatalf("started %d attempts %d err %v", n, attempts, err)
	}
}

func TestCronSyncTriesOnce(t *testing.T) {
	var s testsuite.WorkflowTestSuite
	env := s.NewTestWorkflowEnvironment()
	attempts := 0
	register(env, api.ActivitySyncCronSchedules, func(context.Context) error {
		attempts++
		return errors.New("temporal refused")
	})
	env.ExecuteWorkflow(CronScheduleSyncWorkflow)
	if env.GetWorkflowError() == nil || attempts != 1 {
		t.Fatalf("attempts %d err %v", attempts, env.GetWorkflowError())
	}
}

type triggerFakes struct {
	mu        sync.Mutex
	met       bool
	execute   func(ExecuteTriggerRequest) (ExecuteTriggerResult, error)
	executed  []ExecuteTriggerRequest
	recorded  []RecordTriggerExecutionRequest
	evaluated []EvaluateTriggerConditionsRequest
}

func (f *triggerFakes) env(t *testing.T, scheduled bool) *testsuite.TestWorkflowEnvironment {
	t.Helper()
	var s testsuite.WorkflowTestSuite
	env := s.NewTestWorkflowEnvironment()
	register(env, api.ActivityEvaluateTriggerConditions, func(_ context.Context, r EvaluateTriggerConditionsRequest) (EvaluateTriggerConditionsResult, error) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.evaluated = append(f.evaluated, r)
		return EvaluateTriggerConditionsResult{TriggerID: r.TriggerID, ConditionsMet: f.met}, nil
	})
	register(env, api.ActivityExecuteTrigger, func(_ context.Context, r ExecuteTriggerRequest) (ExecuteTriggerResult, error) {
		f.mu.Lock()
		f.executed = append(f.executed, r)
		f.mu.Unlock()
		return f.execute(r)
	})
	register(env, api.ActivityRecordTriggerExecution, func(_ context.Context, r RecordTriggerExecutionRequest) (RecordTriggerExecutionResult, error) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.recorded = append(f.recorded, r)
		return RecordTriggerExecutionResult{ExecutionID: "exec-1", TriggerID: r.TriggerID}, nil
	})
	if scheduled {
		slot := time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC)
		if err := env.SetTypedSearchAttributesOnStart(temporal.NewSearchAttributes(scheduledStartTime().ValueSet(slot))); err != nil {
			t.Fatal(err)
		}
	}
	return env
}

func TestTriggerFiringReacts(t *testing.T) {
	f := &triggerFakes{met: true, execute: func(r ExecuteTriggerRequest) (ExecuteTriggerResult, error) {
		return ExecuteTriggerResult{TriggerID: r.TriggerID, Status: "success", TaskID: "task-1", ExecutionID: "exec-1", Duration: 40 * time.Millisecond, TriggerData: r.ExecutionData}, nil
	}}
	env := f.env(t, true)
	env.ExecuteWorkflow(TriggerExecutionWorkflow, "trig-1", api.CronFiringData("0 9 * * *", "UTC"))
	var out map[string]any
	if err := env.GetWorkflowResult(&out); err != nil {
		t.Fatal(err)
	}
	if out["status"] != "success" || out["task_id"] != "task-1" || out["execution_time_ms"] != float64(40) || out["workflow_timeout_minutes"] != float64(15) {
		t.Fatalf("%v", out)
	}
	if got := f.executed[0].ExecutionData["scheduled_time"]; got != "2026-11-12T09:00:00+00:00" {
		t.Fatalf("scheduled_time %v", got)
	}
	if f.executed[0].ExecutionData["source"] != "cron" || f.evaluated[0].EventData["scheduled_time"] == nil || len(f.recorded) != 0 {
		t.Fatalf("%+v %+v %+v", f.executed, f.evaluated, f.recorded)
	}
}

func TestTriggerFiringSkipsWhenConditionsUnmet(t *testing.T) {
	f := &triggerFakes{met: false}
	env := f.env(t, true)
	env.ExecuteWorkflow(TriggerExecutionWorkflow, "trig-1", map[string]any{"timeout_minutes": 45})
	var out map[string]any
	if err := env.GetWorkflowResult(&out); err != nil {
		t.Fatal(err)
	}
	if out["status"] != "skipped" || out["reason"] != "conditions_not_met" || out["workflow_timeout_minutes"] != float64(30) || len(f.executed) != 0 {
		t.Fatalf("%v executed %d", out, len(f.executed))
	}
}

func TestTriggerFiringFailureIsRecordedOnceAfterTheLastAttempt(t *testing.T) {
	f := &triggerFakes{met: true, execute: func(ExecuteTriggerRequest) (ExecuteTriggerResult, error) {
		return ExecuteTriggerResult{}, errors.New("database is down")
	}}
	env := f.env(t, true)
	env.ExecuteWorkflow(TriggerExecutionWorkflow, "trig-1", map[string]any{})
	err := env.GetWorkflowError()
	if err == nil {
		t.Fatal("firing that failed every attempt succeeded")
	}
	if len(f.executed) != 3 || len(f.recorded) != 1 {
		t.Fatalf("executed %d recorded %d", len(f.executed), len(f.recorded))
	}
	rec := f.recorded[0].ExecutionData
	if rec["status"] != "failed" || rec["error_type"] != "ApplicationError" || rec["is_unexpected_error"] != nil ||
		rec["error_message"] != "database is down" {
		t.Fatalf("%v", rec)
	}
}

func TestTriggerFiringTimeoutIsRecordedAsUnexpected(t *testing.T) {
	f := &triggerFakes{met: true, execute: func(ExecuteTriggerRequest) (ExecuteTriggerResult, error) {
		return ExecuteTriggerResult{}, temporal.NewTimeoutError(enumspb.TIMEOUT_TYPE_START_TO_CLOSE, nil)
	}}
	env := f.env(t, true)
	env.ExecuteWorkflow(TriggerExecutionWorkflow, "trig-1", map[string]any{})
	if env.GetWorkflowError() == nil || len(f.recorded) != 1 {
		t.Fatalf("recorded %d err %v", len(f.recorded), env.GetWorkflowError())
	}
	rec := f.recorded[0].ExecutionData
	msg, _ := rec["error_message"].(string)
	if rec["is_unexpected_error"] != true || !strings.HasPrefix(msg, "Unexpected error: ") || strings.Contains(msg, "Activity task failed") {
		t.Fatalf("%v", rec)
	}
}

func TestTriggerFiringNotFoundIsNotRetried(t *testing.T) {
	f := &triggerFakes{met: true, execute: func(ExecuteTriggerRequest) (ExecuteTriggerResult, error) {
		return ExecuteTriggerResult{}, temporal.NewNonRetryableApplicationError("Trigger trig-1 not found", "TriggerNotFoundError", nil)
	}}
	env := f.env(t, true)
	env.ExecuteWorkflow(TriggerExecutionWorkflow, "trig-1", map[string]any{})
	if env.GetWorkflowError() == nil || len(f.executed) != 1 || len(f.recorded) != 1 {
		t.Fatalf("executed %d recorded %d", len(f.executed), len(f.recorded))
	}
}

func TestTriggerFiringRefusesAStartNotByItsSchedule(t *testing.T) {
	f := &triggerFakes{met: true}
	env := f.env(t, false)
	env.ExecuteWorkflow(TriggerExecutionWorkflow, "trig-1", map[string]any{})
	var appErr *temporal.ApplicationError
	if err := env.GetWorkflowError(); !errors.As(err, &appErr) || !appErr.NonRetryable() || len(f.evaluated) != 0 {
		t.Fatalf("%v", err)
	}
}

type batchFakes struct {
	mu     sync.Mutex
	fired  []OpenBatch
	closed []OpenBatch
}

func (f *batchFakes) env() *testsuite.TestWorkflowEnvironment {
	var s testsuite.WorkflowTestSuite
	env := s.NewTestWorkflowEnvironment()
	register(env, api.ActivityFireTriggerBatch, func(_ context.Context, b OpenBatch) (BatchResult, error) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.fired = append(f.fired, b)
		return BatchResult{Events: len(b.EventIDs)}, nil
	})
	register(env, api.ActivityCloseTriggerBatch, func(_ context.Context, b OpenBatch) (BatchResult, error) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.closed = append(f.closed, b)
		return BatchResult{Events: len(b.EventIDs)}, nil
	})
	env.SetStartWorkflowOptions(client.StartWorkflowOptions{ID: "trigger-batch-1"})
	return env
}

func TestBatchFiresWhenTheWindowPassesWithEachEventOnce(t *testing.T) {
	f := &batchFakes{}
	env := f.env()
	env.RegisterDelayedCallback(func() { env.SignalWorkflow(SignalAddEvent, "e1") }, time.Second)
	env.RegisterDelayedCallback(func() { env.SignalWorkflow(SignalAddEvent, "e1") }, 2*time.Second)
	env.RegisterDelayedCallback(func() { env.SignalWorkflow(SignalAddEvent, "e2") }, 3*time.Second)
	env.ExecuteWorkflow(TriggerBatchWorkflow, BatchSpec{TriggerID: "trig-1", Window: time.Minute, MaxEvents: 10})
	var n int
	if err := env.GetWorkflowResult(&n); err != nil {
		t.Fatal(err)
	}
	if n != 2 || len(f.fired) != 1 || len(f.fired[0].EventIDs) != 2 || f.fired[0].WorkflowID != "trigger-batch-1" {
		t.Fatalf("n %d fired %+v", n, f.fired)
	}
}

func TestBatchFullFiresAndCarriesTheRestOver(t *testing.T) {
	f := &batchFakes{}
	env := f.env()
	env.ExecuteWorkflow(TriggerBatchWorkflow, BatchSpec{TriggerID: "trig-1", MaxEvents: 2, Pending: []string{"e1", "e2", "e3", "e1"}})
	var can *workflow.ContinueAsNewError
	if err := env.GetWorkflowError(); !errors.As(err, &can) {
		t.Fatalf("not continued as new: %v", err)
	}
	if len(f.fired) != 1 || len(f.fired[0].EventIDs) != 2 {
		t.Fatalf("%+v", f.fired)
	}
	var next BatchSpec
	if err := converter.GetDefaultDataConverter().FromPayloads(can.Input, &next); err != nil || len(next.Pending) != 1 || next.Pending[0] != "e3" {
		t.Fatalf("carried %v %v", next.Pending, err)
	}
}

func TestCancelledBatchClosesUnfired(t *testing.T) {
	f := &batchFakes{}
	env := f.env()
	env.RegisterDelayedCallback(func() { env.SignalWorkflow(SignalAddEvent, "e1") }, time.Second)
	env.RegisterDelayedCallback(env.CancelWorkflow, 10*time.Second)
	env.ExecuteWorkflow(TriggerBatchWorkflow, BatchSpec{TriggerID: "trig-1", Window: time.Hour, MaxEvents: 5})
	var n int
	_ = env.GetWorkflowResult(&n)
	if len(f.fired) != 0 || len(f.closed) != 1 || f.closed[0].Reason != BatchCancelledReason || len(f.closed[0].EventIDs) != 1 {
		t.Fatalf("fired %+v closed %+v", f.fired, f.closed)
	}
}
