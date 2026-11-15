package polling

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
)

// Backlog drains streams.ingest: the items the event service published before the pollers
// ingested in-process. Nothing new is written there; it runs so a cutover loses no item.
type Backlog struct {
	Broker   events.Broker
	Intake   Intake
	Consumer string
	Block    time.Duration
	Batch    int
	Log      *slog.Logger
}

const backlogClaimIdle = time.Minute

// Run consumes until ctx ends.
func (b Backlog) Run(ctx context.Context) error {
	if err := b.Broker.EnsureGroup(ctx, events.StreamsIngest, events.IngestGroup, "0"); err != nil {
		return fmt.Errorf("ingest group: %w", err)
	}
	wait := time.Second
	for ctx.Err() == nil {
		if err := b.round(ctx); err != nil && ctx.Err() == nil {
			b.Log.ErrorContext(ctx, "polled item backlog failed", "retry_in", wait, "error", err)
			t := time.NewTimer(wait)
			select {
			case <-ctx.Done():
			case <-t.C:
			}
			t.Stop()
			wait = min(wait*2, 30*time.Second)
			continue
		}
		wait = time.Second
	}
	return ctx.Err()
}

func (b Backlog) round(ctx context.Context) error {
	msgs, err := b.Broker.Autoclaim(ctx, events.StreamsIngest, events.IngestGroup, b.Consumer, backlogClaimIdle, "0-0", b.Batch)
	if err != nil {
		return fmt.Errorf("autoclaim: %w", err)
	}
	if len(msgs) == 0 {
		if msgs, err = b.Broker.Consume(ctx, events.StreamsIngest, events.IngestGroup, b.Consumer, b.Batch, b.Block); err != nil {
			return err
		}
	}
	for _, m := range msgs {
		if err := b.Handle(ctx, m); err != nil {
			return err
		}
	}
	return nil
}

// Handle ingests one message as PolledItemConsumer did; one no retry can ingest is dead-lettered.
func (b Backlog) Handle(ctx context.Context, m events.Message) error {
	err := b.ingest(ctx, m.Fields)
	if errors.Is(err, ErrUnprocessable) {
		fields := maps.Clone(m.Fields)
		reason := err.Error()
		if len(reason) > 500 {
			reason = reason[:500]
		}
		fields[events.DeadLetterReasonField] = reason
		if _, err := b.Broker.Submit(ctx, events.DeadLetterTopic(events.StreamsIngest, events.IngestGroup), fields, events.DeadLetterRetention); err != nil {
			return err
		}
		b.Log.ErrorContext(ctx, "polled item dead-lettered", "message_id", m.ID, "reason", reason)
	} else if err != nil {
		return err
	}
	return b.Broker.Ack(ctx, events.StreamsIngest, events.IngestGroup, m.ID)
}

func (b Backlog) ingest(ctx context.Context, f map[string]string) error {
	at, err := time.Parse(time.RFC3339Nano, f["received_at"])
	if err != nil {
		return fmt.Errorf("%w: received_at: %w", ErrUnprocessable, err)
	}
	id := f["source_id"]
	switch f["kind"] {
	case "item":
		if !json.Valid([]byte(f["item"])) {
			return fmt.Errorf("%w: item is not JSON", ErrUnprocessable)
		}
		return b.Intake.IngestPolled(ctx, id, json.RawMessage(f["item"]), at)
	case "gap":
		var gap struct {
			Reason string `json:"reason"`
		}
		if err := json.Unmarshal([]byte(f["item"]), &gap); err != nil {
			return fmt.Errorf("%w: gap: %w", ErrUnprocessable, err)
		}
		return b.Intake.IngestGap(ctx, id, gap.Reason, at)
	default:
		return fmt.Errorf("%w: kind %q", ErrUnprocessable, f["kind"])
	}
}
