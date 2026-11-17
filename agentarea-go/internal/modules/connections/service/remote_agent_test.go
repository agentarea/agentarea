package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
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
	return New(Deps{DB: memDB{}, Secrets: &memSecrets{values: secrets}, Out: remoteOut{}})
}

func remoteCall(url, secret string) api.RemoteAgentCall {
	return api.RemoteAgentCall{WorkspaceID: uuid.NewString(), UserID: "u1", AgentID: uuid.NewString(), AgentName: "Docs",
		ToolName: "delegate_to_Docs", ToolCallID: "call-1", A2AURL: url, AuthSecretName: secret, Message: "write the docs"}
}

var fastPoll = a2aPolling{every: time.Millisecond, budget: 50 * time.Millisecond}

func TestRemoteAgentSendsTheMessageAndPollsTheTask(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(method string, _ map[string]any, n int) (int, any) {
		if method == "SendMessage" {
			return 200, result(map[string]any{"task": task("TASK_STATE_WORKING", nil)})
		}
		if n < 3 {
			return 200, result(task("TASK_STATE_WORKING", nil))
		}
		return 200, result(task("TASK_STATE_COMPLETED", map[string]any{"artifacts": []any{
			map[string]any{"artifactId": "a1", "parts": []any{map[string]any{"text": "the docs"}, map[string]any{"data": map[string]any{"pages": 3}}}},
		}}))
	}
	res, err := remoteService(map[string]string{"remote-key": "tok"}).callRemoteAgent(context.Background(), remoteCall(r.url(), "remote-key"), fastPoll)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Success || res.Raised || res.Result != "the docs\n{\"pages\": 3.0}" {
		t.Fatalf("result = %+v", res)
	}
	send := r.calls[0]
	msg, _ := send.Params["message"].(map[string]any)
	parts, _ := msg["parts"].([]any)
	cfg, _ := send.Params["configuration"].(map[string]any)
	if send.Method != "SendMessage" || send.Auth != "Bearer tok" || send.Version != "1.0" || msg["role"] != "ROLE_USER" ||
		len(msg["messageId"].(string)) != 32 || len(parts) != 1 || parts[0].(map[string]any)["text"] != "write the docs" ||
		cfg["returnImmediately"] != true {
		t.Fatalf("send = %+v", send)
	}
	if get := r.calls[1]; get.Method != "GetTask" || get.Params["id"] != "rt1" || get.Auth != "Bearer tok" {
		t.Fatalf("poll = %+v", get)
	}
}

func TestRemoteAgentAnswersWithAMessage(t *testing.T) {
	r := newRemoteAgent(t)
	r.answer = func(string, map[string]any, int) (int, any) {
		return 200, result(map[string]any{"message": map[string]any{"messageId": "m1", "role": "ROLE_AGENT", "parts": []any{
			map[string]any{"text": "hi"}, map[string]any{"text": "there"}}}})
	}
	res, err := remoteService(nil).callRemoteAgent(context.Background(), remoteCall(r.url(), ""), fastPoll)
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
	res, err := remoteService(nil).callRemoteAgent(context.Background(), remoteCall(r.url(), ""), fastPoll)
	if err != nil || !res.Success || res.Result != "done" {
		t.Fatalf("result = %+v %v", res, err)
	}
	send := r.calls[0]
	msg, _ := send.Params["message"].(map[string]any)
	parts, _ := msg["parts"].([]any)
	cfg, _ := send.Params["configuration"].(map[string]any)
	if send.Version != "0.3" || msg["kind"] != "message" || msg["role"] != "user" || parts[0].(map[string]any)["kind"] != "text" ||
		cfg["blocking"] != false {
		t.Fatalf("send = %+v", send)
	}
	if get := r.calls[1]; get.Method != "tasks/get" || get.Params["id"] != "rt1" {
		t.Fatalf("poll = %+v", get)
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
		{"still working", func(method string, _ map[string]any, _ int) (int, any) {
			if method == "GetTask" {
				return 200, result(task("TASK_STATE_WORKING", nil))
			}
			return 200, result(map[string]any{"task": task("TASK_STATE_WORKING", nil)})
		}, api.RemoteAgentResult{Error: "'Docs' is still working on task rt1; no result within the delegation time limit"}},
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
			res, err := remoteService(nil).callRemoteAgent(context.Background(), remoteCall(r.url(), ""), fastPoll)
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

	res, err := svc.callRemoteAgent(ctx, remoteCall(r.url(), "remote-key"), fastPoll)
	if err != nil || !res.Raised || res.Error != "Could not resolve the credential for 'Docs': secret 'remote-key' not found in this workspace" {
		t.Fatalf("missing secret = %+v %v", res, err)
	}
	call := remoteCall(r.url(), "")
	call.Message = ""
	if res, _ := svc.callRemoteAgent(ctx, call, fastPoll); !res.Raised || res.Error != "message is required" {
		t.Fatalf("no message = %+v", res)
	}
	r.card = func(string) any {
		return map[string]any{"supportedInterfaces": []any{map[string]any{"url": "http://elsewhere.test/rpc", "protocolBinding": "JSONRPC"}}}
	}
	res, _ = svc.callRemoteAgent(ctx, remoteCall(r.url(), ""), fastPoll)
	want := "The card of 'Docs' names no endpoint on " + strings.ToLower(r.srv.URL) + ": http://elsewhere.test/rpc"
	if !res.Raised || res.Error != want {
		t.Fatalf("foreign endpoint = %+v, want %q", res, want)
	}
	r.card = func(base string) any {
		return map[string]any{"supportedInterfaces": []any{map[string]any{"url": base + "/rpc", "protocolBinding": "GRPC"}}}
	}
	if res, _ := svc.callRemoteAgent(ctx, remoteCall(r.url(), ""), fastPoll); !res.Raised || res.Error != "no compatible transports found." {
		t.Fatalf("no JSON-RPC interface = %+v", res)
	}
	if len(r.calls) != 0 {
		t.Fatalf("refused calls reached the agent: %+v", r.calls)
	}
	res, _ = svc.callRemoteAgent(ctx, remoteCall(r.srv.URL+"/missing", ""), fastPoll)
	if !res.Raised || !strings.HasPrefix(res.Error, "Could not read the agent card of 'Docs': Failed to fetch agent card from "+r.srv.URL+"/missing/.well-known/agent-card.json (HTTP 404)") {
		t.Fatalf("no card = %+v", res)
	}
}
