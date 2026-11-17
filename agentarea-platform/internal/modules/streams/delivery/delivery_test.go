package delivery

import (
	"context"
	"encoding/json"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

const (
	wsID    = "11111111-1111-1111-1111-111111111111"
	owner   = "user-1"
	subID   = "22222222-2222-2222-2222-222222222222"
	stream  = "33333333-3333-3333-3333-333333333333"
	eventID = "44444444-4444-4444-4444-444444444444"
	secret  = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw" // pragma: allowlist secret
)

type fakeSubs struct {
	mu       sync.Mutex
	sub      *domain.Subscription
	secret   string
	recorded []string
	failed   int
	removed  []string
	expired  []domain.Subscription
}

func (f *fakeSubs) Active(_ context.Context, _ scope.Workspace, id string) (domain.Subscription, bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.sub == nil || f.sub.ID != id {
		return domain.Subscription{}, false, nil
	}
	return *f.sub, true, nil
}

func (f *fakeSubs) Secret(_ context.Context, _ scope.Workspace, _, name string) (string, bool, error) {
	if name == "" || f.secret == "" {
		return "", false, nil
	}
	return f.secret, true, nil
}

func (f *fakeSubs) Record(_ context.Context, _ scope.Workspace, _ string, _ time.Time, deliveryErr string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.recorded = append(f.recorded, deliveryErr)
	return nil
}

func (f *fakeSubs) MarkFailed(context.Context, scope.Workspace, string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.failed++
	return nil
}

func (f *fakeSubs) Remove(_ context.Context, _ scope.Workspace, _ string, sub domain.Subscription) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.removed = append(f.removed, sub.ID)
	f.sub = nil
	return nil
}

func (f *fakeSubs) Expired(context.Context) ([]domain.Subscription, error) { return f.expired, nil }

type allow bool

func (a allow) Check(context.Context, string, string, string, string) (bool, error) {
	return bool(a), nil
}

type post struct {
	url, secret, subscription, id string
	body                          any
}

type fakeEndpoint struct {
	mu    sync.Mutex
	posts []post
	out   Outcome
}

func (f *fakeEndpoint) Post(_ context.Context, url, secret, subscription, id string, body any) (Outcome, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.posts = append(f.posts, post{url, secret, subscription, id, body})
	return f.out, nil
}

type harness struct {
	x      *Delivery
	broker *fakeBroker
	subs   *fakeSubs
	ep     *fakeEndpoint
	now    time.Time
}

func ptr(s string) *string { return &s }

func newHarness(t *testing.T, readers allow) *harness {
	t.Helper()
	broker, dedup := newFakeBroker(), &fakeDedup{kept: map[string]bool{}}
	h := &harness{
		broker: broker,
		subs: &fakeSubs{secret: secret, sub: &domain.Subscription{
			ID: subID, WorkspaceID: wsID, StreamID: stream, Kind: domain.SubExternal, Status: "active",
			ExternalID: ptr("sub_ext"), CallbackURL: ptr("https://hooks.example/cb"), SecretName: ptr("mcp_events_whsec:sub_ext"),
			CreatedBy: owner,
		}},
		ep:  &fakeEndpoint{},
		now: time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC),
	}
	var err error
	h.x, err = New(Deps{
		Broker: broker, Dedup: dedup, Subscriptions: h.subs, Readers: readers, Endpoint: h.ep,
		Slugs:    func(context.Context, string, string) (string, error) { return "acme", nil },
		Consumer: "c1", Now: func() time.Time { return h.now },
	})
	if err != nil {
		t.Fatal(err)
	}
	return h
}

func streamEvent() domain.Event {
	at := time.Date(2026, 11, 12, 9, 59, 0, 0, time.UTC)
	return domain.Event{
		ID: eventID, Kind: "message.created", Source: "agentarea://streams/" + stream, OccurredAt: at,
		Data: map[string]any{"body": map[string]any{"text": "hi"}}, StreamID: stream, WorkspaceID: wsID,
		CreatedBy: owner, EventKey: "k1", ReceivedAt: at, SourceType: ptr("telegram"),
	}
}

// handOver writes what the router's EXTERNAL handler writes.
func (h *harness) handOver(t *testing.T, attempt string) events.Message {
	t.Helper()
	fields, err := events.Encode(service.BusEvent(streamEvent()))
	if err != nil {
		t.Fatal(err)
	}
	fields[FieldSubscription] = subID
	fields[FieldWorkspace] = wsID
	fields[FieldOwner] = owner
	fields[FieldAttempt] = attempt
	fields[FieldDue] = events.PyISO(h.now)
	topic := events.ExternalEvents
	if attempt != "0" {
		topic = events.ExternalRetryTopic(len(attempt))
	}
	if _, err := h.broker.Submit(context.Background(), topic, fields, events.BusRetention); err != nil {
		t.Fatal(err)
	}
	return h.take(t, topic)
}

func (h *harness) take(t *testing.T, topic string) events.Message {
	t.Helper()
	msgs, err := h.broker.Consume(context.Background(), topic, events.DeliveryGroup, "c1", 1, time.Millisecond)
	if err != nil || len(msgs) != 1 {
		t.Fatalf("consume %s: %v, %d", topic, err, len(msgs))
	}
	return msgs[0]
}

func (h *harness) none(t *testing.T, topic string) {
	t.Helper()
	msgs, err := h.broker.Consume(context.Background(), topic, events.DeliveryGroup, "probe", 1, time.Millisecond)
	if err != nil || len(msgs) != 0 {
		t.Fatalf("%s holds %d messages (%v)", topic, len(msgs), err)
	}
}

func TestADeliveryIsTheSignedOccurrenceSentOnce(t *testing.T) {
	h := newHarness(t, true)
	ctx := context.Background()
	m := h.handOver(t, "0")
	if err := h.x.Handle(ctx, events.ExternalEvents, m); err != nil {
		t.Fatal(err)
	}
	if len(h.ep.posts) != 1 {
		t.Fatalf("posts = %+v", h.ep.posts)
	}
	p := h.ep.posts[0]
	if p.url != "https://hooks.example/cb" || p.secret != secret || p.subscription != "sub_ext" || p.id != eventID {
		t.Fatalf("post = %+v", p)
	}
	raw, _ := EncodeBody(p.body)
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil {
		t.Fatal(err)
	}
	data, _ := body["data"].(map[string]any)
	if body["eventId"] != eventID || body["name"] != "acme/"+stream || body["cursor"] != nil ||
		body["timestamp"] != "2026-11-12T09:59:00+00:00" || data["kind"] != "message.created" || data["key"] != "k1" ||
		data["workspace_id"] != wsID || data["v"] != float64(1) {
		t.Fatalf("body = %s", raw)
	}
	if _, ok := body["cursor"]; !ok {
		t.Fatal("the occurrence has no cursor key")
	}
	if len(h.subs.recorded) != 1 || h.subs.recorded[0] != "" {
		t.Fatalf("recorded = %v", h.subs.recorded)
	}

	again := h.handOver(t, "0")
	if err := h.x.Handle(ctx, events.ExternalEvents, again); err != nil {
		t.Fatal(err)
	}
	if len(h.ep.posts) != 1 {
		t.Fatalf("a repeat was sent again: %d posts", len(h.ep.posts))
	}
}

func TestAFailedSendWaitsOnTheNextRetryTopic(t *testing.T) {
	h := newHarness(t, true)
	h.ep.out = Outcome{Error: "http_5xx"}
	if err := h.x.Handle(context.Background(), events.ExternalEvents, h.handOver(t, "0")); err != nil {
		t.Fatal(err)
	}
	retry := h.take(t, events.ExternalRetryTopic(1))
	if retry.Fields[FieldAttempt] != "1" || retry.Fields[FieldDue] != events.PyISO(h.now.Add(30*time.Second)) {
		t.Fatalf("retry = %v", retry.Fields)
	}
	if h.subs.failed != 0 || h.subs.recorded[0] != "http_5xx" {
		t.Fatalf("failed = %d, recorded = %v", h.subs.failed, h.subs.recorded)
	}
	h.none(t, DeadLetterTopic())
}

func TestTheLastFailedAttemptMarksTheSubscriberFailed(t *testing.T) {
	h := newHarness(t, true)
	h.ep.out = Outcome{Error: "timeout"}
	if err := h.x.Handle(context.Background(), events.ExternalRetryTopic(6), h.handOver(t, "6")); err != nil {
		t.Fatal(err)
	}
	if h.subs.failed != 1 {
		t.Fatalf("failed = %d", h.subs.failed)
	}
	dead := h.take(t, DeadLetterTopic())
	if !strings.Contains(dead.Fields[events.DeadLetterReasonField], "7 attempts failed (timeout)") {
		t.Fatalf("dead = %v", dead.Fields[events.DeadLetterReasonField])
	}
}

func TestAFinalRefusalIsDeadLetteredWithoutRetry(t *testing.T) {
	h := newHarness(t, true)
	h.ep.out = Outcome{Error: "http_4xx", Final: true}
	if err := h.x.Handle(context.Background(), events.ExternalEvents, h.handOver(t, "0")); err != nil {
		t.Fatal(err)
	}
	h.none(t, events.ExternalRetryTopic(1))
	if dead := h.take(t, DeadLetterTopic()); dead.Fields[events.DeadLetterReasonField] != "refused by the endpoint (http_4xx)" {
		t.Fatalf("dead = %v", dead.Fields)
	}
}

func TestASubscriberThatLostReadIsTerminatedAndRemoved(t *testing.T) {
	h := newHarness(t, false)
	if err := h.x.Handle(context.Background(), events.ExternalEvents, h.handOver(t, "0")); err != nil {
		t.Fatal(err)
	}
	if len(h.ep.posts) != 1 || !strings.HasPrefix(h.ep.posts[0].id, "msg_terminated_") || len(h.ep.posts[0].id) != len("msg_terminated_")+24 {
		t.Fatalf("posts = %+v", h.ep.posts)
	}
	raw, _ := EncodeBody(h.ep.posts[0].body)
	if string(raw) != `{"error":{"code":-32024,"data":{"reason":"Access revoked"},"message":"Forbidden"},"type":"terminated"}` {
		t.Fatalf("terminated = %s", raw)
	}
	if len(h.subs.removed) != 1 || h.subs.removed[0] != subID {
		t.Fatalf("removed = %v", h.subs.removed)
	}
}

func TestAMissingSecretFailsTheSubscriber(t *testing.T) {
	h := newHarness(t, true)
	h.subs.secret = ""
	if err := h.x.Handle(context.Background(), events.ExternalEvents, h.handOver(t, "0")); err != nil {
		t.Fatal(err)
	}
	if h.subs.failed != 1 || len(h.ep.posts) != 0 {
		t.Fatalf("failed = %d, posts = %d", h.subs.failed, len(h.ep.posts))
	}
	if dead := h.take(t, DeadLetterTopic()); dead.Fields[events.DeadLetterReasonField] != "the subscriber's secret is missing" {
		t.Fatalf("dead = %v", dead.Fields)
	}
}

func TestAGoneSubscriberIsNotSent(t *testing.T) {
	h := newHarness(t, true)
	h.subs.sub = nil
	if err := h.x.Handle(context.Background(), events.ExternalEvents, h.handOver(t, "0")); err != nil {
		t.Fatal(err)
	}
	if len(h.ep.posts) != 0 {
		t.Fatalf("posts = %d", len(h.ep.posts))
	}
	h.none(t, DeadLetterTopic())
}

func TestAnUndecodableDeliveryIsDeadLettered(t *testing.T) {
	h := newHarness(t, true)
	ctx := context.Background()
	if _, err := h.broker.Submit(ctx, events.ExternalEvents, map[string]string{"junk": "1"}, events.BusRetention); err != nil {
		t.Fatal(err)
	}
	if err := h.x.Handle(ctx, events.ExternalEvents, h.take(t, events.ExternalEvents)); err != nil {
		t.Fatal(err)
	}
	if dead := h.take(t, DeadLetterTopic()); !strings.HasPrefix(dead.Fields[events.DeadLetterReasonField], "undecodable: ") {
		t.Fatalf("dead = %v", dead.Fields)
	}
	pending, err := h.broker.Pending(ctx, events.ExternalEvents, events.DeliveryGroup)
	if err != nil || pending.Count != 0 {
		t.Fatalf("pending = %+v, %v", pending, err)
	}
}

func TestSweepRemovesExpiredSubscribers(t *testing.T) {
	h := newHarness(t, true)
	h.subs.expired = []domain.Subscription{*h.subs.sub}
	n, err := h.x.Sweep(context.Background())
	if err != nil || n != 1 || len(h.subs.removed) != 1 {
		t.Fatalf("n = %d, removed = %v, err = %v", n, h.subs.removed, err)
	}
}

func TestTheTopicsAreTheMainThenSixRetries(t *testing.T) {
	got := Topics()
	if len(got) != 7 || got[0] != "streams.external" || got[6] != "streams.external.retry.6" {
		t.Fatalf("topics = %v", got)
	}
	if DeadLetterTopic() != "streams.external.delivery.dlq" {
		t.Fatalf("dlq = %s", DeadLetterTopic())
	}
}
