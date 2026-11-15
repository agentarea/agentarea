package events

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// Envelope is a domain event as the outbox stores it (base_events.py
// EventEnvelope): payload {"event_id", "timestamp", "event_type", "data"},
// custom fields (aggregate_id, ...) inside data.
type Envelope struct {
	EventID   string
	Timestamp time.Time
	EventType string
	Data      map[string]any
}

// NewEnvelope is an event of eventType with a new uuid4 id, stamped now.
func NewEnvelope(eventType string, data map[string]any) Envelope {
	return Envelope{EventID: uuid.NewString(), Timestamp: time.Now().UTC(), EventType: eventType, Data: data}
}

type envelopeJSON struct {
	EventID   string         `json:"event_id"`
	Timestamp string         `json:"timestamp"`
	EventType string         `json:"event_type"`
	Data      map[string]any `json:"data"`
}

// MarshalJSON is EventEnvelope.as_json_dict(): the timestamp as isoformat().
func (e Envelope) MarshalJSON() ([]byte, error) {
	return json.Marshal(envelopeJSON{EventID: e.EventID, Timestamp: PyISO(e.Timestamp), EventType: e.EventType, Data: dataOrEmpty(e.Data)})
}

// ParseEnvelope reads an outbox payload as EventEnvelope.from_dict does: a
// missing id or time gets a new one, the type falls back to "type" then
// "UnknownEvent", and a payload with no data but aggregate fields at the top
// is its own data.
func ParseEnvelope(payload []byte) (Envelope, error) {
	var raw map[string]any
	d := json.NewDecoder(bytes.NewReader(payload))
	d.UseNumber()
	if err := d.Decode(&raw); err != nil {
		return Envelope{}, fmt.Errorf("outbox payload: %w", err)
	}
	e := Envelope{EventID: uuid.NewString(), Timestamp: time.Now().UTC(), EventType: "UnknownEvent", Data: map[string]any{}}
	if v, ok := raw["event_id"]; ok {
		s, _ := v.(string)
		u, err := uuid.Parse(s)
		if err != nil {
			return Envelope{}, fmt.Errorf("outbox payload event_id %v: %w", v, err)
		}
		e.EventID = u.String()
	}
	if v, ok := raw["timestamp"]; ok {
		s, _ := v.(string)
		t, err := ParsePyISO(s)
		if err != nil {
			return Envelope{}, fmt.Errorf("outbox payload timestamp: %w", err)
		}
		e.Timestamp = t
	}
	for _, k := range []string{"event_type", "type"} {
		if s, _ := raw[k].(string); s != "" {
			e.EventType = s
			break
		}
	}
	if v, ok := raw["data"]; ok {
		m, isMap := v.(map[string]any)
		if !isMap {
			return Envelope{}, fmt.Errorf("outbox payload data is %T, not an object", v)
		}
		e.Data = m
	}
	if len(e.Data) == 0 {
		for _, k := range []string{"aggregate_id", "original_event_type", "original_timestamp", "original_data"} {
			if _, ok := raw[k]; ok {
				e.Data = raw
				break
			}
		}
	}
	return e, nil
}

// aggregateIDKeys carry the aggregate id in data, in priority order
// (outbox_publisher.py _AGGREGATE_ID_KEYS).
func aggregateIDKeys() []string {
	return []string{"aggregate_id", "task_id", "server_id", "instance_id", "agent_id", "trigger_id"}
}

// AggregateID is the row's aggregate_id: the first truthy id key of data,
// else the event id.
func (e Envelope) AggregateID() string {
	for _, k := range aggregateIDKeys() {
		if s, ok := pyTruthyStr(e.Data[k]); ok {
			return s
		}
	}
	return e.EventID
}

// AggregateType is data["aggregate_type"] when set, else guessed from the
// event type as outbox_publisher.py _derive_aggregate_type does.
func (e Envelope) AggregateType() string {
	if s, ok := pyTruthyStr(e.Data["aggregate_type"]); ok {
		return s
	}
	t := strings.ToLower(e.EventType)
	switch {
	case strings.Contains(t, "task"):
		return "task"
	case strings.Contains(t, "instance"):
		return "mcp_server_instance"
	case strings.Contains(t, "mcp"), strings.Contains(t, "server"):
		return "mcp_server"
	case strings.Contains(t, "agent"):
		return "agent"
	case strings.Contains(t, "trigger"):
		return "trigger"
	}
	return "unknown"
}

// pyTruthyStr is str(v) when v is truthy in Python.
func pyTruthyStr(v any) (string, bool) {
	switch x := v.(type) {
	case nil:
		return "", false
	case string:
		return x, x != ""
	case bool:
		return "True", x
	case json.Number:
		if f, err := x.Float64(); err == nil && f == 0 {
			return "", false
		}
		return x.String(), true
	case int:
		return strconv.Itoa(x), x != 0
	case int64:
		return strconv.FormatInt(x, 10), x != 0
	case float64:
		return strconv.FormatFloat(x, 'g', -1, 64), x != 0
	case fmt.Stringer:
		s := x.String()
		return s, s != ""
	}
	s := fmt.Sprint(v)
	return s, s != "" && s != "map[]" && s != "[]"
}

// ErrNotInTransaction: an outbox row must commit with the change it reports.
var ErrNotInTransaction = errors.New("events.Publish needs a session inside Database.Write")

// Publish enqueues e on the caller's transaction (OutboxPublisher.publish):
// the row commits with the change it reports or rolls back with it, and the
// relay publishes it after commit. createdBy is the principal the event came
// from; a service principal with no user cannot enqueue, as in Python.
func Publish(ctx context.Context, tx db.Session, createdBy string, e Envelope) error {
	if !tx.InTx() {
		return ErrNotInTransaction
	}
	if tx.Workspace().IsZero() {
		return errors.New("events.Publish: the session names no workspace")
	}
	if createdBy == "" {
		return errors.New("events.Publish: an outbox row has to name the principal it came from")
	}
	if e.EventType == "" {
		return errors.New("events.Publish: event type is required")
	}
	if e.EventID == "" {
		e.EventID = uuid.NewString()
	}
	if e.Timestamp.IsZero() {
		e.Timestamp = time.Now().UTC()
	}
	eventID, err := uuid.Parse(e.EventID)
	if err != nil {
		return fmt.Errorf("events.Publish: event id: %w", err)
	}
	e.EventID = eventID.String()
	payload, err := json.Marshal(e)
	if err != nil {
		return fmt.Errorf("events.Publish %s: %w", e.EventType, err)
	}
	now := time.Now().UTC().Truncate(time.Microsecond)
	_, err = tx.Q().Exec(ctx, `INSERT INTO event_outbox
		(id, created_at, updated_at, workspace_id, created_by, event_id, event_type,
		 aggregate_id, aggregate_type, payload, attempts)
		VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, 0)`,
		uuid.NewString(), now, tx.Workspace().ID(), createdBy, e.EventID, e.EventType,
		e.AggregateID(), e.AggregateType(), payload)
	if err != nil {
		return fmt.Errorf("enqueue %s %s: %w", e.EventType, e.EventID, err)
	}
	return nil
}
