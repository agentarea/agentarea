package submit

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/agentarea/event-service/internal/broker"
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

// InboundMessage is the normalized payload written to the inbound stream.
type InboundMessage struct {
	TriggerID     string         `json:"trigger_id"`
	Event         Event          `json:"event"`
	ChannelOrigin map[string]any `json:"channel_origin"`
}

const DefaultInboundStream = "agentarea.channel.inbound"

// StreamSubmitter appends inbound channel events to a durable broker stream.
type StreamSubmitter struct {
	broker broker.Client
	stream string
}

// NewStreamSubmitter creates a stream-backed submitter.
func NewStreamSubmitter(broker broker.Client, stream string) *StreamSubmitter {
	if stream == "" {
		stream = DefaultInboundStream
	}
	return &StreamSubmitter{broker: broker, stream: stream}
}

// SubmitEvent appends a trigger event to the inbound stream.
func (s *StreamSubmitter) SubmitEvent(ctx context.Context, triggerID string, event Event, channelOrigin map[string]any) error {
	msg := InboundMessage{
		TriggerID:     triggerID,
		Event:         event,
		ChannelOrigin: channelOrigin,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal inbound message: %w", err)
	}

	eventJSON, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("marshal event: %w", err)
	}
	originJSON, err := json.Marshal(channelOrigin)
	if err != nil {
		return fmt.Errorf("marshal channel origin: %w", err)
	}

	dedupKey := fmt.Sprintf("%s:%s:%d", triggerID, event.Type, event.MessageID)
	if event.MessageID == 0 {
		dedupKey = fmt.Sprintf("%s:%s:%x", triggerID, event.Type, data)
	}

	_, err = s.broker.Submit(ctx, s.stream, map[string]string{
		"trigger_id":      triggerID,
		"event":           string(eventJSON),
		"channel_origin":  string(originJSON),
		"dedup_key":       dedupKey,
		"received_at":     time.Now().UTC().Format(time.RFC3339Nano),
		"schema_version":  "1",
		"inbound_message": string(data),
	})
	if err != nil {
		return fmt.Errorf("submit inbound stream: %w", err)
	}

	return nil
}
