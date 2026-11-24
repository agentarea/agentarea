package router

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

// HandedOver is the reason of an external reaction: the event went to delivery.
const HandedOver = "handed to delivery"

// Fields of an external delivery beside the encoded event.
const (
	externalSubscription = "subscription"
	externalWorkspace    = "workspace"
	externalOwner        = "owner"
	externalAttempt      = "attempt"
	externalDue          = "due"
)

func settled(r store.Result) Finish {
	return func(context.Context, db.Session) (store.Result, error) { return r, nil }
}

func errorResult(reason string) store.Result {
	return store.Result{Verdict: domain.VerdictError, Reason: &reason}
}

func skippedResult(reason string) store.Result {
	return store.Result{Verdict: domain.VerdictSkipped, Reason: &reason}
}

func depthExceeded(depth, limit int) string {
	return fmt.Sprintf("causation depth %d exceeds %d", depth, limit)
}

func subWorkspace(sub domain.Subscription) (scope.Workspace, error) {
	return scope.NewWorkspace(sub.WorkspaceID, "")
}

// TriggerHandler is TriggerSubscriptionHandler: admit the sender, check the agent stands, fire.
// It fires in Prepare, with no transaction open; the firing writes the reaction as it goes.
type TriggerHandler struct{ d Deps }

func (h *TriggerHandler) Prepare(ctx context.Context, sub domain.Subscription, e domain.Event) (Finish, error) {
	r, err := h.handle(ctx, sub, e)
	if err != nil {
		return nil, err
	}
	return settled(r), nil
}

func (h *TriggerHandler) handle(ctx context.Context, sub domain.Subscription, e domain.Event) (store.Result, error) {
	if sub.TriggerID == nil {
		return store.Result{}, fmt.Errorf("trigger subscription %s names no trigger", sub.ID)
	}
	ws, err := subWorkspace(sub)
	if err != nil {
		return store.Result{}, err
	}
	svc := h.d.Service
	t, err := svc.Trigger(ctx, ws, *sub.TriggerID)
	if errors.Is(err, domain.ErrNotFound) {
		return errorResult("trigger no longer exists"), nil
	} else if err != nil {
		return store.Result{}, err
	}
	claim := &followUpClaim{d: h.d, ws: ws, cause: store.CauseOf(sub, e), createdBy: sub.CreatedBy}
	routedTo, err := claim.deliveredTo(ctx)
	if err != nil {
		return store.Result{}, err
	}
	if routedTo != nil {
		reason := "follow-up already queued into running task " + *routedTo
		return store.Result{Verdict: domain.VerdictReacted, Reason: &reason, TaskID: routedTo}, nil
	}
	if !t.IsActive {
		return skippedResult("trigger is inactive"), nil
	}
	limit := h.d.Settings.ForwardDepth
	if depth := e.Depth + 1; depth > limit {
		return skippedResult(depthExceeded(depth, limit)), nil
	}
	own, err := h.ownTaskInChain(ctx, ws, t.ID, e, limit)
	if err != nil {
		return store.Result{}, err
	}
	if own != "" {
		return skippedResult(fmt.Sprintf("the event comes from task %s, which this trigger started", own)), nil
	}
	door, err := svc.EventAdmission(ctx, ws, e)
	if errors.Is(err, service.ErrAdmissionLookup) {
		h.d.Log.ErrorContext(ctx, "Event cannot be admitted", "event_id", e.ID, "error", err)
		return errorResult("sender admission: " + err.Error()), nil
	} else if err != nil {
		return store.Result{}, err
	}
	var caller, batchKey string
	if door != nil {
		admitted, refused, err := svc.Admit(ctx, ws, t, e, *door)
		if errors.Is(err, service.ErrAdmissionUnwired) {
			return errorResult(err.Error()), nil
		}
		if err != nil {
			return store.Result{}, err
		}
		if refused != "" {
			return skippedResult(refused), nil
		}
		caller, batchKey = admitted.UserID, firstOf(admitted.Sender, admitted.UserID)
	}
	stands, err := svc.AgentStands(ctx, ws, t.AgentID)
	if err != nil {
		return store.Result{}, err
	}
	if !stands {
		changed, err := svc.MarkNeedsNewOwner(ctx, ws, t.ID)
		if err != nil {
			return store.Result{}, err
		}
		if !changed {
			return store.Result{}, fmt.Errorf("trigger %s could not be stopped for attention: no row updated", t.ID)
		}
		h.d.Log.WarnContext(ctx, "Trigger stopped: its agent is gone or inactive", "trigger_id", t.ID, "agent_id", t.AgentID)
		return errorResult(fmt.Sprintf("agent_unavailable: agent %s is gone or inactive; the trigger needs attention", t.AgentID)), nil
	}
	name, err := svc.StreamName(ctx, ws, e.StreamID)
	if err != nil {
		return store.Result{}, err
	}
	body, err := svc.EventBody(ctx, e)
	if err != nil {
		return store.Result{}, err
	}
	te := service.StreamTriggerEvent(e, name, body)
	if t.Batch != nil {
		return h.joinBatch(ctx, t, sub, e, te.Data, caller, batchKey)
	}
	delivery, err := svc.FiringDelivery(ctx, ws, e, t.ID, t.Session, te.Data["body"])
	if err != nil {
		return store.Result{}, err
	}
	text := delivery.Text
	if (text == nil || *text == "") && len(e.Attachments) > 0 {
		line := service.FilesLine(e.Attachments)
		text = &line
	}
	if text != nil {
		if _, has := te.Data["text"]; !has {
			withText := make(map[string]any, len(te.Data)+1)
			for k, v := range te.Data {
				withText[k] = v
			}
			withText["text"] = *text
			te.Data = withText
		}
	}
	cause := store.CauseOf(sub, e)
	firing, err := svc.Fire(ctx, ws, service.FireRequest{
		TriggerID:   t.ID,
		Data:        te.Data,
		Event:       &te,
		StreamEvent: &e,
		TaskID:      domain.TaskIDFor(sub.ID, e.ID),
		Provenance: &runsapi.TaskProvenance{
			OriginType: "trigger", OriginID: t.ID, CorrelationID: cause.CorrelationID,
			CausationID: cause.CausationID, Depth: e.Depth,
		},
		Claim:          claim,
		RaiseRetryable: true,
		Delivery:       &delivery,
		Cause:          &cause,
		Caller:         caller,
		Actor:          firstOf(caller, sub.CreatedBy),
	})
	if errors.Is(err, domain.ErrNotFound) {
		return errorResult("trigger no longer exists"), nil
	} else if err != nil {
		return store.Result{}, err
	}
	res := store.Result{Verdict: verdictOf(firing.Outcome), Score: firing.Score}
	if firing.Reason != "" {
		reason := firing.Reason
		res.Reason = &reason
	}
	if firing.TaskID != "" {
		id := firing.TaskID
		res.TaskID = &id
	}
	return res, nil
}

func verdictOf(outcome string) string {
	switch outcome {
	case service.OutcomeReacted:
		return domain.VerdictReacted
	case service.OutcomeSkipped:
		return domain.VerdictSkipped
	}
	return domain.VerdictError
}

// joinBatch hands an admitted event that meets the conditions to the trigger's open batch; each
// admitted sender has a batch of their own (batchKey), also when several listed senders run as
// the one user who answers for them.
func (h *TriggerHandler) joinBatch(ctx context.Context, t domain.Trigger, sub domain.Subscription, e domain.Event, data map[string]any, caller, batchKey string) (store.Result, error) {
	if len(t.Conditions) > 0 {
		v, err := h.d.Service.Evaluate(ctx, t, data)
		if err != nil {
			h.d.Log.WarnContext(ctx, "Trigger could not decide an event", "trigger_id", t.ID, "event_id", e.ID, "error", err)
			return errorResult(err.Error()), nil
		}
		if !v.Met {
			reason := v.Reason
			return store.Result{Verdict: domain.VerdictSkipped, Reason: &reason, Score: v.Score}, nil
		}
	}
	window, err := service.BatchWindow(t.Batch)
	if err != nil {
		return errorResult(err.Error()), nil
	}
	limit := h.d.Settings.BatchMaxEvents
	most := limit
	if t.Batch.MaxEvents != nil && *t.Batch.MaxEvents > 0 && *t.Batch.MaxEvents < limit {
		most = *t.Batch.MaxEvents
	}
	workflowID := domain.BatchWorkflowID(t.ID, batchKey)
	spec := service.BatchSpec{
		TriggerID: t.ID, SubscriptionID: sub.ID, WorkspaceID: sub.WorkspaceID, ConfiguredBy: sub.CreatedBy,
		Caller: caller, Window: window, MaxEvents: most,
	}
	if err := h.d.Service.AddToBatch(ctx, spec, e.ID, workflowID); err != nil {
		return store.Result{}, err
	}
	reason := "held in batch " + workflowID
	return store.Result{Verdict: domain.VerdictBatched, Reason: &reason, WorkflowID: &workflowID}, nil
}

// ownTaskInChain is own_task_in_chain: the task of the trigger the event descends from, "" when none.
func (h *TriggerHandler) ownTaskInChain(ctx context.Context, ws scope.Workspace, triggerID string, e domain.Event, maxHops int) (string, error) {
	taskID := taskOf(e.SourceType, e.Subject)
	for range maxHops {
		if taskID == "" {
			return "", nil
		}
		origin, ok, err := h.d.Service.TaskOrigin(ctx, ws, taskID)
		if err != nil {
			return "", err
		}
		if !ok {
			return "", nil
		}
		if origin.OriginType == "trigger" && origin.OriginID == triggerID {
			return taskID, nil
		}
		cause, err := uuid.Parse(origin.CausationID)
		if err != nil {
			return "", nil
		}
		var found map[string]domain.RecordedEvent
		if err := readIn(ctx, h.d, ws, func(sess db.Session) error {
			var err error
			found, err = store.Router{}.EventsByID(ctx, sess, []string{cause.String()})
			return err
		}); err != nil {
			return "", err
		}
		ev, ok := found[cause.String()]
		if !ok {
			return "", nil
		}
		taskID = taskOf(ev.SourceType, ev.Subject)
	}
	return "", nil
}

func taskOf(sourceType, subject *string) string {
	if sourceType == nil || *sourceType != domain.PlatformSourceType || subject == nil {
		return ""
	}
	id, err := uuid.Parse(*subject)
	if err != nil {
		return ""
	}
	return id.String()
}

func readIn(ctx context.Context, d Deps, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

// followUpClaim is SubscriptionFollowUpClaim: the reaction row of one (subscription, event),
// committed before a routed follow-up's signal.
type followUpClaim struct {
	d         Deps
	ws        scope.Workspace
	cause     store.Cause
	createdBy string
}

var _ runsapi.FollowUpClaim = (*followUpClaim)(nil)

func (c *followUpClaim) deliveredTo(ctx context.Context) (*string, error) {
	var id *string
	err := readIn(ctx, c.d, c.ws, func(sess db.Session) error {
		var err error
		id, err = store.Router{}.ReactedTask(ctx, sess, c.cause.SubscriptionID, c.cause.EventID)
		return err
	})
	return id, err
}

func (c *followUpClaim) Claim(ctx context.Context, taskID string) (bool, error) {
	var inserted bool
	err := c.d.DB.Write(ctx, c.ws, func(ctx context.Context, sess db.Session) error {
		var err error
		inserted, err = store.Router{}.ClaimFollowUp(ctx, sess, c.cause, c.createdBy, taskID, c.d.Now().UTC())
		return err
	})
	return inserted, err
}

func (c *followUpClaim) Release(ctx context.Context) error {
	return c.d.DB.Write(ctx, c.ws, func(ctx context.Context, sess db.Session) error {
		return store.Router{}.DeleteReaction(ctx, sess, c.cause.SubscriptionID, c.cause.EventID)
	})
}

// ForwardHandler copies an event into the forward's output streams, in the reaction's transaction.
type ForwardHandler struct{ d Deps }

func (h *ForwardHandler) Prepare(_ context.Context, sub domain.Subscription, e domain.Event) (Finish, error) {
	limit := h.d.Settings.ForwardDepth
	depth := e.Depth + 1
	if depth > limit {
		return settled(errorResult(depthExceeded(depth, limit))), nil
	}
	return func(ctx context.Context, sess db.Session) (store.Result, error) {
		copyID, err := domain.DerivedEventID(sub.ID, e.ID)
		if err != nil {
			return store.Result{}, err
		}
		outputs := append([]string(nil), sub.OutputStreamIDs...)
		sort.Strings(outputs)
		published := []string{}
		for _, output := range outputs {
			id, err := domain.DerivedEventID(copyID, output)
			if err != nil {
				return store.Result{}, err
			}
			ev := derived(e, sub, output, id, "stream:"+e.StreamID, e.StreamID+":"+e.ID, depth)
			ev.Attachments = e.Attachments
			if _, err := h.d.Service.Append(ctx, sess, ev); errors.Is(err, domain.ErrStreamNotFound) {
				h.d.Log.InfoContext(ctx, "Forward skips an output that no longer exists", "subscription_id", sub.ID, "stream_id", output)
				continue
			} else if err != nil {
				return store.Result{}, err
			}
			published = append(published, id)
		}
		return store.Result{Verdict: domain.VerdictReacted, DerivedEventIDs: published}, nil
	}, nil
}

// derived is an event a forward or processor writes from e: the same envelope, linked to e.
func derived(e domain.Event, sub domain.Subscription, streamID, id, source, key string, depth int) domain.Event {
	corr := e.ID
	if e.CorrelationID != nil && *e.CorrelationID != "" {
		corr = *e.CorrelationID
	}
	causation := e.ID
	return domain.Event{
		ID: id, Kind: e.Kind, Source: source, Subject: e.Subject, OccurredAt: e.OccurredAt,
		CorrelationID: &corr, CausationID: &causation, Data: e.Data,
		StreamID: streamID, WorkspaceID: sub.WorkspaceID, CreatedBy: sub.CreatedBy, EventKey: key, Depth: depth,
		SourceID: e.SourceID, SourceType: e.SourceType, SessionKey: e.SessionKey, Sender: e.Sender,
	}
}

// ExternalHandler is ExternalSubscriptionHandler: the event is handed to delivery on streams.external.
type ExternalHandler struct{ d Deps }

func (h *ExternalHandler) Prepare(_ context.Context, sub domain.Subscription, e domain.Event) (Finish, error) {
	return func(ctx context.Context, _ db.Session) (store.Result, error) {
		if h.d.Broker == nil {
			return store.Result{}, errors.New("external delivery needs the broker, which is not wired")
		}
		fields, err := events.Encode(service.BusEvent(e))
		if err != nil {
			return store.Result{}, err
		}
		fields[externalSubscription] = sub.ID
		fields[externalWorkspace] = sub.WorkspaceID
		fields[externalOwner] = sub.CreatedBy
		fields[externalAttempt] = "0"
		fields[externalDue] = events.PyISO(h.d.Now().UTC())
		if _, err := h.d.Broker.Submit(ctx, events.ExternalEvents, fields, events.BusRetention); err != nil {
			return store.Result{}, err
		}
		reason := HandedOver
		return store.Result{Verdict: domain.VerdictReacted, Reason: &reason}, nil
	}, nil
}

// NewExternal is the external handler over d.
func NewExternal(d Deps) *ExternalHandler {
	if d.Now == nil {
		d.Now = time.Now
	}
	return &ExternalHandler{d: d}
}

func firstOf(vs ...string) string {
	for _, v := range vs {
		if v != "" {
			return v
		}
	}
	return ""
}
