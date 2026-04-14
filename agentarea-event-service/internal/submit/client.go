package submit

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/redis/go-redis/v9"
)

// Event is the normalized event payload to submit. It mirrors channels/telegram.Event
// but lives in the submit package to avoid import cycles.
type Event struct {
	Type      string         `json:"type"`
	ChatID    int64          `json:"chat_id"`
	UserID    int64          `json:"user_id"`
	Username  string         `json:"username"`
	Text      string         `json:"text"`
	MessageID int64          `json:"message_id"`
	Raw       map[string]any `json:"raw"`
}

// InboundMessage is the payload published to Redis for the Python worker to consume.
type InboundMessage struct {
	TriggerID     string         `json:"trigger_id"`
	Event         Event          `json:"event"`
	ChannelOrigin map[string]any `json:"channel_origin"`
}

// InboundChannel is the Redis pub/sub channel the Python worker subscribes to.
const InboundChannel = "agentarea.channel.message.received"

// RedisSubmitter publishes inbound channel messages to Redis for the Python worker.
type RedisSubmitter struct {
	client *redis.Client
}

// NewRedisSubmitter creates a new Redis-based submitter.
func NewRedisSubmitter(client *redis.Client) *RedisSubmitter {
	return &RedisSubmitter{client: client}
}

// SubmitEvent publishes a trigger event to Redis.
func (s *RedisSubmitter) SubmitEvent(ctx context.Context, triggerID string, event Event, channelOrigin map[string]any) error {
	msg := InboundMessage{
		TriggerID:     triggerID,
		Event:         event,
		ChannelOrigin: channelOrigin,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal inbound message: %w", err)
	}

	if err := s.client.Publish(ctx, InboundChannel, data).Err(); err != nil {
		return fmt.Errorf("redis publish: %w", err)
	}

	return nil
}
