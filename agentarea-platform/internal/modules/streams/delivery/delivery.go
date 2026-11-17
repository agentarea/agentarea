// Package delivery sends stream events to EXTERNAL subscribers (MCP Events webhook delivery,
// ADR-0043 §7). The router hands each (event, subscriber) to streams.external; the Delivery
// group there POSTs it signed by Standard Webhooks. A failed send moves to the retry topic of
// its next attempt, one fixed delay per topic, so each retry topic is in due order. Past the
// last retry the subscriber is marked failed and the message dead-lettered. Before every send
// the subscriber's right to read the stream is checked again; one that lost it is sent a
// terminated message and removed with its secret. The sweeper removes expired subscribers.
package delivery

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"strconv"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/router"
)

// Fields a delivery message carries beside the encoded event; the router's EXTERNAL handler
// writes them (attempt "0", due now) on streams.external.
const (
	FieldSubscription = "subscription"
	FieldWorkspace    = "workspace"
	FieldOwner        = "owner"
	FieldAttempt      = "attempt"
	FieldDue          = "due"
)

const (
	sweepEvery    = 300 * time.Second
	dedupPrefix   = "external-delivery"
	claimIdleBase = 5 * time.Minute
	claimEvery    = time.Minute
	maxBackoff    = 60 * time.Second
)

// RetryDelays is the wait before each retry: the delay of streams.external.retry.<n> is RetryDelays[n-1].
func RetryDelays() []time.Duration {
	return []time.Duration{30 * time.Second, 2 * time.Minute, 10 * time.Minute, 30 * time.Minute, time.Hour, 2 * time.Hour}
}

// Topics is the main topic, then the retry topic of each attempt in order.
func Topics() []string {
	out := []string{events.ExternalEvents}
	for n := range RetryDelays() {
		out = append(out, events.ExternalRetryTopic(n+1))
	}
	return out
}

// DeadLetterTopic is where a delivery no retry can settle goes.
func DeadLetterTopic() string {
	return events.DeadLetterTopic(events.ExternalEvents, events.DeliveryGroup)
}

// DedupPrefix is the dedup cache prefix of sent deliveries (DedupCache "external-delivery").
func DedupPrefix() string { return dedupPrefix }

// Slugs names a workspace's URL slug, as owner (a member) sees it.
type Slugs func(ctx context.Context, owner, workspaceID string) (string, error)

// Deps are what Delivery runs on.
type Deps struct {
	Broker        events.Broker
	Dedup         events.Dedup
	Subscriptions Subscriptions
	Readers       authz.Checker
	Endpoint      Poster
	Slugs         Slugs
	// Consumer names this replica in the Delivery group.
	Consumer string
	// Block is how long a consume waits for messages; Batch how many the main topic takes at once.
	Block time.Duration
	Batch int
	Now   func() time.Time
	Log   *slog.Logger
}

// Delivery is the consumers of the Delivery group on the main and retry topics, and the sweeper.
type Delivery struct {
	d     Deps
	mu    sync.Mutex
	slugs map[string]string
}

// New builds a Delivery.
func New(d Deps) (*Delivery, error) {
	switch {
	case d.Broker == nil, d.Dedup == nil, d.Subscriptions == nil, d.Readers == nil, d.Endpoint == nil, d.Slugs == nil:
		return nil, errors.New("external delivery needs a broker, dedup, subscriptions, readers, an endpoint and slugs")
	case d.Consumer == "":
		return nil, errors.New("external delivery needs a consumer name")
	}
	if d.Block <= 0 {
		d.Block = 5 * time.Second
	}
	if d.Batch <= 0 {
		d.Batch = 10
	}
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Delivery{d: d, slugs: map[string]string{}}, nil
}

// Components are one consumer per topic and the sweeper.
func (x *Delivery) Components() []lifecycle.Component {
	delays := RetryDelays()
	out := make([]lifecycle.Component, 0, len(delays)+2)
	for i, topic := range Topics() {
		var delay time.Duration
		if i > 0 {
			delay = delays[i-1]
		}
		out = append(out, lifecycle.Loop("external delivery "+topic, func(ctx context.Context) error {
			return x.run(ctx, topic, claimIdleBase+delay)
		}))
	}
	return append(out, lifecycle.Loop("external subscriber sweeper", x.sweepLoop))
}

func (x *Delivery) run(ctx context.Context, topic string, minIdle time.Duration) error {
	if err := x.d.Broker.EnsureGroup(ctx, topic, events.DeliveryGroup, "0"); err != nil {
		return fmt.Errorf("delivery group on %s: %w", topic, err)
	}
	x.d.Log.InfoContext(ctx, "external delivery started", "topic", topic, "consumer", x.d.Consumer)
	// A retry topic is in due order, so its consumer takes one at a time.
	count := 1
	if topic == events.ExternalEvents {
		count = x.d.Batch
	}
	backoff := time.Second
	var lastClaim time.Time
	for ctx.Err() == nil {
		err := x.round(ctx, topic, count, minIdle, &lastClaim)
		if err == nil {
			backoff = time.Second
			continue
		}
		if ctx.Err() != nil {
			break
		}
		x.d.Log.ErrorContext(ctx, "external delivery failed", "topic", topic, "retry_in", backoff, "error", err)
		if sleep(ctx, backoff) != nil {
			break
		}
		backoff = min(backoff*2, maxBackoff)
	}
	return ctx.Err()
}

func (x *Delivery) round(ctx context.Context, topic string, count int, minIdle time.Duration, lastClaim *time.Time) error {
	var msgs []events.Message
	if now := x.d.Now(); now.Sub(*lastClaim) >= claimEvery {
		claimed, err := x.d.Broker.Autoclaim(ctx, topic, events.DeliveryGroup, x.d.Consumer, minIdle, "0-0", count)
		if err != nil {
			return fmt.Errorf("autoclaim: %w", err)
		}
		*lastClaim = now
		msgs = claimed
	}
	if len(msgs) == 0 {
		fresh, err := x.d.Broker.Consume(ctx, topic, events.DeliveryGroup, x.d.Consumer, count, x.d.Block)
		if err != nil {
			return err
		}
		msgs = fresh
	}
	for _, m := range msgs {
		if err := x.waitUntilDue(ctx, m); err != nil {
			return err
		}
		if err := x.Handle(ctx, topic, m); err != nil {
			return err
		}
	}
	return nil
}

func (x *Delivery) waitUntilDue(ctx context.Context, m events.Message) error {
	due, ok := m.Fields[FieldDue]
	if !ok || due == "" {
		return nil
	}
	at, err := events.ParsePyISO(due)
	if err != nil {
		return nil
	}
	if wait := at.Sub(x.d.Now()); wait > 0 {
		return sleep(ctx, wait)
	}
	return nil
}

type delivery struct {
	event   domain.Event
	subID   string
	ws      scope.Workspace
	owner   string
	attempt int
}

func decode(m events.Message) (delivery, error) {
	ie, err := events.Decode(m.Fields)
	if err != nil {
		return delivery{}, err
	}
	e, err := router.EventFromBus(ie)
	if err != nil {
		return delivery{}, err
	}
	d := delivery{event: e, subID: m.Fields[FieldSubscription], owner: m.Fields[FieldOwner]}
	if d.subID == "" || d.owner == "" {
		return delivery{}, errors.New("no subscription or owner")
	}
	if d.ws, err = scope.NewWorkspace(m.Fields[FieldWorkspace], ""); err != nil {
		return delivery{}, err
	}
	if d.attempt, err = strconv.Atoi(m.Fields[FieldAttempt]); err != nil {
		return delivery{}, fmt.Errorf("attempt: %w", err)
	}
	return d, nil
}

// Handle settles one message of topic: send it once, then acknowledge it. An error leaves the
// message pending, to be claimed again.
func (x *Delivery) Handle(ctx context.Context, topic string, m events.Message) error {
	d, err := decode(m)
	if err != nil {
		x.d.Log.ErrorContext(ctx, "undecodable webhook delivery; dead-lettered", "message_id", m.ID, "error", err)
		if err := x.deadLetter(ctx, m, "undecodable: "+err.Error()); err != nil {
			return err
		}
		return x.d.Broker.Ack(ctx, topic, events.DeliveryGroup, m.ID)
	}
	key := d.subID + ":" + d.event.ID
	seen, err := x.d.Dedup.Contains(ctx, key)
	if err != nil {
		return err
	}
	if !seen {
		delivered, err := x.deliver(ctx, d, m)
		if err != nil {
			return err
		}
		if delivered {
			if err := x.d.Dedup.Keep(ctx, key); err != nil {
				return err
			}
		}
	}
	return x.d.Broker.Ack(ctx, topic, events.DeliveryGroup, m.ID)
}

func (x *Delivery) deliver(ctx context.Context, d delivery, m events.Message) (bool, error) {
	sub, ok, err := x.d.Subscriptions.Active(ctx, d.ws, d.subID)
	if err != nil {
		return false, err
	}
	if !ok || sub.ExternalID == nil {
		x.d.Log.InfoContext(ctx, "subscriber is gone, failed or expired; event is not sent", "subscription", d.subID, "event_id", d.event.ID)
		return false, nil
	}
	allowed, err := x.d.Readers.Check(ctx, authz.UserSubject(sub.CreatedBy), "read", "stream", sub.StreamID)
	if err != nil {
		return false, err
	}
	if !allowed {
		return false, x.terminate(ctx, d, sub)
	}
	secret, ok, err := x.d.Subscriptions.Secret(ctx, d.ws, d.owner, deref(sub.SecretName))
	if err != nil {
		return false, err
	}
	if !ok {
		if err := x.d.Subscriptions.MarkFailed(ctx, d.ws, sub.ID); err != nil {
			return false, err
		}
		return false, x.deadLetter(ctx, m, "the subscriber's secret is missing")
	}
	slug, err := x.slug(ctx, d.owner, d.ws.ID())
	if err != nil {
		return false, err
	}
	out, err := x.d.Endpoint.Post(ctx, deref(sub.CallbackURL), secret, *sub.ExternalID, d.event.ID,
		OccurrenceOf(d.event, EventName(slug, sub.StreamID)))
	if err != nil {
		if err := x.d.Subscriptions.MarkFailed(ctx, d.ws, sub.ID); err != nil {
			return false, err
		}
		return false, x.deadLetter(ctx, m, "the subscriber's secret cannot sign: "+err.Error())
	}
	now := x.d.Now()
	if err := x.d.Subscriptions.Record(ctx, d.ws, sub.ID, now, out.Error); err != nil {
		return false, err
	}
	delays := RetryDelays()
	switch {
	case out.Error == "":
		return true, nil
	case out.Final:
		return false, x.deadLetter(ctx, m, "refused by the endpoint ("+out.Error+")")
	case d.attempt < len(delays):
		return false, x.retry(ctx, m, d.attempt+1, now.Add(delays[d.attempt]))
	default:
		if err := x.d.Subscriptions.MarkFailed(ctx, d.ws, sub.ID); err != nil {
			return false, err
		}
		return false, x.deadLetter(ctx, m, fmt.Sprintf("%d attempts failed (%s); subscriber marked failed", d.attempt+1, out.Error))
	}
}

func (x *Delivery) retry(ctx context.Context, m events.Message, attempt int, due time.Time) error {
	fields := maps.Clone(m.Fields)
	fields[FieldAttempt] = strconv.Itoa(attempt)
	fields[FieldDue] = events.PyISO(due)
	_, err := x.d.Broker.Submit(ctx, events.ExternalRetryTopic(attempt), fields, events.BusRetention)
	return err
}

// terminate tells a subscriber that may no longer read the stream so, then removes it.
func (x *Delivery) terminate(ctx context.Context, d delivery, sub domain.Subscription) error {
	x.d.Log.InfoContext(ctx, "subscriber lost read access to its stream; terminated", "subscription", sub.ID)
	secret, ok, err := x.d.Subscriptions.Secret(ctx, d.ws, d.owner, deref(sub.SecretName))
	if err != nil {
		return err
	}
	if ok {
		id, err := ControlMessageID("terminated")
		if err != nil {
			return err
		}
		if _, err := x.d.Endpoint.Post(ctx, deref(sub.CallbackURL), secret, *sub.ExternalID, id, Terminated()); err != nil {
			x.d.Log.WarnContext(ctx, "terminated message not sent", "subscription", sub.ID, "error", err)
		}
	}
	return x.d.Subscriptions.Remove(ctx, d.ws, d.owner, sub)
}

func (x *Delivery) slug(ctx context.Context, owner, workspaceID string) (string, error) {
	x.mu.Lock()
	s, ok := x.slugs[workspaceID]
	x.mu.Unlock()
	if ok {
		return s, nil
	}
	s, err := x.d.Slugs(ctx, owner, workspaceID)
	if err != nil {
		return "", fmt.Errorf("slug of workspace %s: %w", workspaceID, err)
	}
	x.mu.Lock()
	x.slugs[workspaceID] = s
	x.mu.Unlock()
	return s, nil
}

func (x *Delivery) deadLetter(ctx context.Context, m events.Message, reason string) error {
	fields := maps.Clone(m.Fields)
	if len(reason) > 500 {
		reason = reason[:500]
	}
	fields[events.DeadLetterReasonField] = reason
	if _, err := x.d.Broker.Submit(ctx, DeadLetterTopic(), fields, events.DeadLetterRetention); err != nil {
		return err
	}
	x.d.Log.ErrorContext(ctx, "webhook delivery dead-lettered", "message_id", m.ID, "reason", reason)
	return nil
}

// Sweep removes every subscriber past its expiry, and its secret; it returns how many.
func (x *Delivery) Sweep(ctx context.Context) (int, error) {
	expired, err := x.d.Subscriptions.Expired(ctx)
	if err != nil {
		return 0, err
	}
	for _, sub := range expired {
		ws, err := scope.NewWorkspace(sub.WorkspaceID, "")
		if err != nil {
			return 0, err
		}
		if err := x.d.Subscriptions.Remove(ctx, ws, sub.CreatedBy, sub); err != nil {
			return 0, err
		}
	}
	if len(expired) > 0 {
		x.d.Log.InfoContext(ctx, "removed expired MCP Events subscribers", "count", len(expired))
	}
	return len(expired), nil
}

func (x *Delivery) sweepLoop(ctx context.Context) error {
	for {
		if _, err := x.Sweep(ctx); err != nil && ctx.Err() == nil {
			x.d.Log.ErrorContext(ctx, "sweeping expired MCP Events subscribers failed", "error", err)
		}
		if err := sleep(ctx, sweepEvery); err != nil {
			return err
		}
	}
}

func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
