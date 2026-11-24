// Package events is the event bus (ADR-0018): broker-neutral ports, the
// transactional outbox (event_outbox), and the durable stream broker under
// them (Redis Streams today, AGENTAREA_BROKER).
//
// Topic names, the CloudEvents envelope and field encodings are a contract
// with the event service, enterprise readers, the SSE feeds and the rows and
// stream entries already stored before cutover. An event is never
// published to the broker only: Publish stores it on the caller's
// transaction (event_outbox) and the Relay puts it on the broker after commit.
package events

import (
	"context"
	"errors"
	"iter"
	"time"
)

// IntegrationEvent is the cross-boundary envelope (CloudEvents 1.0 attribute
// names; events/ports.py). Type is versioned and context-owned
// ("agentarea.agents.v1.AgentDeleted"); Subject is the aggregate id and the
// partition key.
type IntegrationEvent struct {
	ID              string            `json:"id"`
	Type            string            `json:"type"`
	Source          string            `json:"source"`
	Time            time.Time         `json:"time"`
	SpecVersion     string            `json:"specversion"`
	DataContentType string            `json:"datacontenttype"`
	Subject         string            `json:"subject,omitempty"`
	CorrelationID   string            `json:"correlation_id,omitempty"`
	CausationID     string            `json:"causation_id,omitempty"`
	TraceParent     string            `json:"traceparent,omitempty"`
	Data            map[string]any    `json:"data"`
	Extensions      map[string]string `json:"extensions"`
}

// PartitionKey orders events: the subject, else the event id.
func (e IntegrationEvent) PartitionKey() string {
	if e.Subject != "" {
		return e.Subject
	}
	return e.ID
}

// Handler consumes one event. Delivery is at least once, so handlers are
// idempotent; an error leaves the message unacknowledged for redelivery.
type Handler func(ctx context.Context, e IntegrationEvent) error

// ErrUnprocessable marks a message no redelivery can fix; the adapter
// dead-letters it at once. Wrap it.
var ErrUnprocessable = errors.New("unprocessable event")

// Subscription is a running subscription.
type Subscription interface {
	Stop(ctx context.Context) error
}

// Publisher emits an event to its topic, "domain.events.<type>" unless topic
// is given (a stream's "streams.events.<partition>").
type Publisher interface {
	Publish(ctx context.Context, e IntegrationEvent, topic string) error
}

// Subscriber is a durable consumer-group subscription; competing consumers
// share one group.
type Subscriber interface {
	Subscribe(ctx context.Context, topic, group string, h Handler) (Subscription, error)
}

// GroupSubscriber is one consumer group over the partitions of one topic. A
// message delivered past the limit goes to onDeadLetter, then to
// deadLetterTopic, and is acknowledged.
type GroupSubscriber interface {
	SubscribeMany(ctx context.Context, topics []string, group string, h Handler,
		deadLetterTopic string, onDeadLetter Handler) (Subscription, error)
}

// Stream is the read side (CQRS): catch-up from an opaque offset ("0" is the
// beginning), then the live tail, in append order.
type Stream interface {
	Read(ctx context.Context, stream, fromOffset string) iter.Seq2[IntegrationEvent, error]
}

// Message is a message claimed from a broker stream. DeliveryCount caps
// poison loops whatever the broker.
type Message struct {
	ID            string
	Fields        map[string]string
	DeliveryCount int
	Stream        string
}

// GroupInfo is a consumer group's position on its stream.
type GroupInfo struct {
	Lag             int64
	Consumers       int
	LastDeliveredID string
}

// PendingSummary is what a group holds unacknowledged. OldestAge is nil when
// nothing is pending.
type PendingSummary struct {
	Count     int64
	OldestAge *time.Duration
}

// Broker is the durable stream broker (broker/interface.py BrokerClient).
// Stream names are logical; the adapter adds the namespace
// (AGENTAREA_EVENT_NAMESPACE).
type Broker interface {
	// Submit appends fields and trims entries older than retention.
	Submit(ctx context.Context, stream string, fields map[string]string, retention time.Duration) (string, error)
	// EnsureGroup creates the group and stream if absent; idempotent.
	EnsureGroup(ctx context.Context, stream, group, start string) error
	// Consume claims up to count new messages, blocking up to block.
	Consume(ctx context.Context, stream, group, consumer string, count int, block time.Duration) ([]Message, error)
	// ConsumeMany is Consume over several streams; each message names its stream.
	ConsumeMany(ctx context.Context, streams []string, group, consumer string, count int, block time.Duration) ([]Message, error)
	Ack(ctx context.Context, stream, group, messageID string) error
	// Autoclaim takes over messages pending longer than minIdle from dead consumers.
	Autoclaim(ctx context.Context, stream, group, consumer string, minIdle time.Duration, start string, count int) ([]Message, error)
	// Tail is a broadcast read with no group: "$" live only, "0" from the start.
	Tail(ctx context.Context, stream, lastID string, block time.Duration, count int) (next string, msgs []Message, err error)
	// GroupInfo is nil when the stream or group does not exist.
	GroupInfo(ctx context.Context, stream, group string) (*GroupInfo, error)
	Pending(ctx context.Context, stream, group string) (PendingSummary, error)
	Length(ctx context.Context, stream string) (int64, error)
	// ReadRange returns entries with ids in [start, end] ("-", "+", "(" exclusive).
	ReadRange(ctx context.Context, stream, start, end string, count int) ([]Message, error)
	// LastID is the newest entry's id, "0-0" when empty.
	LastID(ctx context.Context, stream string) (string, error)
	// Notify broadcasts to current listeners; nothing is kept.
	Notify(ctx context.Context, channel string, fields map[string]string) error
	OpenLive(ctx context.Context) (LiveChannels, error)
	// Move appends to target and removes from source atomically; "" when the
	// message is no longer in source.
	Move(ctx context.Context, source, messageID, target string, fields map[string]string) (string, error)
}

// LiveChannels are broadcast channels one connection listens on: at most
// once, nothing kept.
type LiveChannels interface {
	Subscribe(ctx context.Context, channel string) error
	Unsubscribe(ctx context.Context, channel string) error
	// Next returns the next broadcast, or ok false after timeout.
	Next(ctx context.Context, timeout time.Duration) (channel string, fields map[string]string, ok bool, err error)
	Close() error
}

// Dedup claims keys so a redelivered message is handled once (SETNX).
type Dedup interface {
	// Claim returns false when key is already claimed or kept.
	Claim(ctx context.Context, key string, hold time.Duration) (bool, error)
	// Keep makes a claim permanent for the dedup TTL (AGENTAREA_CHANNEL_DEDUP_TTL).
	Keep(ctx context.Context, key string) error
	Contains(ctx context.Context, key string) (bool, error)
	Release(ctx context.Context, key string) error
}
