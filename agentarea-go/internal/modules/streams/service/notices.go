package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
)

// SubscriptionsChanged is the domain event a stream's subscription change publishes (domain/events.py).
const SubscriptionsChanged = "streams.subscriptions.changed"

// SubscriptionsChangedTopic is where the relay publishes it; the router's cache follows it.
func SubscriptionsChangedTopic() string { return events.DomainEventsTopic(SubscriptionsChanged) }

// SubscriptionsChangedNotice is subscriptionsChanged for the module's other packages (delivery's unsubscribe).
func SubscriptionsChangedNotice(ctx context.Context, sess db.Session, createdBy, streamID string) error {
	return subscriptionsChanged(ctx, sess, createdBy, streamID)
}

// subscriptionsChanged enqueues, in sess's transaction, the notice that tells the router to
// read streamID's subscriptions again (StreamService._subscriptions_changed). createdBy is the
// principal the change came from.
func subscriptionsChanged(ctx context.Context, sess db.Session, createdBy, streamID string) error {
	return events.Publish(ctx, sess, createdBy, events.NewEnvelope(SubscriptionsChanged, map[string]any{
		"stream_id": streamID, "aggregate_id": streamID, "aggregate_type": "stream",
	}))
}
