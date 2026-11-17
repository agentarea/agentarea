//go:build suite

package live

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

const (
	liveProvider = "1a7e0000-0000-4000-8000-000000000001"
	liveHaiku    = "1a7e0000-0000-4000-8000-000000000002"
)

func liveModel(t *testing.T, w *h.Workspace) string {
	t.Helper()
	key := os.Getenv("ANTHROPIC_API_KEY")
	if key == "" {
		t.Skip("ANTHROPIC_API_KEY not set")
	}
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": liveProvider, "name": "Anthropic", "api_key": key,
	}).Expect(http.StatusOK).Object()
	return w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": liveHaiku, "name": "Haiku 5.5",
	}).Expect(http.StatusOK).Object()["id"].(string)
}

func policy() map[string]any {
	return map[string]any{
		"budget":    map[string]any{"run_budget_usd": "0.50"},
		"tokens":    map[string]any{"max_tokens": 60000, "max_tokens_per_call": 4000},
		"execution": map[string]any{"max_model_turns": 8, "max_tool_calls_per_turn": 3, "max_tool_calls_total": 8},
	}
}

func agent(t *testing.T, w *h.Workspace, body map[string]any) string {
	t.Helper()
	if _, ok := body["tools"]; !ok {
		body["tools"] = []any{}
	}
	return w.Owner.Post(t, w.Path("/agents/"), body).Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)
}

func start(t *testing.T, w *h.Workspace, agentID, ask string) string {
	t.Helper()
	task := w.Owner.Post(t, w.Path("/agents/"+agentID+"/tasks/sync"), map[string]any{"description": ask, "task_policy": policy()}).
		Expect(http.StatusOK).Object()
	return task["id"].(string)
}

func wait(t *testing.T, w *h.Workspace, agentID, taskID string, until func(task map[string]any) bool) map[string]any {
	t.Helper()
	var task map[string]any
	h.Eventually(t, 180*time.Second, func() error {
		task = w.Owner.Get(t, w.Path("/agents/"+agentID+"/tasks/"+taskID)).Expect(http.StatusOK).Object()
		if until(task) {
			return nil
		}
		switch task["status"] {
		case "failed", "cancelled", "canceled":
			b, _ := json.Marshal(task)
			t.Fatalf("task ended %v: %s\nevents: %s", task["status"], b, eventDump(t, w, agentID, taskID))
		}
		return fmt.Errorf("status %v", task["status"])
	})
	return task
}

func completed(task map[string]any) bool { return task["status"] == "completed" }

func events(t *testing.T, w *h.Workspace, agentID, taskID string) []map[string]any {
	t.Helper()
	page, _ := w.Owner.Get(t, w.Path("/agents/"+agentID+"/tasks/"+taskID+"/events?limit=500")).Expect(http.StatusOK).JSON().(map[string]any)
	var out []map[string]any
	for _, e := range page["events"].([]any) {
		out = append(out, e.(map[string]any))
	}
	return out
}

func eventDump(t *testing.T, w *h.Workspace, agentID, taskID string) string {
	var b strings.Builder
	for _, e := range events(t, w, agentID, taskID) {
		d, _ := json.Marshal(e["data"])
		s := string(d)
		if len(s) > 300 {
			s = s[:300] + "…"
		}
		fmt.Fprintf(&b, "\n  %v %s", e["event_type"], s)
	}
	return b.String()
}

func report(t *testing.T, w *h.Workspace, agentID, taskID string, task map[string]any) {
	t.Helper()
	types := map[string]int{}
	for _, e := range events(t, w, agentID, taskID) {
		types[fmt.Sprint(e["event_type"])]++
	}
	res, _ := json.Marshal(task["result"])
	t.Logf("status=%v cost=%v tokens=%v events=%v\nresult=%s", task["status"], task["total_cost"], task["total_tokens"], types, res)
}

func resultText(task map[string]any) string {
	b, _ := json.Marshal(task["result"])
	return string(b)
}

func TestLiveChat(t *testing.T) {
	w := h.NewWorkspace(t)
	a := agent(t, w, map[string]any{"name": "Calc", "instruction": "You answer arithmetic questions precisely.", "model_id": liveModel(t, w)})
	id := start(t, w, a, "What is 17 multiplied by 23? Reply with the number.")
	task := wait(t, w, a, id, completed)
	report(t, w, a, id, task)
	if !strings.Contains(resultText(task), "391") {
		t.Fatalf("result lacks 391: %s", resultText(task))
	}
}

func TestLiveOpenAPITool(t *testing.T) {
	var mu sync.Mutex
	var cities []string
	srv := httptest.NewServer(http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
		mu.Lock()
		cities = append(cities, r.URL.Query().Get("city"))
		mu.Unlock()
		rw.Header().Set("Content-Type", "application/json")
		_, _ = rw.Write([]byte(`{"city":"` + r.URL.Query().Get("city") + `","temperature_c":-7,"conditions":"heavy snow"}`))
	}))
	defer srv.Close()
	w := h.NewWorkspace(t)
	base := h.StackURL(srv.URL)
	conn := w.Owner.Post(t, w.Path("/openapi-connections/"), map[string]any{"name": "Weather", "base_url": base, "spec_content": map[string]any{
		"openapi": "3.0.0", "info": map[string]any{"title": "Weather", "version": "1.0.0"},
		"paths": map[string]any{"/weather": map[string]any{"get": map[string]any{
			"operationId": "getWeather", "summary": "Current weather for a city",
			"parameters": []any{map[string]any{"name": "city", "in": "query", "required": true, "schema": map[string]any{"type": "string"}}},
			"responses":  map[string]any{"200": map[string]any{"description": "ok"}},
		}}},
	}}).Expect(http.StatusCreated).Object()
	a := agent(t, w, map[string]any{"name": "Weather", "instruction": "Use the weather tool to answer weather questions.",
		"model_id": liveModel(t, w),
		"tools":    []any{map[string]any{"type": "openapi", "name": "Weather", "settings": map[string]any{"openapi_connection_id": conn["id"]}}}})
	id := start(t, w, a, "What's the weather in Oslo right now? Give temperature and conditions.")
	task := wait(t, w, a, id, completed)
	report(t, w, a, id, task)
	mu.Lock()
	defer mu.Unlock()
	if len(cities) == 0 || !strings.EqualFold(cities[0], "Oslo") {
		t.Fatalf("the API saw cities %v", cities)
	}
	if r := strings.ToLower(resultText(task)); !strings.Contains(r, "-7") || !strings.Contains(r, "snow") {
		t.Fatalf("the answer does not use the tool result: %s", resultText(task))
	}
}

func TestLiveAsksTheUser(t *testing.T) {
	w := h.NewWorkspace(t)
	a := agent(t, w, map[string]any{"name": "Greeter",
		"instruction": "Before answering, you must ask the user for their favourite colour with the request_user_input tool. Then write one sentence that uses that colour.",
		"model_id":    liveModel(t, w)})
	id := start(t, w, a, "Write me a one-sentence greeting.")
	var req map[string]any
	h.Eventually(t, 120*time.Second, func() error {
		for _, e := range events(t, w, a, id) {
			if e["event_type"] == "input.request" {
				req, _ = e["data"].(map[string]any)
				return nil
			}
		}
		return fmt.Errorf("no input.request yet")
	})
	qs, _ := req["questions"].([]any)
	qid := "field_1"
	if len(qs) > 0 {
		if v, _ := qs[0].(map[string]any)["id"].(string); v != "" {
			qid = v
		}
	}
	t.Logf("asked: %v (question id %s)", req["question"], qid)
	w.Owner.Post(t, w.Path("/agents/"+a+"/tasks/"+id+"/input"), map[string]any{
		"input_request_id": req["input_request_id"], "answers": map[string]any{qid: "turquoise"},
	}).Expect(http.StatusOK, http.StatusAccepted)
	task := wait(t, w, a, id, completed)
	report(t, w, a, id, task)
	if !strings.Contains(strings.ToLower(resultText(task)), "turquoise") {
		t.Fatalf("the answer ignores the user's input: %s", resultText(task))
	}
}

func TestLiveStreamCarriesTheAnswer(t *testing.T) {
	w := h.NewWorkspace(t)
	a := agent(t, w, map[string]any{"name": "Poet", "instruction": "You write short poems.", "model_id": liveModel(t, w)})
	id := start(t, w, a, "Write a four-line poem about the word 'lantern'. Include the word lantern.")
	stream := w.Owner.Stream(t, w.Path("/agents/"+a+"/tasks/"+id+"/events/stream"), 120*time.Second)
	stream.Until(110*time.Second, func(e h.Event) bool {
		return strings.Contains(e.Data, "task.completed") || strings.Contains(e.Data, "task_completed")
	})
	task := wait(t, w, a, id, completed)
	report(t, w, a, id, task)
}

func TestLiveCronTriggerRunsTheAgent(t *testing.T) {
	w := h.NewWorkspace(t)
	a := agent(t, w, map[string]any{"name": "Daily", "instruction": "You write one-line status notes.", "model_id": liveModel(t, w)})
	trig := w.Owner.Post(t, w.Path("/triggers/"), map[string]any{
		"name": "every minute", "trigger_type": "cron", "agent_id": a, "cron_expression": "* * * * *", "timezone": "UTC",
		"enabled": true, "task_parameters": map[string]any{"text": "Write a one-line status note that contains the word heartbeat."},
	}).Expect(http.StatusOK, http.StatusCreated).Object()
	defer w.Owner.Delete(t, w.Path("/triggers/"+trig["id"].(string)))
	var done map[string]any
	h.Eventually(t, 200*time.Second, func() error {
		page := w.Owner.Get(t, w.Path("/agents/"+a+"/tasks/")).Expect(http.StatusOK).JSON()
		var items []any
		switch p := page.(type) {
		case []any:
			items = p
		case map[string]any:
			items, _ = p["items"].([]any)
			if items == nil {
				items, _ = p["tasks"].([]any)
			}
		}
		for _, it := range items {
			m := it.(map[string]any)
			if m["status"] == "completed" {
				done = m
				return nil
			}
		}
		return fmt.Errorf("%d tasks, none completed", len(items))
	})
	full := w.Owner.Get(t, w.Path("/agents/"+a+"/tasks/"+done["id"].(string))).Expect(http.StatusOK).Object()
	report(t, w, a, done["id"].(string), full)
	if !strings.Contains(strings.ToLower(resultText(full)), "heartbeat") {
		t.Fatalf("result %s", resultText(full))
	}
}

func TestLiveSandboxRunsCode(t *testing.T) {
	w := h.NewWorkspace(t)
	a := agent(t, w, map[string]any{"name": "Coder", "instruction": "You write and run code in your sandbox. Always run what you write.",
		"model_id": liveModel(t, w),
		"tools": []any{map[string]any{"type": "code", "name": "agentarea/shell", "settings": map[string]any{}},
			map[string]any{"type": "code", "name": "agentarea/files", "settings": map[string]any{}}}})
	id := start(t, w, a, "Write outputs/fib.py that prints the 30th Fibonacci number (fib(1)=1, fib(2)=1), run it with python3, and tell me the printed number.")
	task := wait(t, w, a, id, completed)
	report(t, w, a, id, task)
	t.Logf("events:%s", eventDump(t, w, a, id))
	if !strings.Contains(resultText(task), "832040") {
		t.Fatalf("result lacks 832040: %s", resultText(task))
	}
	files := w.Owner.Get(t, w.Path("/agents/"+a+"/tasks/"+id+"/sandbox/files")).Expect(http.StatusOK).JSON()
	b, _ := json.Marshal(files)
	if !strings.Contains(string(b), "fib.py") {
		t.Fatalf("sandbox files lack fib.py: %s", b)
	}
}
