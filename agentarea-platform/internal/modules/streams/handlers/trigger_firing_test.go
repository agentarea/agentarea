package handlers_test

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type firingRig struct {
	t     *testing.T
	h     http.Handler
	ws    string
	graph *storetest.Graph
	tasks *storetest.Tasks
	id    string
}

func newFiringRig(t *testing.T, withTasks bool) *firingRig {
	t.Helper()
	pool := storetest.Pool(t)
	wsv := storetest.Workspace(t, pool)
	agent := uuid.NewString()
	g := &firingRig{t: t, ws: wsv.ID(), graph: &storetest.Graph{AllowAll: true}, tasks: &storetest.Tasks{}}
	deps := service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: g.graph, Agents: storetest.Agents{Known: map[string]bool{agent: true}},
		Schedules: &storetest.Schedules{}, TriggerQueue: "trigger-schedules", FiringTasks: &storetest.FiringTasks{},
		Broker: &storetest.Broker{}, Settings: service.DefaultSettings(),
	}
	if withTasks {
		deps.Tasks = g.tasks
	}
	svc := service.New(deps)
	ctx, _ := storetest.Caller(context.Background(), wsv, "u1")
	expr, tz := "0 9 * * *", "UTC"
	tr, err := svc.Create(ctx, domain.NewTrigger{Name: "daily", AgentID: agent, Type: domain.TypeCron, CronExpression: &expr,
		Timezone: &tz, TaskParameters: map[string]any{"text": "go"}, Enabled: true, FailureThreshold: 5})
	if err != nil {
		t.Fatal(err)
	}
	g.id = tr.ID
	errs := httpx.NewErrors("http://api.test", slog.Default(), handlers.MapError)
	r := chi.NewRouter()
	caller := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			ctx := authn.WithCaller(req.Context(), authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: wsv})
			next.ServeHTTP(w, req.WithContext(ctx))
		})
	}
	handlers.Mount(r, errs, caller, handlers.New(svc, nil, nil))
	g.h = r
	return g
}

func (g *firingRig) post(path string, body any) (*httptest.ResponseRecorder, map[string]any) {
	g.t.Helper()
	var buf bytes.Buffer
	if body != nil {
		_ = json.NewEncoder(&buf).Encode(body)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/workspaces/"+g.ws+"/triggers/"+path, &buf)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	g.h.ServeHTTP(rec, req)
	var m map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &m)
	return rec, m
}

func TestExecuteAndRunStartATask(t *testing.T) {
	g := newFiringRig(t, true)
	rec, m := g.post(g.id+"/execute", map[string]any{"events": []any{map[string]any{"a": 1}}})
	if rec.Code != http.StatusOK || m["status"] != "success" || m["trigger_id"] != g.id || m["task_id"] == nil {
		t.Fatalf("execute = %d %v", rec.Code, m)
	}
	rec, m = g.post(g.id+"/run", nil)
	if rec.Code != http.StatusOK || m["status"] != "started" {
		t.Fatalf("run = %d %v", rec.Code, m)
	}
	if n := len(g.tasks.Submitted()); n != 2 {
		t.Fatalf("submitted = %d", n)
	}
	if rec, _ = g.post(uuid.NewString()+"/run", nil); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown = %d", rec.Code)
	}
}

// triggers.py:1108 and :1147 answered 500 for a caller who may not edit the trigger:
// the blanket except swallowed require_permission's 403.
func TestExecuteAndRunAnswer403NotA500(t *testing.T) {
	g := newFiringRig(t, true)
	g.graph.AllowAll = false
	for _, path := range []string{"/execute", "/run"} {
		if rec, _ := g.post(g.id+path, map[string]any{"events": []any{}}); rec.Code != http.StatusForbidden {
			t.Fatalf("%s = %d %s", path, rec.Code, rec.Body)
		}
	}
	if n := len(g.tasks.Submitted()); n != 0 {
		t.Fatalf("a refused caller started %d tasks", n)
	}
}

func TestFiringRoutesNeedTheTaskPort(t *testing.T) {
	g := newFiringRig(t, false)
	if rec, _ := g.post(g.id+"/run", nil); rec.Code == http.StatusOK {
		t.Fatalf("run without the task port = %d", rec.Code)
	}
}
