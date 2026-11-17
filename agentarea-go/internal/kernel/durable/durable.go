// Package durable is the durable-execution port over Temporal (TEMPORAL_*,
// AGENTAREA_TEMPORAL_*). The Temporal SDK is imported in durable/temporal and
// in internal/modules/*/workflows only (decision 4); services, stores and
// handlers start and drive workflows through this port.
package durable

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

// Status is a workflow execution's status.
type Status string

const (
	StatusRunning    Status = "running"
	StatusCompleted  Status = "completed"
	StatusFailed     Status = "failed"
	StatusCancelled  Status = "cancelled"
	StatusTerminated Status = "terminated"
	StatusUnknown    Status = "unknown"
)

// Result is a workflow's status and, once closed, its result or error.
type Result struct {
	WorkflowID string
	Status     Status
	Result     json.RawMessage
	Error      string
	StartTime  *time.Time
	EndTime    *time.Time
}

// StartOptions configure one start (workflow/executor.py WorkflowConfig).
type StartOptions struct {
	TaskQueue     string
	Timeout       time.Duration
	RetryAttempts int
	RetryInitial  time.Duration
	RetryMax      time.Duration
	StartDelay    time.Duration
	// StartSignal is sent with the start: a new execution receives it as its
	// first signal, a running one receives only the signal.
	StartSignal     string
	StartSignalArgs []any
	// StartOnce refuses a second run of an id that ever started, open or closed.
	StartOnce bool
}

var (
	// ErrAlreadyStarted is returned by Start for an id that is running, or, with
	// StartOnce, that ever ran. temporal_executor.py:263 logs it and returns the
	// id; callers that keep that behaviour treat it as success.
	ErrAlreadyStarted = errors.New("workflow already started")
	// ErrNotFound is returned for a workflow or schedule Temporal does not know.
	ErrNotFound = errors.New("not found")
	// ErrWaitTimeout is returned by Wait when the workflow is still open at the deadline.
	ErrWaitTimeout = errors.New("workflow did not complete within the timeout")
)

// Executor starts and drives workflows (workflow/executor.py WorkflowExecutor).
type Executor interface {
	// Start returns the workflow id (Python returns handle.id).
	Start(ctx context.Context, workflow, workflowID string, args []any, opts StartOptions) (string, error)
	// Status maps a missing workflow to StatusUnknown with Error "Workflow not found".
	Status(ctx context.Context, workflowID string) (Result, error)
	Cancel(ctx context.Context, workflowID string) error
	// Wait returns the closed workflow's Result; a timeout of 0 waits until ctx ends.
	Wait(ctx context.Context, workflowID string, timeout time.Duration) (Result, error)
	Signal(ctx context.Context, workflowID, signal string, args ...any) error
	Query(ctx context.Context, workflowID, query string, out any, args ...any) error
	Update(ctx context.Context, workflowID, update string, out any, args ...any) error
}

// ActivityKind labels every activity (decision 3d): control activities read
// or write definitions, data activities run the agent's work. A run resolves
// its configuration once, as its first activity, into one RunConfig; later
// activities do not read definitions (decision 3c).
type ActivityKind string

const (
	KindControl ActivityKind = "control"
	KindData    ActivityKind = "data"
)

// Valid reports whether k is one of the two kinds.
func (k ActivityKind) Valid() bool { return k == KindControl || k == KindData }

// Activity is one activity registration.
type Activity struct {
	// Name is the name the workflow schedules, the Python function name
	// (call_llm_activity), never derived from the Go function.
	Name string
	Kind ActivityKind
	// Fn is func(context.Context, In) (Out, error) or func(context.Context, In) error.
	Fn any
}

// Workflow is one workflow registration; Fn is written against the Temporal
// SDK inside a module's workflows package.
type Workflow struct {
	Name string
	Fn   any
}

// Worker polls one task queue.
type Worker interface {
	RegisterWorkflow(w Workflow)
	RegisterActivity(a Activity)
	// Kinds is the kind of every registered activity, by name.
	Kinds() map[string]ActivityKind
	// Run polls until ctx ends, then drains for AGENTAREA_TEMPORAL_SHUTDOWN_GRACE.
	// A registration error, or the worker stopping on its own, is returned.
	Run(ctx context.Context) error
	// Polling reports whether Run has started the worker and it still polls.
	Polling() bool
}

// ApplicationError is an activity failure as the workflow sees it: Type is
// the error type its retry policies and handlers match (workflows/retry.py NON_RETRYABLE_ERROR_TYPES, e.g.
// "GovernanceDeniedError"), Details are extra payloads.
type ApplicationError struct {
	Type         string
	Message      string
	NonRetryable bool
	Details      []any
	Cause        error
}

func (e *ApplicationError) Error() string {
	if e.Type == "" {
		return e.Message
	}
	return fmt.Sprintf("%s: %s", e.Type, e.Message)
}

func (e *ApplicationError) Unwrap() error { return e.Cause }

// Overlap is a schedule's overlap policy.
type Overlap string

const (
	OverlapSkip      Overlap = "skip"
	OverlapBufferOne Overlap = "buffer_one"
	OverlapBufferAll Overlap = "buffer_all"
	OverlapCancel    Overlap = "cancel_other"
	OverlapTerminate Overlap = "terminate_other"
	OverlapAllowAll  Overlap = "allow_all"
)

// Schedule is a Temporal Schedule that starts one workflow.
type Schedule struct {
	ID string
	// Workflow, WorkflowID, TaskQueue and Args are the action. WorkflowID may
	// hold Temporal's {{.ScheduledTime}} template.
	Workflow   string
	WorkflowID string
	TaskQueue  string
	Args       []any
	Every      []time.Duration
	Cron       []string
	TimeZone   string
	// Overlap defaults to Temporal's (skip).
	Overlap       Overlap
	CatchupWindow time.Duration
	Paused        bool
	Note          string
}

// ScheduleAction is one recent firing of a schedule.
type ScheduleAction struct {
	ScheduledTime time.Time
	ActualTime    time.Time
	WorkflowID    string
	RunID         string
}

// ScheduleInfo is a described schedule. Cron holds the expressions given at
// creation only when the server still reports them (it normalises them into
// calendar specs); Args are the action's raw JSON arguments.
type ScheduleInfo struct {
	ID            string
	Workflow      string
	WorkflowID    string
	TaskQueue     string
	Args          []json.RawMessage
	Every         []time.Duration
	Cron          []string
	TimeZone      string
	CatchupWindow time.Duration
	Paused        bool
	Note          string
	NextActions   []time.Time
	RecentActions []ScheduleAction
}

// Scheduler keeps Temporal Schedules (ensure_*_schedule,
// temporal_schedule_manager.py).
type Scheduler interface {
	// Ensure creates the schedule, or replaces an existing one with s.
	Ensure(ctx context.Context, s Schedule) error
	Describe(ctx context.Context, id string) (ScheduleInfo, error)
	Delete(ctx context.Context, id string) error
}
