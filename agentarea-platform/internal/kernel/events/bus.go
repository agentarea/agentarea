package events

import (
	"context"
	"errors"
	"fmt"
	"iter"
	"log/slog"
	"maps"
	"strings"
	"time"

	"github.com/google/uuid"
)

// BusOptions are redis_streams.py RedisStreamsEventBus's defaults when zero.
type BusOptions struct {
	// Retention trims a topic as it is appended to; required.
	Retention time.Duration
	// Consumer names this process in its groups; default c-<12 hex>.
	Consumer string
	// MaxDelivery is the deliveries after which a message is dead-lettered (5).
	MaxDelivery int
	// MinIdle is how long a message stays pending before it is reclaimed (60s).
	MinIdle time.Duration
	// Block is SubscribeMany's read block (2s); Subscribe blocks 5s as Python does.
	Block time.Duration
}

// Bus is Publisher, Subscriber and GroupSubscriber over a Broker
// (events/adapters/redis_streams.py RedisStreamsEventBus): at-least-once
// consumer groups, reclaim from dead consumers, poison messages capped by
// delivery count.
type Bus struct {
	broker Broker
	log    *slog.Logger
	o      BusOptions
}

var (
	_ Publisher       = (*Bus)(nil)
	_ Subscriber      = (*Bus)(nil)
	_ GroupSubscriber = (*Bus)(nil)
)

// NewBus builds a bus over b.
func NewBus(b Broker, log *slog.Logger, o BusOptions) (*Bus, error) {
	if o.Retention <= 0 {
		return nil, errors.New("events.NewBus: retention is required")
	}
	if o.Consumer == "" {
		o.Consumer = "c-" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12]
	}
	if o.MaxDelivery <= 0 {
		o.MaxDelivery = 5
	}
	if o.MinIdle <= 0 {
		o.MinIdle = time.Minute
	}
	if o.Block <= 0 {
		o.Block = 2 * time.Second
	}
	return &Bus{broker: b, log: log, o: o}, nil
}

// Publish appends e to topic, domain.events.<type> when topic is empty.
func (b *Bus) Publish(ctx context.Context, e IntegrationEvent, topic string) error {
	fields, err := Encode(e)
	if err != nil {
		return err
	}
	if topic == "" {
		topic = DomainEventsTopic(e.Type)
	}
	_, err = b.broker.Submit(ctx, topic, fields, b.o.Retention)
	return err
}

type subscription struct {
	cancel context.CancelFunc
	done   chan struct{}
}

func (s *subscription) Stop(ctx context.Context) error {
	s.cancel()
	select {
	case <-s.done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (b *Bus) start(ctx context.Context, loop func(ctx context.Context)) Subscription {
	runCtx, cancel := context.WithCancel(context.WithoutCancel(ctx))
	s := &subscription{cancel: cancel, done: make(chan struct{})}
	go func() {
		defer close(s.done)
		loop(runCtx)
	}()
	return s
}

// Subscribe joins group on topic from "$": the group gets what is published
// after it first exists, and keeps its place across restarts.
func (b *Bus) Subscribe(ctx context.Context, topic, group string, h Handler) (Subscription, error) {
	if err := b.broker.EnsureGroup(ctx, topic, group, "$"); err != nil {
		return nil, err
	}
	return b.start(ctx, func(ctx context.Context) {
		for ctx.Err() == nil {
			err := b.pass(ctx, topic, group, h)
			if err != nil && ctx.Err() == nil {
				b.log.ErrorContext(ctx, "Event consume loop error", "stream", topic, "error", err)
				sleep(ctx, time.Second)
			}
		}
	}), nil
}

func (b *Bus) pass(ctx context.Context, topic, group string, h Handler) error {
	reclaimed, err := b.broker.Autoclaim(ctx, topic, group, b.o.Consumer, b.o.MinIdle, "0-0", 100)
	if err != nil {
		return err
	}
	for _, m := range reclaimed {
		if err := b.handle(ctx, topic, group, m, h, nil); err != nil {
			return err
		}
	}
	fresh, err := b.broker.Consume(ctx, topic, group, b.o.Consumer, 10, 5*time.Second)
	if err != nil {
		return err
	}
	for _, m := range fresh {
		if err := b.handle(ctx, topic, group, m, h, nil); err != nil {
			return err
		}
	}
	return nil
}

type deadLetter struct {
	topic    string
	callback Handler
}

// SubscribeMany is one group over topics, created from "0" so events
// published before the group existed are not lost.
func (b *Bus) SubscribeMany(ctx context.Context, topics []string, group string, h Handler,
	deadLetterTopic string, onDeadLetter Handler) (Subscription, error) {
	var streams []string
	seen := map[string]bool{}
	for _, t := range topics {
		if !seen[t] {
			seen[t] = true
			streams = append(streams, t)
		}
	}
	if len(streams) == 0 {
		return nil, fmt.Errorf("subscribe_many for group %s needs at least one topic", group)
	}
	for _, s := range streams {
		if err := b.broker.EnsureGroup(ctx, s, group, "0"); err != nil {
			return nil, err
		}
	}
	dl := &deadLetter{topic: deadLetterTopic, callback: onDeadLetter}
	return b.start(ctx, func(ctx context.Context) {
		var nextClaim time.Time
		for ctx.Err() == nil {
			err := func() error {
				if !time.Now().Before(nextClaim) {
					for _, s := range streams {
						reclaimed, err := b.broker.Autoclaim(ctx, s, group, b.o.Consumer, b.o.MinIdle, "0-0", 100)
						if err != nil {
							return err
						}
						for _, m := range reclaimed {
							if err := b.handle(ctx, s, group, m, h, dl); err != nil {
								return err
							}
						}
					}
					nextClaim = time.Now().Add(b.o.MinIdle)
				}
				fresh, err := b.broker.ConsumeMany(ctx, streams, group, b.o.Consumer, 10, b.o.Block)
				if err != nil {
					return err
				}
				for _, m := range fresh {
					if err := b.handle(ctx, m.Stream, group, m, h, dl); err != nil {
						return err
					}
				}
				return nil
			}()
			if err != nil && ctx.Err() == nil {
				b.log.ErrorContext(ctx, "Event consume loop error", "group", group, "error", err)
				sleep(ctx, time.Second)
			}
		}
	}), nil
}

// handle returns only broker errors; a handler's failure leaves the message
// pending for redelivery.
func (b *Bus) handle(ctx context.Context, stream, group string, m Message, h Handler, dl *deadLetter) error {
	if target, ok := m.Fields[TargetGroupField]; ok && target != group {
		return b.broker.Ack(ctx, stream, group, m.ID)
	}
	if m.DeliveryCount > b.o.MaxDelivery {
		if dl != nil {
			return b.deadLetter(ctx, stream, group, m, dl)
		}
		b.log.ErrorContext(ctx, "Dropping poison message", "id", m.ID, "stream", stream, "deliveries", m.DeliveryCount)
		return b.broker.Ack(ctx, stream, group, m.ID)
	}
	e, err := Decode(m.Fields)
	if err != nil {
		b.log.ErrorContext(ctx, "Undecodable message", "id", m.ID, "stream", stream, "error", err)
		if dl != nil {
			if err := b.submitDeadLetter(ctx, dl, stream, group, m, "undecodable message"); err != nil {
				return err
			}
		}
		return b.broker.Ack(ctx, stream, group, m.ID)
	}
	if herr := h(ctx, e); herr != nil {
		if !errors.Is(herr, ErrUnprocessable) {
			b.log.ErrorContext(ctx, "Handler failed; will redeliver", "id", m.ID, "stream", stream, "error", herr)
			return nil
		}
		b.log.ErrorContext(ctx, "Unprocessable message", "id", m.ID, "stream", stream, "error", herr)
		if dl != nil {
			if err := b.submitDeadLetter(ctx, dl, stream, group, m, "unprocessable: "+herr.Error()); err != nil {
				return err
			}
		}
	}
	return b.broker.Ack(ctx, stream, group, m.ID)
}

func (b *Bus) deadLetter(ctx context.Context, stream, group string, m Message, dl *deadLetter) error {
	attempts := m.DeliveryCount - 1
	b.log.ErrorContext(ctx, "Message failed every delivery; dead-lettering it",
		"id", m.ID, "stream", stream, "attempts", attempts, "dead_letter_topic", dl.topic)
	reason := fmt.Sprintf("max delivery attempts (%d) exceeded", attempts)
	e, err := Decode(m.Fields)
	if err == nil && dl.callback != nil {
		err = dl.callback(ctx, e)
	}
	if err != nil {
		reason = fmt.Sprintf("%s; dead-letter callback failed: %T: %v", reason, err, err)
	}
	if err := b.submitDeadLetter(ctx, dl, stream, group, m, reason); err != nil {
		return err
	}
	return b.broker.Ack(ctx, stream, group, m.ID)
}

func (b *Bus) submitDeadLetter(ctx context.Context, dl *deadLetter, stream, group string, m Message, reason string) error {
	fields := maps.Clone(m.Fields)
	if fields == nil {
		fields = map[string]string{}
	}
	fields[DeadLetterSourceField] = stream
	fields[DeadLetterGroupField] = group
	if r := []rune(reason); len(r) > 500 {
		reason = string(r[:500])
	}
	fields[DeadLetterReasonField] = reason
	_, err := b.broker.Submit(ctx, dl.topic, fields, DeadLetterRetention)
	return err
}

func sleep(ctx context.Context, d time.Duration) {
	select {
	case <-ctx.Done():
	case <-time.After(d):
	}
}

// StreamReader is Stream over a Broker broadcast tail
// (RedisStreamsEventStream): every reader sees every entry, no group, no
// ack, at most once.
type StreamReader struct {
	broker Broker
	block  time.Duration
	log    *slog.Logger
}

var _ Stream = (*StreamReader)(nil)

// NewStreamReader reads with block per wait (5s when zero).
func NewStreamReader(b Broker, log *slog.Logger, block time.Duration) *StreamReader {
	if block <= 0 {
		block = 5 * time.Second
	}
	return &StreamReader{broker: b, block: block, log: log}
}

// Read yields entries after fromOffset, then the live tail, until ctx ends
// or the broker fails; undecodable entries are skipped.
func (r *StreamReader) Read(ctx context.Context, stream, fromOffset string) iter.Seq2[IntegrationEvent, error] {
	return func(yield func(IntegrationEvent, error) bool) {
		cursor := fromOffset
		for ctx.Err() == nil {
			next, msgs, err := r.broker.Tail(ctx, stream, cursor, r.block, 100)
			if err != nil {
				if ctx.Err() == nil {
					yield(IntegrationEvent{}, err)
				}
				return
			}
			cursor = next
			for _, m := range msgs {
				e, err := Decode(m.Fields)
				if err != nil {
					r.log.ErrorContext(ctx, "Undecodable stream message; skipping", "id", m.ID, "stream", stream, "error", err)
					continue
				}
				if !yield(e, nil) {
					return
				}
			}
		}
	}
}

// ReplayResult counts what ReplayDeadLetters moved and left.
type ReplayResult struct {
	Moved   int
	Skipped int
}

// ReplayDeadLetters moves dead letters with ids in [start, end] from dlq back
// to their source (broker/dlq.py): the one stream of targets, or for a
// dead-letter stream shared by partitions, the one the dead letter names.
// Each is appended without the dead-letter fields and removed in one step,
// so a second run replays nothing twice. A dead letter that names its group is
// replayed for that group only: the entry carries TargetGroupField and the other groups of the
// source acknowledge it unprocessed.
func ReplayDeadLetters(ctx context.Context, b Broker, log *slog.Logger, dlq string, targets []string, start, end string, batch int) (ReplayResult, error) {
	var res ReplayResult
	if start == "" {
		start = "-"
	}
	if end == "" {
		end = "+"
	}
	if batch <= 0 {
		batch = 100
	}
	cursor := start
	for {
		msgs, err := b.ReadRange(ctx, dlq, cursor, end, batch)
		if err != nil {
			return res, err
		}
		for _, m := range msgs {
			target, ok := replayTarget(m.Fields, targets)
			if !ok {
				res.Skipped++
				log.ErrorContext(ctx, "dead letter names a source outside the targets; left in place",
					"id", m.ID, "dlq", dlq, "source", m.Fields[DeadLetterSourceField], "targets", targets)
				continue
			}
			fields := maps.Clone(m.Fields)
			delete(fields, DeadLetterReasonField)
			delete(fields, DeadLetterSourceField)
			if group, ok := fields[DeadLetterGroupField]; ok {
				delete(fields, DeadLetterGroupField)
				fields[TargetGroupField] = group
			}
			newID, err := b.Move(ctx, dlq, m.ID, target, fields)
			if err != nil {
				return res, err
			}
			if newID == "" {
				continue
			}
			res.Moved++
			log.InfoContext(ctx, "replayed dead letter", "id", m.ID, "dlq", dlq, "target", target,
				"new_id", newID, "reason", m.Fields[DeadLetterReasonField])
		}
		if len(msgs) < batch {
			return res, nil
		}
		cursor = "(" + msgs[len(msgs)-1].ID
	}
}

func replayTarget(fields map[string]string, targets []string) (string, bool) {
	source, named := fields[DeadLetterSourceField]
	if len(targets) == 1 {
		return targets[0], !named || source == targets[0]
	}
	for _, t := range targets {
		if named && t == source {
			return t, true
		}
	}
	return "", false
}
