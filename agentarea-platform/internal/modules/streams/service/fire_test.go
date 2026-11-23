package service_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type storeTask = api.StoredTask

type fireRig struct {
	ctx    context.Context
	ws     scope.Workspace
	svc    *service.Service
	tasks  *storetest.Tasks
	firing *storetest.FiringTasks
	known  map[string]bool
	agent  string
	turns  turnLog
}

type turnLog map[string]map[string]any

func (l turnLog) Begin(_ context.Context, taskID string, address map[string]any) error {
	l[taskID] = address
	return nil
}

func newFireRig(t *testing.T) *fireRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	g := &fireRig{ctx: ctx, ws: ws, tasks: &storetest.Tasks{}, firing: &storetest.FiringTasks{}, agent: uuid.NewString(), turns: turnLog{}}
	g.known = map[string]bool{g.agent: true}
	g.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true}, Agents: storetest.Agents{Known: g.known},
		Schedules: &storetest.Schedules{}, TriggerQueue: "trigger-schedules", Tasks: g.tasks, Turns: g.turns, FiringTasks: g.firing,
		Broker: &storetest.Broker{}, Settings: service.DefaultSettings(),
	})
	return g
}

func TestARoutedFollowUpIsAnsweredAtItsOwnMessage(t *testing.T) {
	g := newFireRig(t)
	tr := g.cron(t, true, 5)
	fire := func(messageID int) service.Firing {
		t.Helper()
		f, err := g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, Delivery: &service.TaskDelivery{
			Address: map[string]any{"type": "telegram", "sender": "telegram_live", "target": map[string]any{"chat_id": -100, "message_id": messageID}}}})
		if err != nil {
			t.Fatal(err)
		}
		return f
	}
	if f := fire(1); f.Outcome != service.OutcomeReacted || len(g.turns) != 0 {
		t.Fatalf("a task that started recorded a turn: %+v %v", f, g.turns)
	}
	running := uuid.NewString()
	g.tasks.RouteTo = running
	f := fire(2)
	target, _ := g.turns[running]["target"].(map[string]any)
	if f.TaskID != running || len(g.turns) != 1 || target["message_id"] != 2 {
		t.Fatalf("the routed follow-up's turn = %v (firing %+v)", g.turns, f)
	}
}

func (g *fireRig) cron(t *testing.T, enabled bool, threshold int) domain.Trigger {
	t.Helper()
	n := cronNew(g.agent, enabled)
	n.FailureThreshold = threshold
	tr, err := g.svc.Create(g.ctx, n)
	if err != nil {
		t.Fatal(err)
	}
	return tr
}

func (g *fireRig) fire(t *testing.T, id string) service.Firing {
	t.Helper()
	f, err := g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: id})
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func TestFireStartsTheTaskAndRecordsIt(t *testing.T) {
	g := newFireRig(t)
	tr := g.cron(t, true, 5)
	f := g.fire(t, tr.ID)
	reqs := g.tasks.Submitted()
	if f.Outcome != service.OutcomeReacted || len(reqs) != 1 || f.TaskID != reqs[0].TaskID || f.Execution == nil ||
		f.Execution.Status != service.ExecSuccess {
		t.Fatalf("firing = %+v requests = %+v", f, reqs)
	}
	r := reqs[0]
	if r.AgentID != g.agent || r.Provenance.OriginType != "trigger" || r.Provenance.OriginID != tr.ID ||
		!strings.Contains(r.Description, "summarise") || r.UserID != "u1" {
		t.Fatalf("request = %+v", r)
	}
	if r.Parameters["trigger_id"] != tr.ID {
		t.Fatalf("parameters = %v", r.Parameters)
	}
}

func TestFireSkipsInactiveAndOverlappingCron(t *testing.T) {
	g := newFireRig(t)
	off := g.cron(t, false, 5)
	if f := g.fire(t, off.ID); f.Outcome != service.OutcomeSkipped || f.Reason != "trigger is inactive" ||
		f.Execution == nil || f.Execution.Status != service.ExecSkipped {
		t.Fatalf("inactive = %+v", f)
	}
	on := g.cron(t, true, 5)
	g.firing.Running = "task-1"
	f := g.fire(t, on.ID)
	if f.Outcome != service.OutcomeSkipped || f.BlockedBy != "task-1" || f.Reason != "The previous run is still going (task task-1)" {
		t.Fatalf("overlap = %+v", f)
	}
	if len(g.tasks.Submitted()) != 0 {
		t.Fatal("a skipped firing submitted a task")
	}
}

func TestSpendCapIsSkippedNotFailed(t *testing.T) {
	g := newFireRig(t)
	tr := g.cron(t, true, 1)
	g.tasks.Err = runsapi.ErrSpendCapReached
	f := g.fire(t, tr.ID)
	if f.Outcome != service.OutcomeSkipped || f.Execution == nil || f.Execution.Status != service.ExecSkipped {
		t.Fatalf("spend cap = %+v", f)
	}
	got, err := g.svc.Trigger(g.ctx, g.ws, tr.ID)
	if err != nil || !got.IsActive {
		t.Fatalf("a spend cap switched the trigger off: %+v %v", got, err)
	}
}

func TestPermanentFailuresSwitchTheTriggerOff(t *testing.T) {
	g := newFireRig(t)
	tr := g.cron(t, true, 2)
	g.tasks.Err = runsapi.ErrModelNotConfigured
	for i := range 2 {
		f := g.fire(t, tr.ID)
		if f.Outcome != service.OutcomeError || f.Execution == nil || f.Execution.Status != service.ExecFailed {
			t.Fatalf("firing %d = %+v", i, f)
		}
	}
	got, err := g.svc.Trigger(g.ctx, g.ws, tr.ID)
	if err != nil || got.IsActive || got.Consecutive != 2 {
		t.Fatalf("after threshold: %+v %v", got, err)
	}
}

func TestRetryableFailureIsReturned(t *testing.T) {
	g := newFireRig(t)
	tr := g.cron(t, true, 5)
	boom := errors.New("temporal unreachable")
	g.tasks.Err = boom
	_, err := g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, RaiseRetryable: true})
	if !errors.Is(err, boom) {
		t.Fatalf("err = %v", err)
	}
}

func TestAgentGoneFailsAndStopsTheTrigger(t *testing.T) {
	g := newFireRig(t)
	tr := g.cron(t, true, 5)
	delete(g.known, g.agent)
	f := g.fire(t, tr.ID)
	if f.Outcome != service.OutcomeError || !strings.HasPrefix(f.Reason, "agent_unavailable: agent "+g.agent) {
		t.Fatalf("firing = %+v", f)
	}
	got, _ := g.svc.Trigger(g.ctx, g.ws, tr.ID)
	if got.NeedsNewOwnerAt == nil {
		t.Fatal("the trigger was not stopped for attention")
	}
}

func TestRetriedFiringDoesNotStartTwice(t *testing.T) {
	g := newFireRig(t)
	tr := g.cron(t, true, 5)
	id := uuid.NewString()
	g.firing.Stored = map[string]storeTask{id: {Status: "running", ExecutionID: "exec"}}
	f, err := g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, TaskID: id, FiredBy: "u1"})
	if err != nil || f.Outcome != service.OutcomeReacted || f.Reason != "task already started" || len(g.tasks.Submitted()) != 0 {
		t.Fatalf("retry = %+v %v", f, err)
	}
	g.firing.Stored[id] = storeTask{Status: "pending"}
	f, err = g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, TaskID: id, FiredBy: "u1"})
	if err != nil || f.Reason != "task started on retry" || len(g.firing.Restarted) != 1 {
		t.Fatalf("restart = %+v %v", f, err)
	}
}
