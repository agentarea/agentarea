package submit

import (
	"context"
	"encoding/json"
	"testing"
)

type fakeBroker struct {
	stream string
	fields map[string]string
}

func (f *fakeBroker) Submit(ctx context.Context, stream string, fields map[string]string) (string, error) {
	f.stream = stream
	f.fields = fields
	return "1-0", nil
}

func (f *fakeBroker) EnsureGroup(ctx context.Context, stream, group, start string) error {
	return nil
}

func TestStreamSubmitterWritesInboundStream(t *testing.T) {
	b := &fakeBroker{}
	s := NewStreamSubmitter(b, "agentarea.channel.inbound")

	err := s.SubmitEvent(
		context.Background(),
		"trigger-1",
		Event{
			Type:      "message",
			ChatID:    42,
			UserID:    99,
			Username:  "alice",
			Text:      "hello",
			MessageID: 7,
			Raw:       map[string]any{"update_id": float64(1001)},
		},
		map[string]any{"type": "telegram", "chat_id": "42"},
	)
	if err != nil {
		t.Fatalf("SubmitEvent returned error: %v", err)
	}

	if b.stream != "agentarea.channel.inbound" {
		t.Fatalf("stream = %q", b.stream)
	}
	if b.fields["trigger_id"] != "trigger-1" {
		t.Fatalf("trigger_id = %q", b.fields["trigger_id"])
	}
	if b.fields["dedup_key"] != "trigger-1:message:7" {
		t.Fatalf("dedup_key = %q", b.fields["dedup_key"])
	}

	var event Event
	if err := json.Unmarshal([]byte(b.fields["event"]), &event); err != nil {
		t.Fatalf("event json invalid: %v", err)
	}
	if event.Text != "hello" || event.ChatID != 42 {
		t.Fatalf("event = %+v", event)
	}

	var origin map[string]any
	if err := json.Unmarshal([]byte(b.fields["channel_origin"]), &origin); err != nil {
		t.Fatalf("channel_origin json invalid: %v", err)
	}
	if origin["type"] != "telegram" || origin["chat_id"] != "42" {
		t.Fatalf("origin = %+v", origin)
	}
}
