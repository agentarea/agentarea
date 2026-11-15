package service

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// Batch workflow names (trigger_batch_workflow.py; runs' TriggerBatchWorkflow).
const (
	TriggerBatchWorkflow = "TriggerBatchWorkflow"
	AddEventSignal       = "add_event"
)

// ErrBatchesNotWired: a batched trigger holds its events in a workflow, and no executor was given.
var ErrBatchesNotWired = errors.New("trigger batches need the workflow executor, which is not wired")

// BatchSpec is the batch workflow's input, as runs' workflows.BatchSpec reads it.
type BatchSpec struct {
	TriggerID      string        `json:"trigger_id"`
	SubscriptionID string        `json:"subscription_id"`
	WorkspaceID    string        `json:"workspace_id"`
	ConfiguredBy   string        `json:"configured_by"`
	Caller         string        `json:"caller"`
	Window         time.Duration `json:"window"`
	MaxEvents      int           `json:"max_events"`
	Pending        []string      `json:"pending"`
}

// OpenBatch is the input of a batch's fire and close (runs' workflows.OpenBatch).
type OpenBatch struct {
	Spec       BatchSpec
	WorkflowID string
	EventIDs   []string
	Reason     string
}

// BatchWindow is a trigger's window as the workflow takes it: 0 for none.
func BatchWindow(b *domain.Batch) (time.Duration, error) {
	if b == nil || b.Window == nil {
		return 0, nil
	}
	return config.ParseDuration(*b.Window)
}

// AddToBatch hands an event to the open batch workflowID, opening one with spec
// (TemporalTriggerBatches.add: signal-with-start, one attempt).
func (s *Service) AddToBatch(ctx context.Context, spec BatchSpec, eventID, workflowID string) error {
	if s.d.Executor == nil {
		return ErrBatchesNotWired
	}
	if spec.Pending == nil {
		spec.Pending = []string{}
	}
	_, err := s.d.Executor.Start(ctx, TriggerBatchWorkflow, workflowID, []any{spec}, durable.StartOptions{
		TaskQueue: s.d.TriggerQueue, StartSignal: AddEventSignal, StartSignalArgs: []any{eventID}, RetryAttempts: 1,
	})
	return err
}

// closeOpenBatches skips every event held in an open batch of the trigger, in sess's transaction,
// and rewrites their tallies (batch_firing.close_open_batches); the batches' workflow ids.
// It runs before the trigger is switched off or deleted: deleting it deletes its reactions.
func (s *Service) closeOpenBatches(ctx context.Context, sess db.Session, triggerID, reason string, now time.Time) ([]string, error) {
	held, err := store.Router{}.HeldByTrigger(ctx, sess, triggerID)
	if err != nil || len(held) == 0 {
		return nil, err
	}
	if err := (store.Router{}).SkipHeld(ctx, sess, triggerID, reason, now); err != nil {
		return nil, err
	}
	var ids []string
	seen := map[string]bool{}
	flows := map[string]bool{}
	for _, h := range held {
		if !seen[h.EventID] {
			seen[h.EventID] = true
			ids = append(ids, h.EventID)
		}
		if h.WorkflowID != "" {
			flows[h.WorkflowID] = true
		}
	}
	recorded, err := store.Router{}.EventsByID(ctx, sess, ids)
	if err != nil {
		return nil, err
	}
	for _, id := range ids {
		e, ok := recorded[id]
		if !ok {
			s.log.WarnContext(ctx, "Event held in a batch is not recorded", "event_id", id, "trigger_id", triggerID)
			continue
		}
		if err := s.retally(ctx, sess, e.Event); err != nil {
			return nil, err
		}
	}
	out := make([]string, 0, len(flows))
	for f := range flows {
		out = append(out, f)
	}
	sort.Strings(out)
	return out, nil
}

// CloseOpenBatches is _close_open_batches for a stream trigger being switched off or deleted:
// call it in the transaction before the trigger write, then CancelBatches after commit.
func (s *Service) CloseOpenBatches(ctx context.Context, sess db.Session, t domain.Trigger, why string) ([]string, error) {
	if t.Type != domain.TypeStream {
		return nil, nil
	}
	return s.closeOpenBatches(ctx, sess, t.ID, why+" while the event waited in a batch", s.now())
}

// CancelBatches cancels the batch workflows CloseOpenBatches returned; without an executor
// they are left to fire, find their events skipped and start nothing.
func (s *Service) CancelBatches(ctx context.Context, triggerID string, workflowIDs []string) {
	for _, id := range workflowIDs {
		if s.d.Executor == nil {
			s.log.InfoContext(ctx, "Batch is not cancelled from here; its events are skipped and it starts no task when its timer fires",
				"workflow_id", id, "trigger_id", triggerID)
			continue
		}
		if err := s.d.Executor.Cancel(ctx, id); err != nil && !errors.Is(err, durable.ErrNotFound) {
			s.log.ErrorContext(ctx, "Could not cancel a trigger batch", "workflow_id", id, "trigger_id", triggerID, "error", err)
		}
	}
}

func (s *Service) retally(ctx context.Context, sess db.Session, e domain.Event) error {
	reacted, skipped, errs, err := store.Router{}.Tally(ctx, sess, e.ID)
	if err != nil {
		return err
	}
	return s.ss.MarkReactions(ctx, sess, e, reacted, skipped, errs)
}

// Batches is the trigger batch workflow's activities (TriggerBatchFirer).
type Batches struct{ s *Service }

// Batches returns the batch firer.
func (s *Service) Batches() *Batches { return &Batches{s: s} }

// Fire fires the trigger once for the batch; how many events it settled.
func (b *Batches) Fire(ctx context.Context, ob OpenBatch) (int, error) {
	return b.settle(ctx, ob, b.fired)
}

// Close records the batch's events skipped with the batch's reason; no task.
func (b *Batches) Close(ctx context.Context, ob OpenBatch) (int, error) {
	return b.settle(ctx, ob, func(context.Context, scope.Workspace, OpenBatch, []domain.RecordedEvent, []store.Cause) (store.Result, error) {
		reason := ob.Reason
		return store.Result{Verdict: domain.VerdictSkipped, Reason: &reason}, nil
	})
}

type decide func(ctx context.Context, ws scope.Workspace, ob OpenBatch, evs []domain.RecordedEvent, causes []store.Cause) (store.Result, error)

func (b *Batches) settle(ctx context.Context, ob OpenBatch, d decide) (int, error) {
	s := b.s
	spec := ob.Spec
	ws, err := scope.NewWorkspace(spec.WorkspaceID, "")
	if err != nil {
		return 0, err
	}
	var evs []domain.RecordedEvent
	var gone bool
	err = s.read(ctx, ws, func(sess db.Session) error {
		ok, err := store.Router{}.SubscriptionExists(ctx, sess, spec.SubscriptionID)
		if err != nil || !ok {
			gone = !ok
			return err
		}
		ids, err := store.Router{}.Unsettled(ctx, sess, spec.SubscriptionID, ob.EventIDs)
		if err != nil || len(ids) == 0 {
			return err
		}
		recorded, err := store.Router{}.EventsByID(ctx, sess, ids)
		if err != nil {
			return err
		}
		for _, id := range ids {
			e, ok := recorded[id]
			if !ok {
				s.log.WarnContext(ctx, "Event of a batch is not in the events read model", "event_id", id)
				continue
			}
			evs = append(evs, e)
		}
		return nil
	})
	if err != nil {
		return 0, err
	}
	if gone {
		s.log.InfoContext(ctx, "Batch of a deleted trigger settles nothing", "workflow_id", ob.WorkflowID, "trigger_id", spec.TriggerID)
		return 0, nil
	}
	if len(evs) == 0 {
		return 0, nil
	}
	causes := make([]store.Cause, len(evs))
	for i, e := range evs {
		corr := e.ID
		if e.CorrelationID != nil && *e.CorrelationID != "" {
			corr = *e.CorrelationID
		}
		tid := spec.TriggerID
		causes[i] = store.Cause{SubscriptionID: spec.SubscriptionID, TriggerID: &tid, StreamID: e.StreamID, EventID: e.ID,
			CorrelationID: corr, CausationID: e.ID}
	}
	result, err := d(ctx, ws, ob, evs, causes)
	if err != nil {
		return 0, err
	}
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		if err := (store.Router{}).Settle(ctx, sess, causes, spec.ConfiguredBy, result, ob.WorkflowID, s.now()); err != nil {
			return err
		}
		for _, e := range evs {
			if err := s.retally(ctx, sess, e.Event); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return 0, err
	}
	for _, e := range evs {
		s.notify(ctx, "event.processing", e.Event)
	}
	s.log.InfoContext(ctx, "Batch settled", "workflow_id", ob.WorkflowID, "trigger_id", spec.TriggerID,
		"events", len(evs), "verdict", result.Verdict)
	return len(evs), nil
}

// notify is a live notice for the events pages; at most once, a failure only logged.
func (s *Service) notify(ctx context.Context, kind string, e domain.Event) {
	if s.d.Broker == nil {
		return
	}
	if err := s.d.Broker.Notify(ctx, events.StreamsLiveChannel(e.WorkspaceID),
		map[string]string{"type": kind, "event_id": e.ID, "stream_id": e.StreamID}); err != nil {
		s.log.WarnContext(ctx, "Live event notice failed", "event_id", e.ID, "error", err)
	}
}

func (b *Batches) fired(ctx context.Context, ws scope.Workspace, ob OpenBatch, evs []domain.RecordedEvent, causes []store.Cause) (store.Result, error) {
	s := b.s
	spec := ob.Spec
	t, err := s.triggerIn(ctx, ws, spec.TriggerID)
	if errors.Is(err, domain.ErrNotFound) {
		r := "trigger no longer exists"
		return store.Result{Verdict: domain.VerdictSkipped, Reason: &r}, nil
	}
	if err != nil {
		return store.Result{}, err
	}
	if !t.IsActive {
		r := "trigger is inactive"
		return store.Result{Verdict: domain.VerdictSkipped, Reason: &r}, nil
	}
	streamName, err := s.streamName(ctx, ws, evs[0].StreamID)
	if err != nil {
		return store.Result{}, err
	}
	entries := make([]any, len(evs))
	for i, e := range evs {
		entries[i] = batchEvent(e.Event)
	}
	data := map[string]any{"events": entries}
	told := TriggerEvent{StreamName: &streamName, Data: data}
	newest := evs[len(evs)-1]
	maxDepth := 0
	for _, e := range evs {
		maxDepth = max(maxDepth, e.Depth)
	}
	d, err := s.FiringDelivery(ctx, ws, newest.Event, t.ID, nil, newest.Data["body"])
	if err != nil {
		return store.Result{}, err
	}
	d.StreamEventID, d.Session = nil, nil
	delivery := &d
	last := causes[len(causes)-1]
	firing, err := s.Fire(ctx, ws, FireRequest{
		TriggerID: t.ID, Data: data, Event: &told, TaskID: domain.BatchTaskID(spec.SubscriptionID, ob.EventIDs[0]),
		Provenance: &runsapi.TaskProvenance{OriginType: "trigger", OriginID: t.ID, CorrelationID: last.CorrelationID,
			CausationID: last.CausationID, Depth: maxDepth},
		RaiseRetryable: true, Caller: spec.Caller, Delivery: delivery, SkipConditions: true,
		Cause: &causes[0], Actor: firstOf(spec.Caller, spec.ConfiguredBy),
	})
	if err != nil {
		return store.Result{}, err
	}
	reason := firing.Reason
	if firing.Outcome == OutcomeReacted {
		reason = fmt.Sprintf("fired with %d events of batch %s", len(evs), ob.WorkflowID)
	}
	res := store.Result{Verdict: verdictOfOutcome(firing.Outcome)}
	if reason != "" {
		res.Reason = &reason
	}
	if firing.TaskID != "" {
		tid := firing.TaskID
		res.TaskID = &tid
	}
	return res, nil
}

func verdictOfOutcome(o string) string {
	switch o {
	case OutcomeReacted:
		return domain.VerdictReacted
	case OutcomeSkipped:
		return domain.VerdictSkipped
	}
	return domain.VerdictError
}

// batchEvent is batches.batch_event without the body read-back (a body moved to files stays a body_ref).
func batchEvent(e domain.Event) map[string]any {
	return map[string]any{"id": e.ID, "kind": e.Kind, "key": e.EventKey,
		"received_at": events.PyISO(e.ReceivedAt.UTC()), "data": e.Data}
}

func (s *Service) streamName(ctx context.Context, ws scope.Workspace, streamID string) (string, error) {
	var name string
	err := s.read(ctx, ws, func(sess db.Session) error {
		names, err := s.ss.StreamNames(ctx, sess, []string{streamID})
		if err != nil {
			return err
		}
		n, ok := names[streamID]
		if !ok {
			return domain.StreamNotFound(streamID)
		}
		name = n
		return nil
	})
	return name, err
}
