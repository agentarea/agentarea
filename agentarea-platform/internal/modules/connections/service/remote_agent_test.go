package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
)

// remoteOut dials every address directly.
type remoteOut struct{}

func (remoteOut) Transport(netguard.Destination) http.RoundTripper { return http.DefaultTransport }
func (remoteOut) Guard() *netguard.Guard                           { return nil }

type rpcCall struct {
	Method  string
	Params  map[string]any
	Auth    string
	Version string
}

// remoteAgent is an A2A agent: its card, and a JSON-RPC endpoint answering from a script.
type remoteAgent struct {
	srv    *httptest.Server
	mu     sync.Mutex
	card   func(base string) any
	answer func(method string, params map[string]any, n int) (status int, body any)
	calls  []rpcCall
}

func newRemoteAgent(t *testing.T) *remoteAgent {
	t.Helper()
	r := &remoteAgent{}
	r.card = func(base string) any {
		return map[string]any{"name": "Docs", "supportedInterfaces": []any{
			map[string]any{"url": base + "/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
		}}
	}
	r.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if req.Method == http.MethodGet {
			if req.URL.Path != "/a2a/.well-known/agent-card.json" {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			_ = json.NewEncoder(w).Encode(r.card("http://" + req.Host))
			return
		}
		var rpc struct {
			Method string         `json:"method"`
			Params map[string]any `json:"params"`
			ID     any            `json:"id"`
		}
		_ = json.NewDecoder(req.Body).Decode(&rpc)
		r.mu.Lock()
		r.calls = append(r.calls, rpcCall{Method: rpc.Method, Params: rpc.Params, Auth: req.Header.Get("Authorization"), Version: req.Header.Get("A2A-Version")})
		n := len(r.calls)
		r.mu.Unlock()
		status, body := r.answer(rpc.Method, rpc.Params, n)
		w.WriteHeader(status)
		if m, ok := body.(map[string]any); ok && (m["result"] != nil || m["error"] != nil) {
			m["jsonrpc"], m["id"] = "2.0", rpc.ID
		}
		_ = json.NewEncoder(w).Encode(body)
	}))
	t.Cleanup(r.srv.Close)
	return r
}

func (r *remoteAgent) url() string { return r.srv.URL + "/a2a" }

func result(v any) map[string]any { return map[string]any{"result": v} }

func task(state string, extra map[string]any) map[string]any {
	t := map[string]any{"id": "rt1", "contextId": "c1", "status": map[string]any{"state": state}}
	for k, v := range extra {
		t[k] = v
	}
	return t
}

func remoteService(secrets map[string]string) *Service {
	return New(Deps{Stamps: NewStamps(), Verdicts: NewVerdicts(), DB: memDB{}, Secrets: &memSecrets{values: secrets}, Out: remoteOut{}})
}

func remoteCall(url, secret string) api.RemoteAgentCall {
	return api.RemoteAgentCall{WorkspaceID: uuid.NewString(), UserID: "u1", AgentID: uuid.NewString(), AgentName: "Docs",
		ToolName: "delegate_to_Docs", ToolCallID: "call-1", A2AURL: url, AuthSecretName: secret, Message: "write the docs",
		MessageID: "0123456789abcdef0123456789abcdef"}
}

func taskCall(url, secret string, task api.RemoteTask) api.RemoteTaskCall {
	return api.RemoteTaskCall{WorkspaceID: uuid.NewString(), UserID: "u1", AgentName: "Docs", A2AURL: url, AuthSecretName: secret, Task: task}
}

func TestRemoteAgentSendsTheMessageAndLeavesTheRunningTaskPending(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(string, map[string]any, int) (int, any) {
		return 200, result(map[string]any{"task": task("TASK_STATE_WORKING", nil)})
	}
	res, err := remoteService(map[string]string{"remote-key": "tok"}).SendRemoteAgent(context.Background(), remoteCall(r.url(), "remote-key"))
	if err != nil {
		t.Fatal(err)
	}
	want := api.RemoteTask{ID: "rt1", Endpoint: r.srv.URL + "/rpc"}
	if res.Success || res.Raised || res.Pending == nil || *res.Pending != want {
		t.Fatalf("result = %+v", res)
	}
	if len(r.calls) != 1 {
		t.Fatalf("the send waited for the task: %+v", r.calls)
	}
	send := r.calls[0]
	msg, _ := send.Params["message"].(map[string]any)
	parts, _ := msg["parts"].([]any)
	cfg, _ := send.Params["configuration"].(map[string]any)
	if send.Method != "SendMessage" || send.Auth != "Bearer tok" || send.Version != "1.0" || msg["role"] != "ROLE_USER" ||
		msg["messageId"] != "0123456789abcdef0123456789abcdef" || len(parts) != 1 || parts[0].(map[string]any)["text"] != "write the docs" ||
		cfg["returnImmediately"] != true {
		t.Fatalf("send = %+v", send)
	}
}

func TestRemoteAgentSendsOneMessageIDOnEveryAttempt(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(string, map[string]any, int) (int, any) {
		return 200, result(map[string]any{"task": task("TASK_STATE_WORKING", nil)})
	}
	svc := remoteService(nil)
	for range 2 {
		if _, err := svc.SendRemoteAgent(context.Background(), remoteCall(r.url(), "")); err != nil {
			t.Fatal(err)
		}
	}
	first, _ := r.calls[0].Params["message"].(map[string]any)
	second, _ := r.calls[1].Params["message"].(map[string]any)
	if first["messageId"] != second["messageId"] {
		t.Fatalf("message ids %v and %v", first["messageId"], second["messageId"])
	}
	call := remoteCall(r.url(), "")
	call.MessageID = ""
	if _, err := svc.SendRemoteAgent(context.Background(), call); err == nil {
		t.Fatal("a send without a message id went out")
	}
}

func TestRemoteAgentReadsAndCancelsItsTask(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(method string, _ map[string]any, n int) (int, any) {
		switch {
		case method == "CancelTask":
			return 200, result(task("TASK_STATE_CANCELED", nil))
		case n < 2:
			return 200, result(task("TASK_STATE_WORKING", nil))
		}
		return 200, result(task("TASK_STATE_COMPLETED", map[string]any{"artifacts": []any{
			map[string]any{"artifactId": "a1", "parts": []any{map[string]any{"text": "the docs"}, map[string]any{"data": map[string]any{"pages": 3}}}},
		}}))
	}
	svc := remoteService(map[string]string{"remote-key": "tok"})
	ctx := context.Background()
	rt := api.RemoteTask{ID: "rt1", Endpoint: r.srv.URL + "/rpc"}
	res, err := svc.GetRemoteAgentTask(ctx, taskCall(r.url(), "remote-key", rt))
	if err != nil || res.Pending == nil || *res.Pending != rt {
		t.Fatalf("working = %+v %v", res, err)
	}
	res, err = svc.GetRemoteAgentTask(ctx, taskCall(r.url(), "remote-key", rt))
	if err != nil || !res.Success || res.Pending != nil || res.Result != "the docs\n{\"pages\": 3.0}" {
		t.Fatalf("completed = %+v %v", res, err)
	}
	if err := svc.CancelRemoteAgentTask(ctx, taskCall(r.url(), "remote-key", rt)); err != nil {
		t.Fatal(err)
	}
	for i, want := range []string{"GetTask", "GetTask", "CancelTask"} {
		if c := r.calls[i]; c.Method != want || c.Params["id"] != "rt1" || c.Auth != "Bearer tok" || c.Version != "1.0" {
			t.Fatalf("call %d = %+v, want %s", i, c, want)
		}
	}
}

func TestRemoteAgentKeepsWaitingThroughAnOutage(t *testing.T) {
	for _, c := range []struct {
		name    string
		status  int
		body    any
		pending bool
		want    string
	}{
		{"unavailable", 503, map[string]any{}, true, ""},
		{"throttled", 429, map[string]any{}, true, ""},
		{"gone", 404, map[string]any{}, false, "A2A request failed with HTTP 404"},
		{"not found", 200, map[string]any{"error": map[string]any{"code": -32001, "message": "Task not found"}}, false, "Task not found"},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := newRemoteAgent(t)
			r.answer = func(string, map[string]any, int) (int, any) { return c.status, c.body }
			rt := api.RemoteTask{ID: "rt1", Endpoint: r.srv.URL + "/rpc"}
			res, err := remoteService(nil).GetRemoteAgentTask(context.Background(), taskCall(r.url(), "", rt))
			if err != nil || (res.Pending != nil) != c.pending || res.Error != c.want || res.Success {
				t.Fatalf("result = %+v %v", res, err)
			}
		})
	}
}

func TestRemoteAgentTaskMustLiveOnTheAgentsOrigin(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(string, map[string]any, int) (int, any) { return 200, result(task("TASK_STATE_COMPLETED", nil)) }
	svc := remoteService(nil)
	rt := api.RemoteTask{ID: "rt1", Endpoint: "http://elsewhere.test/rpc"}
	res, err := svc.GetRemoteAgentTask(context.Background(), taskCall(r.url(), "", rt))
	if err != nil || !res.Raised || !strings.HasPrefix(res.Error, "The task of 'Docs' is not on ") {
		t.Fatalf("result = %+v %v", res, err)
	}
	if err := svc.CancelRemoteAgentTask(context.Background(), taskCall(r.url(), "", rt)); err == nil {
		t.Fatal("cancelled a task off the agent's origin")
	}
	if len(r.calls) != 0 {
		t.Fatalf("calls reached the agent: %+v", r.calls)
	}
}

func TestRemoteAgentAnswersWithAMessage(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(string, map[string]any, int) (int, any) {
		return 200, result(map[string]any{"message": map[string]any{"messageId": "m1", "role": "ROLE_AGENT", "parts": []any{
			map[string]any{"text": "hi"}, map[string]any{"text": "there"}}}})
	}
	res, err := remoteService(nil).SendRemoteAgent(context.Background(), remoteCall(r.url(), ""))
	if err != nil || !res.Success || res.Result != "hi\nthere" || r.calls[0].Auth != "" {
		t.Fatalf("result = %+v %v, auth %q", res, err, r.calls[0].Auth)
	}
}

func TestRemoteAgentSpeaksA2A03ToALegacyCard(t *testing.T) {
	r := newRemoteAgent(t)
	r.card = func(base string) any {
		return map[string]any{"name": "Docs", "url": base + "/rpc", "protocolVersion": "0.3.0"}
	}
	r.answer = func(method string, _ map[string]any, _ int) (int, any) {
		if method == "message/send" {
			return 200, result(map[string]any{"kind": "task", "id": "rt1", "contextId": "c1", "status": map[string]any{"state": "working"}})
		}
		return 200, result(map[string]any{"kind": "task", "id": "rt1", "contextId": "c1",
			"status": map[string]any{"state": "completed", "message": map[string]any{"kind": "message", "messageId": "m", "role": "agent",
				"parts": []any{map[string]any{"kind": "text", "text": "done"}}}}})
	}
	svc := remoteService(nil)
	res, err := svc.SendRemoteAgent(context.Background(), remoteCall(r.url(), ""))
	if err != nil || res.Pending == nil || !res.Pending.Legacy {
		t.Fatalf("send = %+v %v", res, err)
	}
	res, err = svc.GetRemoteAgentTask(context.Background(), taskCall(r.url(), "", *res.Pending))
	if err != nil || !res.Success || res.Result != "done" {
		t.Fatalf("result = %+v %v", res, err)
	}
	if err := svc.CancelRemoteAgentTask(context.Background(), taskCall(r.url(), "", api.RemoteTask{ID: "rt1", Endpoint: r.srv.URL + "/rpc", Legacy: true})); err != nil {
		t.Fatal(err)
	}
	send := r.calls[0]
	msg, _ := send.Params["message"].(map[string]any)
	parts, _ := msg["parts"].([]any)
	cfg, _ := send.Params["configuration"].(map[string]any)
	if send.Version != "0.3" || msg["kind"] != "message" || msg["role"] != "user" || parts[0].(map[string]any)["kind"] != "text" ||
		cfg["blocking"] != false {
		t.Fatalf("send = %+v", send)
	}
	if get := r.calls[1]; get.Method != "tasks/get" || get.Params["id"] != "rt1" || get.Version != "0.3" {
		t.Fatalf("poll = %+v", get)
	}
	if cancel := r.calls[2]; cancel.Method != "tasks/cancel" || cancel.Params["id"] != "rt1" {
		t.Fatalf("cancel = %+v", cancel)
	}
}

func TestRemoteAgentOutcomes(t *testing.T) {
	for _, c := range []struct {
		name   string
		answer func(string, map[string]any, int) (int, any)
		want   api.RemoteAgentResult
	}{
		{"failed", func(string, map[string]any, int) (int, any) {
			return 200, result(map[string]any{"task": task("TASK_STATE_FAILED", map[string]any{"status": map[string]any{"state": "TASK_STATE_FAILED",
				"message": map[string]any{"messageId": "m", "role": "ROLE_AGENT", "parts": []any{map[string]any{"text": "boom"}}}}})})
		}, api.RemoteAgentResult{Error: "'Docs' ended the task as TASK_STATE_FAILED: boom"}},
		{"input required", func(string, map[string]any, int) (int, any) {
			return 200, result(map[string]any{"task": task("TASK_STATE_INPUT_REQUIRED", nil)})
		}, api.RemoteAgentResult{Error: "'Docs' stopped at TASK_STATE_INPUT_REQUIRED on task rt1: (No output from agent)"}},
		{"rpc error", func(string, map[string]any, int) (int, any) {
			return 200, map[string]any{"error": map[string]any{"code": -32001, "message": "Task not found"}}
		}, api.RemoteAgentResult{Error: "Task not found"}},
		{"unknown rpc error", func(string, map[string]any, int) (int, any) {
			return 200, map[string]any{"error": map[string]any{"code": 7, "message": "odd"}}
		}, api.RemoteAgentResult{Error: "JSON-RPC Error 7: odd"}},
		{"http error", func(string, map[string]any, int) (int, any) {
			return 500, map[string]any{}
		}, api.RemoteAgentResult{Error: "A2A request failed with HTTP 500", Raised: true}},
		{"unpaid", func(string, map[string]any, int) (int, any) {
			return 402, map[string]any{}
		}, api.RemoteAgentResult{Error: "A2A request failed with HTTP 402", Raised: true}},
		{"neither", func(string, map[string]any, int) (int, any) {
			return 200, result(map[string]any{})
		}, api.RemoteAgentResult{Error: "Response has neither task nor message", Raised: true}},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := newRemoteAgent(t)
			r.answer = c.answer
			res, err := remoteService(nil).SendRemoteAgent(context.Background(), remoteCall(r.url(), ""))
			if err != nil || res.Success != c.want.Success || res.Error != c.want.Error || res.Raised != c.want.Raised {
				t.Fatalf("result = %+v %v, want %+v", res, err, c.want)
			}
		})
	}
}

func TestRemoteAgentRefusals(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(string, map[string]any, int) (int, any) {
		return 200, result(map[string]any{"task": task("TASK_STATE_COMPLETED", nil)})
	}
	svc := remoteService(nil)
	ctx := context.Background()

	res, err := svc.SendRemoteAgent(ctx, remoteCall(r.url(), "remote-key"))
	if err != nil || !res.Raised || res.Error != "Could not resolve the credential for 'Docs': secret 'remote-key' not found in this workspace" {
		t.Fatalf("missing secret = %+v %v", res, err)
	}
	call := remoteCall(r.url(), "")
	call.Message = ""
	if res, _ := svc.SendRemoteAgent(ctx, call); !res.Raised || res.Error != "message is required" {
		t.Fatalf("no message = %+v", res)
	}
	r.card = func(string) any {
		return map[string]any{"supportedInterfaces": []any{map[string]any{"url": "http://elsewhere.test/rpc", "protocolBinding": "JSONRPC"}}}
	}
	res, _ = svc.SendRemoteAgent(ctx, remoteCall(r.url(), ""))
	want := "The card of 'Docs' names no endpoint on " + strings.ToLower(r.srv.URL) + ": http://elsewhere.test/rpc"
	if !res.Raised || res.Error != want {
		t.Fatalf("foreign endpoint = %+v, want %q", res, want)
	}
	r.card = func(base string) any {
		return map[string]any{"supportedInterfaces": []any{map[string]any{"url": base + "/rpc", "protocolBinding": "GRPC"}}}
	}
	if res, _ := svc.SendRemoteAgent(ctx, remoteCall(r.url(), "")); !res.Raised || res.Error != "no compatible transports found." {
		t.Fatalf("no JSON-RPC interface = %+v", res)
	}
	if len(r.calls) != 0 {
		t.Fatalf("refused calls reached the agent: %+v", r.calls)
	}
	res, _ = svc.SendRemoteAgent(ctx, remoteCall(r.srv.URL+"/missing", ""))
	if !res.Raised || !strings.HasPrefix(res.Error, "Could not read the agent card of 'Docs': Failed to fetch agent card from "+r.srv.URL+"/missing/.well-known/agent-card.json (HTTP 404)") {
		t.Fatalf("no card = %+v", res)
	}
}
