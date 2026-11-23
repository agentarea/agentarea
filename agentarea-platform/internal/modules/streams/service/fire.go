package service

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

// Firing outcomes (TriggerFiring.outcome).
const (
	OutcomeReacted = "reacted"
	OutcomeSkipped = "skipped"
	OutcomeError   = "error"
)

// Execution statuses a firing records (ExecutionStatus).
const (
	ExecSuccess = "success"
	ExecFailed  = "failed"
	ExecSkipped = "skipped"
)

// ErrTasksNotWired: firing a trigger starts a task, and no task port was given.
var ErrTasksNotWired = errors.New("firing a trigger needs the runs task port, which is not wired")

// ErrFiringTasksNotWired: the firing needs a task read (retry, overlap, saved task) no port gives.
var ErrFiringTasksNotWired = errors.New("firing this trigger needs the task reads port, which is not wired")

// ErrTaskNotStarted: the task was stored but its workflow did not start; the retry starts it.
var ErrTaskNotStarted = errors.New("task stored but its workflow did not start")

// FireRequest is one firing (TriggerService.fire's arguments).
type FireRequest struct {
	TriggerID string
	Data      map[string]any
	// FiredBy is the user who pressed "run now"; empty for the schedule and streams.
	FiredBy string
	// TaskID makes a retried firing idempotent.
	TaskID     string
	Provenance *runsapi.TaskProvenance
	Claim      runsapi.FollowUpClaim
	// RaiseRetryable: only a permanent failure is an error outcome; anything else is returned.
	RaiseRetryable bool
	Event          *TriggerEvent
	// Caller is the admitted sender a messenger event came from; the task is theirs.
	Caller   string
	Delivery *TaskDelivery
	// SkipConditions: a batch's events met the conditions before they joined it.
	SkipConditions bool
	// Cause makes every row the firing writes that subscription's reaction to that event.
	Cause *store.Cause
	// Actor is who the rows are written as; empty is the trigger's creator.
	Actor string
}

// ExecutionRef is the trigger_executions row a firing wrote.
type ExecutionRef struct {
	ID           string
	ExecutedAt   time.Time
	Status       string
	TaskID       *string
	ErrorMessage *string
}

// Firing is what a firing did (TriggerFiring).
type Firing struct {
	Outcome   string
	Reason    string
	TaskID    string
	BlockedBy string
	// Verdict says the conditions were evaluated; Score is how sure their verdict was.
	Verdict   bool
	Score     *float64
	Execution *ExecutionRef
}

// Fire fires a trigger of ws once (TriggerService.fire). domain.ErrNotFound for a trigger that is gone.
func (s *Service) Fire(ctx context.Context, ws scope.Workspace, r FireRequest) (Firing, error) {
	if s.d.Tasks == nil {
		return Firing{}, ErrTasksNotWired
	}
	t, err := s.triggerIn(ctx, ws, r.TriggerID)
	if err != nil {
		return Firing{}, err
	}
	f := firer{s: s, ws: ws, t: t, r: r}
	return f.fire(ctx)
}

// FireManually is the run and execute routes' firing: the caller, who may edit the trigger,
// fires it once with data; the run is theirs and runs on a trigger switched off too.
func (s *Service) FireManually(ctx context.Context, triggerID string, data map[string]any) (Firing, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return Firing{}, err
	}
	if c.UserID == "" {
		return Firing{}, authn.ErrUnauthenticated
	}
	if err := s.perms.Require(ctx, c, "edit", "trigger", triggerID); err != nil {
		return Firing{}, err
	}
	return s.Fire(ctx, c.Workspace, FireRequest{TriggerID: triggerID, Data: data, FiredBy: c.UserID, Actor: c.UserID})
}

func (s *Service) triggerIn(ctx context.Context, ws scope.Workspace, id string) (domain.Trigger, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return domain.Trigger{}, domain.ErrNotFound
	}
	var t domain.Trigger
	var ok bool
	err = s.read(ctx, ws, func(sess db.Session) error {
		t, ok, err = s.st.Get(ctx, sess, u)
		return err
	})
	if err != nil {
		return t, err
	}
	if !ok {
		return t, domain.ErrNotFound
	}
	return t, nil
}

type firer struct {
	s  *Service
	ws scope.Workspace
	t  domain.Trigger
	r  FireRequest
}

func (f firer) fire(ctx context.Context) (Firing, error) {
	t, r := f.t, f.r
	if !t.IsActive && r.FiredBy == "" {
		f.s.log.WarnContext(ctx, "Attempted to execute inactive trigger", "trigger_id", t.ID)
		ex, err := f.record(ctx, ExecSkipped, "Trigger is inactive", "", 0)
		return Firing{Outcome: OutcomeSkipped, Reason: "trigger is inactive", Execution: ex}, err
	}
	if r.FiredBy != "" {
		c, ok := authn.CallerFrom(ctx)
		if !ok {
			return Firing{}, authn.ErrUnauthenticated
		}
		if err := f.s.perms.Require(ctx, c, "execute", "agent", t.AgentID); err != nil {
			return Firing{}, err
		}
	}
	stands, err := f.agentStands(ctx)
	if err != nil {
		return Firing{}, err
	}
	if !stands {
		reason := fmt.Sprintf("agent_unavailable: agent %s is gone or inactive", t.AgentID)
		if err := f.s.d.DB.Write(ctx, f.ws, func(ctx context.Context, sess db.Session) error {
			_, err := store.Router{}.MarkNeedsNewOwner(ctx, sess, t.ID, f.s.now())
			return err
		}); err != nil {
			return Firing{}, err
		}
		ex, err := f.record(ctx, ExecFailed, reason, "", 0)
		return Firing{Outcome: OutcomeError, Reason: reason, Execution: ex}, err
	}
	var def *TaskDefinitionText
	if t.TaskDefinitionID != nil {
		if f.s.d.FiringTasks == nil {
			return Firing{}, ErrFiringTasksNotWired
		}
		d, ok, err := f.s.d.FiringTasks.Definition(ctx, f.ws, *t.TaskDefinitionID)
		if err != nil {
			return Firing{}, err
		}
		if !ok {
			reason := fmt.Sprintf("Task definition %s no longer exists", *t.TaskDefinitionID)
			ex, err := f.record(ctx, ExecFailed, reason, "", 0)
			return Firing{Outcome: OutcomeError, Reason: reason, Execution: ex}, err
		}
		def = &TaskDefinitionText{Description: d.Description, Parameters: d.Parameters}
	}
	if r.TaskID != "" {
		if done, firing, err := f.retried(ctx, def); done || err != nil {
			return firing, err
		}
	}
	if t.Type == domain.TypeCron && r.FiredBy == "" {
		if f.s.d.FiringTasks == nil {
			return Firing{}, ErrFiringTasksNotWired
		}
		running, err := f.s.d.FiringTasks.OpenRunFrom(ctx, f.ws, "trigger", t.ID)
		if err != nil {
			return Firing{}, err
		}
		if running != "" {
			reason := fmt.Sprintf("The previous run is still going (task %s)", running)
			f.s.log.InfoContext(ctx, "Trigger skipped", "trigger_id", t.ID, "reason", reason)
			ex, err := f.record(ctx, ExecSkipped, reason, "", 0)
			return Firing{Outcome: OutcomeSkipped, Reason: reason, Execution: ex, BlockedBy: running}, err
		}
	}
	start := time.Now()
	firing, ferr := f.start(ctx, def)
	if ferr == nil {
		return firing, nil
	}
	return f.failed(ctx, firing, ferr, time.Since(start))
}

func (f firer) agentStands(ctx context.Context) (bool, error) {
	if f.s.d.Agents == nil {
		return false, errors.New("a trigger cannot fire without the agent lookup")
	}
	return f.s.d.Agents.AgentExists(ctx, f.ws, f.t.AgentID)
}

// retried handles a firing whose task an earlier attempt stored: true when it decided.
func (f firer) retried(ctx context.Context, def *TaskDefinitionText) (bool, Firing, error) {
	t, r := f.t, f.r
	if f.s.d.FiringTasks == nil {
		return true, Firing{}, ErrFiringTasksNotWired
	}
	existing, ok, err := f.s.d.FiringTasks.Task(ctx, f.ws, r.TaskID)
	if err != nil || !ok {
		return false, Firing{}, err
	}
	if existing.ExecutionID == "" && (existing.Status == "pending" || (r.RaiseRetryable && existing.Status == "failed")) {
		in, asks, err := composeTaskInput(t, r.Data, r.Event, def)
		if err != nil {
			return true, Firing{}, err
		}
		if !asks {
			f.s.log.WarnContext(ctx, "Not restarting the task of a trigger: "+NoTaskText, "task_id", r.TaskID, "trigger_id", t.ID)
			ex, err := f.record(ctx, ExecFailed, NoTaskText, "", 0)
			return true, Firing{Outcome: OutcomeError, Reason: NoTaskText, Execution: ex}, err
		}
		if err := f.s.d.FiringTasks.RestartUndispatched(ctx, f.ws, r.TaskID, in.message); err != nil {
			return true, Firing{}, err
		}
		ex, err := f.startedOnce(ctx)
		return true, Firing{Outcome: OutcomeReacted, Reason: "task started on retry", TaskID: r.TaskID, Execution: ex}, err
	}
	ex, err := f.startedOnce(ctx)
	return true, Firing{Outcome: OutcomeReacted, Reason: "task already started", TaskID: r.TaskID, Execution: ex}, err
}

func (f firer) startedOnce(ctx context.Context) (*ExecutionRef, error) {
	var named bool
	err := f.s.read(ctx, f.ws, func(sess db.Session) error {
		var err error
		named, err = store.Router{}.NamesTask(ctx, sess, f.t.ID, f.r.TaskID)
		return err
	})
	if err != nil || named {
		return nil, err
	}
	return f.record(ctx, ExecSuccess, "", f.r.TaskID, 0)
}

// start evaluates the conditions, then submits the task; every outcome after a verdict carries it.
func (f firer) start(ctx context.Context, def *TaskDefinitionText) (Firing, error) {
	t, r := f.t, f.r
	if len(t.Conditions) == 0 || r.SkipConditions {
		return f.submit(ctx, def)
	}
	v, err := f.s.evaluate(ctx, f.ws, t, r.Data)
	if err != nil {
		return Firing{}, err
	}
	if !v.Met {
		f.s.log.InfoContext(ctx, "Trigger conditions not met, skipping execution", "trigger_id", t.ID)
		ex, err := f.record(ctx, ExecSkipped, "Trigger conditions not met", "", 0)
		return Firing{Outcome: OutcomeSkipped, Reason: v.Reason, Verdict: true, Score: v.Score, Execution: ex}, err
	}
	firing, err := f.submit(ctx, def)
	firing.Verdict, firing.Score = true, v.Score
	return firing, err
}

func (f firer) submit(ctx context.Context, def *TaskDefinitionText) (Firing, error) {
	t, r := f.t, f.r
	began := time.Now()
	in, asks, err := composeTaskInput(t, r.Data, r.Event, def)
	if err != nil {
		return Firing{}, err
	}
	if !asks {
		ex, err := f.record(ctx, ExecFailed, NoTaskText, "", time.Since(began))
		return Firing{Outcome: OutcomeError, Reason: NoTaskText, Execution: ex}, err
	}
	params := buildTaskParameters(t, r.Data, r.FiredBy, r.Delivery, def, f.s.now())
	f.s.extractParameters(ctx, f.ws, t, askedParameters(t, def), r.Data, params)
	params = in.stamp(params)
	taskID := r.TaskID
	if taskID == "" {
		taskID = uuid.NewString()
	}
	prov := runsapi.TaskProvenance{OriginType: "trigger", OriginID: t.ID}
	if r.Provenance != nil {
		prov = *r.Provenance
	}
	if who := firstOf(r.FiredBy, r.Caller); who != "" {
		prov.SourceIdentity = "user:" + who
	} else {
		prov.SourceIdentity = ""
	}
	prov.TaskDefinitionID = ""
	if t.TaskDefinitionID != nil {
		prov.TaskDefinitionID = *t.TaskDefinitionID
	}
	sub, err := f.s.d.Tasks.Submit(ctx, f.ws, runsapi.TaskRequest{
		TaskID: taskID, AgentID: t.AgentID, Description: in.message,
		UserID: firstOf(r.FiredBy, r.Caller, t.CreatedBy), Parameters: params, Provenance: prov, Claim: r.Claim,
	})
	if err != nil {
		return Firing{}, err
	}
	if r.RaiseRetryable && sub.Status == "failed" && sub.ExecutionID == "" {
		return Firing{}, fmt.Errorf("%w: task %s", ErrTaskNotStarted, sub.TaskID)
	}
	if sub.Routed {
		f.s.log.InfoContext(ctx, "Routed follow-up to existing workflow", "trigger_id", t.ID)
		if r.Delivery != nil && r.Delivery.Address != nil && f.s.d.Turns != nil {
			if err := f.s.d.Turns.Begin(ctx, sub.TaskID, r.Delivery.Address); err != nil {
				f.s.log.ErrorContext(ctx, "The follow-up's turn is answered at the message that started its task",
					"task_id", sub.TaskID, "trigger_id", t.ID, "error", err)
			}
		}
	} else {
		f.s.log.InfoContext(ctx, "Submitted task for trigger", "trigger_id", t.ID, "task_id", sub.TaskID)
	}
	ex, rerr := f.record(ctx, ExecSuccess, "", sub.TaskID, time.Since(began))
	if rerr != nil {
		f.s.log.WarnContext(ctx, "Failed to record execution history (task was created successfully)", "trigger_id", t.ID, "error", rerr)
		ex = nil
	}
	return Firing{Outcome: OutcomeReacted, TaskID: sub.TaskID, Execution: ex}, nil
}

// failed is fire's except branch: a spend cap is skipped, a retryable failure is returned, the rest recorded.
func (f firer) failed(ctx context.Context, firing Firing, err error, took time.Duration) (Firing, error) {
	if errors.Is(err, runsapi.ErrSpendCapReached) {
		f.s.log.InfoContext(ctx, "Trigger refused by a spend cap", "trigger_id", f.t.ID, "error", err)
		ex, rerr := f.record(ctx, ExecSkipped, err.Error(), "", 0)
		return Firing{Outcome: OutcomeSkipped, Reason: err.Error(), Verdict: firing.Verdict, Score: firing.Score, Execution: ex}, rerr
	}
	if f.r.RaiseRetryable && !Permanent(err) {
		f.s.log.WarnContext(ctx, "Trigger failed in a way a retry may not repeat; the event is retried", "trigger_id", f.t.ID, "error", err)
		return Firing{}, err
	}
	f.s.log.ErrorContext(ctx, "Error executing trigger", "trigger_id", f.t.ID, "error", err)
	ex, rerr := f.record(ctx, ExecFailed, err.Error(), "", took)
	if rerr != nil {
		f.s.log.WarnContext(ctx, "Failed to record execution failure", "trigger_id", f.t.ID, "error", rerr)
		ex = nil
	}
	return Firing{Outcome: OutcomeError, Reason: err.Error(), Verdict: firing.Verdict, Score: firing.Score, Execution: ex}, nil
}

// Permanent is failures.is_permanent: a failure a retry of the same event repeats.
func Permanent(err error) bool {
	var invalid *domain.ValidationError
	return errors.Is(err, runsapi.ErrAgentNotFound) || errors.Is(err, runsapi.ErrAgentArchived) ||
		errors.Is(err, runsapi.ErrModelNotConfigured) || errors.Is(err, runsapi.ErrTaskPolicyRejected) ||
		errors.Is(err, runsapi.ErrSpendCapReached) || errors.Is(err, domain.ErrConditionUndecided) ||
		errors.Is(err, authz.ErrDenied) || errors.Is(err, errEventDataMismatch) || errors.As(err, &invalid)
}

func firstOf(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

// record is record_execution: the row (the cause's reaction when there is one), then the
// trigger's last run, failure count and, at its threshold, the trigger switched off.
func (f firer) record(ctx context.Context, status, reason, taskID string, took time.Duration) (*ExecutionRef, error) {
	t, r := f.t, f.r
	now := f.s.now()
	row := store.Firing{TriggerID: t.ID, Status: status, ExecutionTime: took, TriggerData: r.Data,
		CreatedBy: firstOf(r.Actor, t.CreatedBy)}
	if reason != "" {
		row.ErrorMessage = &reason
	}
	if taskID != "" {
		row.TaskID = &taskID
	}
	if r.FiredBy != "" {
		row.FiredBy = &r.FiredBy
	}
	var ref ExecutionRef
	var disabled *domain.Trigger
	err := f.s.d.DB.Write(ctx, f.ws, func(ctx context.Context, sess db.Session) error {
		var err error
		if r.Cause != nil {
			ref.ID, ref.ExecutedAt, err = store.Router{}.RecordCausedFiring(ctx, sess, *r.Cause, row, now)
		} else {
			ref.ID, ref.ExecutedAt, err = store.Router{}.RecordFiring(ctx, sess, row, now)
		}
		if err != nil {
			return err
		}
		ref.Status, ref.TaskID, ref.ErrorMessage = status, row.TaskID, row.ErrorMessage
		if status == ExecSkipped {
			return nil
		}
		disabled, err = f.s.track(ctx, sess, t, status, firstOf(r.Actor, t.CreatedBy), now)
		return err
	})
	if err != nil {
		return nil, fmt.Errorf("failed to record trigger execution: %w", err)
	}
	if disabled != nil {
		f.s.applySchedule(ctx, *disabled)
	}
	return &ref, nil
}

// track is _update_trigger_execution_tracking: stamp the run, count a failure, switch off at the threshold.
func (s *Service) track(ctx context.Context, sess db.Session, t domain.Trigger, status, actor string, now time.Time) (*domain.Trigger, error) {
	if err := (store.Router{}).StampExecuted(ctx, sess, t.ID, now); err != nil {
		return nil, err
	}
	if status == ExecSuccess {
		return nil, nil
	}
	return s.countFailure(ctx, sess, t.ID, actor, now)
}

// countFailure is _count_failure: one more consecutive failure; at the threshold the trigger is
// switched off (its open batches closed, trigger.auto_disabled written) and returned.
func (s *Service) countFailure(ctx context.Context, sess db.Session, triggerID, actor string, now time.Time) (*domain.Trigger, error) {
	count, ok, err := store.Router{}.CountFailure(ctx, sess, triggerID, now)
	if err != nil || !ok || !count.Active || count.Failures < count.Threshold {
		return nil, err
	}
	s.log.WarnContext(ctx, "Disabling trigger after consecutive failures, its failure threshold",
		"trigger_id", triggerID, "failures", count.Failures)
	cur, found, err := s.st.Get(ctx, sess, uuid.MustParse(triggerID))
	if err != nil || !found {
		return nil, err
	}
	cur.IsActive = false
	if _, err := s.st.Update(ctx, sess, cur, now); err != nil {
		return nil, err
	}
	if cur.Type == domain.TypeStream {
		if _, err := s.closeOpenBatches(ctx, sess, cur.ID, "trigger disabled while the event waited in a batch", now); err != nil {
			return nil, err
		}
	}
	if err := events.Publish(ctx, sess, actor, events.NewEnvelope("trigger.auto_disabled", map[string]any{
		"trigger_id": triggerID, "consecutive_failures": count.Failures, "disabled_at": naiveISO(now),
		"reason": "consecutive_failures_threshold_exceeded", "aggregate_id": triggerID, "aggregate_type": "trigger",
	})); err != nil {
		return nil, err
	}
	return &cur, nil
}

// CanFire reports whether the task port a firing starts its task through is wired.
func (s *Service) CanFire() bool { return s.d.Tasks != nil }

// Trigger reads a trigger of ws; domain.ErrNotFound when it is gone.
func (s *Service) Trigger(ctx context.Context, ws scope.Workspace, id string) (domain.Trigger, error) {
	return s.triggerIn(ctx, ws, id)
}

// AgentStands is agent_stands: the agent a trigger runs still exists and is active.
func (s *Service) AgentStands(ctx context.Context, ws scope.Workspace, agentID string) (bool, error) {
	return firer{s: s, ws: ws, t: domain.Trigger{AgentID: agentID}}.agentStands(ctx)
}

// MarkNeedsNewOwner stops a trigger whose agent is gone; false when no row changed.
func (s *Service) MarkNeedsNewOwner(ctx context.Context, ws scope.Workspace, triggerID string) (bool, error) {
	var changed bool
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		var err error
		changed, err = store.Router{}.MarkNeedsNewOwner(ctx, sess, triggerID, s.now())
		return err
	})
	return changed, err
}

// StreamName is the name of a stream of ws; a StreamNotFound error when it is gone.
func (s *Service) StreamName(ctx context.Context, ws scope.Workspace, streamID string) (string, error) {
	return s.streamName(ctx, ws, streamID)
}

// TaskOrigin is FiringTasks.Origin; ErrFiringTasksNotWired without the port.
func (s *Service) TaskOrigin(ctx context.Context, ws scope.Workspace, taskID string) (api.TaskOrigin, bool, error) {
	if s.d.FiringTasks == nil {
		return api.TaskOrigin{}, false, ErrFiringTasksNotWired
	}
	return s.d.FiringTasks.Origin(ctx, ws, taskID)
}

// Settings are the stream and trigger settings the service runs with.
func (s *Service) Settings() Settings { return s.d.Settings }

// Now is the service's clock in UTC.
func (s *Service) Now() time.Time { return s.now() }
