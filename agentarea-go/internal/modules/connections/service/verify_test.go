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

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

const testGatewaySecret = "gateway-secret-of-at-least-32-bytes!!"

func TestDerivedContextKeyMatchesPython(t *testing.T) {
	got := DerivedContextKey(testGatewaySecret, "c92f0870-465a-4c70-8c11-b33d08fd8c54")
	if got != "4896aeffbc037762218722536c6b3909507c657b401b1dfd840e39b056c940f8" {
		t.Fatalf("key %s", got)
	}
}

func TestSignContextClaims(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	cc := CallerContext{TaskID: "task", ToolCallID: "call", UserID: "u", AgentID: "a"}
	token, err := SignContext("ws", cc, "k", "inst", "search", now)
	if err != nil {
		t.Fatal(err)
	}
	claims := jwt.MapClaims{}
	if _, err := jwt.ParseWithClaims(token, claims, func(*jwt.Token) (any, error) { return []byte("k"), nil },
		jwt.WithTimeFunc(func() time.Time { return now }), jwt.WithAudience("inst")); err != nil {
		t.Fatal(err)
	}
	if claims["iss"] != "agentarea" || claims["tool"] != "search" || claims["workspace_id"] != "ws" ||
		claims["idempotency_key"] != "task:call" || claims["protocol"] != "1" || claims["agent_id"] != "a" {
		t.Fatalf("claims %v", claims)
	}
	if exp, _ := claims.GetExpirationTime(); exp == nil || exp.Sub(now) != 300*time.Second {
		t.Fatalf("exp %v", exp)
	}
}

func TestCredentialHints(t *testing.T) {
	got := credentialHints([]any{
		map[string]any{"name": "API_KEY", "description": "the key"},
		map[string]any{"name": "REGION", "description": "x"},
		map[string]any{"name": "Authorization", "required": false},
	})
	raw, _ := json.Marshal(got)
	want := `[{"description":"the key","name":"API_KEY","required":true},{"description":"","name":"Authorization","required":false}]`
	if string(raw) != want {
		t.Fatalf("hints %s", raw)
	}
}

// mcpFake is a streamable-HTTP MCP server (handshake era, JSON answers).
type mcpFake struct {
	mu      sync.Mutex
	methods []string
	calls   []http.Header
	metas   []map[string]any
}

func (m *mcpFake) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		return
	}
	var req struct {
		ID     *int64         `json:"id"`
		Method string         `json:"method"`
		Params map[string]any `json:"params"`
	}
	_ = json.NewDecoder(r.Body).Decode(&req)
	m.mu.Lock()
	m.methods = append(m.methods, req.Method)
	if req.Method == "tools/call" {
		m.calls = append(m.calls, r.Header.Clone())
		meta, _ := req.Params["_meta"].(map[string]any)
		m.metas = append(m.metas, meta)
	}
	m.mu.Unlock()
	if req.ID == nil {
		w.WriteHeader(http.StatusAccepted)
		return
	}
	out := map[string]any{"jsonrpc": "2.0", "id": req.ID}
	switch req.Method {
	case "initialize":
		out["result"] = map[string]any{"protocolVersion": "2025-11-25", "capabilities": map[string]any{"tools": map[string]any{}},
			"serverInfo": map[string]any{"name": "fake"}}
	case "tools/list":
		out["result"] = map[string]any{"tools": []any{map[string]any{"name": "echo", "inputSchema": map[string]any{"type": "object"}}}}
	case "tools/call":
		out["result"] = map[string]any{"content": []any{map[string]any{"type": "text", "text": "echoed"}}}
	default:
		out["error"] = map[string]any{"code": -32601, "message": "Method not found"}
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(out)
}

type gwRuntime struct {
	Runtime
	h http.Handler
}

func (g gwRuntime) Gateway() http.Handler                { return g.h }
func (g gwRuntime) Retire(context.Context, string) error { return nil }

type verifyOut struct {
	g  *netguard.Guard
	rt http.RoundTripper
}

func (o verifyOut) Guard() *netguard.Guard                           { return o.g }
func (o verifyOut) Transport(netguard.Destination) http.RoundTripper { return o.rt }

func newVerifyFixture(t *testing.T, member http.RoundTripper) (*instFixture, *mcpFake) {
	t.Helper()
	f := newInstFixture(t)
	fake := &mcpFake{}
	f.svc.d.Runtime = gwRuntime{h: fake}
	f.svc.d.Out = verifyOut{g: f.svc.d.Out.Guard(), rt: member}
	f.svc.d.Config.GatewaySecret = testGatewaySecret
	return f, fake
}

func (f *instFixture) waitTerminal(t *testing.T, id string) domain.Verification {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		inst, err := f.svc.instanceIn(context.Background(), f.c.Workspace, uuid.MustParse(id))
		if err != nil {
			t.Fatal(err)
		}
		if s := inst.Verification.Status; s == domain.VerifySucceeded || s == domain.VerifyFailed {
			return inst.Verification
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("verification never finished")
	return domain.Verification{}
}

func TestCommandInstanceVerifiesThroughTheGatewayAndSignsCalls(t *testing.T) {
	f, fake := newVerifyFixture(t, http.DefaultTransport)
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"node", "server.js"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID,
		JSONSpec: map[string]any{domain.ContextSpecKey: map[string]any{"enabled": true}}})
	if err != nil {
		t.Fatal(err)
	}
	id := v.Instance.ID
	if got := f.waitTerminal(t, id); got.Status != domain.VerifySucceeded {
		t.Fatalf("background verification %+v", got)
	}
	got, err := f.svc.Verify(ctx, f.c.Workspace, uuid.MustParse(id), true)
	if err != nil || got.Status != domain.VerifySucceeded {
		t.Fatalf("verify %+v err %v", got, err)
	}
	tools, ver, err := f.svc.DiscoverInstanceTools(ctx, f.c.Workspace, uuid.MustParse(id))
	if err != nil || ver.Status != domain.VerifySucceeded || len(tools) != 1 {
		t.Fatalf("discover %v %+v %v", tools, ver, err)
	}

	res, err := f.svc.MCPTools().Call(ctx, api.MCPCall{WorkspaceID: f.c.Workspace.ID(), UserID: "owner", TaskID: "t1",
		ToolCallID: "c1", InstanceID: id, Tool: "echo", Args: map[string]any{"q": 1}})
	if err != nil || !res.Success || res.Result != "echoed" {
		t.Fatalf("call %+v err %v", res, err)
	}
	fake.mu.Lock()
	h, meta := fake.calls[0], fake.metas[0]
	fake.mu.Unlock()
	token := h.Get(ContextHeader)
	claims := jwt.MapClaims{}
	if _, err := jwt.ParseWithClaims(token, claims, func(*jwt.Token) (any, error) {
		return []byte(DerivedContextKey(testGatewaySecret, id)), nil
	}, jwt.WithAudience(id)); err != nil {
		t.Fatalf("context header %q: %v", token, err)
	}
	if claims["tool"] != "echo" || claims["task_id"] != "t1" {
		t.Fatalf("claims %v", claims)
	}
	if meta["agentarea/task_id"] != "t1" {
		t.Fatalf("_meta %v", meta)
	}

	if n := f.svc.FlushDispatchStamps(ctx); n < 1 {
		t.Fatalf("flushed %d stamps", n)
	}
	var status string
	q, done, err := f.pools.Global().Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer done()
	if err := q.QueryRow(ctx, `SELECT last_dispatch->>'status' FROM mcp_server_instances WHERE id = $1`, id).Scan(&status); err != nil {
		t.Fatal(err)
	}
	if status != domain.VerifySucceeded {
		t.Fatalf("last_dispatch status %q", status)
	}
}

func TestURLInstanceRefusedWithoutCredentials(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusUnauthorized) }))
	defer srv.Close()
	f, _ := newVerifyFixture(t, http.DefaultTransport)
	ctx := context.Background()
	url := srv.URL + "/mcp"
	specID := f.spec(t, catalogapi.MCPSpec{Name: "remote", RemoteURL: &url})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "remote", ServerSpecID: specID, JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	got := f.waitTerminal(t, v.Instance.ID)
	if got.Status != domain.VerifyFailed || got.Error == nil || got.Error.Code != CodeUpstreamUnauthorized ||
		!strings.Contains(got.Error.Message, "requires sign-in or a key (HTTP 401)") {
		t.Fatalf("verification %+v", got.Error)
	}

	res, err := f.svc.ExecuteTool(ctx, f.c.Workspace, api.MCPCall{InstanceID: v.Instance.ID, Tool: "x"})
	if err != nil || res.Success || !strings.HasPrefix(res.Error, "MCP tool call failed") {
		t.Fatalf("call %+v err %v", res, err)
	}
}

func TestValidateConnectionRefusesUnsafeURL(t *testing.T) {
	policy, err := netguard.NewAddressPolicy(false, nil)
	if err != nil {
		t.Fatal(err)
	}
	s := New(Deps{Out: verifyOut{g: &netguard.Guard{Policy: policy}, rt: http.DefaultTransport}})
	ws, _ := scope.NewWorkspace(uuid.NewString(), "")
	got := s.ValidateConnection(context.Background(), ws, "http://127.0.0.1:9/mcp", nil, "")
	if got.Valid || len(got.Errors) != 1 || got.Errors[0] != "URL is not allowed" {
		t.Fatalf("%+v", got)
	}
	if got := s.ValidateConnection(context.Background(), ws, "", nil, ""); got.Errors[0] != "URL is required" {
		t.Fatalf("%+v", got)
	}
}

func TestValidateConnectionListsTools(t *testing.T) {
	srv := httptest.NewServer(&mcpFake{})
	defer srv.Close()
	policy, err := netguard.NewAddressPolicy(true, nil)
	if err != nil {
		t.Fatal(err)
	}
	s := New(Deps{Out: verifyOut{g: &netguard.Guard{Policy: policy}, rt: http.DefaultTransport}})
	ws, _ := scope.NewWorkspace(uuid.NewString(), "")
	got := s.ValidateConnection(context.Background(), ws, srv.URL+"/mcp", map[string]string{"X-Key": "k"}, "")
	if !got.Valid || len(got.Tools) != 1 || got.AuthMethods != nil {
		t.Fatalf("%+v", got)
	}
}

func TestMonitorReapsOrphanedVerification(t *testing.T) {
	f, _ := newVerifyFixture(t, http.DefaultTransport)
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"node", "server.js"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID, JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	id := v.Instance.ID
	f.waitTerminal(t, id)
	stale := time.Now().Add(-13 * time.Minute).UTC().Format(time.RFC3339)
	globalExec(t, f.pools, `UPDATE mcp_server_instances SET verification = jsonb_build_object('schema_version', 1, 'status', 'in_progress', 'at', $2::text, 'error', null), updated_at = now() - interval '13 minutes' WHERE id = $1`, id, stale)
	var wg sync.WaitGroup
	if err := f.svc.MonitorTick(ctx, &wg, make(chan struct{}, 5)); err != nil {
		t.Fatal(err)
	}
	wg.Wait()
	got := f.waitTerminal(t, id)
	if got.Status != domain.VerifyFailed || got.Error == nil || got.Error.Code != CodeInterrupted {
		t.Fatalf("verification %+v", got)
	}
}
