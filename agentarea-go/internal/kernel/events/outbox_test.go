package events

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

func TestAggregateDerivation(t *testing.T) {
	cases := []struct {
		typ          string
		data         map[string]any
		wantID, want string
	}{
		{"TaskStatusChanged", map[string]any{"task_id": "t1", "agent_id": "a1"}, "t1", "task"},
		{"TaskStatusChanged", map[string]any{"aggregate_id": "", "task_id": "t1"}, "t1", "task"},
		{"MCPServerInstanceCreated", map[string]any{"instance_id": "i1"}, "i1", "mcp_server_instance"},
		{"MCPServerCreated", map[string]any{"server_id": json.Number("0"), "agent_id": "a"}, "a", "mcp_server"},
		{"AgentDeleted", map[string]any{"agent_id": "a1", "aggregate_type": "agent_custom"}, "a1", "agent_custom"},
		{"TriggerFired", map[string]any{"trigger_id": json.Number("42")}, "42", "trigger"},
		{"MembershipEnded", map[string]any{}, "EVENT", "unknown"},
	}
	for _, c := range cases {
		e := Envelope{EventID: "EVENT", EventType: c.typ, Data: c.data}
		if got := e.AggregateID(); got != c.wantID {
			t.Errorf("%s AggregateID = %q, want %q", c.typ, got, c.wantID)
		}
		if got := e.AggregateType(); got != c.want {
			t.Errorf("%s AggregateType = %q, want %q", c.typ, got, c.want)
		}
	}
}

func TestEnvelopeJSONRoundTrip(t *testing.T) {
	e := Envelope{EventID: "6f1c2a7e-3c1b-4b8e-9a51-2f4f0d1c9e10", Timestamp: time.Date(2026, 1, 2, 3, 4, 5, 6000, time.UTC), EventType: "TaskCreated", Data: map[string]any{"task_id": "t"}}
	b, err := json.Marshal(e)
	if err != nil {
		t.Fatal(err)
	}
	want := `{"event_id":"6f1c2a7e-3c1b-4b8e-9a51-2f4f0d1c9e10","timestamp":"2026-01-02T03:04:05.000006+00:00","event_type":"TaskCreated","data":{"task_id":"t"}}`
	if string(b) != want {
		t.Errorf("json\n got %s\nwant %s", b, want)
	}
	back, err := ParseEnvelope(b)
	if err != nil || back.EventID != e.EventID || !back.Timestamp.Equal(e.Timestamp) || back.Data["task_id"] != "t" {
		t.Errorf("ParseEnvelope = %+v, %v", back, err)
	}
}

func TestParseEnvelopeTolerance(t *testing.T) {
	e, err := ParseEnvelope([]byte(`{"type":"Legacy","aggregate_id":"a1","original_event_type":"X"}`))
	if err != nil {
		t.Fatal(err)
	}
	if e.EventType != "Legacy" || e.Data["aggregate_id"] != "a1" || e.EventID == "" {
		t.Errorf("legacy payload: %+v", e)
	}
	e, _ = ParseEnvelope([]byte(`{}`))
	if e.EventType != "UnknownEvent" {
		t.Errorf("type = %s", e.EventType)
	}
	if _, err := ParseEnvelope([]byte(`{"event_id":"nope"}`)); err == nil {
		t.Error("bad event id accepted")
	}
}

func TestDomainEvent(t *testing.T) {
	env := Envelope{EventID: "id", EventType: "TaskCreated", Data: map[string]any{"aggregate_id": "t1", "task_id": "t2"}}
	if e := DomainEvent(env); e.Subject != "t1" || e.Source != "agentarea-outbox" || e.ID != "id" {
		t.Errorf("%+v", e)
	}
	if e := DomainEvent(Envelope{EventID: "id", EventType: "X", Data: map[string]any{"task_id": "t2"}}); e.Subject != "" {
		t.Errorf("subject comes from aggregate_id only: %q", e.Subject)
	}
}

type recordingQuerier struct{ db.Querier }

func TestPublishRefusesSessionOutsideTransaction(t *testing.T) {
	ws, _ := scope.NewWorkspace("ws", "")
	err := Publish(context.Background(), db.NewSession(ws, recordingQuerier{}), "user", NewEnvelope("X", nil))
	if !errors.Is(err, ErrNotInTransaction) {
		t.Errorf("err = %v", err)
	}
	if err := Publish(context.Background(), db.NewTxSession(ws, recordingQuerier{}), "", NewEnvelope("X", nil)); err == nil {
		t.Error("no principal accepted")
	}
}
