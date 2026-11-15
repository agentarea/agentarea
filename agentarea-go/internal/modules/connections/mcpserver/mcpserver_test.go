package mcpserver

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

const wsID = "11111111-1111-1111-1111-111111111111"

type fakeGate struct {
	authn.Gate
	principals map[string]authn.Principal
	turnOnly   map[string]bool
}

func (g fakeGate) Optional(_ context.Context, token string, admitTurn bool) (*authn.Principal, error) {
	p, ok := g.principals[token]
	if !ok || (g.turnOnly[token] && !admitTurn) {
		return nil, nil
	}
	return &p, nil
}

func (g fakeGate) EnterWorkspace(_ context.Context, p authn.Principal, ref string) (authn.Caller, error) {
	if ref != "acme" && ref != wsID {
		return authn.Caller{}, &scope.UnreachableError{Reference: ref}
	}
	ws, err := scope.NewWorkspace(wsID, "acme")
	if err != nil {
		return authn.Caller{}, err
	}
	return authn.Caller{Principal: p, Workspace: ws}, nil
}

func gate() fakeGate {
	return fakeGate{
		principals: map[string]authn.Principal{
			"user":  {UserID: "u1"},
			"bound": {UserID: "u1", BoundAgentID: "a1"},
			"turn":  {UserID: "u1", TurnClientID: "c1"},
		},
		turnOnly: map[string]bool{"turn": true},
	}
}

// echoToolset records the workspace each call ran in.
type echoToolset struct {
	name, ns string
	seen     *string
}

func (t echoToolset) Name() string      { return t.name }
func (t echoToolset) Namespace() string { return t.ns }
func (t echoToolset) Tools(context.Context, authn.Principal) ([]mcpserve.Tool, error) {
	return []mcpserve.Tool{
		{Name: t.name + "_list", InputSchema: json.RawMessage(`{"type":"object","properties":{"q":{"type":"string"}},"required":["q"]}`)},
		{Name: t.name + "_drop", InputSchema: json.RawMessage(`{"type":"object"}`)},
	}, nil
}
func (t echoToolset) Call(ctx context.Context, _ authn.Principal, tool string, args json.RawMessage) (mcpserve.Result, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return mcpserve.Result{}, errors.New("no caller")
	}
	*t.seen = c.Workspace.ID() + " " + string(args)
	return mcpserve.Result{Content: []mcpserve.Content{{Type: "text", Text: tool}}}, nil
}

func server(t *testing.T) (*chi.Mux, *string) {
	t.Helper()
	seen := new(string)
	auth := Auth{Gate: gate(), APIURL: "https://api.example/"}
	r := chi.NewRouter()
	for _, spanning := range []bool{true, false} {
		p := NewPlatform(spanning, Identity("https://api.example", PlatformName, PlatformInstructions), auth, nil)
		p.Register(echoToolset{name: "agents", ns: "agentarea/agents", seen: seen}, echoToolset{name: "runs", ns: "agentarea/runs", seen: seen})
		mount := mcpserve.MountSpan
		if !spanning {
			mount = mcpserve.MountPinned
		}
		r.Handle(mount, p.Handler(mount))
	}
	return r, seen
}

type rpcReply struct {
	status int
	header http.Header
	body   map[string]any
}

func call(t *testing.T, h http.Handler, path, token, body string, headers map[string]string) rpcReply {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	out := rpcReply{status: rec.Code, header: rec.Header()}
	if rec.Body.Len() > 0 {
		if err := json.Unmarshal(rec.Body.Bytes(), &out.body); err != nil {
			t.Fatalf("body %q: %v", rec.Body.String(), err)
		}
	}
	return out
}

func errCode(r rpcReply) float64 {
	e, _ := r.body["error"].(map[string]any)
	c, _ := e["code"].(float64)
	return c
}

func TestInitializeNegotiatesWithoutToken(t *testing.T) {
	h, _ := server(t)
	for requested, want := range map[string]string{"2025-03-26": "2025-03-26", "1999-01-01": LatestHandshakeVersion} {
		r := call(t, h, "/mcp", "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"`+requested+`"}}`, nil)
		res, _ := r.body["result"].(map[string]any)
		if r.status != 200 || res["protocolVersion"] != want {
			t.Fatalf("requested %s: %d %v", requested, r.status, r.body)
		}
		info, _ := res["serverInfo"].(map[string]any)
		if info["name"] != PlatformName || res["instructions"] != PlatformInstructions {
			t.Fatalf("identity: %v", res)
		}
	}
	if r := call(t, h, "/mcp", "", `{"jsonrpc":"2.0","method":"notifications/initialized"}`, nil); r.status != http.StatusAccepted {
		t.Fatalf("notification: %d", r.status)
	}
}

func TestUnauthenticatedChallenge(t *testing.T) {
	h, _ := server(t)
	for _, tc := range []struct{ path, token, metadata string }{
		{"/mcp", "", "https://api.example/.well-known/oauth-protected-resource"},
		{"/mcp/w/acme", "", "https://api.example/.well-known/oauth-protected-resource/mcp/w/acme"},
		{"/mcp", "bound", "https://api.example/.well-known/oauth-protected-resource"},
		{"/mcp", "turn", "https://api.example/.well-known/oauth-protected-resource"},
	} {
		r := call(t, h, tc.path, tc.token, `{"jsonrpc":"2.0","id":7,"method":"tools/list"}`, nil)
		if r.status != 401 || errCode(r) != CodeInvalidRequest || r.body["id"] != float64(7) {
			t.Fatalf("%s %s: %d %v", tc.path, tc.token, r.status, r.body)
		}
		if got := r.header.Get("WWW-Authenticate"); got != `Bearer resource_metadata="`+tc.metadata+`"` {
			t.Fatalf("%s: challenge %q", tc.path, got)
		}
	}
}

func TestPinnedForeignWorkspaceIs403AndBadReference404(t *testing.T) {
	h, _ := server(t)
	r := call(t, h, "/mcp/w/other", "user", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`, nil)
	e, _ := r.body["error"].(map[string]any)
	if r.status != 403 || e["message"] != "No accessible workspace 'other'" {
		t.Fatalf("foreign: %d %v", r.status, r.body)
	}
	if r := call(t, h, "/mcp/w/Not_A_Slug", "user", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`, nil); r.status != 404 {
		t.Fatalf("bad reference: %d", r.status)
	}
}

func toolNames(r rpcReply) []string {
	res, _ := r.body["result"].(map[string]any)
	tools, _ := res["tools"].([]any)
	var out []string
	for _, t := range tools {
		out = append(out, t.(map[string]any)["name"].(string))
	}
	return out
}

func TestSpanningMountAddsWorkspaceArgumentAndBindsIt(t *testing.T) {
	h, seen := server(t)
	r := call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`, nil)
	res, _ := r.body["result"].(map[string]any)
	first := res["tools"].([]any)[0].(map[string]any)
	schema := first["inputSchema"].(map[string]any)
	required := schema["required"].([]any)
	if required[0] != "workspace" || required[1] != "q" {
		t.Fatalf("required: %v", required)
	}
	if _, ok := schema["properties"].(map[string]any)["workspace"]; !ok {
		t.Fatalf("no workspace property: %v", schema)
	}

	r = call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"agents_list","arguments":{"workspace":"acme","q":"x"}}}`, nil)
	if res, _ := r.body["result"].(map[string]any); res["isError"] == true || *seen != wsID+` {"q":"x"}` {
		t.Fatalf("call: %v seen %q", r.body, *seen)
	}
	for args, want := range map[string]string{
		`{"q":"x"}`:                     "Missing required argument 'workspace' for tool agents_list",
		`{"workspace":"other","q":"x"}`: "No accessible workspace 'other'",
	} {
		r = call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"agents_list","arguments":`+args+`}}`, nil)
		res, _ := r.body["result"].(map[string]any)
		text := res["content"].([]any)[0].(map[string]any)["text"]
		if res["isError"] != true || text != want {
			t.Fatalf("%s: %v", args, r.body)
		}
	}
}

func TestPinnedMountRunsInItsWorkspace(t *testing.T) {
	h, seen := server(t)
	r := call(t, h, "/mcp/w/acme", "user", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`, nil)
	res, _ := r.body["result"].(map[string]any)
	schema := res["tools"].([]any)[0].(map[string]any)["inputSchema"].(map[string]any)
	if _, ok := schema["properties"].(map[string]any)["workspace"]; ok {
		t.Fatalf("pinned tool has a workspace argument")
	}
	call(t, h, "/mcp/w/acme", "user", `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"runs_drop","arguments":{}}}`, nil)
	if *seen != wsID+" {}" {
		t.Fatalf("seen %q", *seen)
	}
}

func TestToolsetSelection(t *testing.T) {
	h, _ := server(t)
	r := call(t, h, "/mcp?toolsets=agentarea/runs", "user", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`, nil)
	if got := toolNames(r); len(got) != 2 || got[0] != "runs_list" {
		t.Fatalf("selected: %v", got)
	}
	for q, want := range map[string]string{
		"toolsets=nope": "Unknown toolset 'nope'. Available: agents, runs",
		"toolsets=":     "'toolsets' names no toolset. Available: agents, runs",
	} {
		r := call(t, h, "/mcp?"+q, "user", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`, nil)
		e, _ := r.body["error"].(map[string]any)
		if r.status != 400 || e["message"] != want || errCode(r) != CodeInvalidParams {
			t.Fatalf("%s: %d %v", q, r.status, r.body)
		}
	}
}

func modernHeaders(method, name string) map[string]string {
	h := map[string]string{HeaderProtocolVersion: ModernVersions()[0], HeaderMethod: method}
	if name != "" {
		h[HeaderName] = "=?base64?" + base64.StdEncoding.EncodeToString([]byte(name)) + "?="
	}
	return h
}

func TestModernLadder(t *testing.T) {
	h, _ := server(t)
	v := ModernVersions()[0]
	envelope := `"_meta":{"` + MetaProtocolVersion + `":"` + v + `","` + MetaClientCapabilities + `":{}}`
	call1 := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"runs_drop","arguments":{},` + envelope + `}}`

	r := call(t, h, "/mcp/w/acme", "user", call1, modernHeaders("tools/call", "runs_drop"))
	res, _ := r.body["result"].(map[string]any)
	if r.status != 200 || res["resultType"] != "complete" {
		t.Fatalf("modern call: %d %v", r.status, r.body)
	}
	if meta, _ := res["_meta"].(map[string]any); meta[MetaServerInfo] == nil {
		t.Fatalf("no serverInfo meta: %v", res)
	}

	cases := []struct {
		name    string
		body    string
		headers map[string]string
		status  int
		code    float64
	}{
		{"envelope", `{"jsonrpc":"2.0","id":1,"method":"ping","params":{"_meta":{"` + MetaProtocolVersion + `":"` + v + `"}}}`, modernHeaders("ping", ""), 400, CodeInvalidParams},
		{"name header", call1, modernHeaders("tools/call", "other"), 400, CodeHeaderMismatch},
		{"method header", call1, modernHeaders("tools/list", "runs_drop"), 400, CodeHeaderMismatch},
		{"unknown method", `{"jsonrpc":"2.0","id":1,"method":"nope","params":{` + envelope + `}}`, modernHeaders("nope", ""), 404, CodeMethodNotFound},
	}
	for _, tc := range cases {
		r := call(t, h, "/mcp/w/acme", "user", tc.body, tc.headers)
		if r.status != tc.status || errCode(r) != tc.code {
			t.Fatalf("%s: %d %v", tc.name, r.status, r.body)
		}
	}

	old := `{"jsonrpc":"2.0","id":1,"method":"ping","params":{"_meta":{"` + MetaProtocolVersion + `":"1999-01-01","` + MetaClientCapabilities + `":{}}}}`
	hh := modernHeaders("ping", "")
	hh[HeaderProtocolVersion] = "1999-01-01"
	r = call(t, h, "/mcp", "", old, hh)
	e, _ := r.body["error"].(map[string]any)
	if r.status != 400 || errCode(r) != CodeUnsupportedProtocolVer || e["data"].(map[string]any)["requested"] != "1999-01-01" {
		t.Fatalf("version: %d %v", r.status, r.body)
	}

	if r := call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":1,"method":"server/discover"}`, nil); errCode(r) != CodeMethodNotFound || r.status != 200 {
		t.Fatalf("legacy discover: %d %v", r.status, r.body)
	}
}

func TestEndpointRefusesBatchAndWrongMedia(t *testing.T) {
	h, _ := server(t)
	if r := call(t, h, "/mcp", "user", `[{"jsonrpc":"2.0","id":1,"method":"ping"}]`, nil); r.status != 400 || errCode(r) != CodeInvalidRequest {
		t.Fatalf("batch: %d %v", r.status, r.body)
	}
	req := httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "text/plain")
	req.Header.Set("Authorization", "Bearer user")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("media: %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	get := httptest.NewRequest(http.MethodGet, "/mcp", nil)
	get.Header.Set("Authorization", "Bearer user")
	h.ServeHTTP(rec, get)
	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("GET: %d", rec.Code)
	}
}

func TestCarriedDropsDisabledMethodsAndUnknownToolsets(t *testing.T) {
	seen := new(string)
	p := NewPlatform(false, Info{}, Auth{Gate: gate()}, nil)
	p.Register(echoToolset{name: "agents", ns: "agentarea/agents", seen: seen})
	c, err := gate().EnterWorkspace(context.Background(), authn.Principal{UserID: "u1"}, "acme")
	if err != nil {
		t.Fatal(err)
	}
	tools, err := p.Carried(context.Background(), c, []agentsapi.ClientToolset{
		{Toolset: "agentarea/agents", DisabledMethods: []string{"drop"}},
		{Toolset: "gone"},
	})
	if err != nil || len(tools) != 1 || tools[0].Name != "agents_list" {
		t.Fatalf("carried: %v %v", tools, err)
	}
	if _, err := p.CallCarried(context.Background(), c, "agents_list", json.RawMessage(`{"q":"y"}`)); err != nil || *seen != wsID+` {"q":"y"}` {
		t.Fatalf("call carried: %v %q", err, *seen)
	}
}

func TestProvidersServeOnlyWhatIsSet(t *testing.T) {
	ts, err := Providers{}.Toolsets("https://api.example")
	if err != nil || len(ts) != 0 {
		t.Fatalf("empty providers: %v %v", ts, err)
	}
	ts, err = Providers{WorkspaceConfig: exportStub{}}.Toolsets("https://api.example")
	if err != nil || len(ts) != 1 {
		t.Fatalf("workspace_config: %v %v", ts, err)
	}
	tools, _ := ts[0].Tools(context.Background(), authn.Principal{})
	if len(tools) != 1 || tools[0].Name != "workspace_config_export" {
		t.Fatalf("tools: %v", tools)
	}
	c, _ := gate().EnterWorkspace(context.Background(), authn.Principal{UserID: "u1"}, "acme")
	res, err := ts[0].Call(authn.WithCaller(context.Background(), c), c.Principal, "workspace_config_export", json.RawMessage(`{}`))
	if err != nil || res.Content[0].Text != `{"yaml":"agents: []\n"}` {
		t.Fatalf("export: %v %v", res, err)
	}
}

type exportStub struct{}

func (exportStub) Export(context.Context, authn.Caller) (string, error) { return "agents: []\n", nil }
