package usage

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/go-redis/redis/v8"
	"github.com/google/uuid"
)

const (
	eventStream      = "agentarea:usage:events"
	consumerGroup    = "usage-persistence"
	streamBatch      = 100
	commitAckTimeout = 10 * time.Second
	commitAckTTL     = 5 * time.Minute
	commitAckPoll    = 50 * time.Millisecond
)

type Publisher struct {
	client redis.UniversalClient
	stream string
}

func NewPublisher(client redis.UniversalClient) *Publisher {
	return &Publisher{client: client, stream: eventStream}
}

func (p *Publisher) Record(ctx context.Context, event Event) error {
	if err := event.Validate(); err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, commitAckTimeout)
	defer cancel()
	data, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("encode usage event: %w", err)
	}
	// Never trim a stream containing facts not yet durably stored. Retries may
	// append the same identity more than once; PostgreSQL verifies that identity.
	if err := p.client.XAdd(ctx, &redis.XAddArgs{
		Stream: p.stream, Values: map[string]any{"event": string(data)},
	}).Err(); err != nil {
		return fmt.Errorf("publish usage event %s/%s: %w", event.Source, event.ID, err)
	}
	key := commitAckKey(p.stream, data)
	ticker := time.NewTicker(commitAckPoll)
	defer ticker.Stop()
	for {
		if err := ctx.Err(); err != nil {
			return fmt.Errorf("await usage commit %s/%s: %w", event.Source, event.ID, err)
		}
		ack, err := p.client.Get(ctx, key).Result()
		if err != nil && !errors.Is(err, redis.Nil) {
			return fmt.Errorf("read usage commit %s/%s: %w", event.Source, event.ID, err)
		}
		if ack == "1" {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("await usage commit %s/%s: %w", event.Source, event.ID, ctx.Err())
		case <-ticker.C:
		}
	}
}

func commitAckKey(stream string, payload []byte) string {
	return fmt.Sprintf("%s:committed:%x", stream, sha256.Sum256(payload))
}

type Consumer struct {
	client    redis.UniversalClient
	recorder  Recorder
	logger    *slog.Logger
	stream    string
	name      string
	claimIdle time.Duration
}

func NewConsumer(client redis.UniversalClient, recorder Recorder, logger *slog.Logger) *Consumer {
	if logger == nil {
		logger = slog.Default()
	}
	return &Consumer{
		client: client, recorder: recorder, logger: logger, stream: eventStream,
		name: uuid.NewString(), claimIdle: 30 * time.Second,
	}
}

func (c *Consumer) Run(ctx context.Context) error {
	if c.client == nil || c.recorder == nil {
		return errors.New("usage consumer requires Redis and a durable recorder")
	}
	if err := c.client.XGroupCreateMkStream(ctx, c.stream, consumerGroup, "0").Err(); err != nil && !strings.Contains(err.Error(), "BUSYGROUP") {
		return fmt.Errorf("create usage consumer group: %w", err)
	}
	pendingCursor := "-"
	for ctx.Err() == nil {
		// One bounded pending page per iteration prevents poison messages from
		// starving new facts; the cursor also eventually visits every old owner.
		next, err := c.reclaim(ctx, pendingCursor)
		if err != nil {
			c.logger.Error("usage pending reclaim failed", "error", err)
		} else {
			pendingCursor = next
		}
		streams, err := c.client.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group: consumerGroup, Consumer: c.name, Streams: []string{c.stream, ">"},
			Count: streamBatch, Block: time.Second,
		}).Result()
		if err != nil && !errors.Is(err, redis.Nil) {
			if ctx.Err() != nil {
				break
			}
			c.logger.Error("usage stream read failed", "error", err)
			select {
			case <-ctx.Done():
			case <-time.After(time.Second):
			}
			continue
		}
		for _, stream := range streams {
			for _, message := range stream.Messages {
				c.process(ctx, message)
			}
		}
	}
	return ctx.Err()
}

func (c *Consumer) reclaim(ctx context.Context, cursor string) (string, error) {
	pending, err := c.client.XPendingExt(ctx, &redis.XPendingExtArgs{
		Stream: c.stream, Group: consumerGroup, Start: cursor, End: "+", Count: streamBatch,
	}).Result()
	if err != nil {
		return cursor, err
	}
	ids := make([]string, 0, len(pending))
	for _, entry := range pending {
		if entry.Idle >= c.claimIdle {
			ids = append(ids, entry.ID)
		}
	}
	if len(ids) > 0 {
		messages, err := c.client.XClaim(ctx, &redis.XClaimArgs{
			Stream: c.stream, Group: consumerGroup, Consumer: c.name,
			MinIdle: c.claimIdle, Messages: ids,
		}).Result()
		if err != nil {
			return cursor, err
		}
		for _, message := range messages {
			c.process(ctx, message)
		}
	}
	if len(pending) < streamBatch {
		return "-", nil
	}
	return "(" + pending[len(pending)-1].ID, nil
}

func (c *Consumer) process(ctx context.Context, message redis.XMessage) {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	payload, ok := message.Values["event"].(string)
	if !ok {
		c.logger.Error("invalid usage stream envelope; retained pending", "stream_id", message.ID)
		return
	}
	data := []byte(payload)
	var event Event
	if err := json.Unmarshal(data, &event); err != nil {
		c.logger.Error("invalid usage event; retained pending", "stream_id", message.ID, "error", err)
		return
	}
	if err := c.recorder.Record(ctx, event); err != nil {
		c.logger.Error("usage persistence failed; retained pending", "stream_id", message.ID,
			"source", event.Source, "event_id", event.ID, "error", err)
		return
	}
	// The commit happened before this atomic Redis transaction. If its reply is
	// lost, reclaim safely replays the same event against the immutable store.
	_, err := c.client.TxPipelined(ctx, func(pipe redis.Pipeliner) error {
		pipe.Set(ctx, commitAckKey(c.stream, data), "1", commitAckTTL)
		pipe.XAck(ctx, c.stream, consumerGroup, message.ID)
		pipe.XDel(ctx, c.stream, message.ID)
		return nil
	})
	if err != nil {
		c.logger.Error("usage acknowledgement failed after persistence", "stream_id", message.ID, "error", err)
	}
}
