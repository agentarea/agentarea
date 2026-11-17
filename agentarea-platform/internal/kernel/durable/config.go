package durable

import (
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

// Limits size one worker's pollers and slots. Pollers are explicit: the Go
// SDK's default of two per kind halved throughput in the bake-off, the Python
// SDK polls with five.
type Limits struct {
	MaxActivities   int
	MaxWorkflows    int
	ActivityPollers int
	WorkflowPollers int
}

// Validate reports limits the Go SDK refuses: a worker with one workflow
// slot or poller would only ever poll its sticky queue.
func (l Limits) Validate() error {
	var errs []error
	if l.MaxActivities < 1 || l.ActivityPollers < 1 {
		errs = append(errs, fmt.Errorf("activity slots and pollers must be at least 1: %+v", l))
	}
	if l.MaxWorkflows < 2 || l.WorkflowPollers < 2 {
		errs = append(errs, fmt.Errorf("workflow slots and pollers must be at least 2: %+v", l))
	}
	return errors.Join(errs...)
}

// TriggerLimits are the trigger worker's, fixed in Python (main.py:354-355)
// with the Python SDK's five pollers.
func TriggerLimits() Limits {
	return Limits{MaxActivities: 5, MaxWorkflows: 5, ActivityPollers: 5, WorkflowPollers: 5}
}

// Config is how AgentArea uses Temporal (config/temporal.py TemporalSettings).
// Where Temporal is (TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_API_KEY,
// TEMPORAL_TLS_*, TEMPORAL_CONFIG_FILE, TEMPORAL_PROFILE, TEMPORAL_GRPC_META_*)
// is Temporal's own envconfig contract, read by durable/temporal.
type Config struct {
	Queues Queues
	// Limits are the agent queue worker's.
	Limits Limits
	// MaxCached is the workflows kept in memory between their tasks (sticky cache).
	MaxCached int
	// ShutdownGrace is how long a stopping worker lets activities finish.
	ShutdownGrace time.Duration
	// HeartbeatThrottle is the heartbeat throttle interval, Python's
	// CANCELLATION_DELIVERY_INTERVAL (activities/heartbeat.py:21): a cancelled
	// activity learns of it within this time.
	HeartbeatThrottle time.Duration
}

// Load reads Config. AGENTAREA_TEMPORAL_QUEUE has no default: Python's empty
// default leaves a worker that cannot poll.
func Load(l *config.Loader) Config {
	c := Config{
		Queues: Queues{
			Agent:   l.RequiredEnv("AGENTAREA_TEMPORAL_QUEUE"),
			Trigger: l.StringEnv("AGENTAREA_TRIGGER_QUEUE", "trigger-schedules"),
		},
		Limits: Limits{
			MaxActivities:   l.IntEnv("AGENTAREA_TEMPORAL_MAX_ACTIVITIES", 10),
			MaxWorkflows:    l.IntEnv("AGENTAREA_TEMPORAL_MAX_WORKFLOWS", 5),
			ActivityPollers: l.IntEnv("AGENTAREA_TEMPORAL_ACTIVITY_POLLERS", 5),
			WorkflowPollers: l.IntEnv("AGENTAREA_TEMPORAL_WORKFLOW_POLLERS", 5),
		},
		MaxCached:         l.IntEnv("AGENTAREA_TEMPORAL_MAX_CACHED", 200),
		ShutdownGrace:     l.DurationEnv("AGENTAREA_TEMPORAL_SHUTDOWN_GRACE", 120*time.Second),
		HeartbeatThrottle: 2 * time.Second,
	}
	minimum := []struct {
		name     string
		value, n int
	}{
		{"AGENTAREA_TEMPORAL_MAX_ACTIVITIES", c.Limits.MaxActivities, 1},
		{"AGENTAREA_TEMPORAL_ACTIVITY_POLLERS", c.Limits.ActivityPollers, 1},
		{"AGENTAREA_TEMPORAL_MAX_WORKFLOWS", c.Limits.MaxWorkflows, 2},
		{"AGENTAREA_TEMPORAL_WORKFLOW_POLLERS", c.Limits.WorkflowPollers, 2},
		{"AGENTAREA_TEMPORAL_MAX_CACHED", c.MaxCached, 1},
	}
	for _, m := range minimum {
		if m.value < m.n {
			l.Fail(m.name, fmt.Errorf("must be at least %d", m.n))
		}
	}
	if c.ShutdownGrace < 0 {
		l.Fail("AGENTAREA_TEMPORAL_SHUTDOWN_GRACE", errors.New("must not be negative"))
	}
	return c
}

// Queues are the task queues as Python names them.
type Queues struct {
	// Agent runs AgentExecutionWorkflow and the reconciler (AGENTAREA_TEMPORAL_QUEUE).
	Agent string
	// Trigger runs the trigger, batch and cron-sync workflows (AGENTAREA_TRIGGER_QUEUE).
	Trigger string
}

// RunnerQueue is the queue a client's runner turns wait on, polled by the API
// process holding that client's runner (models.py:1303 runner_task_queue).
func RunnerQueue(clientID string) string { return "runner-turns-" + clientID }
