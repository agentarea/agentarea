package handlers_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

func specs(docs ...string) []json.RawMessage {
	out := make([]json.RawMessage, len(docs))
	for i, d := range docs {
		out[i] = json.RawMessage(d)
	}
	return out
}

func fieldLocs(t *testing.T, err error) [][]any {
	t.Helper()
	var ve *httpx.ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("err = %v, want a validation error", err)
	}
	var locs [][]any
	for _, e := range ve.Errors {
		locs = append(locs, e.Loc)
	}
	return locs
}

func TestCheckSchemaErrorsAreLocatedUnderTheTriggerIndex(t *testing.T) {
	a := handlers.NewAgentTriggers(nil, nil)
	c := authn.Caller{}
	err := a.Check(context.Background(), c, specs(
		`{"name":"ok","trigger_type":"cron","cron_expression":"0 9 * * *","task_parameters":{"text":"x"}}`,
		`{"name":"x","trigger_type":"cron","cron_expression":"0 9 * * *","surprise":1,"failure_threshold":0}`,
	))
	locs := fieldLocs(t, err)
	if len(locs) != 2 || locs[0][2] != 1 || locs[0][3] != "failure_threshold" || locs[1][3] != "surprise" {
		t.Fatalf("locs = %v", locs)
	}
	err = a.Check(context.Background(), c, specs(`{"name":"x","trigger_type":"cron"}`))
	if locs := fieldLocs(t, err); len(locs) != 1 || len(locs[0]) != 3 {
		t.Fatalf("model-level loc = %v", locs)
	}
	err = a.Check(context.Background(), c, specs(`{"name":"x","trigger_type":"cron","cron_expression":"* * * * *","task_parameters":{"session":"s"}}`))
	if locs := fieldLocs(t, err); len(locs) != 1 || locs[0][3] != "task_parameters" {
		t.Fatalf("reserved loc = %v", locs)
	}
}

type agentTrigRig struct {
	a     handlers.AgentTriggers
	svc   *service.Service
	graph *storetest.Graph
	sched *storetest.Schedules
	c     authn.Caller
	ctx   context.Context
	agent string
}

func newAgentTrigRig(t *testing.T) *agentTrigRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	agent := uuid.NewString()
	graph := &storetest.Graph{AllowAll: true}
	sched := &storetest.Schedules{}
	svc := service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: graph, Agents: storetest.Agents{Known: map[string]bool{agent: true}},
		Schedules: sched, TriggerQueue: "trigger-schedules",
	})
	ctx, c := storetest.Caller(context.Background(), ws, "u1")
	return &agentTrigRig{a: handlers.NewAgentTriggers(svc, nil), svc: svc, graph: graph, sched: sched, c: c, ctx: ctx, agent: agent}
}

func TestCheckRefusesWhatCreateWould(t *testing.T) {
	g := newAgentTrigRig(t)
	err := g.a.Check(g.ctx, g.c, specs(`{"name":"x","trigger_type":"cron","cron_expression":"not a cron","task_parameters":{"text":"t"}}`))
	var he *httpx.Error
	if !errors.As(err, &he) || he.Status != http.StatusBadRequest || he.Detail[:12] != "Trigger 'x':" {
		t.Fatalf("bad cron = %v", err)
	}
	missing := uuid.NewString()
	err = g.a.Check(g.ctx, g.c, specs(`{"name":"s","trigger_type":"stream","stream_id":"`+missing+`"}`))
	if !errors.As(err, &he) || he.Status != http.StatusBadRequest {
		t.Fatalf("missing stream = %v", err)
	}
	st, err := handlers.NewPlatformStreams(g.svc, nil).Create(g.ctx, g.c, "orders", "")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(st)
	var made struct {
		ID string `json:"id"`
	}
	_ = json.Unmarshal(raw, &made)
	doc := `{"name":"s","trigger_type":"stream","stream_id":"` + made.ID + `","task_parameters":{"text":"t"}}`
	if err := g.a.Check(g.ctx, g.c, specs(doc)); err != nil {
		t.Fatalf("readable stream = %v", err)
	}
	g.graph.AllowAll = false
	err = g.a.Check(g.ctx, g.c, specs(doc))
	if !errors.As(err, &he) || he.Status != http.StatusForbidden {
		t.Fatalf("unreadable stream = %v", err)
	}
}

func TestCreateRollsBackTheFirstWhenTheSecondFails(t *testing.T) {
	g := newAgentTrigRig(t)
	err := g.a.Create(g.ctx, g.c, g.agent, specs(
		`{"name":"first","trigger_type":"cron","cron_expression":"0 9 * * *","task_parameters":{"text":"t"}}`,
		`{"name":"second","trigger_type":"stream","stream_id":"`+uuid.NewString()+`"}`,
	))
	var he *httpx.Error
	if !errors.As(err, &he) || he.Status != http.StatusBadRequest {
		t.Fatalf("create = %v", err)
	}
	ts, err := g.svc.List(g.ctx, store.Filter{Limit: 100})
	if err != nil || len(ts) != 0 {
		t.Fatalf("left behind %d triggers, %v", len(ts), err)
	}
	if len(g.sched.Items) != 0 {
		t.Fatalf("left behind schedules %v", g.sched.Items)
	}
}

func TestCreateMakesDisabledTriggersPaused(t *testing.T) {
	g := newAgentTrigRig(t)
	err := g.a.Create(g.ctx, g.c, g.agent, specs(
		`{"name":"off","trigger_type":"cron","cron_expression":"0 9 * * *","enabled":false,"task_parameters":{"text":"t"}}`,
	))
	if err != nil {
		t.Fatal(err)
	}
	ts, err := g.svc.List(g.ctx, store.Filter{Limit: 100})
	if err != nil || len(ts) != 1 || ts[0].IsActive || ts[0].AgentID != g.agent {
		t.Fatalf("triggers = %+v, %v", ts, err)
	}
	for _, s := range g.sched.Items {
		if !s.Paused {
			t.Fatalf("schedule not paused: %+v", s)
		}
	}
}

type leavingGraph struct {
	*storetest.Graph
	stream string
	cancel context.CancelFunc
}

func (g leavingGraph) Check(ctx context.Context, subject, relation, objectType, objectID string) (bool, error) {
	if objectID == g.stream {
		g.cancel()
		return false, nil
	}
	return g.Graph.Check(ctx, subject, relation, objectType, objectID)
}

func TestCreateRollsBackAfterTheClientLeft(t *testing.T) {
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	agent, stream := uuid.NewString(), uuid.NewString()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	svc := service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: leavingGraph{Graph: &storetest.Graph{AllowAll: true}, stream: stream, cancel: cancel},
		Agents: storetest.Agents{Known: map[string]bool{agent: true}}, Schedules: &storetest.Schedules{}, TriggerQueue: "trigger-schedules",
	})
	ctx, c := storetest.Caller(ctx, ws, "u1")
	err := handlers.NewAgentTriggers(svc, nil).Create(ctx, c, agent, specs(
		`{"name":"first","trigger_type":"cron","cron_expression":"0 9 * * *","task_parameters":{"text":"t"}}`,
		`{"name":"second","trigger_type":"stream","stream_id":"`+stream+`"}`,
	))
	if err == nil {
		t.Fatal("the second trigger was made")
	}
	listCtx, _ := storetest.Caller(context.Background(), ws, "u1")
	ts, err := svc.List(listCtx, store.Filter{Limit: 100})
	if err != nil || len(ts) != 0 {
		t.Fatalf("left behind %d triggers, %v", len(ts), err)
	}
}
