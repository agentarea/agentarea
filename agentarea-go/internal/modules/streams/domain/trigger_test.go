package domain_test

import (
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

func TestNewTriggerValidate(t *testing.T) {
	expr, tz, sid := "0 9 * * *", "UTC", "s1"
	cases := []struct {
		name string
		n    domain.NewTrigger
		want string
	}{
		{"blank name", domain.NewTrigger{Name: "  ", Type: domain.TypeCron}, "Trigger name is required"},
		{"cron without expression", domain.NewTrigger{Name: "a", Type: domain.TypeCron, Timezone: &tz, TaskParameters: map[string]any{"text": "x"}}, "Cron expression is required for CRON triggers"},
		{"cron without timezone", domain.NewTrigger{Name: "a", Type: domain.TypeCron, CronExpression: &expr, TaskParameters: map[string]any{"text": "x"}}, "Timezone is required for CRON triggers"},
		{"cron without text", domain.NewTrigger{Name: "a", Type: domain.TypeCron, CronExpression: &expr, Timezone: &tz}, "Task text is required for CRON triggers"},
		{"stream without stream", domain.NewTrigger{Name: "a", Type: domain.TypeStream}, "stream_id is required for STREAM triggers"},
		{"bad type", domain.NewTrigger{Name: "a", Type: "webhook"}, "trigger_type must be cron or stream"},
		{"filter unknown key", domain.NewTrigger{Name: "a", Type: domain.TypeStream, StreamID: &sid, EventFilter: map[string]any{"nope": 1}}, "event_filter.nope: Extra inputs are not permitted"},
	}
	for _, c := range cases {
		err := c.n.Validate()
		var v *domain.ValidationError
		if !errors.As(err, &v) || v.Msg != c.want {
			t.Errorf("%s: got %v, want %q", c.name, err, c.want)
		}
	}
	ok := domain.NewTrigger{Name: "a", Type: domain.TypeCron, CronExpression: &expr, Timezone: &tz, TaskParameters: map[string]any{"text": "x"}}
	if err := ok.Validate(); err != nil {
		t.Fatalf("valid cron refused: %v", err)
	}
	withConds := ok
	withConds.Conditions = map[string]any{"x": 1}
	var inv *domain.ValidationError
	if err := withConds.Validate(); !errors.As(err, &inv) ||
		err.Error() != "LLM condition must have a 'description'; LLM condition must name its 'model_id'" {
		t.Fatalf("conditions: %v", err)
	}
}

func TestStatus(t *testing.T) {
	if (domain.Trigger{IsActive: true}).Status() != domain.StatusActive {
		t.Fatal("active")
	}
	if (domain.Trigger{}).Status() != domain.StatusInactive {
		t.Fatal("inactive")
	}
}

func TestDropReserved(t *testing.T) {
	out := domain.DropReserved(map[string]any{"text": "x", "session": 1, "trigger_event": 2})
	if len(out) != 1 || out["text"] != "x" {
		t.Fatalf("got %v", out)
	}
	if err := domain.RefuseReserved(map[string]any{"delivery_address": 1}); err == nil {
		t.Fatal("reserved key accepted")
	}
}

func intp(i int) *int { return &i }

func TestValidateBatch(t *testing.T) {
	w, bad := "1h", "0h"
	text := map[string]any{"text": "sum up"}
	td := "d1"
	cases := []struct {
		name string
		b    *domain.Batch
		p    map[string]any
		td   *string
		want string
	}{
		{"too big", &domain.Batch{MaxEvents: intp(500)}, text, nil, "batch max_events is 500; a batch holds at most 100 events"},
		{"one event", &domain.Batch{MaxEvents: intp(1)}, text, nil, "batch.max_events: Input should be greater than or equal to 2"},
		{"empty", &domain.Batch{}, text, nil, "batch: a batch needs a window or max_events"},
		{"zero window", &domain.Batch{Window: &bad}, text, nil, "batch.window: String should match pattern '^[1-9][0-9]*[smhd]$'"},
		{"no text", &domain.Batch{Window: &w}, nil, nil, "a batched trigger needs task text: what to do with the events of each batch"},
		{"saved task", &domain.Batch{Window: &w}, nil, &td, ""},
		{"ok", &domain.Batch{Window: &w, MaxEvents: intp(100)}, text, nil, ""},
	}
	for _, c := range cases {
		err := domain.ValidateBatch(c.b, 100, c.p, c.td)
		if c.want == "" {
			if err != nil {
				t.Errorf("%s: %v", c.name, err)
			}
			continue
		}
		var v *domain.ValidationError
		if !errors.As(err, &v) || v.Msg != c.want {
			t.Errorf("%s: got %v, want %q", c.name, err, c.want)
		}
	}
}
