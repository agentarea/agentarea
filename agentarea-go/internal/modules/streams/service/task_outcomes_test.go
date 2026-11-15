package service_test

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
)

type outcomeTasks struct {
	mu    sync.Mutex
	tasks map[string]runsapi.OutcomeTask
}

func (o *outcomeTasks) put(t runsapi.OutcomeTask) {
	o.mu.Lock()
	defer o.mu.Unlock()
	if o.tasks == nil {
		o.tasks = map[string]runsapi.OutcomeTask{}
	}
	o.tasks[t.ID] = t
}

func (o *outcomeTasks) OutcomeTask(_ context.Context, _ scope.Workspace, id string) (runsapi.OutcomeTask, bool, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	t, ok := o.tasks[id]
	return t, ok, nil
}

type outcomeRig struct {
	*fireRig
	outcomes *outcomeTasks
	bus      *storetest.Bus
	graph    *storetest.Graph
}

func newOutcomeRig(t *testing.T) *outcomeRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	g := &fireRig{ctx: ctx, ws: ws, tasks: &storetest.Tasks{}, firing: &storetest.FiringTasks{}, agent: uuid.NewString()}
	g.known = map[string]bool{g.agent: true}
	r := &outcomeRig{fireRig: g, outcomes: &outcomeTasks{}, bus: &storetest.Bus{}, graph: &storetest.Graph{AllowAll: true}}
	g.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: r.graph, Agents: storetest.Agents{Known: g.known},
		Schedules: &storetest.Schedules{}, TriggerQueue: "trigger-schedules", Tasks: g.tasks, FiringTasks: g.firing,
		Broker: &storetest.Broker{}, Settings: service.DefaultSettings(), TaskOutcomes: r.outcomes,
		Bus: r.bus, Dedup: &storetest.Dedup{}, Quota: &storetest.Quota{},
	})
	return r
}

// fired fires the trigger and registers the task it started as one a trigger started.
func (r *outcomeRig) fired(t *testing.T, tr domain.Trigger) string {
	t.Helper()
	f := r.fire(t, tr.ID)
	if f.TaskID == "" {
		t.Fatalf("firing started no task: %+v", f)
	}
	r.outcomes.put(runsapi.OutcomeTask{ID: f.TaskID, AgentID: r.agent, Owner: "u1", OriginType: "trigger", OriginID: tr.ID})
	return f.TaskID
}

func (r *outcomeRig) taskEvent(kind, task string, data map[string]any) events.IntegrationEvent {
	return events.IntegrationEvent{
		ID: uuid.NewString(), Type: kind, Subject: task, Time: time.Now().UTC(), Data: data,
		Extensions: map[string]string{"workspace": r.ws.ID()},
	}
}

func (r *outcomeRig) trigger(t *testing.T, id string) domain.Trigger {
	t.Helper()
	got, err := r.svc.Trigger(r.ctx, r.ws, id)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

func TestFailedRunsCountOnceAndSwitchTheTriggerOff(t *testing.T) {
	r := newOutcomeRig(t)
	tr := r.cron(t, true, 2)
	first := r.fired(t, tr)
	failed := r.taskEvent(service.TaskFailed, first, map[string]any{"error": "model refused"})
	for range 2 {
		if err := r.svc.CountTaskOutcome(r.ctx, failed); err != nil {
			t.Fatal(err)
		}
	}
	if got := r.trigger(t, tr.ID); got.Consecutive != 1 || !got.IsActive {
		t.Fatalf("a redelivered failure counted twice: %+v", got)
	}
	second := r.fired(t, tr)
	if err := r.svc.CountTaskOutcome(r.ctx, r.taskEvent(service.TaskFailed, second, nil)); err != nil {
		t.Fatal(err)
	}
	if got := r.trigger(t, tr.ID); got.Consecutive != 2 || got.IsActive {
		t.Fatalf("the threshold did not switch the trigger off: %+v", got)
	}
}

func TestCompletedRunResetsTheCount(t *testing.T) {
	r := newOutcomeRig(t)
	tr := r.cron(t, true, 5)
	failed := r.fired(t, tr)
	if err := r.svc.CountTaskOutcome(r.ctx, r.taskEvent(service.TaskFailed, failed, nil)); err != nil {
		t.Fatal(err)
	}
	ok := r.fired(t, tr)
	if err := r.svc.CountTaskOutcome(r.ctx, r.taskEvent(service.TaskCompleted, ok, nil)); err != nil {
		t.Fatal(err)
	}
	if got := r.trigger(t, tr.ID); got.Consecutive != 0 || !got.IsActive {
		t.Fatalf("a completed run did not reset the count: %+v", got)
	}
}

func TestOutcomesThatDoNotCount(t *testing.T) {
	r := newOutcomeRig(t)
	tr := r.cron(t, true, 1)
	task := r.fired(t, tr)
	if err := r.svc.CountTaskOutcome(r.ctx, r.taskEvent(service.TaskCancelled, task, nil)); err != nil {
		t.Fatal(err)
	}
	api := uuid.NewString()
	r.outcomes.put(runsapi.OutcomeTask{ID: api, Owner: "u1", OriginType: "api"})
	if err := r.svc.CountTaskOutcome(r.ctx, r.taskEvent(service.TaskFailed, api, nil)); err != nil {
		t.Fatal(err)
	}
	if err := r.svc.CountTaskOutcome(r.ctx, r.taskEvent(service.TaskFailed, uuid.NewString(), nil)); err != nil {
		t.Fatal(err)
	}
	if got := r.trigger(t, tr.ID); got.Consecutive != 0 || !got.IsActive {
		t.Fatalf("an outcome that does not count counted: %+v", got)
	}
}

func TestFailureBeforeItsFiringIsRedelivered(t *testing.T) {
	r := newOutcomeRig(t)
	tr := r.cron(t, true, 5)
	early := uuid.NewString()
	r.outcomes.put(runsapi.OutcomeTask{ID: early, Owner: "u1", OriginType: "trigger", OriginID: tr.ID})
	err := r.svc.CountTaskOutcome(r.ctx, r.taskEvent(service.TaskFailed, early, nil))
	if !errors.Is(err, store.ErrFiringNotRecorded) {
		t.Fatalf("err = %v", err)
	}
}

func TestTaskEventWithoutScopeIsUnprocessable(t *testing.T) {
	r := newOutcomeRig(t)
	e := r.taskEvent(service.TaskFailed, "not-a-task", nil)
	if err := r.svc.CountTaskOutcome(r.ctx, e); !errors.Is(err, events.ErrUnprocessable) {
		t.Fatalf("no task: %v", err)
	}
	e = r.taskEvent(service.TaskCompleted, uuid.NewString(), nil)
	e.Extensions = nil
	if err := r.svc.ProjectTaskEvent(r.ctx, e); !errors.Is(err, events.ErrUnprocessable) {
		t.Fatalf("no workspace: %v", err)
	}
}

func TestTaskOutcomesReachThePlatformStream(t *testing.T) {
	r := newOutcomeRig(t)
	task := uuid.NewString()
	r.outcomes.put(runsapi.OutcomeTask{ID: task, AgentID: r.agent, Owner: "u1", OriginType: "api", CorrelationID: "corr-1", Depth: 1})
	long := strings.Repeat("x", 600)
	done := r.taskEvent(service.TaskCompleted, task, map[string]any{"result": long, "total_cost": "0.25"})
	for range 2 {
		if err := r.svc.ProjectTaskEvent(r.ctx, done); err != nil {
			t.Fatal(err)
		}
	}
	asked := r.taskEvent(service.ApprovalRequested, task, map[string]any{"escalation_id": "esc-1", "tool_name": "shell", "message": "may I?"})
	again := asked
	again.ID = uuid.NewString()
	for _, e := range []events.IntegrationEvent{asked, again, r.taskEvent("task.progress", task, nil)} {
		if err := r.svc.ProjectTaskEvent(r.ctx, e); err != nil {
			t.Fatal(err)
		}
	}
	got := r.bus.Events()
	if len(got) != 2 {
		t.Fatalf("published %d events, want the completion and one approval: %+v", len(got), got)
	}
	ev := got[0].Event
	inner, _ := ev.Data["body"].(map[string]any)
	if ev.Type != service.TaskCompleted || inner["status"] != "completed" || inner["task_id"] != task || inner["cost"] != "0.25" ||
		ev.CorrelationID != "corr-1" || ev.CausationID != done.ID || ev.Extensions["depth"] != "2" || ev.Subject != task {
		t.Fatalf("completion = %+v", ev)
	}
	if res, _ := inner["result"].(string); len([]rune(res)) != 501 || !strings.HasSuffix(res, "…") {
		t.Fatalf("result summary = %q", res)
	}
	approval := got[1].Event
	if approval.Type != service.ApprovalRequested || approval.Extensions["eventkey"] != "approval:esc-1" {
		t.Fatalf("approval = %+v", approval)
	}
	owners := 0
	for _, w := range r.graph.Writes {
		if w.User == authz.UserSubject(service.PlatformPrincipal) {
			owners++
		}
	}
	if owners == 0 {
		t.Fatalf("the platform stream was not granted to its creator: %+v", r.graph.Writes)
	}
	streams := map[string]bool{}
	for _, p := range got {
		streams[p.Topic] = true
	}
	if len(streams) != 1 {
		t.Fatalf("events went to %d partitions of different streams: %v", len(streams), streams)
	}
}

func TestPlatformEventShape(t *testing.T) {
	d := service.PlatformEventData(service.TaskFailed, "failed", "t1", "a1", map[string]any{
		"error": "boom", "failure_reason": map[string]any{"code": "x<y"}, "total_cost": nil,
	})
	if d["error"] != "boom" || d["failure_reason"] != `{"code":"x<y"}` || d["status"] != "failed" {
		t.Fatalf("failed = %v", d)
	}
	if _, ok := d["cost"]; ok {
		t.Fatalf("a null cost was kept: %v", d)
	}
	q := service.PlatformEventData(service.InputRequest, "waiting_for_input", "t1", "a1", map[string]any{"question": "which?"})
	if q["question"] != "which?" {
		t.Fatalf("input = %v", q)
	}
	for _, c := range []struct {
		kind string
		data map[string]any
		want string
	}{
		{service.ApprovalRequested, map[string]any{"escalation_id": "e1"}, "approval:e1"},
		{service.InputRequest, map[string]any{"input_request_id": "i1"}, "input:i1"},
		{service.InputRequest, map[string]any{"escalation_id": "e1"}, "ev"},
		{service.TaskCompleted, nil, "ev"},
	} {
		if got := service.PlatformEventKey(c.kind, "ev", c.data); got != c.want {
			t.Fatalf("%s %v key = %q want %q", c.kind, c.data, got, c.want)
		}
	}
}
