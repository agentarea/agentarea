package service_test

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
)

func newFixture(t *testing.T, graph *storetest.Graph) (context.Context, *service.Service, *storetest.Schedules, string, string) {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	agent := uuid.NewString()
	if graph == nil {
		graph = &storetest.Graph{AllowAll: true}
	}
	sched := &storetest.Schedules{}
	svc := service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: graph, Agents: storetest.Agents{Known: map[string]bool{agent: true}},
		Schedules: sched, TriggerQueue: "trigger-schedules",
	})
	return ctx, svc, sched, agent, ws.ID()
}

func cronNew(agent string, enabled bool) domain.NewTrigger {
	expr, tz := "0 9 * * *", "UTC"
	return domain.NewTrigger{
		Name: "daily", AgentID: agent, Type: domain.TypeCron, CronExpression: &expr, Timezone: &tz,
		TaskParameters: map[string]any{"text": "summarise"}, Enabled: enabled, FailureThreshold: 5,
	}
}

func TestCreateCronSchedulesAndReads(t *testing.T) {
	ctx, svc, sched, agent, _ := newFixture(t, nil)
	tr, err := svc.Create(ctx, cronNew(agent, true))
	if err != nil {
		t.Fatal(err)
	}
	if tr.Status() != domain.StatusActive || tr.CronExpression == nil || *tr.CronExpression != "0 9 * * *" {
		t.Fatalf("created trigger = %+v", tr)
	}
	s, ok := sched.Items["cron-trigger-"+tr.ID]
	if !ok || s.Paused || s.Workflow != "TriggerExecutionWorkflow" || s.CatchupWindow != api.CronTriggerCatchupWindow {
		t.Fatalf("schedule = %+v ok=%v", s, ok)
	}
	got, err := svc.Get(ctx, tr.ID)
	if err != nil || got.Name != "daily" {
		t.Fatalf("get = %+v, %v", got, err)
	}
	list, err := svc.List(ctx, storeFilter())
	if err != nil || len(list) != 1 {
		t.Fatalf("list = %d, %v", len(list), err)
	}
}

func TestCreateRefusals(t *testing.T) {
	ctx, svc, _, agent, _ := newFixture(t, nil)
	noText := cronNew(agent, true)
	noText.TaskParameters = map[string]any{}
	if _, err := svc.Create(ctx, noText); !isValidation(err, "Task text is required for CRON triggers") {
		t.Fatalf("no text: %v", err)
	}
	withConds := cronNew(agent, true)
	withConds.Conditions = map[string]any{"x": 1}
	if _, err := svc.Create(ctx, withConds); !isValidation(err, "LLM condition must have a 'description'; LLM condition must name its 'model_id'") {
		t.Fatalf("conditions: %v", err)
	}
	unknown := cronNew(uuid.NewString(), true)
	if _, err := svc.Create(ctx, unknown); !isValidation(err, "Agent with ID "+unknown.AgentID+" does not exist") {
		t.Fatalf("unknown agent: %v", err)
	}
	badCron := cronNew(agent, true)
	bad := "not a cron"
	badCron.CronExpression = &bad
	if _, err := svc.Create(ctx, badCron); err == nil {
		t.Fatal("bad cron accepted")
	}
	badTZ := cronNew(agent, true)
	zone := "Mars/Olympus"
	badTZ.Timezone = &zone
	if _, err := svc.Create(ctx, badTZ); err == nil {
		t.Fatal("bad timezone accepted")
	}
}

func TestCreateDeniedWithoutExecute(t *testing.T) {
	graph := &storetest.Graph{}
	ctx, svc, _, agent, _ := newFixture(t, graph)
	if _, err := svc.Create(ctx, cronNew(agent, true)); !errors.Is(err, errDenied()) {
		t.Fatalf("want denied, got %v", err)
	}
}

func TestDisableEnablePausesSchedule(t *testing.T) {
	ctx, svc, sched, agent, _ := newFixture(t, nil)
	tr, err := svc.Create(ctx, cronNew(agent, true))
	if err != nil {
		t.Fatal(err)
	}
	off, err := svc.Disable(ctx, tr.ID)
	if err != nil || off.IsActive || off.Status() != domain.StatusInactive {
		t.Fatalf("disable = %+v, %v", off, err)
	}
	if !sched.Items["cron-trigger-"+tr.ID].Paused {
		t.Fatal("schedule not paused")
	}
	on, err := svc.Enable(ctx, tr.ID)
	if err != nil || !on.IsActive {
		t.Fatalf("enable = %+v, %v", on, err)
	}
	if sched.Items["cron-trigger-"+tr.ID].Paused {
		t.Fatal("schedule still paused")
	}
}

func TestUpdateRules(t *testing.T) {
	ctx, svc, _, agent, _ := newFixture(t, nil)
	tr, err := svc.Create(ctx, cronNew(agent, true))
	if err != nil {
		t.Fatal(err)
	}
	name := "renamed"
	got, err := svc.Update(ctx, tr.ID, service.Patch{Name: &name})
	if err != nil || got.Name != "renamed" || got.CronExpression == nil {
		t.Fatalf("partial update = %+v, %v", got, err)
	}
	fc := 0
	if _, err := svc.Update(ctx, tr.ID, service.Patch{FailureThreshold: &fc}); err == nil {
		t.Fatal("threshold 0 accepted")
	}
	filter := map[string]any{"kinds": []any{"order.paid"}}
	if _, err := svc.Update(ctx, tr.ID, service.Patch{EventFilter: filter}); !isValidation(err, "event_filter applies only to stream triggers") {
		t.Fatalf("filter on cron trigger: %v", err)
	}
	if _, err := svc.Get(ctx, uuid.NewString()); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown get: %v", err)
	}
}

func TestDeleteRemovesSchedule(t *testing.T) {
	ctx, svc, sched, agent, _ := newFixture(t, nil)
	tr, err := svc.Create(ctx, cronNew(agent, true))
	if err != nil {
		t.Fatal(err)
	}
	if err := svc.Delete(ctx, tr.ID); err != nil {
		t.Fatal(err)
	}
	if _, ok := sched.Items["cron-trigger-"+tr.ID]; ok {
		t.Fatal("schedule kept")
	}
	if _, err := svc.Get(ctx, tr.ID); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("after delete: %v", err)
	}
}

func TestScheduleFailureIsLoggedNotReturned(t *testing.T) {
	ctx, svc, sched, agent, _ := newFixture(t, nil)
	sched.EnsureErr = errors.New("temporal down")
	if _, err := svc.Create(ctx, cronNew(agent, true)); err != nil {
		t.Fatalf("create should succeed: %v", err)
	}
}

func TestSchedulingPortRecordsAndDisablesAtThreshold(t *testing.T) {
	ctx, svc, sched, agent, _ := newFixture(t, nil)
	cfg := cronNew(agent, true)
	cfg.FailureThreshold = 1
	tr, err := svc.Create(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	p := svc.Scheduling()
	crons, err := p.CronTriggers(context.Background())
	if err != nil || len(crons) == 0 {
		t.Fatalf("crons = %v, %v", crons, err)
	}
	row, ok, err := p.CronTrigger(context.Background(), tr.ID)
	if err != nil || !ok || !row.Active {
		t.Fatalf("cron row = %+v ok=%v err=%v", row, ok, err)
	}
	state, err := p.Trigger(context.Background(), tr.ID)
	if err != nil || state.Name != "daily" {
		t.Fatalf("state = %+v, %v", state, err)
	}
	if _, err := p.Trigger(context.Background(), uuid.NewString()); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("missing trigger: %v", err)
	}
	rec, err := p.RecordExecution(context.Background(), tr.ID, api.ExecutionRecord{Status: "failed", ErrorMessage: "boom",
		TriggerData: map[string]any{"source": "cron"}})
	if err != nil || rec.ID == "" {
		t.Fatalf("record = %+v, %v", rec, err)
	}
	after, err := svc.Get(ctx, tr.ID)
	if err != nil || after.IsActive {
		t.Fatalf("trigger should be disabled at threshold: %+v, %v", after, err)
	}
	if !sched.Items["cron-trigger-"+tr.ID].Paused {
		t.Fatal("schedule not paused at threshold")
	}
	count, err := svc.CountByTaskDefinition(ctx, mustWorkspace(ctx), uuid.NewString())
	if err != nil || count != 0 {
		t.Fatalf("count = %d, %v", count, err)
	}
}

func storeFilter() store.Filter { return store.Filter{Limit: 100} }

func isValidation(err error, msg string) bool {
	var v *domain.ValidationError
	return errors.As(err, &v) && v.Msg == msg
}

func errDenied() error { return authz.ErrDenied }

func mustWorkspace(ctx context.Context) scope.Workspace {
	c, _ := authn.CallerFrom(ctx)
	return c.Workspace
}
