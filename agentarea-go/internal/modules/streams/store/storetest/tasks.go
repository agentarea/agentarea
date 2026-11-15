package storetest

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// Tasks is runs' task port: it records each request and starts it, or answers Err.
type Tasks struct {
	mu       sync.Mutex
	Requests []runsapi.TaskRequest
	Err      error
}

var _ runsapi.Tasks = (*Tasks)(nil)

// Submit records req and reports it running.
func (f *Tasks) Submit(_ context.Context, _ scope.Workspace, req runsapi.TaskRequest) (runsapi.TaskSubmitted, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.Requests = append(f.Requests, req)
	if f.Err != nil {
		return runsapi.TaskSubmitted{}, f.Err
	}
	return runsapi.TaskSubmitted{TaskID: req.TaskID, Status: "running", ExecutionID: "exec-" + req.TaskID}, nil
}

// Submitted is what was submitted so far.
func (f *Tasks) Submitted() []runsapi.TaskRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]runsapi.TaskRequest(nil), f.Requests...)
}

// FiringTasks answers a firing's task reads from maps.
type FiringTasks struct {
	mu        sync.Mutex
	Stored    map[string]api.StoredTask
	Origins   map[string]api.TaskOrigin
	Running   string
	Restarted []string
}

var _ api.FiringTasks = (*FiringTasks)(nil)

func (f *FiringTasks) Task(_ context.Context, _ scope.Workspace, id string) (api.StoredTask, bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	t, ok := f.Stored[id]
	return t, ok, nil
}

func (f *FiringTasks) RestartUndispatched(_ context.Context, _ scope.Workspace, id, _ string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.Restarted = append(f.Restarted, id)
	return nil
}

func (f *FiringTasks) OpenRunFrom(context.Context, scope.Workspace, string, string) (string, error) {
	return f.Running, nil
}

func (f *FiringTasks) Definition(context.Context, scope.Workspace, string) (api.TaskDefinition, bool, error) {
	return api.TaskDefinition{}, false, nil
}

func (f *FiringTasks) Origin(_ context.Context, _ scope.Workspace, taskID string) (api.TaskOrigin, bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	o, ok := f.Origins[taskID]
	return o, ok, nil
}

// Broker records live notices and submissions; the rest of events.Broker is not used.
type Broker struct {
	events.Broker
	mu        sync.Mutex
	Notices   []map[string]string
	Submitted []map[string]string
}

func (b *Broker) Notify(_ context.Context, _ string, fields map[string]string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.Notices = append(b.Notices, fields)
	return nil
}

func (b *Broker) Submit(_ context.Context, _ string, fields map[string]string, _ time.Duration) (string, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.Submitted = append(b.Submitted, fields)
	return "1-0", nil
}

// Executor records the workflows started.
type Executor struct {
	durable.Executor
	mu      sync.Mutex
	Started []durable.StartOptions
	IDs     []string
}

func (e *Executor) Start(_ context.Context, _ string, id string, _ []any, o durable.StartOptions) (string, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.Started = append(e.Started, o)
	e.IDs = append(e.IDs, id)
	return id, nil
}

// Runner answers every processor run with Run, or Err.
type Runner struct {
	Result service.CodeRun
	Err    error
}

func (r Runner) Run(context.Context, string, string, string, time.Duration, int) (service.CodeRun, error) {
	return r.Result, r.Err
}

// Reaction is a subscription's recorded reaction to an event.
type Reaction struct {
	Verdict string
	Reason  *string
	TaskID  *string
	Derived []string
}

// ReactionOf reads the reaction of sub to event; false when none is recorded.
func (d DB) ReactionOf(ctx context.Context, sub, event string) (Reaction, bool, error) {
	var r Reaction
	var raw string
	err := d.Pool.QueryRow(ctx, `SELECT verdict, reason, task_id::text, COALESCE(derived_event_ids::text, '[]')
		FROM trigger_executions WHERE subscription_id = $1 AND event_id = $2`, sub, event).
		Scan(&r.Verdict, &r.Reason, &r.TaskID, &raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return r, false, nil
	}
	if err != nil {
		return r, false, err
	}
	return r, true, json.Unmarshal([]byte(raw), &r.Derived)
}

// Tally is an event's routing tally in the events view.
type Tally struct {
	Subscribers              *int32
	Reacted, Skipped, Errors int32
}

// TallyOf reads the event's tally.
func (d DB) TallyOf(ctx context.Context, event string) (Tally, error) {
	var t Tally
	err := d.Pool.QueryRow(ctx, `SELECT subscribers, reacted, skipped, errors FROM stream_events WHERE event_id = $1`, event).
		Scan(&t.Subscribers, &t.Reacted, &t.Skipped, &t.Errors)
	return t, err
}
