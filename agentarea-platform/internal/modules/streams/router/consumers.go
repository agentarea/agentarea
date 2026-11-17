package router

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

const (
	changesBlock = 5 * time.Second
	changesCount = 100
	changesPause = time.Second
)

// FollowChanges keeps the router's cache in step with streams.subscriptions.changed: it tails the
// topic from its end and forgets the stream each notice names, every stream when it names none.
func (r *Router) FollowChanges(ctx context.Context) error {
	topic := service.SubscriptionsChangedTopic()
	cursor, err := r.d.Broker.LastID(ctx, topic)
	if err != nil {
		return err
	}
	r.Invalidate("")
	for {
		next, msgs, err := r.d.Broker.Tail(ctx, topic, cursor, changesBlock, changesCount)
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			r.d.Log.WarnContext(ctx, "Reading subscription changes failed; the cache starts over", "error", err)
			r.Invalidate("")
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(changesPause):
			}
			continue
		}
		cursor = next
		for _, m := range msgs {
			r.Invalidate(changedStream(m.Fields))
		}
	}
}

func changedStream(fields map[string]string) string {
	e, err := events.Decode(fields)
	if err != nil {
		return ""
	}
	id, _ := e.Data["stream_id"].(string)
	return id
}

// Consumers are the worker's stream consumers: the subscription changes, the events view and the
// router, each over every partition of streams.events. The subscriber's delivery limit is
// Settings.MaxAttempts; past it the router records what is missing as error and dead-letters.
func Consumers(d Deps) []lifecycle.Component {
	if d.Subscriber == nil || d.DB == nil || d.Service == nil {
		return nil
	}
	r := New(d)
	view := NewEventsView(d)
	topics := events.StreamEventsPartitions(r.d.Settings.Partitions)
	var out []lifecycle.Component
	if d.Broker != nil {
		out = append(out, lifecycle.Loop("streams-subscription-changes", r.FollowChanges))
	}
	out = append(out,
		group("streams-events-view", d.Subscriber, topics, events.EventsViewGroup, view.Handle, view.GiveUp),
		group("streams-router", d.Subscriber, topics, events.RouterGroup, r.Handle, r.GiveUp),
	)
	return out
}

func group(name string, sub events.GroupSubscriber, topics []string, g string, h, giveUp events.Handler) lifecycle.Component {
	var running events.Subscription
	return lifecycle.Func(name,
		func(ctx context.Context) error {
			s, err := sub.SubscribeMany(context.WithoutCancel(ctx), topics, g, h, events.DeadLetterTopic(events.StreamEvents, g), giveUp)
			if err != nil {
				return err
			}
			running = s
			return nil
		},
		func(ctx context.Context) error {
			if running == nil {
				return nil
			}
			err := running.Stop(ctx)
			running = nil
			if errors.Is(err, context.Canceled) {
				return nil
			}
			return err
		})
}
