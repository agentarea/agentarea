package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// Router is the store of firings, reactions and batches the router and TriggerService.fire write.
type Router struct{}

// Cause is the subscription and bus event a reaction answers (StreamCause).
type Cause struct {
	SubscriptionID string
	TriggerID      *string
	StreamID       string
	EventID        string
	CorrelationID  string
	CausationID    string
}

// CauseOf is StreamCause.of.
func CauseOf(sub domain.Subscription, e domain.Event) Cause {
	corr := e.ID
	if e.CorrelationID != nil && *e.CorrelationID != "" {
		corr = *e.CorrelationID
	}
	return Cause{SubscriptionID: sub.ID, TriggerID: sub.TriggerID, StreamID: e.StreamID, EventID: e.ID,
		CorrelationID: corr, CausationID: e.ID}
}

// Firing is one trigger_executions row a firing writes.
type Firing struct {
	TriggerID     string
	Status        string
	ExecutionTime time.Duration
	TaskID        *string
	ErrorMessage  *string
	TriggerData   map[string]any
	FiredBy       *string
	CreatedBy     string
}

// Result is a reaction's outcome (HandlerResult).
type Result struct {
	Verdict         string
	Reason          *string
	Score           *float64
	TaskID          *string
	DerivedEventIDs []string
	WorkflowID      *string
}

// StatusOf is the execution status a verdict records (_STATUS).
func StatusOf(verdict string) string {
	switch verdict {
	case domain.VerdictReacted:
		return "success"
	case domain.VerdictSkipped:
		return "skipped"
	case domain.VerdictBatched:
		return "batched"
	}
	return "failed"
}

func nu(id string) (uuid.NullUUID, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return uuid.NullUUID{}, err
	}
	return uuid.NullUUID{UUID: u, Valid: true}, nil
}

func pgText(s string) pgtype.Text { return pgtype.Text{String: s, Valid: true} }

func (c Cause) ids() (sub, stream, event uuid.NullUUID, trig uuid.NullUUID, err error) {
	if sub, err = nu(c.SubscriptionID); err != nil {
		return
	}
	if stream, err = nu(c.StreamID); err != nil {
		return
	}
	if event, err = nu(c.EventID); err != nil {
		return
	}
	trig, err = nullUUID(c.TriggerID)
	return
}

// RecordFiring writes a firing's row; its id and time.
func (Router) RecordFiring(ctx context.Context, s db.Session, f Firing, now time.Time) (string, time.Time, error) {
	trig, err := nu(f.TriggerID)
	if err != nil {
		return "", time.Time{}, err
	}
	task, err := nullUUID(f.TaskID)
	if err != nil {
		return "", time.Time{}, err
	}
	data, err := marshal(orEmpty(f.TriggerData))
	if err != nil {
		return "", time.Time{}, err
	}
	r, err := New(s.Q()).InsertFiring(ctx, InsertFiringParams{ID: uuid.New(), TriggerID: trig, At: naive(now), Status: f.Status,
		TaskID: task, ExecutionTimeMs: int32(f.ExecutionTime / time.Millisecond), ErrorMessage: text(f.ErrorMessage),
		TriggerData: data, WorkspaceID: s.Workspace().ID(), CreatedBy: f.CreatedBy, FiredBy: text(f.FiredBy)})
	if err != nil {
		return "", time.Time{}, err
	}
	return r.ID.String(), fromNaive(r.ExecutedAt), nil
}

// RecordCausedFiring writes a stream firing's row as the cause's reaction, once
// (CausedExecutionRepository.create); the row there, whoever wrote it.
func (Router) RecordCausedFiring(ctx context.Context, s db.Session, c Cause, f Firing, now time.Time) (string, time.Time, error) {
	sub, stream, event, trig, err := c.ids()
	if err != nil {
		return "", time.Time{}, err
	}
	task, err := nullUUID(f.TaskID)
	if err != nil {
		return "", time.Time{}, err
	}
	data, err := marshal(orEmpty(f.TriggerData))
	if err != nil {
		return "", time.Time{}, err
	}
	q := New(s.Q())
	if err := q.InsertCausedFiring(ctx, InsertCausedFiringParams{ID: uuid.New(), TriggerID: trig, At: naive(now), Status: f.Status,
		TaskID: task, ExecutionTimeMs: int32(f.ExecutionTime / time.Millisecond), ErrorMessage: text(f.ErrorMessage),
		TriggerData: data, WorkspaceID: s.Workspace().ID(), CreatedBy: f.CreatedBy, FiredBy: text(f.FiredBy),
		SubscriptionID: sub, StreamID: stream, EventID: event, Verdict: pgText(domain.VerdictOf(f.Status)),
		CorrelationID: pgText(c.CorrelationID), CausationID: pgText(c.CausationID)}); err != nil {
		return "", time.Time{}, err
	}
	r, err := q.ReactionOfEvent(ctx, ReactionOfEventParams{SubscriptionID: sub, EventID: event, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return "", time.Time{}, err
	}
	return r.ID.String(), fromNaive(r.ExecutedAt), nil
}

// ReactedTask is the task an earlier attempt's reacted reaction names, nil when none.
func (Router) ReactedTask(ctx context.Context, s db.Session, subscriptionID, eventID string) (*string, error) {
	sub, err := nu(subscriptionID)
	if err != nil {
		return nil, err
	}
	event, err := nu(eventID)
	if err != nil {
		return nil, err
	}
	r, err := New(s.Q()).ReactionOfEvent(ctx, ReactionOfEventParams{SubscriptionID: sub, EventID: event, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil || r.Verdict.String != domain.VerdictReacted {
		return nil, err
	}
	return fromNullUUID(r.TaskID), nil
}

// ClaimFollowUp writes the reacted reaction a routed follow-up stands on; false when one exists.
func (Router) ClaimFollowUp(ctx context.Context, s db.Session, c Cause, createdBy, taskID string, now time.Time) (bool, error) {
	sub, stream, event, trig, err := c.ids()
	if err != nil {
		return false, err
	}
	task, err := nu(taskID)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).ClaimReaction(ctx, ClaimReactionParams{ID: uuid.New(), TriggerID: trig, At: naive(now), TaskID: task,
		WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, SubscriptionID: sub, StreamID: stream, EventID: event,
		Reason: pgText("follow-up queued into running task " + taskID), CorrelationID: pgText(c.CorrelationID),
		CausationID: pgText(c.CausationID)})
	return n > 0, err
}

// DeleteReaction drops the cause's reaction (a released follow-up claim).
func (Router) DeleteReaction(ctx context.Context, s db.Session, subscriptionID, eventID string) error {
	sub, err := nu(subscriptionID)
	if err != nil {
		return err
	}
	event, err := nu(eventID)
	if err != nil {
		return err
	}
	return New(s.Q()).DeleteReactionOfEvent(ctx, DeleteReactionOfEventParams{SubscriptionID: sub, EventID: event, WorkspaceID: s.Workspace().ID()})
}

// StampExecuted sets last_execution_at; the failure count moves only by CountFailure.
func (Router) StampExecuted(ctx context.Context, s db.Session, triggerID string, at time.Time) error {
	u, err := uuid.Parse(triggerID)
	if err != nil {
		return err
	}
	return New(s.Q()).StampTriggerExecuted(ctx, StampTriggerExecutedParams{At: naive(at), ID: u, WorkspaceID: s.Workspace().ID()})
}

// FailureCount is the count after one more consecutive failure.
type FailureCount struct {
	Failures, Threshold int
	Active              bool
}

// CountFailure adds one consecutive failure; false when the trigger is gone.
func (Router) CountFailure(ctx context.Context, s db.Session, triggerID string, at time.Time) (FailureCount, bool, error) {
	u, err := uuid.Parse(triggerID)
	if err != nil {
		return FailureCount{}, false, err
	}
	r, err := New(s.Q()).CountTriggerFailure(ctx, CountTriggerFailureParams{At: naive(at), ID: u, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return FailureCount{}, false, nil
	}
	if err != nil {
		return FailureCount{}, false, err
	}
	return FailureCount{Failures: int(r.ConsecutiveFailures), Threshold: int(r.FailureThreshold), Active: r.IsActive}, true, nil
}

// MarkNeedsNewOwner stops a trigger whose agent is gone; false when no row changed.
func (Router) MarkNeedsNewOwner(ctx context.Context, s db.Session, triggerID string, at time.Time) (bool, error) {
	u, err := uuid.Parse(triggerID)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).MarkTriggerNeedsNewOwner(ctx, MarkTriggerNeedsNewOwnerParams{At: naive(at), ID: u, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}

// NamesTask reports whether a firing of the trigger already records the task.
func (Router) NamesTask(ctx context.Context, s db.Session, triggerID, taskID string) (bool, error) {
	trig, err := nu(triggerID)
	if err != nil {
		return false, err
	}
	task, err := nu(taskID)
	if err != nil {
		return false, err
	}
	return New(s.Q()).TriggerNamesTask(ctx, TriggerNamesTaskParams{TriggerID: trig, TaskID: task, WorkspaceID: s.Workspace().ID()})
}

const givenUp = domain.GaveUpReason

// Recorded is the subscriptions that already reacted to the event, given-up ones left out.
func (Router) Recorded(ctx context.Context, s db.Session, eventID string) (map[string]bool, error) {
	event, err := nu(eventID)
	if err != nil {
		return nil, err
	}
	ids, err := New(s.Q()).RecordedSubscriptions(ctx, RecordedSubscriptionsParams{EventID: event, WorkspaceID: s.Workspace().ID(), GaveUp: givenUp})
	if err != nil {
		return nil, err
	}
	out := make(map[string]bool, len(ids))
	for _, id := range ids {
		out[id.String()] = true
	}
	return out, nil
}

// ForgetGivenUp drops the given-up reaction of the subscription to the event before a rerun.
func (Router) ForgetGivenUp(ctx context.Context, s db.Session, subscriptionID, eventID string) error {
	sub, err := nu(subscriptionID)
	if err != nil {
		return err
	}
	event, err := nu(eventID)
	if err != nil {
		return err
	}
	return New(s.Q()).ForgetGivenUp(ctx, ForgetGivenUpParams{SubscriptionID: sub, EventID: event, WorkspaceID: s.Workspace().ID(), GaveUp: givenUp})
}

// RecordReactionResult inserts the reaction, or gives the row a firing wrote its verdict,
// reason and score; a batched result never overwrites a settled row (ReactionRepository.record).
func (Router) RecordReactionResult(ctx context.Context, s db.Session, c Cause, createdBy string, r Result, now time.Time) error {
	sub, stream, event, trig, err := c.ids()
	if err != nil {
		return err
	}
	task, err := nullUUID(r.TaskID)
	if err != nil {
		return err
	}
	derived := r.DerivedEventIDs
	if derived == nil {
		derived = []string{}
	}
	dj, err := json.Marshal(derived)
	if err != nil {
		return err
	}
	var errMsg pgtype.Text
	if r.Verdict == domain.VerdictError {
		errMsg = text(r.Reason)
	}
	score := pgtype.Float8{}
	if r.Score != nil {
		score = pgtype.Float8{Float64: *r.Score, Valid: true}
	}
	return New(s.Q()).UpsertReaction(ctx, UpsertReactionParams{ID: uuid.New(), TriggerID: trig, At: naive(now),
		Status: StatusOf(r.Verdict), TaskID: task, ErrorMessage: errMsg, WorkflowID: text(r.WorkflowID),
		WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, SubscriptionID: sub, StreamID: stream, EventID: event,
		Verdict: pgText(r.Verdict), Reason: text(r.Reason), Score: score, DerivedEventIds: dj,
		CorrelationID: pgText(c.CorrelationID), CausationID: pgText(c.CausationID)})
}

// Tally counts the event's reactions: all but batched, skipped, errors (ReactionFeedRepository.tally).
func (Router) Tally(ctx context.Context, s db.Session, eventID string) (int, int, int, error) {
	event, err := nu(eventID)
	if err != nil {
		return 0, 0, 0, err
	}
	r, err := New(s.Q()).RouterTally(ctx, RouterTallyParams{EventID: event, WorkspaceID: s.Workspace().ID()})
	return int(r.Reacted), int(r.Skipped), int(r.Errors), err
}

// Unsettled is the batch's events still to settle: held or not recorded yet, in batch order.
func (Router) Unsettled(ctx context.Context, s db.Session, subscriptionID string, eventIDs []string) ([]string, error) {
	if len(eventIDs) == 0 {
		return nil, nil
	}
	sub, err := nu(subscriptionID)
	if err != nil {
		return nil, err
	}
	settled, err := New(s.Q()).SettledOfBatch(ctx, SettledOfBatchParams{SubscriptionID: sub, EventIds: uuids(eventIDs), WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	done := map[string]bool{}
	for _, id := range settled {
		done[id.String()] = true
	}
	var out []string
	for _, id := range eventIDs {
		if !done[id] {
			out = append(out, id)
		}
	}
	return out, nil
}

// Settle turns each cause's held reaction into the batch's verdict; a settled one keeps what it says.
func (Router) Settle(ctx context.Context, s db.Session, causes []Cause, createdBy string, r Result, workflowID string, now time.Time) error {
	if r.Verdict == domain.VerdictBatched {
		return errors.New("a batch settles its events with a final verdict")
	}
	task, err := nullUUID(r.TaskID)
	if err != nil {
		return err
	}
	var errMsg pgtype.Text
	if r.Verdict == domain.VerdictError {
		errMsg = text(r.Reason)
	}
	q := New(s.Q())
	for _, c := range causes {
		sub, stream, event, trig, err := c.ids()
		if err != nil {
			return err
		}
		if err := q.SettleReaction(ctx, SettleReactionParams{ID: uuid.New(), TriggerID: trig, At: naive(now), Status: StatusOf(r.Verdict),
			TaskID: task, ErrorMessage: errMsg, WorkflowID: pgText(workflowID), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy,
			SubscriptionID: sub, StreamID: stream, EventID: event, Verdict: pgText(r.Verdict), Reason: text(r.Reason),
			CorrelationID: pgText(c.CorrelationID), CausationID: pgText(c.CausationID)}); err != nil {
			return err
		}
	}
	return nil
}

// Held is an event held in an open batch of a trigger.
type Held struct{ EventID, WorkflowID string }

// HeldByTrigger is every event held in the trigger's open batches.
func (Router) HeldByTrigger(ctx context.Context, s db.Session, triggerID string) ([]Held, error) {
	trig, err := nu(triggerID)
	if err != nil {
		return nil, err
	}
	rows, err := New(s.Q()).HeldByTrigger(ctx, HeldByTriggerParams{TriggerID: trig, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]Held, 0, len(rows))
	for _, r := range rows {
		out = append(out, Held{EventID: r.EventID.String(), WorkflowID: r.WorkflowID})
	}
	return out, nil
}

// SkipHeld records every held event of the trigger skipped with reason.
func (Router) SkipHeld(ctx context.Context, s db.Session, triggerID, reason string, now time.Time) error {
	trig, err := nu(triggerID)
	if err != nil {
		return err
	}
	return New(s.Q()).SkipHeld(ctx, SkipHeldParams{Reason: pgText(reason), At: naive(now), TriggerID: trig, WorkspaceID: s.Workspace().ID()})
}

// SubscriptionExists reports whether the subscription is still in the session's workspace.
func (Router) SubscriptionExists(ctx context.Context, s db.Session, id string) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, err
	}
	return New(s.Q()).SubscriptionInWorkspace(ctx, SubscriptionInWorkspaceParams{ID: u, WorkspaceID: s.Workspace().ID()})
}

// EventsByID reads the recorded events of ids, keyed by id.
func (Router) EventsByID(ctx context.Context, s db.Session, ids []string) (map[string]domain.RecordedEvent, error) {
	rows, err := New(s.Q()).EventsByIDs(ctx, EventsByIDsParams{WorkspaceID: s.Workspace().ID(), Ids: uuids(ids)})
	if err != nil {
		return nil, err
	}
	out := make(map[string]domain.RecordedEvent, len(rows))
	for _, r := range rows {
		e := ToRecorded(r)
		out[e.ID] = e
	}
	return out, nil
}

func orEmpty(m map[string]any) map[string]any {
	if m == nil {
		return map[string]any{}
	}
	return m
}

// IsForeignKeyViolation reports a write that named a row deleted meanwhile (23503).
func IsForeignKeyViolation(err error) bool {
	var pg *pgconn.PgError
	return errors.As(err, &pg) && pg.Code == "23503"
}
