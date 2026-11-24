package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"reflect"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// Launched is a started AgentExecutionWorkflow: its execution id, and
// whether a start delay holds its first task (the task is then scheduled).
type Launched struct {
	ExecutionID string
	Scheduled   bool
}

// RunLauncher starts a stored task's AgentExecutionWorkflow, once
// (TemporalTaskManager.submit_task): a workflow that already started counts
// as started.
type RunLauncher interface {
	Launch(ctx context.Context, workspaceID string, t store.StoredTask) (Launched, error)
}

// CronTrigger is a cron trigger's schedule as its row says it should be.
type CronTrigger struct {
	ID             string
	CronExpression string
	TimeZone       string
	Active         bool
}

// TriggerState is a trigger found by id across workspaces.
type TriggerState struct {
	ID          string
	Name        string
	WorkspaceID string
	Active      bool
}

// TaskProvenance is stamped on the task a firing creates.
type TaskProvenance struct {
	OriginType    string
	OriginID      string
	CorrelationID string
}

// TriggerFire is one firing of a trigger by its schedule (TriggerService.fire
// with raise_retryable): TaskID makes every retry name the same task.
type TriggerFire struct {
	TriggerID  string
	Data       map[string]any
	TaskID     string
	Provenance TaskProvenance
}

// TriggerFiring is what a firing did (TriggerFiring). Outcome is reacted,
// skipped or error; BlockedBy is the trigger's own run a firing gave way to;
// Verdict says the conditions were evaluated (and not met, when skipped).
type TriggerFiring struct {
	Outcome     string
	Reason      string
	TaskID      string
	ExecutionID string
	BlockedBy   string
	Verdict     bool
}

// TriggerExecutionRecord is a firing's row in trigger_executions.
type TriggerExecutionRecord struct {
	Status        string
	ExecutionTime time.Duration
	TaskID        string
	ErrorMessage  string
	TriggerData   map[string]any
}

// RecordedTriggerExecution is the row record_execution wrote.
type RecordedTriggerExecution struct {
	ID         string
	ExecutedAt time.Time
}

// Triggers is the streams module's trigger service as the trigger workflows
// drive it. Trigger and RecordExecution return ErrNotFound for a trigger that
// is gone; errors that are *durable.ApplicationError keep their type.
type Triggers interface {
	// CronTriggers lists every workspace's cron triggers; CronTrigger reads
	// one again, false when it is gone (schedule_sync._cron_rows).
	CronTriggers(ctx context.Context) ([]CronTrigger, error)
	CronTrigger(ctx context.Context, id string) (CronTrigger, bool, error)
	Trigger(ctx context.Context, id string) (TriggerState, error)
	// EvaluateConditions is TriggerService.evaluate_trigger_conditions; a
	// trigger that is gone has its conditions unmet.
	EvaluateConditions(ctx context.Context, id string, eventData map[string]any) (bool, error)
	Fire(ctx context.Context, f TriggerFire) (TriggerFiring, error)
	RecordExecution(ctx context.Context, id string, r TriggerExecutionRecord) (RecordedTriggerExecution, error)
}

// TriggerBatch is one open batch of a windowed stream trigger.
type TriggerBatch struct {
	TriggerID      string
	SubscriptionID string
	WorkspaceID    string
	ConfiguredBy   string
	Caller         string
	WorkflowID     string
	EventIDs       []string
	Reason         string
}

// TriggerBatches fires or closes a batch (TriggerBatchFirer); both return how
// many events they handled.
type TriggerBatches interface {
	Fire(ctx context.Context, b TriggerBatch) (int, error)
	Close(ctx context.Context, b TriggerBatch) (int, error)
}

// SchedulingDeps are the ports of the reconciler, the cron schedule sync and
// the trigger activities. A nil port fails the activity that needs it.
type SchedulingDeps struct {
	DB        db.Database
	Launcher  RunLauncher
	Triggers  Triggers
	Batches   TriggerBatches
	Schedules durable.Scheduler
	// TriggerQueue is AGENTAREA_TRIGGER_QUEUE, where cron schedules start their firings.
	TriggerQueue string
	Now          func() time.Time
	Log          *slog.Logger
}

// Scheduling is phase 3 of the run: tasks left unstarted, cron schedules,
// trigger firings.
type Scheduling struct {
	d     SchedulingDeps
	store store.Runs
}

// NewScheduling builds the scheduling use cases; Now and Log default to the clock and slog.
func NewScheduling(d SchedulingDeps) *Scheduling {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Scheduling{d: d}
}

// Missing names the ports a worker running every scheduling activity lacks.
func (d SchedulingDeps) Missing() []string {
	var out []string
	if d.DB == nil {
		out = append(out, "database")
	}
	if d.Launcher == nil {
		out = append(out, "run launcher")
	}
	if d.Triggers == nil {
		out = append(out, "triggers (streams)")
	}
	if d.Batches == nil {
		out = append(out, "trigger batches (streams)")
	}
	if d.Schedules == nil {
		out = append(out, "schedules")
	}
	if d.TriggerQueue == "" {
		out = append(out, "trigger queue")
	}
	return out
}

func (s *Scheduling) now() time.Time { return s.d.Now().UTC() }

// Reconciler bounds (undispatched_tasks.py).
const (
	undispatchedStaleAfter = 2 * time.Minute
	undispatchedHorizon    = 24 * time.Hour
	undispatchedBatch      = 100
)

// StartUndispatched starts every task left pending with no workflow; a task
// whose start fails stays pending for the next tick (start_undispatched_tasks).
func (s *Scheduling) StartUndispatched(ctx context.Context) (int, error) {
	if s.d.DB == nil || s.d.Launcher == nil {
		return 0, errors.New("starting undispatched tasks needs the database and the run launcher")
	}
	now := s.now()
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return 0, err
	}
	found, err := store.FindUndispatched(ctx, q, now.Add(-undispatchedStaleAfter), now.Add(-undispatchedHorizon), undispatchedBatch)
	release()
	if err != nil {
		return 0, err
	}
	started := 0
	for _, c := range found {
		ok, err := s.startUndispatched(ctx, c)
		if err != nil {
			s.d.Log.ErrorContext(ctx, "task left pending with no workflow could not be started; retried next run", "task_id", c.ID, "error", err)
			continue
		}
		if ok {
			started++
			s.d.Log.InfoContext(ctx, "started task that was left pending with no workflow", "task_id", c.ID)
		}
	}
	return started, nil
}

func (s *Scheduling) startUndispatched(ctx context.Context, c store.UndispatchedTask) (bool, error) {
	ws, err := scope.NewWorkspace(c.WorkspaceID, "")
	if err != nil {
		return false, err
	}
	started := false
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		t, err := s.store.TaskToLaunch(ctx, tx, c.ID)
		if errors.Is(err, store.ErrTaskNotFound) {
			return nil
		}
		if err != nil {
			return err
		}
		if t.Status != "pending" || t.ExecutionID != "" {
			return nil
		}
		if !hasEffectivePolicy(t.Metadata) {
			return fmt.Errorf("task %s has no stored effective policy to start under", t.ID)
		}
		launched, err := s.d.Launcher.Launch(ctx, c.WorkspaceID, t)
		if err != nil {
			return err
		}
		status := "running"
		if launched.Scheduled {
			status = "scheduled"
		}
		ok, err := s.store.MarkLaunched(ctx, tx, t.ID, status, launched.ExecutionID, s.now())
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("failed to update task %s status", t.ID)
		}
		started = true
		return nil
	})
	return started, err
}

func hasEffectivePolicy(metadata map[string]any) bool {
	snapshot, ok := metadata["governance_snapshot"].(map[string]any)
	return ok && snapshot["effective_policy"] != nil
}

// CronSyncReport is how many cron schedules a pass changed and failed to change.
type CronSyncReport struct {
	Changed, Failed int
}

// SyncCronSchedules brings every cron trigger's schedule to what its row
// says, each row read again just before its schedule is applied; one schedule
// Temporal refuses is logged and left to the next pass (sync_cron_schedules).
// It never deletes a schedule.
func (s *Scheduling) SyncCronSchedules(ctx context.Context) (CronSyncReport, error) {
	var r CronSyncReport
	if s.d.Triggers == nil || s.d.Schedules == nil {
		return r, errors.New("the cron schedule sync needs the triggers and schedules ports")
	}
	listed, err := s.d.Triggers.CronTriggers(ctx)
	if err != nil {
		return r, err
	}
	for _, l := range listed {
		row, ok, err := s.d.Triggers.CronTrigger(ctx, l.ID)
		if err != nil {
			return r, err
		}
		if !ok {
			continue
		}
		if row.CronExpression == "" {
			s.d.Log.ErrorContext(ctx, "cron trigger has no cron expression; it has no schedule", "trigger_id", row.ID)
			r.Failed++
			continue
		}
		tz := row.TimeZone
		if tz == "" {
			tz = "UTC"
		}
		changed, err := s.ApplyCronSchedule(ctx, row.ID, row.CronExpression, tz, !row.Active)
		if err != nil {
			s.d.Log.ErrorContext(ctx, "could not bring the schedule of a trigger in line", "trigger_id", row.ID, "error", err)
			r.Failed++
			continue
		}
		if changed {
			r.Changed++
		}
	}
	if r.Changed > 0 || r.Failed > 0 {
		s.d.Log.InfoContext(ctx, "schedule sync", "brought_in_line", r.Changed, "failed", r.Failed)
	}
	return r, nil
}

// ApplyCronSchedule makes the trigger's schedule exactly what the trigger
// says, creating it when missing; it reports whether anything changed
// (TemporalScheduleManager.apply_cron_schedule).
func (s *Scheduling) ApplyCronSchedule(ctx context.Context, triggerID, cronExpression, timezone string, paused bool) (bool, error) {
	if s.d.Schedules == nil || s.d.TriggerQueue == "" {
		return false, errors.New("applying a cron schedule needs the schedules port and the trigger queue")
	}
	wanted := api.CronTriggerSchedule(triggerID, cronExpression, timezone, s.d.TriggerQueue, paused)
	info, err := s.d.Schedules.Describe(ctx, wanted.ID)
	if errors.Is(err, durable.ErrNotFound) {
		return true, s.d.Schedules.Ensure(ctx, wanted)
	}
	if err != nil {
		return false, err
	}
	if cronScheduleMatches(info, cronExpression, timezone, s.d.TriggerQueue, paused) {
		return false, nil
	}
	return true, s.d.Schedules.Ensure(ctx, wanted)
}

func cronScheduleMatches(info durable.ScheduleInfo, cronExpression, timezone, queue string, paused bool) bool {
	payload := firingPayload(info)
	crons := info.Cron
	if len(crons) == 0 {
		if c, ok := payload["cron_expression"].(string); ok && c != "" {
			crons = []string{c}
		}
	}
	return len(crons) == 1 && crons[0] == cronExpression &&
		info.TimeZone == timezone && info.Paused == paused && info.CatchupWindow == api.CronCatchupWindow &&
		payload != nil && reflect.DeepEqual(payload, api.CronFiringData(cronExpression, timezone)) &&
		info.TaskQueue == queue
}

// firingPayload is the firing data a schedule hands its workflow (its second argument).
func firingPayload(info durable.ScheduleInfo) map[string]any {
	if len(info.Args) < 2 {
		return nil
	}
	var m map[string]any
	if json.Unmarshal(info.Args[1], &m) != nil {
		return nil
	}
	return m
}

// scheduledTaskNamespace names the task a schedule firing starts (trigger_execution_activities.py).
const scheduledTaskNamespace = "6f1d4c2a-8e3b-4a57-9c0d-2b7e5f9a1c83"

// ScheduledTaskID is the task a schedule firing starts; every attempt of that
// firing names the same one.
func ScheduledTaskID(workflowID string) string {
	return uuid.NewSHA1(uuid.MustParse(scheduledTaskNamespace), []byte(workflowID)).String()
}

// Trigger outcomes and skip reasons (TriggerOutcome, TriggerSkipReason).
const (
	TriggerSuccess = "success"
	TriggerFailed  = "failed"
	TriggerSkipped = "skipped"

	SkipTriggerInactive   = "trigger_inactive"
	SkipConditionsNotMet  = "conditions_not_met"
	SkipPreviousRunActive = "previous_run_active"
	errTriggerNotFound    = "TriggerNotFoundError"
	errTriggerExecution   = "TriggerExecutionError"
)

// TriggerRun is what execute_trigger_activity answers.
type TriggerRun struct {
	Status      string
	Reason      string
	TaskID      string
	ExecutionID string
	Error       string
	Elapsed     time.Duration
}

// EvaluateTriggerConditions reports whether a trigger's conditions hold for
// the event; any failure means they do not (evaluate_trigger_conditions_activity).
func (s *Scheduling) EvaluateTriggerConditions(ctx context.Context, triggerID string, eventData map[string]any) bool {
	if s.d.Triggers == nil {
		s.d.Log.ErrorContext(ctx, "evaluating trigger conditions needs the triggers port", "trigger_id", triggerID)
		return false
	}
	met, err := s.d.Triggers.EvaluateConditions(ctx, triggerID, eventData)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "error evaluating conditions for trigger", "trigger_id", triggerID, "error", err)
		return false
	}
	return met
}

// ExecuteTrigger fires a trigger for its schedule tick. workflowID is the
// firing's workflow, the same on every attempt: it names the task and ties
// the run back to the tick (execute_trigger_activity). A failure is not
// recorded here: Temporal retries, and the workflow records the firing once.
func (s *Scheduling) ExecuteTrigger(ctx context.Context, triggerID string, data map[string]any, workflowID string) (TriggerRun, error) {
	if workflowID == "" {
		return TriggerRun{}, &durable.ApplicationError{Type: errTriggerExecution, Message: "execute_trigger_activity runs only inside a trigger workflow"}
	}
	if s.d.Triggers == nil {
		return TriggerRun{}, errors.New("executing a trigger needs the triggers port")
	}
	start := s.d.Now()
	trigger, err := s.d.Triggers.Trigger(ctx, triggerID)
	if errors.Is(err, ErrNotFound) {
		return TriggerRun{}, nonRetryable(errTriggerNotFound, fmt.Sprintf("Trigger %s not found", triggerID), err)
	}
	if err != nil {
		return TriggerRun{}, &durable.ApplicationError{Type: errTriggerExecution, Message: fmt.Sprintf("Error retrieving trigger: %v", err), Cause: err}
	}
	if !trigger.Active {
		s.d.Log.InfoContext(ctx, "trigger is inactive, skipping execution", "trigger_id", triggerID, "trigger_name", trigger.Name)
		return TriggerRun{Status: TriggerSkipped, Reason: SkipTriggerInactive}, nil
	}
	firing, err := s.d.Triggers.Fire(ctx, TriggerFire{
		TriggerID: triggerID, Data: data, TaskID: ScheduledTaskID(workflowID),
		Provenance: TaskProvenance{OriginType: "trigger", OriginID: triggerID, CorrelationID: workflowID},
	})
	if errors.Is(err, ErrNotFound) {
		return TriggerRun{}, nonRetryable(errTriggerNotFound, fmt.Sprintf("Trigger %s not found", triggerID), err)
	}
	if err != nil {
		s.d.Log.ErrorContext(ctx, "error executing trigger", "trigger_id", triggerID, "error", err)
		return TriggerRun{}, err
	}
	run := TriggerRun{ExecutionID: firing.ExecutionID, Elapsed: s.d.Now().Sub(start)}
	switch firing.Outcome {
	case "reacted":
		run.Status, run.TaskID = TriggerSuccess, firing.TaskID
	case "skipped":
		run.Status = TriggerSkipped
		switch {
		case firing.BlockedBy != "":
			run.Reason = SkipPreviousRunActive
		case firing.Verdict:
			run.Reason = SkipConditionsNotMet
		default:
			run.Reason = SkipTriggerInactive
		}
	default:
		s.d.Log.WarnContext(ctx, "trigger produced no task", "trigger_id", triggerID, "reason", firing.Reason)
		run.Status, run.Error = TriggerFailed, firing.Reason
	}
	return run, nil
}

// RecordTriggerExecution writes a firing's execution row (record_trigger_execution_activity).
func (s *Scheduling) RecordTriggerExecution(ctx context.Context, triggerID string, r TriggerExecutionRecord) (RecordedTriggerExecution, error) {
	if s.d.Triggers == nil {
		return RecordedTriggerExecution{}, errors.New("recording a trigger execution needs the triggers port")
	}
	rec, err := s.d.Triggers.RecordExecution(ctx, triggerID, r)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "failed to record execution for trigger", "trigger_id", triggerID, "error", err)
	}
	return rec, err
}

// FireBatch fires an open batch; CloseBatch closes it unfired.
func (s *Scheduling) FireBatch(ctx context.Context, b TriggerBatch) (int, error) {
	if s.d.Batches == nil {
		return 0, errors.New("firing a trigger batch needs the trigger batches port")
	}
	return s.d.Batches.Fire(ctx, b)
}

func (s *Scheduling) CloseBatch(ctx context.Context, b TriggerBatch) (int, error) {
	if s.d.Batches == nil {
		return 0, errors.New("closing a trigger batch needs the trigger batches port")
	}
	return s.d.Batches.Close(ctx, b)
}
