package handlers_test

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
)

type rig struct {
	t     *testing.T
	h     http.Handler
	ws    string
	agent string
}

func newRig(t *testing.T) *rig {
	t.Helper()
	pool := storetest.Pool(t)
	wsv := storetest.Workspace(t, pool)
	agent := uuid.NewString()
	svc := service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true},
		Agents: storetest.Agents{Known: map[string]bool{agent: true}}, Schedules: &storetest.Schedules{},
		TriggerQueue: "trigger-schedules",
	})
	errs := httpx.NewErrors("http://api.test", slog.Default(), handlers.MapError)
	r := chi.NewRouter()
	caller := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			ctx := authn.WithCaller(req.Context(), authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: wsv})
			next.ServeHTTP(w, req.WithContext(ctx))
		})
	}
	handlers.Mount(r, errs, caller, handlers.New(svc, nil, nil))
	return &rig{t: t, h: r, ws: wsv.ID(), agent: agent}
}

func (g *rig) do(method, path string, body any) *httptest.ResponseRecorder {
	g.t.Helper()
	var buf bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&buf).Encode(body); err != nil {
			g.t.Fatal(err)
		}
	}
	req := httptest.NewRequest(method, "/v1/workspaces/"+g.ws+"/triggers"+path, &buf)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	g.h.ServeHTTP(rec, req)
	return rec
}

func cronBody(agent string) map[string]any {
	return map[string]any{"name": "daily", "agent_id": agent, "trigger_type": "cron",
		"cron_expression": "0 9 * * *", "timezone": "UTC", "task_parameters": map[string]any{"text": "go"}}
}

func decode(t *testing.T, rec *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &m); err != nil {
		t.Fatalf("body %q: %v", rec.Body.String(), err)
	}
	return m
}

func TestCreateGetDisableDelete(t *testing.T) {
	g := newRig(t)
	rec := g.do(http.MethodPost, "/", cronBody(g.agent))
	if rec.Code != http.StatusCreated {
		t.Fatalf("create = %d %s", rec.Code, rec.Body.String())
	}
	created := decode(t, rec)
	id := created["id"].(string)
	if created["status"] != "active" || created["trigger_type"] != "cron" || created["stream_id"] != nil {
		t.Fatalf("created body = %v", created)
	}
	if _, ok := created["next_run_time"]; !ok {
		t.Fatal("next_run_time must be present as null")
	}
	if rec := g.do(http.MethodGet, "/"+id, nil); rec.Code != http.StatusOK {
		t.Fatalf("get = %d", rec.Code)
	}
	rec = g.do(http.MethodPost, "/"+id+"/disable", nil)
	if rec.Code != http.StatusOK || decode(t, rec)["is_active"] != false {
		t.Fatalf("disable = %d %s", rec.Code, rec.Body.String())
	}
	if rec := g.do(http.MethodDelete, "/"+id, nil); rec.Code != http.StatusNoContent {
		t.Fatalf("delete = %d", rec.Code)
	}
	if rec := g.do(http.MethodGet, "/"+id, nil); rec.Code != http.StatusNotFound {
		t.Fatalf("get after delete = %d", rec.Code)
	}
}

func TestListReturnsArray(t *testing.T) {
	g := newRig(t)
	if rec := g.do(http.MethodPost, "/", cronBody(g.agent)); rec.Code != http.StatusCreated {
		t.Fatalf("create = %d", rec.Code)
	}
	rec := g.do(http.MethodGet, "/?limit=10", nil)
	if rec.Code != http.StatusOK || !strings.HasPrefix(rec.Body.String(), "[") {
		t.Fatalf("list = %d %s", rec.Code, rec.Body.String())
	}
}

func TestRefusals(t *testing.T) {
	g := newRig(t)
	body := cronBody(g.agent)
	body["conditions"] = map[string]any{"x": 1}
	if rec := g.do(http.MethodPost, "/", body); rec.Code != http.StatusBadRequest ||
		!strings.Contains(rec.Body.String(), "LLM condition must have a 'description'") {
		t.Fatalf("conditions = %d %s", rec.Code, rec.Body.String())
	}
	body["conditions"] = map[string]any{"description": "urgent", "model_id": "4a0b2b5e-8d4f-4a52-9a43-3f3b1c1f2d10"}
	if rec := g.do(http.MethodPost, "/", body); rec.Code != http.StatusNotImplemented {
		t.Fatalf("llm conditions = %d", rec.Code)
	}
	body["conditions"] = map[string]any{"type": "rule", "logic": "OR", "rules": []any{map[string]any{"field": "a", "operator": "exists"}}}
	if rec := g.do(http.MethodPost, "/", body); rec.Code != http.StatusCreated && rec.Code != http.StatusOK ||
		!strings.Contains(rec.Body.String(), `"operator":"exists"`) {
		t.Fatalf("rule conditions = %d %s", rec.Code, rec.Body.String())
	}
	noText := cronBody(g.agent)
	noText["task_parameters"] = map[string]any{}
	rec := g.do(http.MethodPost, "/", noText)
	if rec.Code != http.StatusBadRequest || !strings.Contains(rec.Body.String(), "Task text is required") {
		t.Fatalf("no text = %d %s", rec.Code, rec.Body.String())
	}
	if rec := g.do(http.MethodGet, "/"+uuid.NewString(), nil); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown = %d", rec.Code)
	}
	if rec := g.do(http.MethodPost, "/"+uuid.NewString()+"/enable", nil); rec.Code != http.StatusNotFound {
		t.Fatalf("enable unknown = %d", rec.Code)
	}
}
