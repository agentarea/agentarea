package router

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// DefaultCacheTTL is how long a stream's subscriptions are served from the cache.
const DefaultCacheTTL = 60 * time.Second

// Notice kinds on streams.live.<workspace> (NoticeKind).
const (
	NoticeRecorded   = "event.recorded"
	NoticeProcessing = "event.processing"
)

// Finish writes a prepared reaction in the router's transaction and returns its result.
type Finish func(ctx context.Context, sess db.Session) (store.Result, error)

// Handler reacts to one matching event. Prepare runs with no transaction open, after the
// subscription was read again; the Finish it returns runs in the reaction's transaction.
type Handler interface {
	Prepare(ctx context.Context, sub domain.Subscription, e domain.Event) (Finish, error)
}

// Deps are what the consumers need.
type Deps struct {
	Service *service.Service
	DB      db.Database
	// Subscriber runs the router and events-view groups; its MaxDelivery is Settings.MaxAttempts.
	Subscriber events.GroupSubscriber
	// Broker sends the live notices, the external hand-over, and tails the subscription changes.
	Broker events.Broker
	// Runner runs processors in the sandbox; nil makes every processor reaction retried as unavailable.
	Runner   service.ProcessorRunner
	Settings service.Settings
	CacheTTL time.Duration
	Now      func() time.Time
	Log      *slog.Logger
}

type cached struct {
	subs     []domain.Subscription
	loadedAt time.Time
	readAt   time.Time
}

// Router is EventRouter: every bus event to every matching subscription of its stream.
type Router struct {
	d        Deps
	handlers map[string]Handler
	mu       sync.Mutex
	cache    map[string]cached
}

// ErrReactionsFailed: some subscriptions could not react; the event is redelivered for them.
var ErrReactionsFailed = errors.New("reactions failed")

// New builds the router with its four handlers.
func New(d Deps) *Router {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	if d.CacheTTL <= 0 {
		d.CacheTTL = DefaultCacheTTL
	}
	r := &Router{d: d, cache: map[string]cached{}}
	r.handlers = map[string]Handler{
		domain.SubTrigger:   &TriggerHandler{d: d},
		domain.SubForward:   &ForwardHandler{d: d},
		domain.SubExternal:  &ExternalHandler{d: d},
		domain.SubProcessor: &ProcessorHandler{d: d},
	}
	return r
}

// Invalidate forgets one stream's subscriptions, or every stream's with "".
func (r *Router) Invalidate(streamID string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if streamID == "" {
		r.cache = map[string]cached{}
		return
	}
	delete(r.cache, streamID)
}

func (r *Router) now() time.Time { return r.d.Now().UTC() }

func wsOf(e domain.Event) (scope.Workspace, error) { return scope.NewWorkspace(e.WorkspaceID, "") }

// Handle is EventRouter.handle.
func (r *Router) Handle(ctx context.Context, m events.IntegrationEvent) error {
	e, err := EventFromBus(m)
	if err != nil {
		return err
	}
	ws, err := wsOf(e)
	if err != nil {
		return fmt.Errorf("%w: %w", events.ErrUnprocessable, err)
	}
	matching, pending, err := r.pending(ctx, ws, e)
	if err != nil {
		return err
	}
	if err := r.routed(ctx, ws, e, len(matching)); err != nil {
		return err
	}
	var failed []string
	gone := 0
	for _, sub := range pending {
		reacted, err := r.react(ctx, ws, sub, e)
		if err != nil {
			r.d.Log.WarnContext(ctx, "Subscription failed on an event; it is retried", "subscription_id", sub.ID,
				"event_id", e.ID, "stream_id", e.StreamID, "error", err)
			failed = append(failed, sub.ID)
			continue
		}
		if reacted {
			r.notify(ctx, NoticeProcessing, e)
		} else {
			gone++
		}
	}
	if gone > 0 {
		if err := r.routed(ctx, ws, e, len(matching)-gone); err != nil {
			return err
		}
	}
	if len(failed) > 0 {
		return fmt.Errorf("%w: event %s: subscriptions %s failed", ErrReactionsFailed, e.ID, strings.Join(failed, ", "))
	}
	return nil
}

// GiveUp records every reaction still missing as error; the event is dead-lettered.
func (r *Router) GiveUp(ctx context.Context, m events.IntegrationEvent) error {
	e, err := EventFromBus(m)
	if err != nil {
		return err
	}
	ws, err := wsOf(e)
	if err != nil {
		return err
	}
	matching, pending, err := r.pending(ctx, ws, e)
	if err != nil {
		return err
	}
	gone := 0
	reason := domain.GaveUpReason
	for _, sub := range pending {
		err := r.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			cur, ok, err := r.recheck(ctx, sess, sub)
			if err != nil {
				return err
			}
			if !ok {
				gone++
				return nil
			}
			if err := (store.Router{}).RecordReactionResult(ctx, sess, store.CauseOf(cur, e), cur.CreatedBy,
				store.Result{Verdict: domain.VerdictError, Reason: &reason}, r.now()); err != nil {
				return err
			}
			return r.tally(ctx, sess, e)
		})
		if err != nil {
			return err
		}
	}
	return r.routed(ctx, ws, e, len(matching)-gone)
}

func (r *Router) routed(ctx context.Context, ws scope.Workspace, e domain.Event, subscribers int) error {
	var wrote bool
	err := r.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		var err error
		wrote, err = store.Streams{}.MarkRouted(ctx, sess, e, subscribers, r.now())
		return err
	})
	if err != nil {
		return err
	}
	if wrote {
		r.notify(ctx, NoticeRecorded, e)
	} else {
		r.notify(ctx, NoticeProcessing, e)
	}
	return nil
}

func (r *Router) tally(ctx context.Context, sess db.Session, e domain.Event) error {
	reacted, skipped, errs, err := store.Router{}.Tally(ctx, sess, e.ID)
	if err != nil {
		return err
	}
	return store.Streams{}.MarkReactions(ctx, sess, e, reacted, skipped, errs)
}

// pending is the subscriptions matching the event, and those of them yet to react.
func (r *Router) pending(ctx context.Context, ws scope.Workspace, e domain.Event) ([]domain.Subscription, []domain.Subscription, error) {
	subs, err := r.subscriptions(ctx, ws, e)
	if err != nil {
		return nil, nil, err
	}
	var matching []domain.Subscription
	for _, s := range subs {
		if domain.StoredFilter(s.Filter).Admits(e) {
			matching = append(matching, s)
		}
	}
	if len(matching) == 0 {
		return nil, nil, nil
	}
	var done map[string]bool
	err = r.read(ctx, ws, func(sess db.Session) error {
		var err error
		done, err = store.Router{}.Recorded(ctx, sess, e.ID)
		return err
	})
	if err != nil {
		return nil, nil, err
	}
	var pending []domain.Subscription
	for _, s := range matching {
		if !done[s.ID] {
			pending = append(pending, s)
		}
	}
	return matching, pending, nil
}

func (r *Router) read(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := r.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

func (r *Router) recheck(ctx context.Context, sess db.Session, sub domain.Subscription) (domain.Subscription, bool, error) {
	id, err := uuid.Parse(sub.ID)
	if err != nil {
		return domain.Subscription{}, false, err
	}
	return store.Streams{}.GetActiveSubscription(ctx, sess, id)
}

// react runs and records one reaction; false when the subscription is gone or paused.
func (r *Router) react(ctx context.Context, ws scope.Workspace, sub domain.Subscription, e domain.Event) (bool, error) {
	var finish Finish
	if !e.ReceivedAt.Before(sub.StartedAt) {
		var cur domain.Subscription
		var ok bool
		err := r.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			var err error
			if cur, ok, err = r.recheck(ctx, sess, sub); err != nil || !ok {
				return err
			}
			return store.Router{}.ForgetGivenUp(ctx, sess, cur.ID, e.ID)
		})
		if err != nil {
			return false, err
		}
		if !ok {
			r.d.Log.InfoContext(ctx, "Subscription is gone or paused; the event is not delivered to it", "subscription_id", sub.ID, "event_id", e.ID)
			return false, nil
		}
		h, known := r.handlers[cur.Kind]
		if !known {
			return false, fmt.Errorf("no handler for subscription kind %q", cur.Kind)
		}
		if finish, err = h.Prepare(ctx, cur, e); err != nil {
			return false, err
		}
	}
	recorded := false
	err := r.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		cur, ok, err := r.recheck(ctx, sess, sub)
		if err != nil || !ok {
			return err
		}
		if err := (store.Router{}).ForgetGivenUp(ctx, sess, cur.ID, e.ID); err != nil {
			return err
		}
		var res store.Result
		if e.ReceivedAt.Before(cur.StartedAt) || finish == nil {
			reason := domain.BeforeStartReason
			res = store.Result{Verdict: domain.VerdictSkipped, Reason: &reason}
		} else if res, err = finish(ctx, sess); err != nil {
			return err
		}
		if err := (store.Router{}).RecordReactionResult(ctx, sess, store.CauseOf(cur, e), cur.CreatedBy, res, r.now()); err != nil {
			return err
		}
		recorded = true
		return r.tally(ctx, sess, e)
	})
	if err != nil {
		if !store.IsForeignKeyViolation(err) {
			return false, err
		}
		var still bool
		if rerr := r.read(ctx, ws, func(sess db.Session) error {
			_, ok, err := r.recheck(ctx, sess, sub)
			still = ok
			return err
		}); rerr != nil || still {
			return false, err
		}
		r.d.Log.InfoContext(ctx, "Subscription was deleted while it reacted to an event; not recorded", "subscription_id", sub.ID, "event_id", e.ID)
		return false, nil
	}
	if !recorded {
		r.d.Log.InfoContext(ctx, "Subscription is gone or paused; the event is not delivered to it", "subscription_id", sub.ID, "event_id", e.ID)
	}
	return recorded, nil
}

// subscriptions is the stream's active subscriptions; the cache serves only events received before it was read.
func (r *Router) subscriptions(ctx context.Context, ws scope.Workspace, e domain.Event) ([]domain.Subscription, error) {
	now := r.d.Now()
	r.mu.Lock()
	c, ok := r.cache[e.StreamID]
	r.mu.Unlock()
	if ok && now.Sub(c.loadedAt) < r.d.CacheTTL && !e.ReceivedAt.After(c.readAt) {
		return c.subs, nil
	}
	readAt := r.now()
	streamID, err := uuid.Parse(e.StreamID)
	if err != nil {
		return nil, fmt.Errorf("%w: stream id: %w", events.ErrUnprocessable, err)
	}
	var rows []domain.Subscription
	if err := r.read(ctx, ws, func(sess db.Session) error {
		var err error
		rows, err = store.Streams{}.ListSubscriptions(ctx, sess, streamID)
		return err
	}); err != nil {
		return nil, err
	}
	subs := make([]domain.Subscription, 0, len(rows))
	for _, s := range rows {
		if s.Status == domain.SubActive {
			subs = append(subs, s)
		}
	}
	r.mu.Lock()
	r.cache[e.StreamID] = cached{subs: subs, loadedAt: now, readAt: readAt}
	r.mu.Unlock()
	return subs, nil
}

// notify is a live notice on streams.live.<workspace>: at most once, kept nowhere, a failure logged.
func (r *Router) notify(ctx context.Context, kind string, e domain.Event) {
	notify(ctx, r.d, kind, e)
}

func notify(ctx context.Context, d Deps, kind string, e domain.Event) {
	if d.Broker == nil {
		return
	}
	if err := d.Broker.Notify(ctx, events.StreamsLiveChannel(e.WorkspaceID),
		map[string]string{"type": kind, "event_id": e.ID, "stream_id": e.StreamID}); err != nil {
		d.Log.WarnContext(ctx, "Live event notice failed", "event_id", e.ID, "error", err)
	}
}
