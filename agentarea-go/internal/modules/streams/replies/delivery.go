package replies

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// DedupPrefix is the dedup cache prefix of delivered targets (DedupCache "channel-delivery").
const DedupPrefix = "channel-delivery"

const (
	replyTTL   = time.Minute
	maxBackoff = 60 * time.Second

	// maxSendTimeout is the longest a sender waits on one call (smtp, signed webhook); a message has at most
	// maxTargets targets (the delivery address and the task webhook).
	maxSendTimeout = 30 * time.Second
	maxTargets     = 2
	sendingPrefix  = "sending:"
)

// Config is ChannelDeliverySettings (AGENTAREA_CHANNEL_*), Python's names and defaults.
type Config struct {
	AutoclaimIdle  time.Duration
	AutoclaimEvery time.Duration
	DedupTTL       time.Duration
	Block          time.Duration
	BatchSize      int
	MaxAttempts    int
}

// DefaultConfig is Python's defaults.
func DefaultConfig() Config {
	return Config{AutoclaimIdle: time.Minute, AutoclaimEvery: 30 * time.Second, DedupTTL: 24 * time.Hour,
		Block: 5 * time.Second, BatchSize: 10, MaxAttempts: 20}
}

// LoadConfig reads Config; a value that is not positive fails startup.
func LoadConfig(l *config.Loader) Config {
	d := DefaultConfig()
	c := Config{
		AutoclaimIdle:  l.DurationEnv("AGENTAREA_CHANNEL_AUTOCLAIM_IDLE", d.AutoclaimIdle),
		AutoclaimEvery: l.DurationEnv("AGENTAREA_CHANNEL_AUTOCLAIM_EVERY", d.AutoclaimEvery),
		DedupTTL:       l.DurationEnv("AGENTAREA_CHANNEL_DEDUP_TTL", d.DedupTTL),
		Block:          l.DurationEnv("AGENTAREA_CHANNEL_BLOCK", d.Block),
		BatchSize:      l.IntEnv("AGENTAREA_CHANNEL_BATCH_SIZE", d.BatchSize),
		MaxAttempts:    l.IntEnv("AGENTAREA_CHANNEL_MAX_ATTEMPTS", d.MaxAttempts),
	}
	for name, ok := range map[string]bool{
		"AGENTAREA_CHANNEL_AUTOCLAIM_IDLE": c.AutoclaimIdle > 0, "AGENTAREA_CHANNEL_AUTOCLAIM_EVERY": c.AutoclaimEvery > 0,
		"AGENTAREA_CHANNEL_DEDUP_TTL": c.DedupTTL > 0, "AGENTAREA_CHANNEL_BLOCK": c.Block > 0,
		"AGENTAREA_CHANNEL_BATCH_SIZE": c.BatchSize > 0, "AGENTAREA_CHANNEL_MAX_ATTEMPTS": c.MaxAttempts > 0,
	} {
		if !ok {
			l.Fail(name, errors.New("must be positive"))
		}
	}
	return c
}

// Replies reads the reply block of a catalog entry by its slug; false when there is no entry.
type Replies func(ctx context.Context, slug string) (*domain.Reply, bool, error)

// Deps are what delivery runs on.
type Deps struct {
	Broker events.Broker
	// Dedup is the dedup cache of delivered targets (prefix DedupPrefix, TTL Config.DedupTTL).
	Dedup events.Dedup
	Tasks runsapi.TaskOutcomes
	// Replies is the catalog entries' reply blocks, read at send time.
	Replies Replies
	// Senders by the name a target gives (http, telegram_live, smtp, task_webhook).
	Senders map[string]Sender
	// Consumer names this replica in the delivery group.
	Consumer string
	Config   Config
	Now      func() time.Time
	Log      *slog.Logger
}

// Delivery is the consumer of the delivery group on tasks.events and its autoclaimer.
type Delivery struct {
	d       Deps
	mu      sync.Mutex
	replies map[string]cachedReply
}

type cachedReply struct {
	at    time.Time
	reply *domain.Reply
}

// claimIdle is how long a message stays pending before another replica takes it: the configured
// AutoclaimIdle, never less than the worst case of one batch sent target by target.
func (c Config) claimIdle() time.Duration {
	return max(c.AutoclaimIdle, time.Duration(c.BatchSize*maxTargets)*maxSendTimeout)
}

// DeadLetterTopic is where a target that fails for good goes.
func DeadLetterTopic() string { return events.DeadLetterTopic(events.TaskEvents, events.DeliveryGroup) }

// New builds a Delivery.
func New(d Deps) (*Delivery, error) {
	switch {
	case d.Broker == nil, d.Dedup == nil, d.Tasks == nil, d.Replies == nil, len(d.Senders) == 0:
		return nil, errors.New("task reply delivery needs a broker, dedup, task reads, reply blocks and senders")
	case d.Consumer == "":
		return nil, errors.New("task reply delivery needs a consumer name")
	}
	if d.Config == (Config{}) {
		d.Config = DefaultConfig()
	}
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Delivery{d: d, replies: map[string]cachedReply{}}, nil
}

// Components are the consumer and its autoclaimer.
func (x *Delivery) Components() []lifecycle.Component {
	return []lifecycle.Component{
		lifecycle.Loop("task reply delivery", x.consume),
		lifecycle.Loop("task reply autoclaimer", x.autoclaim),
	}
}

func (x *Delivery) consume(ctx context.Context) error {
	// From "0": events published before the group first existed still go out.
	if err := x.d.Broker.EnsureGroup(ctx, events.TaskEvents, events.DeliveryGroup, "0"); err != nil {
		return fmt.Errorf("delivery group on %s: %w", events.TaskEvents, err)
	}
	x.d.Log.InfoContext(ctx, "task reply delivery started", "consumer", x.d.Consumer)
	backoff := time.Second
	for ctx.Err() == nil {
		err := func() error {
			msgs, err := x.d.Broker.Consume(ctx, events.TaskEvents, events.DeliveryGroup, x.d.Consumer, x.d.Config.BatchSize, x.d.Config.Block)
			if err != nil {
				return err
			}
			for _, m := range msgs {
				if err := x.Handle(ctx, m); err != nil {
					return err
				}
			}
			return nil
		}()
		if err == nil {
			backoff = time.Second
			continue
		}
		if ctx.Err() != nil {
			break
		}
		x.d.Log.ErrorContext(ctx, "task reply delivery failed", "retry_in", backoff, "error", err)
		if sleep(ctx, backoff) != nil {
			break
		}
		backoff = min(backoff*2, maxBackoff)
	}
	return ctx.Err()
}

func (x *Delivery) autoclaim(ctx context.Context) error {
	if err := x.d.Broker.EnsureGroup(ctx, events.TaskEvents, events.DeliveryGroup, "0"); err != nil {
		return fmt.Errorf("delivery group on %s: %w", events.TaskEvents, err)
	}
	for {
		if _, err := x.Reclaim(ctx); err != nil && ctx.Err() == nil {
			x.d.Log.ErrorContext(ctx, "autoclaim of task reply delivery failed", "error", err)
		}
		if err := sleep(ctx, x.d.Config.AutoclaimEvery); err != nil {
			return err
		}
	}
}

// Reclaim takes the entries idle past AutoclaimIdle and handles each; it returns how many.
func (x *Delivery) Reclaim(ctx context.Context) (int, error) {
	msgs, err := x.d.Broker.Autoclaim(ctx, events.TaskEvents, events.DeliveryGroup, x.d.Consumer, x.d.Config.claimIdle(), "0-0", x.d.Config.BatchSize)
	if err != nil {
		return 0, err
	}
	if len(msgs) > 0 {
		x.d.Log.InfoContext(ctx, "autoclaimed task events", "count", len(msgs), "consumer", x.d.Consumer)
	}
	for _, m := range msgs {
		if err := x.Handle(ctx, m); err != nil {
			return 0, err
		}
	}
	return len(msgs), nil
}

// Handle sends one task event to each of its task's targets that shows it and acknowledges it
// once none is left. A target that failed and may be retried leaves the message pending; an
// error is the broker, the dedup cache or the task read failing.
func (x *Delivery) Handle(ctx context.Context, m events.Message) error {
	if group, ok := m.Fields[events.TargetGroupField]; ok && group != events.DeliveryGroup {
		return x.ack(ctx, m)
	}
	e, err := events.Decode(m.Fields)
	var ws scope.Workspace
	if err == nil {
		ws, err = scope.NewWorkspace(e.Extensions["workspace"], "")
	}
	if err == nil && e.Subject == "" {
		err = errors.New("no task")
	}
	if err != nil {
		x.d.Log.ErrorContext(ctx, "undecodable task event; dead-lettered", "message_id", m.ID, "error", err)
		if err := x.deadLetter(ctx, m, "", "undecodable task event: "+err.Error()); err != nil {
			return err
		}
		return x.ack(ctx, m)
	}
	task, ok, err := x.d.Tasks.OutcomeTask(ctx, ws, e.Subject)
	if err != nil {
		return fmt.Errorf("task %s of event %s: %w", e.Subject, e.ID, err)
	}
	if !ok {
		x.d.Log.InfoContext(ctx, "task of event is gone; nothing to deliver", "task_id", e.Subject, "event_id", e.ID)
		return x.ack(ctx, m)
	}
	targets, malformed := Targets(task)
	for _, why := range malformed {
		x.d.Log.ErrorContext(ctx, "task has a malformed reply target", "task_id", task.ID, "problem", why)
	}
	only, replay := m.Fields[TargetField]
	exhausted := m.DeliveryCount > x.d.Config.MaxAttempts
	failed := false
	for _, t := range targets {
		if (replay && t.Key != only) || !Visible(e.Type, t.Presentation) {
			continue
		}
		key := e.ID + ":" + t.Key
		if done, err := x.d.Dedup.Contains(ctx, key); err != nil || done {
			if err != nil {
				return err
			}
			continue
		}
		if !replay {
			if dead, err := x.d.Dedup.Contains(ctx, "dead:"+key); err != nil || dead {
				if err != nil {
					return err
				}
				continue
			}
		}
		if exhausted {
			if err := x.giveUp(ctx, m, t, key, fmt.Sprintf("max delivery attempts (%d) exceeded", m.DeliveryCount-1)); err != nil {
				return err
			}
			continue
		}
		lock := sendingPrefix + key
		mine, err := x.d.Dedup.Claim(ctx, lock, 2*maxSendTimeout)
		if err != nil {
			return err
		}
		if !mine {
			failed = true
			continue
		}
		err = x.send(ctx, e, ws, task.Owner, t)
		switch {
		case err == nil:
			if err := x.d.Dedup.Keep(ctx, key); err != nil {
				_ = x.d.Dedup.Release(ctx, lock)
				return err
			}
		case IsFatal(err):
			if err := x.giveUp(ctx, m, t, key, err.Error()); err != nil {
				return err
			}
		default:
			failed = true
			x.d.Log.WarnContext(ctx, "delivery of task event failed; retried", "event_id", e.ID, "target", t.Key, "error", err)
		}
		if err := x.d.Dedup.Release(ctx, lock); err != nil {
			return err
		}
	}
	if failed {
		return nil
	}
	return x.ack(ctx, m)
}

func (x *Delivery) send(ctx context.Context, e events.IntegrationEvent, ws scope.Workspace, owner string, t Target) error {
	sender, ok := x.d.Senders[t.Sender]
	if !ok {
		// A newer channel than this replica knows; one that knows it takes the message when reclaimed.
		return fmt.Errorf("no sender for %q", t.Sender)
	}
	data := make(map[string]any, len(e.Data)+len(t.Data))
	maps.Copy(data, e.Data)
	maps.Copy(data, t.Data)
	s := Send{
		Event:  Event{Type: e.Type, ID: e.ID, TaskID: e.Subject, Timestamp: events.PyISO(e.Time), Data: data},
		Target: t, Workspace: ws, Owner: owner,
	}
	if t.Key == AddressTarget {
		slug, _ := t.Config["type"].(string)
		reply, err := x.reply(ctx, slug)
		if err != nil {
			return err
		}
		s.Reply = reply
	}
	message, err := sender.Format(s)
	if err != nil {
		if IsFatal(err) {
			return err
		}
		return fatalf("cannot format %s: %v", e.Type, err)
	}
	return sender.Send(ctx, s, message)
}

func (x *Delivery) reply(ctx context.Context, slug string) (*domain.Reply, error) {
	now := x.d.Now()
	x.mu.Lock()
	c, ok := x.replies[slug]
	x.mu.Unlock()
	if !ok || now.Sub(c.at) >= replyTTL {
		reply, _, err := x.d.Replies(ctx, slug)
		if err != nil {
			return nil, fmt.Errorf("reply block of %q: %w", slug, err)
		}
		c = cachedReply{at: now, reply: reply}
		x.mu.Lock()
		x.replies[slug] = c
		x.mu.Unlock()
	}
	if c.reply == nil {
		return nil, fatalf("the catalog entry %q has no reply block", slug)
	}
	return c.reply, nil
}

// giveUp dead-letters one target. The delivered mark stays free for a replay; the dead mark only
// keeps a redelivery of the message from dead-lettering it twice.
func (x *Delivery) giveUp(ctx context.Context, m events.Message, t Target, key, reason string) error {
	if err := x.deadLetter(ctx, m, t.Key, reason); err != nil {
		return err
	}
	return x.d.Dedup.Keep(ctx, "dead:"+key)
}

func (x *Delivery) deadLetter(ctx context.Context, m events.Message, target, reason string) error {
	fields := maps.Clone(m.Fields)
	if fields == nil {
		fields = map[string]string{}
	}
	delete(fields, TargetField)
	if r := []rune(reason); len(r) > 500 {
		reason = string(r[:500])
	}
	fields[events.DeadLetterReasonField] = reason
	fields[events.DeadLetterGroupField] = events.DeliveryGroup
	if target != "" {
		fields[TargetField] = target
	}
	if _, err := x.d.Broker.Submit(ctx, DeadLetterTopic(), fields, events.DeadLetterRetention); err != nil {
		return err
	}
	who := target
	if who == "" {
		who = "every target"
	}
	x.d.Log.ErrorContext(ctx, "task event dead-lettered", "message_id", m.ID, "target", who, "reason", reason)
	return nil
}

func (x *Delivery) ack(ctx context.Context, m events.Message) error {
	return x.d.Broker.Ack(ctx, events.TaskEvents, events.DeliveryGroup, m.ID)
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
