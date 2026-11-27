//go:build suite

package runs

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

// The suite catalog's provider and chat model (test/suite/models/seed.sql).
const (
	suiteProvider = "5e1f0000-0000-4000-8000-000000000001"
	suiteChat     = "5e1f0000-0000-4000-8000-000000000002"
	finalAnswer   = "The suite answer is 42."
)

// builtins are the workflow's own tools; the fake model calls the first other one.
var builtins = []string{"completion", "task_complete", "request_user_input", "recall_history", "read_file"}

// fakeHost is the run's outside world on the host: an OpenAI-compatible
// provider whose first turn calls the agent's tool and whose turn after the
// tool result answers in text, and the HTTP API that tool calls.
type fakeHost struct {
	mu       sync.Mutex
	requests []map[string]any
	apiCalls int
}

func (f *fakeHost) serve(t *testing.T) string {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/answer" {
			f.mu.Lock()
			f.apiCalls++
			f.mu.Unlock()
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"answer":42}`))
			return
		}
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !strings.HasSuffix(r.URL.Path, "/chat/completions") {
			http.Error(w, "not a chat completion", http.StatusBadRequest)
			return
		}
		f.mu.Lock()
		f.requests = append(f.requests, req)
		f.mu.Unlock()
		msg := map[string]any{"role": "assistant", "content": finalAnswer}
		finish := "stop"
		if tool := agentTool(toolNames(req)); !hasToolResult(req) && tool != "" {
			msg = map[string]any{"role": "assistant", "content": nil, "tool_calls": []any{map[string]any{
				"index": 0, "id": "call_suite_1", "type": "function",
				"function": map[string]any{"name": tool, "arguments": `{}`},
			}}}
			finish = "tool_calls"
		}
		usage := map[string]any{"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
		if stream, _ := req["stream"].(bool); !stream {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id": "chatcmpl-suite", "object": "chat.completion", "model": req["model"],
				"choices": []any{map[string]any{"index": 0, "message": msg, "finish_reason": finish}}, "usage": usage,
			})
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		for _, chunk := range []map[string]any{
			{"id": "chatcmpl-suite", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": msg}}},
			{"id": "chatcmpl-suite", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": map[string]any{}, "finish_reason": finish}}},
			{"id": "chatcmpl-suite", "object": "chat.completion.chunk", "choices": []any{}, "usage": usage},
		} {
			b, _ := json.Marshal(chunk)
			_, _ = fmt.Fprintf(w, "data: %s\n\n", b)
		}
		_, _ = fmt.Fprint(w, "data: [DONE]\n\n")
	}))
	t.Cleanup(srv.Close)
	return h.StackURL(srv.URL)
}

func toolNames(req map[string]any) []string {
	var names []string
	tools, _ := req["tools"].([]any)
	for _, tool := range tools {
		fn, _ := tool.(map[string]any)["function"].(map[string]any)
		names = append(names, fmt.Sprint(fn["name"]))
	}
	return names
}

func agentTool(names []string) string {
	for _, n := range names {
		if !slices.Contains(builtins, n) {
			return n
		}
	}
	return ""
}

func hasToolResult(req map[string]any) bool {
	msgs, _ := req["messages"].([]any)
	for _, m := range msgs {
		if mm, _ := m.(map[string]any); mm["role"] == "tool" {
			return true
		}
	}
	return false
}

func (f *fakeHost) seen() (modelCalls, apiCalls int, offered []string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.requests) > 0 {
		offered = toolNames(f.requests[0])
	}
	return len(f.requests), f.apiCalls, offered
}

// answerAPI is the one-operation API the agent's OpenAPI connection calls.
func answerAPI() map[string]any {
	return map[string]any{
		"openapi": "3.0.0",
		"info":    map[string]any{"title": "Answers", "version": "1.0.0"},
		"paths": map[string]any{"/api/answer": map[string]any{"get": map[string]any{
			"operationId": "getAnswer", "summary": "Get the suite answer",
			"responses": map[string]any{"200": map[string]any{"description": "ok"}},
		}}},
	}
}

// taskEvents are the events of a task's events page, by type.
func taskEvents(t *testing.T, body any) (types []string, byType map[string]map[string]any) {
	t.Helper()
	page, _ := body.(map[string]any)
	events, ok := page["events"].([]any)
	if !ok {
		t.Fatalf("events page %v", body)
	}
	byType = map[string]map[string]any{}
	for _, e := range events {
		ev, _ := e.(map[string]any)
		typ, _ := ev["event_type"].(string)
		types = append(types, typ)
		data, _ := ev["data"].(map[string]any)
		byType[typ] = data
	}
	return types, byType
}

// An agent task runs end to end on the stack's serve, worker and events: the
// worker calls the fake provider, calls the OpenAPI tool it asked for, takes
// the final answer as the result, and the task's events record the model and
// tool calls.
func TestAnAgentTaskRunsEndToEnd(t *testing.T) {
	w := h.NewWorkspace(t)
	host := &fakeHost{}
	base := host.serve(t)
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Fake", "api_key": "sk-suite", "endpoint_url": base,
	}).Expect(http.StatusOK).Object()
	inst := w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Fake chat",
	}).Expect(http.StatusOK).Object()
	conn := w.Owner.Post(t, w.Path("/openapi-connections/"), map[string]any{
		"name": "Answers", "base_url": base, "spec_content": answerAPI(),
	}).Expect(http.StatusCreated).Object()
	agent := w.Owner.Post(t, w.Path("/agents/"), map[string]any{
		"name": "E2E", "instruction": "Answer the question.", "model_id": inst["id"],
		"tools": []any{map[string]any{"type": "openapi", "name": "Answers", "settings": map[string]any{"openapi_connection_id": conn["id"]}}},
	}).Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)

	tasks := "/agents/" + agent + "/tasks/"
	task := w.Owner.Post(t, w.Path(tasks+"sync"), map[string]any{
		"description": "What is the suite answer?",
		"task_policy": map[string]any{
			"budget":    map[string]any{"run_budget_usd": "1.00"},
			"tokens":    map[string]any{"max_tokens": 10000, "max_tokens_per_call": 1000},
			"execution": map[string]any{"max_model_turns": 5, "max_tool_calls_per_turn": 2, "max_tool_calls_total": 5},
		},
	}).Expect(http.StatusOK).Object()
	taskID, _ := task["id"].(string)
	if taskID == "" {
		t.Fatalf("no task id in %v", task)
	}

	var final map[string]any
	h.Eventually(t, 90*time.Second, func() error {
		final = w.Owner.Get(t, w.Path(tasks+taskID)).Expect(http.StatusOK).Object()
		switch final["status"] {
		case "completed":
			return nil
		case "failed", "cancelled", "canceled":
			t.Fatalf("task ended %v: %v", final["status"], final)
		}
		calls, _, _ := host.seen()
		return fmt.Errorf("status %v after %d model calls", final["status"], calls)
	})
	modelCalls, apiCalls, offered := host.seen()
	if modelCalls != 2 || apiCalls != 1 {
		t.Fatalf("the provider was called %d times (want 2), the API %d times (want 1); offered %v", modelCalls, apiCalls, offered)
	}
	if !slices.Contains(offered, "completion") || agentTool(offered) == "" {
		t.Fatalf("offered tools %v lack completion or the connection's operation", offered)
	}
	if b, _ := json.Marshal(final); !strings.Contains(string(b), finalAnswer) {
		t.Fatalf("the result is not the model's answer: %s", b)
	}

	types, byType := taskEvents(t, w.Owner.Get(t, w.Path(tasks+taskID+"/events")).Expect(http.StatusOK).JSON())
	for _, want := range []string{"task.started", "llm.call.completed", "tool.call", "tool.result", "task.completed"} {
		if _, ok := byType[want]; !ok {
			t.Fatalf("no %s event in %v", want, types)
		}
	}
	if r := byType["tool.result"]; r["success"] != true || r["source"] != "openapi" || r["tool_name"] != agentTool(offered) ||
		!strings.Contains(fmt.Sprint(r["result"]), "42") {
		t.Fatalf("tool.result %v", r)
	}
	if c := byType["task.completed"]; c["result"] != finalAnswer || c["success"] != true {
		t.Fatalf("task.completed %v", c)
	}

	stream := w.Owner.Stream(t, w.Path(tasks+taskID+"/events/stream"), 20*time.Second)
	stream.Until(15*time.Second, func(e h.Event) bool { return strings.Contains(e.Data, finalAnswer) })
}
