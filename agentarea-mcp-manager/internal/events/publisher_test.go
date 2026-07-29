package events

import (
	"encoding/json"
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
	idStr, _ := fields["ce_id"].(string)
	if _, err := uuid.Parse(idStr); err != nil {
		t.Errorf("ce_id %q is not a valid UUID: %v", idStr, err)
	}

	// ce_time must be RFC3339 — Python datetime.fromisoformat() must accept it.
	timeStr, _ := fields["ce_time"].(string)
	if _, err := time.Parse(time.RFC3339, timeStr); err != nil {
		t.Errorf("ce_time %q is not RFC3339: %v", timeStr, err)
	}

	// data is a JSON string whose keys match what the Python handler reads.
	dataStr, ok := fields["data"].(string)
	if !ok {
		t.Fatalf("data field is not a string: %T", fields["data"])
	}
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

func TestStreamFor(t *testing.T) {
	if got := streamFor(statusChangedType); got != "events:"+statusChangedType {
		t.Errorf("streamFor = %v", got)
	}
}
