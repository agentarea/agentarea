package events

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/google/uuid"
)

// TestBuildEventFieldsContract pins the Go->Python wire contract (ADR-0018):
// CloudEvents `ce_*` envelope fields plus a JSON `data` payload, matching the
// Python `decode()` in agentarea_common.events.adapters.redis_streams.
func TestBuildEventFieldsContract(t *testing.T) {
	event := StatusUpdateEvent{
		InstanceID:  "inst-1",
		Name:        "svc",
		Status:      "running",
		ContainerID: "c-1",
		URL:         "http://localhost:8080",
		Timestamp:   time.Now(),
	}

	fields, err := buildEventFields(statusChangedType, event.InstanceID, event)
	if err != nil {
		t.Fatalf("buildEventFields returned error: %v", err)
	}

	if got := fields["ce_type"]; got != statusChangedType {
		t.Errorf("ce_type = %v, want %v", got, statusChangedType)
	}
	if got := fields["ce_source"]; got != eventSource {
		t.Errorf("ce_source = %v, want %v", got, eventSource)
	}
	if got := fields["ce_subject"]; got != "inst-1" {
		t.Errorf("ce_subject = %v, want inst-1", got)
	}
	if got := fields["ce_specversion"]; got != "1.0" {
		t.Errorf("ce_specversion = %v, want 1.0", got)
	}
	if got := fields["ce_datacontenttype"]; got != "application/json" {
		t.Errorf("ce_datacontenttype = %v, want application/json", got)
	}

	// ce_id must be a parseable UUID — Python decode()s it as UUID().
	idStr := fields["ce_id"]
	if _, err := uuid.Parse(idStr); err != nil {
		t.Errorf("ce_id %q is not a valid UUID: %v", idStr, err)
	}

	// ce_time must be RFC3339 — Python datetime.fromisoformat() must accept it.
	timeStr := fields["ce_time"]
	if _, err := time.Parse(time.RFC3339, timeStr); err != nil {
		t.Errorf("ce_time %q is not RFC3339: %v", timeStr, err)
	}

	// data is a JSON string whose keys match what the Python handler reads.
	dataStr := fields["data"]
	var decoded map[string]any
	if err := json.Unmarshal([]byte(dataStr), &decoded); err != nil {
		t.Fatalf("data is not valid JSON: %v", err)
	}
	if decoded["instance_id"] != "inst-1" || decoded["status"] != "running" {
		t.Errorf("data payload mismatch: %v", decoded)
	}
}

func TestBuildEventFieldsOmitsEmptySubject(t *testing.T) {
	fields, err := buildEventFields(errorType, "", ErrorEvent{Error: "boom"})
	if err != nil {
		t.Fatalf("buildEventFields returned error: %v", err)
	}
	if _, present := fields["ce_subject"]; present {
		t.Errorf("ce_subject should be omitted when subject is empty")
	}
}

func TestTopicFor(t *testing.T) {
	if got := topicFor(statusChangedType); got != "domain.events."+statusChangedType {
		t.Errorf("topicFor = %v", got)
	}
}

type submission struct {
	stream    string
	fields    map[string]string
	retention time.Duration
}

type fakeSubmitter struct {
	submissions []submission
}

func (f *fakeSubmitter) Submit(_ context.Context, stream string, fields map[string]string, retention time.Duration) (string, error) {
	f.submissions = append(f.submissions, submission{stream: stream, fields: fields, retention: retention})
	return "1-0", nil
}

func TestPublishFailedSubmitsErrorThenStatus(t *testing.T) {
	broker := &fakeSubmitter{}
	publisher := NewEventPublisher(broker, slog.New(slog.NewTextHandler(io.Discard, nil)))

	if err := publisher.PublishFailed(context.Background(), "inst-1", "svc", "boom"); err != nil {
		t.Fatalf("PublishFailed: %v", err)
	}

	if len(broker.submissions) != 2 {
		t.Fatalf("submissions = %d, want 2", len(broker.submissions))
	}
	errSub, statusSub := broker.submissions[0], broker.submissions[1]
	if errSub.stream != topicFor(errorType) || statusSub.stream != topicFor(statusChangedType) {
		t.Errorf("streams = %s, %s", errSub.stream, statusSub.stream)
	}
	for _, s := range broker.submissions {
		if s.retention != Retention {
			t.Errorf("retention = %v, want %v", s.retention, Retention)
		}
		if s.fields["ce_subject"] != "inst-1" {
			t.Errorf("ce_subject = %q, want inst-1", s.fields["ce_subject"])
		}
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(statusSub.fields["data"]), &payload); err != nil {
		t.Fatalf("data: %v", err)
	}
	if payload["status"] != "failed" {
		t.Errorf("status = %v, want failed", payload["status"])
	}
}
