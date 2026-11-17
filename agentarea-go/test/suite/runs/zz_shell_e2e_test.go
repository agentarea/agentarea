//go:build suite

package runs

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestShellToolRunsInTheSandbox(t *testing.T) {
	w := h.NewWorkspace(t)
	var mu sync.Mutex
	var offered []string
	srv := httptest.NewServer(http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(rw, "bad", http.StatusBadRequest)
			return
		}
		mu.Lock()
		if offered == nil {
			offered = toolNames(req)
		}
		mu.Unlock()
		msg := map[string]any{"role": "assistant", "content": "done"}
		finish := "stop"
		if tool := agentTool(toolNames(req)); !hasToolResult(req) && tool != "" {
			msg = map[string]any{"role": "assistant", "content": nil, "tool_calls": []any{map[string]any{
				"index": 0, "id": "call_shell_1", "type": "function",
				"function": map[string]any{"name": tool, "arguments": `{"command":"echo shell-$((6*7)) && uname -s"}`},
			}}}
			finish = "tool_calls"
		}
		usage := map[string]any{"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
		if stream, _ := req["stream"].(bool); !stream {
			rw.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(rw).Encode(map[string]any{"id": "c", "object": "chat.completion", "model": req["model"],
				"choices": []any{map[string]any{"index": 0, "message": msg, "finish_reason": finish}}, "usage": usage})
			return
		}
		rw.Header().Set("Content-Type", "text/event-stream")
		for _, chunk := range []map[string]any{
			{"id": "c", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": msg}}},
			{"id": "c", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": map[string]any{}, "finish_reason": finish}}},
			{"id": "c", "object": "chat.completion.chunk", "choices": []any{}, "usage": usage},
		} {
			b, _ := json.Marshal(chunk)
			_, _ = fmt.Fprintf(rw, "data: %s\n\n", b)
		}
		_, _ = fmt.Fprint(rw, "data: [DONE]\n\n")
	}))
	t.Cleanup(srv.Close)

	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Fake", "api_key": "sk-suite", "endpoint_url": h.StackURL(srv.URL),
	}).Expect(http.StatusOK).Object()
	inst := w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Fake chat",
	}).Expect(http.StatusOK).Object()
	agent := w.Owner.Post(t, w.Path("/agents/"), map[string]any{
		"name": "Shell", "instruction": "Run the command.", "model_id": inst["id"],
		"tools": []any{map[string]any{"type": "code", "name": "agentarea/shell", "settings": map[string]any{"requires_user_confirmation": false}}},
	}).Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)

	tasks := "/agents/" + agent + "/tasks/"
	task := w.Owner.Post(t, w.Path(tasks+"sync"), map[string]any{
		"description": "Run the shell command.",
		"task_policy": map[string]any{
			"budget":    map[string]any{"run_budget_usd": "1.00"},
			"tokens":    map[string]any{"max_tokens": 10000, "max_tokens_per_call": 1000},
			"execution": map[string]any{"max_model_turns": 5, "max_tool_calls_per_turn": 2, "max_tool_calls_total": 5},
		},
	}).Expect(http.StatusOK).Object()
	taskID, _ := task["id"].(string)

	var final map[string]any
	h.Eventually(t, 180*time.Second, func() error {
		final = w.Owner.Get(t, w.Path(tasks+taskID)).Expect(http.StatusOK).Object()
		switch final["status"] {
		case "completed":
			return nil
		case "failed", "cancelled", "canceled":
			t.Fatalf("task ended %v: %v", final["status"], final)
		}
		return fmt.Errorf("status %v", final["status"])
	})
	types, byType := taskEvents(t, w.Owner.Get(t, w.Path(tasks+taskID+"/events")).Expect(http.StatusOK).JSON())
	if rt := byType["runtime.discovered"]; rt["error"] != nil {
		t.Skipf("the stack serves no sandbox: %v", rt["error"])
	}
	r, ok := byType["tool.result"]
	b, _ := json.Marshal(r)
	t.Logf("offered %v; events %v; tool.result %s", offered, types, b)
	if !ok || r["success"] != true || !strings.Contains(fmt.Sprint(r["result"]), "shell-42") || !strings.Contains(fmt.Sprint(r["result"]), "Linux") {
		t.Fatalf("tool.result %s", b)
	}
}
