package durable

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

func TestLoadDefaults(t *testing.T) {
	l := config.FromMap(map[string]string{"AGENTAREA_TEMPORAL_QUEUE": "agent-tasks"})
	c := Load(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	want := Config{
		Queues:            Queues{Agent: "agent-tasks", Trigger: "trigger-schedules"},
		Limits:            Limits{MaxActivities: 10, MaxWorkflows: 5, ActivityPollers: 5, WorkflowPollers: 5},
		MaxCached:         200,
		ShutdownGrace:     120 * time.Second,
		HeartbeatThrottle: 2 * time.Second,
	}
	if c != want {
		t.Fatalf("got %+v\nwant %+v", c, want)
	}
	if RunnerQueue("c1") != "runner-turns-c1" {
		t.Fatal(RunnerQueue("c1"))
	}
}

func TestLoadReadsEveryVariable(t *testing.T) {
	l := config.FromMap(map[string]string{
		"AGENTAREA_TEMPORAL_QUEUE":            "q",
		"AGENTAREA_TRIGGER_QUEUE":             "t",
		"AGENTAREA_TEMPORAL_MAX_ACTIVITIES":   "40",
		"AGENTAREA_TEMPORAL_MAX_WORKFLOWS":    "20",
		"AGENTAREA_TEMPORAL_ACTIVITY_POLLERS": "8",
		"AGENTAREA_TEMPORAL_WORKFLOW_POLLERS": "4",
		"AGENTAREA_TEMPORAL_MAX_CACHED":       "1000",
		"AGENTAREA_TEMPORAL_SHUTDOWN_GRACE":   "30s",
	})
	c := Load(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if c.Queues.Trigger != "t" || c.Limits != (Limits{40, 20, 8, 4}) || c.MaxCached != 1000 || c.ShutdownGrace != 30*time.Second {
		t.Fatalf("%+v", c)
	}
}

func TestLoadFailsLoud(t *testing.T) {
	l := config.FromMap(map[string]string{
		"AGENTAREA_TEMPORAL_ACTIVITY_POLLERS": "0",
		"AGENTAREA_TEMPORAL_WORKFLOW_POLLERS": "1",
		"AGENTAREA_TEMPORAL_SHUTDOWN_GRACE":   "120",
	})
	Load(l)
	err := l.Err()
	for _, name := range []string{"AGENTAREA_TEMPORAL_QUEUE", "AGENTAREA_TEMPORAL_ACTIVITY_POLLERS", "AGENTAREA_TEMPORAL_WORKFLOW_POLLERS", "AGENTAREA_TEMPORAL_SHUTDOWN_GRACE"} {
		if err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("%s not reported: %v", name, err)
		}
	}
	if !errors.Is(err, config.ErrMissing) {
		t.Errorf("missing queue is not ErrMissing: %v", err)
	}
}

func TestApplicationErrorUnwraps(t *testing.T) {
	cause := errors.New("budget exhausted")
	err := error(&ApplicationError{Type: "GovernanceDeniedError", Message: "denied", NonRetryable: true, Cause: cause})
	if !errors.Is(err, cause) || err.Error() != "GovernanceDeniedError: denied" {
		t.Fatal(err)
	}
}
