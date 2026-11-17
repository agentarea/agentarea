//go:build suite

package streams

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

// The suite catalog's provider and chat model (test/suite/models/seed.sql).
const (
	suiteProvider = "5e1f0000-0000-4000-8000-000000000001"
	suiteChat     = "5e1f0000-0000-4000-8000-000000000002"
	webhookAnswer = "The webhook answer is 42."
	webhookSecret = "suite-task-webhook-secret-0123456789abcdef"
)

type webhookCall struct {
	header http.Header
	body   []byte
}

// replyHost is the run's outside world on the host: a chat model that answers in text, and the
// caller's task webhook.
type replyHost struct {
	mu    sync.Mutex
	calls []webhookCall
}

func (r *replyHost) serve(t *testing.T) string {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Path == "/hook" {
			b, _ := io.ReadAll(req.Body)
			r.mu.Lock()
			r.calls = append(r.calls, webhookCall{header: req.Header.Clone(), body: b})
			r.mu.Unlock()
			w.WriteHeader(http.StatusNoContent)
			return
		}
		var body map[string]any
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || !strings.HasSuffix(req.URL.Path, "/chat/completions") {
			http.Error(w, "not a chat completion", http.StatusBadRequest)
			return
		}
		msg := map[string]any{"role": "assistant", "content": webhookAnswer}
		usage := map[string]any{"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
		if stream, _ := body["stream"].(bool); !stream {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id": "chatcmpl-suite", "object": "chat.completion", "model": body["model"],
				"choices": []any{map[string]any{"index": 0, "message": msg, "finish_reason": "stop"}}, "usage": usage,
			})
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		for _, chunk := range []map[string]any{
			{"id": "chatcmpl-suite", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": msg}}},
			{"id": "chatcmpl-suite", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": map[string]any{}, "finish_reason": "stop"}}},
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

func (r *replyHost) webhooks() []webhookCall {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]webhookCall(nil), r.calls...)
}

// A task an API caller started with a webhook ends with one signed POST of its outcome to the
// webhook (the events role's delivery group on tasks.events).
func TestTaskWebhookIsCalledWhenTheTaskCompletes(t *testing.T) {
	w := h.NewWorkspace(t)
	host := &replyHost{}
	base := host.serve(t)
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Fake", "api_key": "sk-suite", "endpoint_url": base,
	}).Expect(http.StatusOK).Object()
	inst := w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Fake chat",
	}).Expect(http.StatusOK).Object()
	agent := w.Owner.Post(t, w.Path("/agents/"), map[string]any{
		"name": "Webhook", "instruction": "Answer the question.", "model_id": inst["id"], "tools": []any{},
	}).Expect(http.StatusOK, http.StatusCreated).Object()["id"].(string)

	api := w.APIKey(t)
	tasks := "/agents/" + agent + "/tasks/"
	task := api.Post(t, w.Path(tasks+"sync"), map[string]any{
		"description": "What is the webhook answer?",
		"end_user_id": "end-user-1",
		"metadata":    map[string]any{"order": "o-1"},
		"webhook":     map[string]any{"url": base + "/hook", "secret": webhookSecret},
		"task_policy": map[string]any{
			"budget":    map[string]any{"run_budget_usd": "1.00"},
			"tokens":    map[string]any{"max_tokens": 10000, "max_tokens_per_call": 1000},
			"execution": map[string]any{"max_model_turns": 3},
		},
	}).Expect(http.StatusOK, http.StatusCreated).Object()
	taskID, _ := task["id"].(string)
	if taskID == "" {
		t.Fatalf("no task id in %v", task)
	}

	var call webhookCall
	h.Eventually(t, 90*time.Second, func() error {
		calls := host.webhooks()
		if len(calls) == 0 {
			status := api.Get(t, w.Path(tasks+taskID)).Expect(http.StatusOK).Object()["status"]
			if status == "failed" || status == "cancelled" {
				t.Fatalf("task ended %v", status)
			}
			return fmt.Errorf("no webhook call yet; task %v", status)
		}
		call = calls[0]
		return nil
	})
	if call.header.Get("X-AgentArea-Event") != "task.completed" || call.header.Get("X-AgentArea-Delivery") == "" ||
		call.header.Get("Content-Type") != "application/json" {
		t.Fatalf("webhook headers %v", call.header)
	}
	sig := call.header.Get("X-AgentArea-Signature")
	ts, mac, ok := strings.Cut(strings.TrimPrefix(sig, "t="), ",v1=")
	if !ok {
		t.Fatalf("signature %q", sig)
	}
	m := hmac.New(sha256.New, []byte(webhookSecret))
	m.Write([]byte(ts + "."))
	m.Write(call.body)
	if want := hex.EncodeToString(m.Sum(nil)); !hmac.Equal([]byte(mac), []byte(want)) {
		t.Fatalf("signature %q does not sign the body", sig)
	}
	var body map[string]any
	if err := json.Unmarshal(call.body, &body); err != nil {
		t.Fatalf("webhook body %s: %v", call.body, err)
	}
	if body["version"] != "1" || body["type"] != "task.completed" || body["status"] != "completed" || body["task_id"] != taskID ||
		body["agent_id"] != agent || body["result"] != webhookAnswer || body["end_user_id"] != "end-user-1" ||
		fmt.Sprint(body["metadata"]) != "map[order:o-1]" {
		t.Fatalf("webhook body %s", call.body)
	}
	h.Never(t, 3*time.Second, func() error {
		if n := len(host.webhooks()); n != 1 {
			return fmt.Errorf("the webhook was called %d times", n)
		}
		return nil
	})
}
