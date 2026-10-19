// Package ingest hands raw poll items to the platform's ingest over the
// broker topic streams.ingest (ADR-0040 §3). Each message carries one item as
// the source sent it, or a gap; the platform names, keys and dedups it.
package ingest

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"

	"github.com/agentarea/event-service/internal/tracing"
)

const (
	// Topic is the logical name; the broker adapter puts the namespace in front.
	Topic = "streams.ingest"
	// Retention is how long the topic keeps an entry: enough to ride out a
	// consumer outage, as every bus topic does.
	Retention = 72 * time.Hour

	KindItem = "item"
	KindGap  = "gap"
)

// Submitter appends one message to a topic.
type Submitter interface {
	Submit(ctx context.Context, stream string, fields map[string]string, retention time.Duration) (string, error)
}

// Publisher writes a source's items to streams.ingest.
type Publisher struct {
	broker Submitter
	now    func() time.Time
}

// NewPublisher wraps the broker.
func NewPublisher(broker Submitter) *Publisher {
	return &Publisher{broker: broker, now: time.Now}
}

// Item publishes one raw item.
func (p *Publisher) Item(ctx context.Context, sourceID string, item any) error {
	return p.publish(ctx, sourceID, KindItem, item)
}

// Gap publishes that items of the source may be missing, and why.
func (p *Publisher) Gap(ctx context.Context, sourceID, reason string) error {
	return p.publish(ctx, sourceID, KindGap, map[string]string{"reason": reason})
}

func (p *Publisher) publish(ctx context.Context, sourceID, kind string, item any) (err error) {
	ctx, span := tracing.Tracer().Start(ctx, "publish "+Topic,
		trace.WithSpanKind(trace.SpanKindProducer),
		trace.WithAttributes(
			tracing.AttrSourceID.String(sourceID),
			attribute.String("messaging.system", "redis"),
			attribute.String("messaging.destination.name", Topic),
			attribute.String("agentarea.ingest.kind", kind),
		),
	)
	defer func() {
		if err != nil {
			tracing.RecordError(span, err)
		}
		span.End()
	}()

	encoded, err := json.Marshal(item)
	if err != nil {
		return fmt.Errorf("encode %s of source %s: %w", kind, sourceID, err)
	}
	fields := map[string]string{
		"source_id":   sourceID,
		"kind":        kind,
		"item":        string(encoded),
		"received_at": p.now().UTC().Format(time.RFC3339Nano),
	}
	if traceparent := tracing.Traceparent(ctx); traceparent != "" {
		fields[tracing.TraceparentField] = traceparent
	}
	if _, err := p.broker.Submit(ctx, Topic, fields, Retention); err != nil {
		return fmt.Errorf("publish %s of source %s: %w", kind, sourceID, err)
	}
	return nil
}
