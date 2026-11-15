//go:build suite

package agents

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

// The suite catalog's provider and chat model (test/suite/models/seed.sql).
const (
	suiteProvider = "5e1f0000-0000-4000-8000-000000000001"
	suiteChat     = "5e1f0000-0000-4000-8000-000000000002"
	suiteAnswer   = "The A2A answer is 42."
)

// fakeModel is an OpenAI-compatible provider that answers every call with
// suiteAnswer, or holds the call until release when hold is set.
type fakeModel struct {
	mu      sync.Mutex
	hold    bool
	release chan struct{}
	calls   int
}

func (f *fakeModel) serve(t *testing.T) string {
	t.Helper()
	f.release = make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !strings.HasSuffix(r.URL.Path, "/chat/completions") {
			http.Error(w, "not a chat completion", http.StatusBadRequest)
			return
		}
		f.mu.Lock()
		f.calls++
		hold := f.hold
		f.mu.Unlock()
		if hold {
			select {
			case <-f.release:
			case <-r.Context().Done():
				return
			}
		}
		usage := map[string]any{"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
		msg := map[string]any{"role": "assistant", "content": suiteAnswer}
		if stream, _ := req["stream"].(bool); !stream {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id": "chatcmpl-a2a", "object": "chat.completion", "model": req["model"],
				"choices": []any{map[string]any{"index": 0, "message": msg, "finish_reason": "stop"}}, "usage": usage,
			})
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		for _, chunk := range []map[string]any{
			{"id": "chatcmpl-a2a", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": msg}}},
			{"id": "chatcmpl-a2a", "object": "chat.completion.chunk", "choices": []any{map[string]any{"index": 0, "delta": map[string]any{}, "finish_reason": "stop"}}},
			{"id": "chatcmpl-a2a", "object": "chat.completion.chunk", "choices": []any{}, "usage": usage},
		} {
			b, _ := json.Marshal(chunk)
			_, _ = fmt.Fprintf(w, "data: %s\n\n", b)
		}
		_, _ = fmt.Fprint(w, "data: [DONE]\n\n")
	}))
	t.Cleanup(srv.Close)
	return srv.URL
}

func (f *fakeModel) holding(on bool) {
	f.mu.Lock()
	f.hold = on
	f.mu.Unlock()
}

// modelAgent is an agent whose model is the fake provider.
func modelAgent(t *testing.T, w *h.Workspace, f *fakeModel) string {
	t.Helper()
	base := f.serve(t)
	cfg := w.Owner.Post(t, w.Path("/provider-configs/"), map[string]any{
		"provider_spec_id": suiteProvider, "name": "Fake", "api_key": "sk-suite", "endpoint_url": base,
	}).Expect(http.StatusOK).Object()
	inst := w.Owner.Post(t, w.Path("/model-instances/"), map[string]any{
		"provider_config_id": cfg["id"], "model_spec_id": suiteChat, "name": "Fake chat",
	}).Expect(http.StatusOK).Object()
	return create(t, w.Owner, w, map[string]any{"name": "A2A", "instruction": "Answer.", "model_id": inst["id"], "tools": []any{}})["id"].(string)
}

func sendBody(id any, method, text string, extra map[string]any) map[string]any {
	params := map[string]any{"message": map[string]any{
		"messageId": "m-" + fmt.Sprint(id), "role": "ROLE_USER", "parts": []any{map[string]any{"text": text}},
	}}
	for k, v := range extra {
		params[k] = v
	}
	return map[string]any{"jsonrpc": "2.0", "id": id, "method": method, "params": params}
}

func rpcResult(t *testing.T, c *h.Client, agent string, body any) map[string]any {
	t.Helper()
	got := a2aRPC(t, c, agent, "1.0", body).Expect(http.StatusOK).Object()
	if got["error"] != nil {
		t.Fatalf("rpc error: %v", got["error"])
	}
	res, _ := got["result"].(map[string]any)
	return res
}

func taskState(task map[string]any) string {
	status, _ := task["status"].(map[string]any)
	state, _ := status["state"].(string)
	return state
}

func getTask(t *testing.T, c *h.Client, agent, id string) map[string]any {
	t.Helper()
	return rpcResult(t, c, agent, map[string]any{"jsonrpc": "2.0", "id": "g", "method": "GetTask", "params": map[string]any{"id": id}})
}

func waitState(t *testing.T, c *h.Client, agent, id, want string) map[string]any {
	t.Helper()
	var task map[string]any
	h.Eventually(t, 90*time.Second, func() error {
		task = getTask(t, c, agent, id)
		if taskState(task) != want {
			return fmt.Errorf("state %s, want %s", taskState(task), want)
		}
		return nil
	})
	return task
}

func answerOf(task map[string]any) string {
	arts, _ := task["artifacts"].([]any)
	if len(arts) == 0 {
		return ""
	}
	parts, _ := arts[0].(map[string]any)["parts"].([]any)
	if len(parts) == 0 {
		return ""
	}
	text, _ := parts[0].(map[string]any)["text"].(string)
	return text
}

func TestA2ASendMessageStartsARunGetTaskReadsIt(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := modelAgent(t, w, &fakeModel{})
	sent := rpcResult(t, w.Owner, agent, sendBody(1, "SendMessage", "What is the answer?", map[string]any{"metadata": map[string]any{"requires_human_approval": false}}))
	task, _ := sent["task"].(map[string]any)
	id, _ := task["id"].(string)
	if id == "" || task["contextId"] != id {
		t.Fatalf("send answered %v", sent)
	}
	run := w.Owner.Get(t, w.Path("/agents/"+agent+"/tasks/"+id)).Expect(http.StatusOK).Object()
	if run["agent_id"] != agent {
		t.Fatalf("the A2A task is an ordinary run of the agent: %v", run)
	}
	done := waitState(t, w.Owner, agent, id, "TASK_STATE_COMPLETED")
	if answerOf(done) != suiteAnswer {
		t.Fatalf("artifact %q in %v", answerOf(done), done)
	}
	md, _ := done["metadata"].(map[string]any)
	if md["source"] != "a2a" || md["created_via"] != "a2a_protocol" {
		t.Fatalf("task metadata %v", md)
	}
	listed := rpcResult(t, w.Owner, agent, map[string]any{"jsonrpc": "2.0", "id": "l", "method": "ListTasks", "params": map[string]any{"pageSize": 10}})
	if tasks, _ := listed["tasks"].([]any); len(tasks) != 1 || fmt.Sprint(listed["totalSize"]) != "1" {
		t.Fatalf("list %v", listed)
	}
}

func TestA2AContextIDIsKept(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := modelAgent(t, w, &fakeModel{})
	body := sendBody(2, "SendMessage", "Hello", nil)
	body["params"].(map[string]any)["message"].(map[string]any)["contextId"] = "ctx-1"
	task, _ := rpcResult(t, w.Owner, agent, body)["task"].(map[string]any)
	if task["contextId"] != "ctx-1" {
		t.Fatalf("%v", task)
	}
}

func TestA2ARefusesAnEmptyMessageAndUnknownTasks(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := modelAgent(t, w, &fakeModel{})
	got := a2aRPC(t, w.Owner, agent, "1.0", sendBody(3, "SendMessage", "   ", nil)).Expect(http.StatusOK).Object()
	if e, _ := got["error"].(map[string]any); fmt.Sprint(e["code"]) != "-32602" || e["message"] != "Message must contain non-empty text content" {
		t.Fatalf("%v", got)
	}
	got = a2aRPC(t, w.Owner, agent, "1.0", map[string]any{"jsonrpc": "2.0", "id": 4, "method": "SendMessage", "params": map[string]any{}}).Expect(http.StatusOK).Object()
	if e, _ := got["error"].(map[string]any); fmt.Sprint(e["code"]) != "-32602" || e["message"] != "Validation failed" {
		t.Fatalf("%v", got)
	}
	got = a2aRPC(t, w.Owner, agent, "1.0", map[string]any{"jsonrpc": "2.0", "id": 5, "method": "GetTask", "params": map[string]any{"id": "00000000-0000-4000-8000-000000000000"}}).Expect(http.StatusOK).Object()
	if e, _ := got["error"].(map[string]any); fmt.Sprint(e["code"]) != "-32001" {
		t.Fatalf("%v", got)
	}
}

func TestA2ACancelTask(t *testing.T) {
	w := h.NewWorkspace(t)
	f := &fakeModel{}
	agent := modelAgent(t, w, f)
	f.holding(true)
	task, _ := rpcResult(t, w.Owner, agent, sendBody(6, "SendMessage", "Take your time", nil))["task"].(map[string]any)
	id := task["id"].(string)
	w.Member.Do(t, h.Request{Method: http.MethodPost, Path: "/v1/agents/" + agent + "/a2a/rpc", Body: map[string]any{
		"jsonrpc": "2.0", "id": 7, "method": "CancelTask", "params": map[string]any{"id": id}}, Header: http.Header{"A2A-Version": {"1.0"}}}).
		Expect(http.StatusForbidden).Match(h.Problem(http.StatusForbidden, "http_error", "Only a workspace admin may perform this action"))
	cancelled := rpcResult(t, w.Owner, agent, map[string]any{"jsonrpc": "2.0", "id": 8, "method": "CancelTask", "params": map[string]any{"id": id}})
	if taskState(cancelled) != "TASK_STATE_CANCELED" {
		t.Fatalf("%v", cancelled)
	}
	got := a2aRPC(t, w.Owner, agent, "1.0", map[string]any{"jsonrpc": "2.0", "id": 9, "method": "CancelTask", "params": map[string]any{"id": id}}).Expect(http.StatusOK).Object()
	if e, _ := got["error"].(map[string]any); fmt.Sprint(e["code"]) != "-32002" {
		t.Fatalf("a task that ended cannot be cancelled again: %v", got)
	}
	close(f.release)
}

func sseData(t *testing.T, body []byte) []map[string]any {
	t.Helper()
	var out []map[string]any
	for _, line := range strings.Split(string(body), "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &m); err != nil {
			t.Fatalf("frame %q: %v", line, err)
		}
		out = append(out, m)
	}
	return out
}

func TestA2AMessageStreamEndsWithTheAnswer(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := modelAgent(t, w, &fakeModel{})
	resp := a2aRPC(t, w.Owner, agent, "1.0", sendBody(10, "SendStreamingMessage", "Stream it", nil)).Expect(http.StatusOK)
	if ct := resp.ContentType(); ct != "text/event-stream" {
		t.Fatalf("content-type %q: %s", ct, resp.Body)
	}
	frames := sseData(t, resp.Body)
	if len(frames) < 2 {
		t.Fatalf("frames %v in %s", frames, resp.Body)
	}
	first, _ := frames[0]["result"].(map[string]any)
	task, _ := first["task"].(map[string]any)
	if fmt.Sprint(frames[0]["id"]) != "10" || task["id"] == nil {
		t.Fatalf("the stream opens with the task: %v", frames[0])
	}
	last, _ := frames[len(frames)-1]["result"].(map[string]any)
	status, _ := last["statusUpdate"].(map[string]any)["status"].(map[string]any)
	if status["state"] != "TASK_STATE_COMPLETED" {
		t.Fatalf("the stream ends with the terminal status: %v", frames[len(frames)-1])
	}
	var answered bool
	for _, f := range frames {
		res, _ := f["result"].(map[string]any)
		if art, ok := res["artifactUpdate"].(map[string]any); ok && strings.Contains(fmt.Sprint(art["artifact"]), suiteAnswer) {
			answered = true
		}
	}
	if !answered {
		t.Fatalf("no artifact carries the answer: %s", resp.Body)
	}
	w.Anonymous.Do(t, h.Request{Method: http.MethodPost, Path: "/v1/agents/" + agent + "/a2a/rpc", Body: sendBody(11, "SendStreamingMessage", "x", nil)}).
		Expect(http.StatusUnauthorized)
}

func TestA2APushNotificationConfigs(t *testing.T) {
	w := h.NewWorkspace(t)
	f := &fakeModel{}
	agent := modelAgent(t, w, f)
	f.holding(true)
	task, _ := rpcResult(t, w.Owner, agent, sendBody(12, "SendMessage", "Hold on", nil))["task"].(map[string]any)
	id := task["id"].(string)
	call := func(method string, params map[string]any) map[string]any {
		return a2aRPC(t, w.Owner, agent, "1.0", map[string]any{"jsonrpc": "2.0", "id": method, "method": method, "params": params}).Expect(http.StatusOK).Object()
	}
	created := call("CreateTaskPushNotificationConfig", map[string]any{"taskId": id, "id": "c1", "url": "https://93.184.216.34/a2a", "token": "s3cret"})
	res, _ := created["result"].(map[string]any)
	if res["id"] != "c1" || res["taskId"] != id || res["url"] != "https://93.184.216.34/a2a" || res["token"] != nil {
		t.Fatalf("create %v", created)
	}
	if got, _ := call("GetTaskPushNotificationConfig", map[string]any{"taskId": id, "id": "c1"})["result"].(map[string]any); got["url"] != "https://93.184.216.34/a2a" {
		t.Fatalf("get %v", got)
	}
	list, _ := call("ListTaskPushNotificationConfigs", map[string]any{"taskId": id})["result"].(map[string]any)
	if configs, _ := list["configs"].([]any); len(configs) != 1 {
		t.Fatalf("list %v", list)
	}
	if deleted := call("DeleteTaskPushNotificationConfig", map[string]any{"taskId": id, "id": "c1"}); deleted["result"] != nil || deleted["error"] != nil {
		t.Fatalf("delete %v", deleted)
	}
	list, _ = call("ListTaskPushNotificationConfigs", map[string]any{"taskId": id})["result"].(map[string]any)
	if list["configs"] != nil {
		t.Fatalf("list after delete %v", list)
	}
	close(f.release)
}

func TestA2APersonalKeyNeedsInvokeOnTheAgent(t *testing.T) {
	w := h.NewWorkspace(t)
	agent := modelAgent(t, w, &fakeModel{})
	var key struct {
		Token string `json:"token"`
	}
	w.Member.Post(t, w.Path("/api-keys/"), map[string]any{"name": "member's"}).Expect(http.StatusCreated).Decode(&key)
	personal := h.Bearer(t, "member key", key.Token)
	for _, c := range []*h.Client{w.Member, personal} {
		a2aRPC(t, c, agent, "1.0", sendBody(10, "SendMessage", "Start without invoke", nil)).Expect(http.StatusForbidden)
	}
	if runs := w.Owner.Get(t, w.Path("/tasks/")).Expect(http.StatusOK).Array(); len(runs) != 0 {
		t.Fatalf("a member without invoke started %d runs", len(runs))
	}
}
