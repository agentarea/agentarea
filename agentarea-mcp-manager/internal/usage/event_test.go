package usage

import (
	"context"
	"encoding/json"
	"testing"
)

func TestMissingOrUnsupportedVersionIsNotDefaultedAtIngestion(t *testing.T) {
	for _, version := range []int{0, -1, SchemaVersion + 1} {
		event := testEvent()
		event.SchemaVersion = version
		if err := event.Validate(); err == nil {
			t.Fatalf("accepted unsupported schema version %d", version)
		}
		// Validation must reject before either transport can accept a fact.
		if err := NewPublisher(nil).Record(context.Background(), event); err == nil {
			t.Fatalf("publisher accepted schema version %d", version)
		}
		if err := (&Store{}).Record(context.Background(), event); err == nil {
			t.Fatalf("store accepted schema version %d", version)
		}
	}

	event := testEvent()
	encoded, err := json.Marshal(event)
	if err != nil {
		t.Fatal(err)
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(encoded, &envelope); err != nil {
		t.Fatal(err)
	}
	delete(envelope, "schema_version")
	missingVersion, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	var decoded Event
	if err := json.Unmarshal(missingVersion, &decoded); err != nil {
		t.Fatal(err)
	}
	if err := decoded.Validate(); err == nil {
		t.Fatal("unversioned envelope accepted at ingestion")
	}
	if decoded.SchemaVersion != 0 {
		t.Fatalf("missing schema version was defaulted to %d", decoded.SchemaVersion)
	}
}
