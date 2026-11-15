package service_test

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
)

type fakeTasks struct{ costs map[string]float64 }

func (fakeTasks) Statuses(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return map[string]string{}, nil
}
func (f fakeTasks) Costs(_ context.Context, _ scope.Workspace, ids []string) (map[string]api.TaskCost, error) {
	out := map[string]api.TaskCost{}
	for _, id := range ids {
		if v, ok := f.costs[id]; ok {
			out[id] = api.TaskCost{CostUSD: &v}
		}
	}
	return out, nil
}

type fakeAudit struct {
	mu   sync.Mutex
	recs []govapi.AuditRecord
}

func (a *fakeAudit) RecordOnce(_ context.Context, _ db.Session, r govapi.AuditRecord) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.recs = append(a.recs, r)
	return nil
}

func (a *fakeAudit) actions() []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	var out []string
	for _, r := range a.recs {
		out = append(out, r.Action+":"+r.ResourceID)
	}
	return out
}

type readsFixture struct {
	ctx   context.Context
	svc   *service.Service
	sched *storetest.Schedules
	audit *fakeAudit
	agent string
	tasks map[string]float64
}

func newReadsFixture(t *testing.T) readsFixture {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	f := readsFixture{ctx: ctx, sched: &storetest.Schedules{}, audit: &fakeAudit{}, agent: uuid.NewString(), tasks: map[string]float64{}}
	f.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true},
		Agents: storetest.Agents{Known: map[string]bool{f.agent: true}}, Schedules: f.sched,
		TriggerQueue: "trigger-schedules", TaskReads: fakeTasks{costs: f.tasks}, Audit: f.audit,
		APIURL: "https://api.example.test", Settings: service.DefaultSettings(),
	})
	return f
}

func TestExecutionReads(t *testing.T) {
	f := newReadsFixture(t)
	tr, err := f.svc.Create(f.ctx, cronNew(f.agent, true))
	if err != nil {
		t.Fatal(err)
	}
	p := f.svc.Scheduling()
	paid, gone := uuid.NewString(), uuid.NewString()
	f.tasks[paid] = 0.25
	for _, r := range []api.ExecutionRecord{
		{Status: "success", TaskID: paid, ExecutionTime: 10 * time.Millisecond},
		{Status: "success", TaskID: gone, ExecutionTime: 30 * time.Millisecond},
		{Status: "skipped"},
		{Status: "failed", ErrorMessage: "boom", ExecutionTime: 20 * time.Millisecond},
	} {
		if _, err := p.RecordExecution(context.Background(), tr.ID, r); err != nil {
			t.Fatal(err)
		}
	}

	pg, err := f.svc.Executions(f.ctx, tr.ID, service.ExecutionQuery{Page: 1, PageSize: 3})
	if err != nil || pg.Total != 4 || len(pg.Executions) != 3 || !pg.HasNext {
		t.Fatalf("page = %+v, %v", pg, err)
	}
	all, err := f.svc.Executions(f.ctx, tr.ID, service.ExecutionQuery{Page: 1, PageSize: 50})
	if err != nil || len(all.Executions) != 4 || all.HasNext || all.Executions[0].Status != "failed" {
		t.Fatalf("all = %+v, %v", all, err)
	}
	costs := map[string]*float64{}
	for _, e := range all.Executions {
		if e.TaskID != nil {
			costs[*e.TaskID] = e.CostUSD
		}
	}
	if c := costs[paid]; c == nil || *c != 0.25 {
		t.Fatalf("paid task cost = %v", c)
	}
	if c, ok := costs[gone]; ok && c != nil {
		t.Fatalf("task with no row has a cost: %v", *c)
	}
	upper := "FAILED"
	failed, err := f.svc.Executions(f.ctx, tr.ID, service.ExecutionQuery{Status: &upper, Page: 1, PageSize: 50})
	if err != nil || failed.Total != 1 || failed.Executions[0].Status != "failed" {
		t.Fatalf("status filter = %+v, %v", failed, err)
	}
	bogus := "exploded"
	if _, err := f.svc.Executions(f.ctx, tr.ID, service.ExecutionQuery{Status: &bogus, Page: 1, PageSize: 50}); !isValidation(err, "Invalid status: exploded") {
		t.Fatalf("bad status: %v", err)
	}
	future := time.Now().Add(time.Hour)
	later, err := f.svc.Executions(f.ctx, tr.ID, service.ExecutionQuery{Start: &future, Page: 1, PageSize: 50})
	if err != nil || later.Total != 0 {
		t.Fatalf("start filter = %+v, %v", later, err)
	}

	m, err := f.svc.Metrics(f.ctx, tr.ID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if m.Total != 4 || m.Successful != 2 || m.Failed != 1 || m.Skipped != 1 || m.PeriodHours != nil {
		t.Fatalf("metrics counts = %+v", m)
	}
	if m.SuccessRate < 66.66 || m.SuccessRate > 66.67 || m.MinMs != 0 || m.MaxMs != 30 {
		t.Fatalf("metrics rates = %+v", m)
	}
	if m.TotalCostUSD != 0.25 || m.CostedExecutions != 1 || m.AvgCostUSD != 0.25 {
		t.Fatalf("metrics spend = %+v", m)
	}
	h := 1
	if m, err = f.svc.Metrics(f.ctx, tr.ID, &h); err != nil || m.Total != 4 || m.PeriodHours == nil {
		t.Fatalf("windowed metrics = %+v, %v", m, err)
	}

	tl, err := f.svc.Timeline(f.ctx, tr.ID, 24, 5)
	if err != nil || len(tl) == 0 {
		t.Fatalf("timeline = %+v, %v", tl, err)
	}
	total := 0
	for _, b := range tl {
		total += b.Total
		if b.Start.Minute()%5 != 0 || b.Start.Second() != 0 {
			t.Fatalf("bucket not on a 5 minute boundary: %v", b.Start)
		}
	}
	if total != 4 {
		t.Fatalf("timeline total = %d", total)
	}

	rows, n, err := f.svc.Correlations(f.ctx, tr.ID, 2, 3)
	if err != nil || n != 4 || len(rows) != 1 {
		t.Fatalf("correlations = %d/%d, %v", len(rows), n, err)
	}
	if _, err := f.svc.Metrics(f.ctx, uuid.NewString(), nil); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown trigger: %v", err)
	}
}

func TestStatusAndHealth(t *testing.T) {
	f := newReadsFixture(t)
	tr, err := f.svc.Create(f.ctx, cronNew(f.agent, true))
	if err != nil {
		t.Fatal(err)
	}
	st, err := f.svc.Status(f.ctx, tr.ID)
	if err != nil || st.ScheduleInfo == nil {
		t.Fatalf("status = %+v, %v", st, err)
	}
	if st.ScheduleInfo["schedule_id"] != "cron-trigger-"+tr.ID || st.ScheduleInfo["paused"] != false {
		t.Fatalf("schedule_info = %+v", st.ScheduleInfo)
	}
	if crons, _ := st.ScheduleInfo["cron_expressions"].([]string); len(crons) != 1 || crons[0] != "0 9 * * *" {
		t.Fatalf("cron_expressions = %v", st.ScheduleInfo["cron_expressions"])
	}
	delete(f.sched.Items, "cron-trigger-"+tr.ID)
	if st, err = f.svc.Status(f.ctx, tr.ID); err != nil || st.ScheduleInfo != nil {
		t.Fatalf("status without schedule = %+v, %v", st, err)
	}

	h := f.svc.Health(f.ctx)
	comps := h["components"].(map[string]any)
	if h["overall_status"] != "healthy" || h["service"] != "triggers" {
		t.Fatalf("health = %+v", h)
	}
	db := comps["database"].(map[string]any)["details"].(map[string]any)
	if db["trigger_count"] != 1 {
		t.Fatalf("database details = %+v", db)
	}
	if hook := comps["webhook_manager"].(map[string]any)["details"].(map[string]any); hook["base_url"] != "https://api.example.test/webhooks" {
		t.Fatalf("webhook details = %+v", hook)
	}
}

func TestStreamTriggerFilterAndClears(t *testing.T) {
	f := newReadsFixture(t)
	s, err := f.svc.CreateStream(f.ctx, "orders", "")
	if err != nil {
		t.Fatal(err)
	}
	w := "1h"
	n := domain.NewTrigger{Name: "on order", AgentID: f.agent, Type: domain.TypeStream, StreamID: &s.ID, Enabled: true,
		FailureThreshold: 5, TaskParameters: map[string]any{"text": "handle"},
		EventFilter: map[string]any{"kinds": []any{"order.paid"}}, Batch: &domain.Batch{Window: &w}}
	tr, err := f.svc.Create(f.ctx, n)
	if err != nil {
		t.Fatal(err)
	}
	if fields, ok := tr.Binding.Filter["fields"].(map[string]any); !ok || len(fields) != 0 {
		t.Fatalf("stored filter is not model_dump shaped: %+v", tr.Binding.Filter)
	}
	if tr.Batch == nil || tr.Batch.Window == nil || *tr.Batch.Window != "1h" {
		t.Fatalf("batch = %+v", tr.Batch)
	}
	got, err := f.svc.Update(f.ctx, tr.ID, service.Patch{BatchSet: true})
	if err != nil || got.Batch != nil {
		t.Fatalf("batch sent as null should clear: %+v, %v", got.Batch, err)
	}
	name := "kept"
	if got, err = f.svc.Update(f.ctx, tr.ID, service.Patch{Name: &name}); err != nil || got.Binding == nil {
		t.Fatalf("rename = %+v, %v", got, err)
	}
	if _, err := f.svc.Update(f.ctx, tr.ID, service.Patch{EventFilter: map[string]any{"kind": "x"}}); !isValidation(err, "event_filter.kind: Extra inputs are not permitted") {
		t.Fatalf("bad filter: %v", err)
	}
	if err := f.svc.Delete(f.ctx, tr.ID); err != nil {
		t.Fatal(err)
	}
	want := []string{"trigger.create:" + tr.ID, "trigger.update:" + tr.ID, "trigger.update:" + tr.ID, "trigger.delete:" + tr.ID}
	if got := f.audit.actions(); len(got) != len(want) {
		t.Fatalf("audit = %v, want %v", got, want)
	} else {
		for i := range want {
			if got[i] != want[i] {
				t.Fatalf("audit = %v, want %v", got, want)
			}
		}
	}
}

func TestCronUpdateClearsTaskDefinitionAndEnableResets(t *testing.T) {
	f := newReadsFixture(t)
	cfg := cronNew(f.agent, true)
	td := uuid.NewString()
	cfg.TaskDefinitionID = &td
	cfg.TaskParameters = map[string]any{}
	tr, err := f.svc.Create(f.ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Update(f.ctx, tr.ID, service.Patch{TaskDefinitionSet: true}); !isValidation(err, "Task text is required for CRON triggers") {
		t.Fatalf("clearing the saved task without text: %v", err)
	}
	got, err := f.svc.Update(f.ctx, tr.ID, service.Patch{TaskDefinitionSet: true, TaskParameters: map[string]any{"text": "now this"}})
	if err != nil || got.TaskDefinitionID != nil {
		t.Fatalf("null task_definition_id should clear: %+v, %v", got.TaskDefinitionID, err)
	}
	year := "0 9 * * 1-5 2030"
	if got, err = f.svc.Update(f.ctx, tr.ID, service.Patch{CronExpression: &year}); err != nil || *got.CronExpression != year {
		t.Fatalf("six field cron = %v, %v", got.CronExpression, err)
	}
	p := f.svc.Scheduling()
	if _, err := p.RecordExecution(context.Background(), tr.ID, api.ExecutionRecord{Status: "failed", ErrorMessage: "x"}); err != nil {
		t.Fatal(err)
	}
	if _, err := f.svc.Disable(f.ctx, tr.ID); err != nil {
		t.Fatal(err)
	}
	on, err := f.svc.Enable(f.ctx, tr.ID)
	if err != nil || !on.IsActive || on.Consecutive != 0 {
		t.Fatalf("enable = active %v failures %d, %v", on.IsActive, on.Consecutive, err)
	}
	for _, a := range f.audit.actions() {
		if a != "trigger.create:"+tr.ID && a != "trigger.update:"+tr.ID {
			t.Fatalf("enable/disable are not audited: %v", f.audit.actions())
		}
	}
}
