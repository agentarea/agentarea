package service

import (
	"context"
	"errors"
	"net/http"
	"slices"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

type rtInstances struct {
	InstanceStore
	rows map[string]domain.Instance
}

func (m rtInstances) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	i, ok := m.rows[id.String()]
	return i, ok, nil
}

func (m rtInstances) GetMany(_ context.Context, _ db.Session, ids []uuid.UUID) (map[string]domain.Instance, error) {
	out := map[string]domain.Instance{}
	for _, id := range ids {
		if i, ok := m.rows[id.String()]; ok {
			out[id.String()] = i
		}
	}
	return out, nil
}

// rtGraph allows exactly the subject#resource pairs it holds.
type rtGraph struct{ allowed map[string]bool }

func (g rtGraph) Check(_ context.Context, subject, _, _, id string) (bool, error) {
	return g.allowed[subject+"#"+id], nil
}
func (rtGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error) { return nil, nil }

func succeeded(id, name string, tools ...any) domain.Instance {
	return domain.Instance{ID: id, Name: name, Transport: domain.TransportURL, Tools: tools, ToolsSet: true,
		Verification: domain.Verification{SchemaVersion: 1, Status: domain.VerifySucceeded}}
}

func tool(name string, meta map[string]any) map[string]any {
	t := map[string]any{"name": name, "description": name + " it", "inputSchema": map[string]any{"type": "object"}}
	if meta != nil {
		t["_meta"] = meta
	}
	return t
}

type rtFixture struct {
	svc   *Service
	insts rtInstances
	conns *memConns
	graph rtGraph
	ws    string
}

func newRTFixture() *rtFixture {
	f := &rtFixture{insts: rtInstances{rows: map[string]domain.Instance{}}, conns: &memConns{rows: map[uuid.UUID]domain.Connection{}},
		graph: rtGraph{allowed: map[string]bool{}}, ws: uuid.NewString()}
	f.svc = New(Deps{Stamps: NewStamps(), Verdicts: NewVerdicts(), DB: memDB{}, Instances: f.insts, Connections: f.conns, Graph: f.graph})
	return f
}

func (f *rtFixture) resolve(t *testing.T, agent runsapi.AgentSpec, selected ...string) (api.RunToolSet, error) {
	t.Helper()
	if agent.ID == "" {
		agent.ID = "agent-1"
	}
	return f.svc.RunTools(context.Background(), api.RunToolsRequest{WorkspaceID: f.ws, UserID: "u1", AgentID: agent.ID,
		Agent: agent, MCPInstanceIDs: selected})
}

func TestRunToolsMCPNamesPinningAndVisibility(t *testing.T) {
	f := newRTFixture()
	a, b := uuid.NewString(), uuid.NewString()
	f.insts.rows[a] = succeeded(a, "GitHub", tool("search", nil), tool("push", nil),
		tool("widget", map[string]any{"ui": map[string]any{"visibility": []any{"app"}}}),
		tool("board", map[string]any{"ui": map[string]any{"resourceUri": "ui://board"}}))
	f.insts.rows[b] = succeeded(b, "github", tool("search", nil))
	f.graph.allowed["Agent:agent-1#"+a] = true
	f.graph.allowed["Agent:agent-1#"+b] = true
	got, err := f.resolve(t, runsapi.AgentSpec{Tools: []runsapi.ToolConfig{
		{Type: "mcp", Name: a, Settings: runsapi.ToolConfigSettings{AllowedTools: []string{"search", "board", "widget"}}},
		{Type: "mcp", Name: b},
	}})
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, d := range got.Tools {
		names = append(names, d.Name)
	}
	suffix := strings.ReplaceAll(b, "-", "")[:6]
	want := []string{"mcp__github__search", "mcp__github__board", "mcp__github_" + suffix + "__search"}
	if !slices.Equal(names, want) {
		t.Fatalf("names %v, want %v", names, want)
	}
	bind := got.Bindings["mcp__github__search"]
	if bind.Source != "mcp" || bind.MCP.InstanceID != a || bind.MCP.RawName != "search" ||
		!slices.Equal(bind.PolicyNames, []string{"mcp:" + a + ":search"}) ||
		!slices.Equal(bind.RestrictingNames, []string{"mcp:GitHub:search", "search"}) {
		t.Fatalf("binding %+v %+v", bind, bind.MCP)
	}
	if got.Bindings["mcp__github__board"].MCP.OpensApp != "ui://board" {
		t.Fatalf("board does not open its app")
	}
	if len(got.ToolProviders) != 2 || got.ToolProviders[0].ProviderType != "mcp" || len(got.ToolProviders[0].Tools) != 2 {
		t.Fatalf("providers %+v", got.ToolProviders)
	}
}

func TestRunToolsSkipsUnverifiedAndUnboundInstances(t *testing.T) {
	f := newRTFixture()
	a := uuid.NewString()
	inst := succeeded(a, "x", tool("t", nil))
	inst.Verification.Status = domain.VerifyFailed
	f.insts.rows[a] = inst
	f.graph.allowed["Agent:agent-1#"+a] = true
	got, err := f.resolve(t, runsapi.AgentSpec{Tools: []runsapi.ToolConfig{{Type: "mcp", Name: a}, {Type: "mcp", Name: "by-name"}}})
	if err != nil || len(got.Tools) != 0 || len(got.Bindings) != 0 {
		t.Fatalf("got %+v err %v", got, err)
	}
}

func TestRunToolsRefusesAnUnlentConnection(t *testing.T) {
	f := newRTFixture()
	a := uuid.NewString()
	f.insts.rows[a] = succeeded(a, "mine", tool("t", nil))
	_, err := f.resolve(t, runsapi.AgentSpec{Name: "bot", Tools: []runsapi.ToolConfig{{Type: "mcp", Name: a}}})
	if !errors.Is(err, api.ErrToolsRefused) || !strings.Contains(err.Error(), "was not lent") {
		t.Fatalf("err %v", err)
	}
	managed := domain.ManagedByPlatform
	inst := f.insts.rows[a]
	inst.ManagedBy = &managed
	f.insts.rows[a] = inst
	if _, err := f.resolve(t, runsapi.AgentSpec{Tools: []runsapi.ToolConfig{{Type: "mcp", Name: a}}}); err != nil {
		t.Fatalf("platform connection refused: %v", err)
	}
}

func TestRunToolsSelectedInstances(t *testing.T) {
	f := newRTFixture()
	a, b := uuid.NewString(), uuid.NewString()
	f.insts.rows[a] = succeeded(a, "crm", tool("find", nil), tool("drop", nil))
	f.insts.rows[b] = succeeded(b, "other", tool("x", nil))
	f.graph.allowed["User:u1#"+a] = true
	got, err := f.resolve(t, runsapi.AgentSpec{Tools: []runsapi.ToolConfig{
		{Type: "mcp", Name: "crm", Settings: runsapi.ToolConfigSettings{AllowedTools: []string{"find"}}},
	}}, a)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Tools) != 1 || got.Tools[0].Name != "mcp__crm__find" || got.Bindings["mcp__crm__find"].MCP.AttachmentRef != a {
		t.Fatalf("selected by name keeps the restriction: %+v", got.Tools)
	}
	if _, err := f.resolve(t, runsapi.AgentSpec{}, b); !errors.Is(err, api.ErrToolsRefused) {
		t.Fatalf("someone else's connection: %v", err)
	}
	if _, err := f.resolve(t, runsapi.AgentSpec{}, uuid.NewString()); !errors.Is(err, api.ErrToolsNotFound) {
		t.Fatalf("missing connection: %v", err)
	}
}

func TestRunToolsOpenAPISplitAndCodeToolsets(t *testing.T) {
	f := newRTFixture()
	id := uuid.New()
	f.conns.rows[id] = domain.Connection{ID: id.String(), Name: "Weather API", BaseURL: "https://w.example",
		AvailableTools: []domain.Tool{{Name: "get forecast", Description: "Forecast"}, {Name: "alerts"}}}
	f.graph.allowed["Agent:agent-1#"+id.String()] = true
	got, err := f.resolve(t, runsapi.AgentSpec{Tools: []runsapi.ToolConfig{
		{Type: "openapi", Name: "weather", Settings: runsapi.ToolConfigSettings{OpenAPIConnectionID: id.String(), LoadMode: "searchable"}},
		{Type: "code", Name: "agentarea/files", Settings: runsapi.ToolConfigSettings{DisabledMethods: []string{"search_files"}}},
		{Type: "code", Name: "agentarea/shell"},
		{Type: "code", Name: "agentarea/agents"},
		{Type: "code", Name: "agentarea/nothing"},
	}})
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(got.OpenAPIOperationTools["weather"], []string{"get_forecast", "alerts"}) {
		t.Fatalf("operations %v", got.OpenAPIOperationTools)
	}
	if len(got.SearchableTools) != 2 || got.SearchableTools[0].Name != "get_forecast" || got.SearchableTools[1].Description != "OpenAPI operation alerts" {
		t.Fatalf("searchable %+v", got.SearchableTools)
	}
	for _, d := range got.Tools {
		if d.Name == "get_forecast" || d.Name == "files_search_files" {
			t.Fatalf("%s offered explicitly", d.Name)
		}
	}
	op := got.Bindings["get_forecast"]
	if op.Source != "openapi" || op.OpenAPI.OperationID != "get forecast" || op.OpenAPI.ConnectionID != id.String() {
		t.Fatalf("openapi binding %+v", op)
	}
	sh := got.Bindings["shell"]
	if sh.Code == nil || sh.Code.Namespace != "agentarea/shell" || sh.Code.Method != "bash" {
		t.Fatalf("shell binding %+v", sh)
	}
	if save := got.Bindings["files_save_file"]; save.Code == nil || save.Code.Method != "save_file" {
		t.Fatalf("files binding %+v", save)
	}
	if list := got.Bindings["agents_list"]; list.Code == nil || list.Code.Namespace != "agentarea/agents" || list.Code.Method != "list" {
		t.Fatalf("platform toolset binding %+v", list)
	}
}

// Python appended a second tool under a name already offered (two OpenAPI
// attachments with the same operation), so the model provider refused every
// call of the run; the resolution now refuses it, naming both.
func TestRunToolsRefusesADuplicateToolName(t *testing.T) {
	f := newRTFixture()
	one, two := uuid.New(), uuid.New()
	for _, id := range []uuid.UUID{one, two} {
		f.conns.rows[id] = domain.Connection{ID: id.String(), Name: "api-" + id.String()[:4], AvailableTools: []domain.Tool{{Name: "list"}}}
		f.graph.allowed["Agent:agent-1#"+id.String()] = true
	}
	_, err := f.resolve(t, runsapi.AgentSpec{Tools: []runsapi.ToolConfig{
		{Type: "openapi", Name: "a", Settings: runsapi.ToolConfigSettings{OpenAPIConnectionID: one.String()}},
		{Type: "openapi", Name: "b", Settings: runsapi.ToolConfigSettings{OpenAPIConnectionID: two.String()}},
	}})
	if !errors.Is(err, api.ErrToolsRefused) || !strings.Contains(err.Error(), `as "list"`) {
		t.Fatalf("err %v", err)
	}
}

// An instance verified before tools were pinned has none stored: the run
// lists them once over MCP and pins the snapshot (ADR-0032).
func TestRunToolsPinsAnUnpinnedInstanceOverMCP(t *testing.T) {
	f, fake := newVerifyFixture(t, http.DefaultTransport)
	f.svc.d.Connections = store.OpenAPI{}
	ctx := context.Background()
	specID := f.spec(t, catalogapi.MCPSpec{Name: "fs", Cmd: []any{"node", "server.js"}})
	v, err := f.svc.CreateInstance(ctx, f.c, InstanceCreate{Name: "fs", ServerSpecID: specID, JSONSpec: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	id := v.Instance.ID
	if got := f.waitTerminal(t, id); got.Status != domain.VerifySucceeded {
		t.Fatalf("verification %+v", got)
	}
	globalExec(t, f.pools, `UPDATE mcp_server_instances SET tools = NULL WHERE id = $1`, id)
	fake.mu.Lock()
	fake.methods = nil
	fake.mu.Unlock()

	got, err := f.svc.RunTools(ctx, api.RunToolsRequest{WorkspaceID: f.c.Workspace.ID(), UserID: "owner", AgentID: "a1",
		Agent: runsapi.AgentSpec{ID: "a1", Tools: []runsapi.ToolConfig{{Type: "mcp", Name: id}}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Tools) != 1 || got.Tools[0].Name != "mcp__fs__echo" || got.Bindings["mcp__fs__echo"].MCP.RawName != "echo" {
		t.Fatalf("tools %+v", got.Tools)
	}
	fake.mu.Lock()
	listed := slices.Contains(fake.methods, "tools/list")
	fake.mu.Unlock()
	if !listed {
		t.Fatal("the server was never asked for its tools")
	}
	inst, err := f.svc.instanceIn(ctx, f.c.Workspace, uuid.MustParse(id))
	if err != nil || !inst.ToolsSet || len(inst.Tools) != 1 {
		t.Fatalf("snapshot not pinned: %+v %v", inst.Tools, err)
	}

	fake.mu.Lock()
	fake.methods = nil
	fake.mu.Unlock()
	if _, err := f.svc.RunTools(ctx, api.RunToolsRequest{WorkspaceID: f.c.Workspace.ID(), UserID: "owner", AgentID: "a1",
		Agent: runsapi.AgentSpec{ID: "a1", Tools: []runsapi.ToolConfig{{Type: "mcp", Name: id}}}}); err != nil {
		t.Fatal(err)
	}
	fake.mu.Lock()
	defer fake.mu.Unlock()
	if len(fake.methods) != 0 {
		t.Fatalf("a pinned instance was listed live: %v", fake.methods)
	}
}

// Python resolved an OpenAPI config with no openapi_connection_id by name
// (or by an id in its name) across the workspace with no permission check,
// so a run could call through someone's personal connection; only a
// connection the agent may use (or a platform one) resolves now.
func TestRunToolsOpenAPIResolvesOnlyConnectionsTheAgentMayUse(t *testing.T) {
	f := newRTFixture()
	id := uuid.New()
	f.conns.rows[id] = domain.Connection{ID: id.String(), Name: "Weather", AvailableTools: []domain.Tool{{Name: "forecast"}}}
	for _, c := range []runsapi.ToolConfig{{Type: "openapi", Name: "Weather"}, {Type: "openapi", Name: id.String()}} {
		_, err := f.resolve(t, runsapi.AgentSpec{Name: "bot", Tools: []runsapi.ToolConfig{c}})
		if !errors.Is(err, api.ErrToolsRefused) || !strings.Contains(err.Error(), "was not lent") {
			t.Fatalf("%s: err %v", c.Name, err)
		}
	}
	f.graph.allowed["Agent:agent-1#"+id.String()] = true
	got, err := f.resolve(t, runsapi.AgentSpec{Tools: []runsapi.ToolConfig{{Type: "openapi", Name: "Weather"}}})
	if err != nil || got.Bindings["forecast"].OpenAPI == nil {
		t.Fatalf("lent connection: %+v %v", got.Bindings, err)
	}
	b := got.Bindings["forecast"]
	if !slices.Equal(b.PolicyNames, []string{"openapi:" + id.String() + ":forecast"}) ||
		!slices.Equal(b.RestrictingNames, []string{"forecast", "Weather", id.String()}) {
		t.Fatalf("names %v %v", b.PolicyNames, b.RestrictingNames)
	}
}

// Python checked use_connection only when the run's tools were resolved, so a
// connection withdrawn from the agent mid-run stayed callable; each call now
// re-checks it (the agent's own right, or the starter's for an instance
// selected for the run), a platform instance excepted.
func TestMCPCallRechecksUseAtCallTime(t *testing.T) {
	f := newRTFixture()
	a := uuid.NewString()
	f.insts.rows[a] = domain.Instance{ID: a, Name: "b", Transport: domain.TransportBundle}
	call := func() api.MCPResult {
		t.Helper()
		res, err := f.svc.MCPTools().Call(context.Background(), api.MCPCall{WorkspaceID: f.ws, UserID: "u1", AgentID: "agent-1", InstanceID: a, Tool: "x"})
		if err != nil {
			t.Fatal(err)
		}
		return res
	}
	if res := call(); res.Success || !strings.Contains(res.Error, "may not call through") {
		t.Fatalf("unlent: %+v", res)
	}
	for _, grant := range []string{"Agent:agent-1#" + a, "User:u1#" + a} {
		clear(f.graph.allowed)
		f.graph.allowed[grant] = true
		if res := call(); strings.Contains(res.Error, "may not call through") || !strings.Contains(res.Result, "does not expose tool") {
			t.Fatalf("%s: %+v", grant, res)
		}
	}
	clear(f.graph.allowed)
	managed := domain.ManagedByPlatform
	inst := f.insts.rows[a]
	inst.ManagedBy = &managed
	f.insts.rows[a] = inst
	if res := call(); strings.Contains(res.Error, "may not call through") {
		t.Fatalf("platform: %+v", res)
	}
}
