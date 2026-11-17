package replies_test

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
)

type broker struct {
	events.Broker
	mu    sync.Mutex
	acked []string
	dead  []map[string]string
}

func (b *broker) Ack(_ context.Context, _, _, id string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.acked = append(b.acked, id)
	return nil
}

func (b *broker) Submit(_ context.Context, stream string, fields map[string]string, _ time.Duration) (string, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if stream != replies.DeadLetterTopic() {
		return "", errors.New("submitted to " + stream)
	}
	b.dead = append(b.dead, fields)
	return "1-0", nil
}

type dedup struct {
	mu   sync.Mutex
	keys map[string]bool
}

func (d *dedup) Claim(_ context.Context, key string, _ time.Duration) (bool, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.keys[key] {
		return false, nil
	}
	d.keys[key] = true
	return true, nil
}

func (d *dedup) Keep(_ context.Context, key string) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.keys[key] = true
	return nil
}

func (d *dedup) Contains(_ context.Context, key string) (bool, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.keys[key], nil
}

func (d *dedup) Release(_ context.Context, key string) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	delete(d.keys, key)
	return nil
}

type tasks map[string]runsapi.OutcomeTask

func (t tasks) OutcomeTask(_ context.Context, _ scope.Workspace, id string) (runsapi.OutcomeTask, bool, error) {
	x, ok := t[id]
	return x, ok, nil
}

type sender struct {
	mu   sync.Mutex
	err  error
	sent []string
}

func (s *sender) Format(x replies.Send) (string, error) {
	return x.Event.Type + ":" + x.Target.Key, nil
}

func (s *sender) Send(_ context.Context, _ replies.Send, message string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.err != nil {
		return s.err
	}
	s.sent = append(s.sent, message)
	return nil
}

func (s *sender) messages() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.sent...)
}

type deliveryRig struct {
	x       *replies.Delivery
	broker  *broker
	dedup   *dedup
	chat    *sender
	webhook *sender
	ws      string
	task    string
}

func newDeliveryRig(t *testing.T) *deliveryRig {
	t.Helper()
	r := &deliveryRig{broker: &broker{}, dedup: &dedup{keys: map[string]bool{}}, chat: &sender{}, webhook: &sender{},
		ws: uuid.NewString(), task: uuid.NewString()}
	x, err := replies.New(replies.Deps{
		Broker: r.broker, Dedup: r.dedup, Consumer: "c1", Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
		Tasks: tasks{r.task: {ID: r.task, Owner: "u1",
			Parameters: map[string]any{"delivery_address": map[string]any{"type": "slack", "sender": "http"}},
			Metadata:   map[string]any{"task_webhook": map[string]any{"url": "https://x.test", "signed": false}}}},
		Replies: func(context.Context, string) (*domain.Reply, bool, error) {
			return &domain.Reply{Markup: "slack"}, true, nil
		},
		Senders: map[string]replies.Sender{"http": r.chat, "task_webhook": r.webhook},
	})
	if err != nil {
		t.Fatal(err)
	}
	r.x = x
	return r
}

func (r *deliveryRig) message(t *testing.T, kind string, deliveries int) events.Message {
	t.Helper()
	fields, err := events.Encode(events.IntegrationEvent{ID: uuid.NewString(), Type: kind, Source: "runs", Time: time.Now().UTC(),
		Subject: r.task, Data: map[string]any{"task_id": r.task}, Extensions: map[string]string{"workspace": r.ws}})
	if err != nil {
		t.Fatal(err)
	}
	return events.Message{ID: uuid.NewString(), Fields: fields, DeliveryCount: deliveries}
}

func TestDeliveryGoesToEachTargetThatShowsTheEvent(t *testing.T) {
	r := newDeliveryRig(t)
	ctx := context.Background()
	for _, m := range []events.Message{r.message(t, "tool.call", 1), r.message(t, "task.completed", 1)} {
		if err := r.x.Handle(ctx, m); err != nil {
			t.Fatal(err)
		}
	}
	if got := r.chat.messages(); len(got) != 2 || got[0] != "tool.call:address" || got[1] != "task.completed:address" {
		t.Fatalf("chat = %v", got)
	}
	if got := r.webhook.messages(); len(got) != 1 || got[0] != "task.completed:task_webhook" {
		t.Fatalf("a silent webhook saw = %v", got)
	}
	if len(r.broker.acked) != 2 || len(r.broker.dead) != 0 {
		t.Fatalf("acked %v dead %v", r.broker.acked, r.broker.dead)
	}
}

func TestRetryLeavesTheMessagePendingAndSendsOnlyWhatIsLeft(t *testing.T) {
	r := newDeliveryRig(t)
	ctx := context.Background()
	m := r.message(t, "task.completed", 1)
	r.webhook.err = errors.New("503")
	if err := r.x.Handle(ctx, m); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.acked) != 0 || len(r.chat.messages()) != 1 {
		t.Fatalf("acked %v chat %v", r.broker.acked, r.chat.messages())
	}
	r.webhook.err = nil
	m.DeliveryCount = 2
	if err := r.x.Handle(ctx, m); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.acked) != 1 || len(r.chat.messages()) != 1 || len(r.webhook.messages()) != 1 {
		t.Fatalf("redelivery acked %v chat %v webhook %v", r.broker.acked, r.chat.messages(), r.webhook.messages())
	}
}

func TestFatalAndExhaustedTargetsAreDeadLettered(t *testing.T) {
	r := newDeliveryRig(t)
	ctx := context.Background()
	r.webhook.err = &replies.Fatal{Msg: "404"}
	m := r.message(t, "task.completed", 1)
	if err := r.x.Handle(ctx, m); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.dead) != 1 || r.broker.dead[0][replies.TargetField] != replies.TaskWebhookTarget ||
		r.broker.dead[0][events.DeadLetterReasonField] != "404" || len(r.broker.acked) != 1 {
		t.Fatalf("dead %v acked %v", r.broker.dead, r.broker.acked)
	}
	if err := r.x.Handle(ctx, m); err != nil || len(r.broker.dead) != 1 {
		t.Fatalf("a redelivery dead-lettered twice: %v %v", err, r.broker.dead)
	}

	r.webhook.err = errors.New("503")
	tired := r.message(t, "task.completed", 21)
	if err := r.x.Handle(ctx, tired); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.dead) != 3 || len(r.broker.acked) != 3 || len(r.chat.messages()) != 1 {
		t.Fatalf("exhausted: dead %v acked %v chat %v", r.broker.dead, r.broker.acked, r.chat.messages())
	}
}

func TestReplaySendsToItsTargetOnly(t *testing.T) {
	r := newDeliveryRig(t)
	ctx := context.Background()
	r.webhook.err = &replies.Fatal{Msg: "404"}
	m := r.message(t, "task.completed", 1)
	if err := r.x.Handle(ctx, m); err != nil {
		t.Fatal(err)
	}
	r.webhook.err = nil
	replay := r.broker.dead[0]
	if err := r.x.Handle(ctx, events.Message{ID: "replay-1", Fields: replay, DeliveryCount: 1}); err != nil {
		t.Fatal(err)
	}
	if len(r.webhook.messages()) != 1 || len(r.chat.messages()) != 1 {
		t.Fatalf("replay chat %v webhook %v", r.chat.messages(), r.webhook.messages())
	}
}

func TestUndecodableAndOrphanEventsAreAcked(t *testing.T) {
	r := newDeliveryRig(t)
	ctx := context.Background()
	if err := r.x.Handle(ctx, events.Message{ID: "bad", Fields: map[string]string{"x": "y"}, DeliveryCount: 1}); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.dead) != 1 || len(r.broker.acked) != 1 {
		t.Fatalf("undecodable: dead %v acked %v", r.broker.dead, r.broker.acked)
	}
	r.task = uuid.NewString()
	if err := r.x.Handle(ctx, r.message(t, "task.completed", 1)); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.dead) != 1 || len(r.broker.acked) != 2 || len(r.chat.messages()) != 0 {
		t.Fatalf("gone task: dead %v acked %v", r.broker.dead, r.broker.acked)
	}
}

type claimBroker struct {
	broker
	idle  time.Duration
	count int
}

func (b *claimBroker) Autoclaim(_ context.Context, _, _, _ string, idle time.Duration, _ string, count int) ([]events.Message, error) {
	b.idle, b.count = idle, count
	return nil, nil
}

func TestClaimIdleCoversAWholeBatchOfSlowSends(t *testing.T) {
	b := &claimBroker{}
	x, err := replies.New(replies.Deps{
		Broker: b, Dedup: &dedup{keys: map[string]bool{}}, Consumer: "c1", Tasks: tasks{},
		Replies: func(context.Context, string) (*domain.Reply, bool, error) { return nil, false, nil },
		Senders: map[string]replies.Sender{"http": &sender{}},
		Config:  replies.Config{AutoclaimIdle: time.Minute, AutoclaimEvery: time.Second, DedupTTL: time.Hour, Block: time.Second, BatchSize: 10, MaxAttempts: 5},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := x.Reclaim(context.Background()); err != nil {
		t.Fatal(err)
	}
	if worst := 10 * 2 * 30 * time.Second; b.idle < worst || b.count != 10 {
		t.Fatalf("claim idle %s count %d; a batch of 10 can take %s", b.idle, b.count, worst)
	}
}

type gate struct {
	sender
	in      chan struct{}
	release chan struct{}
}

func (g *gate) Send(ctx context.Context, s replies.Send, message string) error {
	g.in <- struct{}{}
	select {
	case <-g.release:
	case <-time.After(2 * time.Second):
		return errors.New("the gate was never opened")
	}
	return g.sender.Send(ctx, s, message)
}

func TestTwoReplicasHandlingOneMessageSendEachTargetOnce(t *testing.T) {
	r := newDeliveryRig(t)
	g := &gate{in: make(chan struct{}, 4), release: make(chan struct{})}
	x, err := replies.New(replies.Deps{
		Broker: r.broker, Dedup: r.dedup, Consumer: "c2", Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
		Tasks: tasks{r.task: {ID: r.task, Owner: "u1",
			Parameters: map[string]any{"delivery_address": map[string]any{"type": "slack", "sender": "http"}}}},
		Replies: func(context.Context, string) (*domain.Reply, bool, error) {
			return &domain.Reply{Markup: "slack"}, true, nil
		},
		Senders: map[string]replies.Sender{"http": g},
	})
	if err != nil {
		t.Fatal(err)
	}
	m := r.message(t, "task.completed", 1)
	done := make(chan error, 1)
	go func() { done <- x.Handle(context.Background(), m) }()
	<-g.in
	other := m
	other.DeliveryCount = 2
	if err := x.Handle(context.Background(), other); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.acked) != 0 {
		t.Fatalf("the claimer acknowledged a message another replica is sending: %v", r.broker.acked)
	}
	close(g.release)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if got := g.messages(); len(got) != 1 {
		t.Fatalf("sent %v", got)
	}
}

func TestReplayForAnotherGroupIsAckedUnsent(t *testing.T) {
	r := newDeliveryRig(t)
	m := r.message(t, "task.completed", 1)
	m.Fields[events.TargetGroupField] = events.PlatformGroup
	if err := r.x.Handle(context.Background(), m); err != nil {
		t.Fatal(err)
	}
	if len(r.broker.acked) != 1 || len(r.chat.messages()) != 0 || len(r.webhook.messages()) != 0 {
		t.Fatalf("acked %v chat %v webhook %v", r.broker.acked, r.chat.messages(), r.webhook.messages())
	}
}
