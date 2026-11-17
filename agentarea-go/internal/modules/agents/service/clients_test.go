package service

import (
	"context"
	"errors"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func clientOpenDB(t *testing.T) db.Database {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pass, _ := u.User.Password()
	pools, err := db.Open(context.Background(), db.Config{
		Host: u.Hostname(), Port: port, Name: strings.TrimPrefix(u.Path, "/"), User: u.User.Username(), Password: pass,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 4, PoolTimeout: 10 * time.Second,
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

// clientFakeGraph grants every relation on the resources written to it, plus deny-listed exceptions.
type clientFakeGraph struct {
	mu      sync.Mutex
	objects map[string]bool
	deny    map[string]bool
}

func (g *clientFakeGraph) Check(_ context.Context, _, _, _, id string) (bool, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.objects[id] && !g.deny[id], nil
}

func (g *clientFakeGraph) ListObjects(context.Context, string, string, string) ([]string, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	var out []string
	for id := range g.objects {
		out = append(out, id)
	}
	return out, nil
}

func (g *clientFakeGraph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	for _, w := range writes {
		if id, ok := strings.CutPrefix(w.Object, authz.TypeResource+":"); ok {
			g.objects[id] = true
		}
	}
	return nil
}

type clientFakeConnections struct{ names map[string]string }

func (f clientFakeConnections) MCPInstanceNames(_ context.Context, _ scope.Workspace, ids []string) (map[string]string, error) {
	out := map[string]string{}
	for _, id := range ids {
		if n, ok := f.names[id]; ok {
			out[id] = n
		}
	}
	return out, nil
}

func (f clientFakeConnections) MCPInstance(_ context.Context, _ scope.Workspace, id string) (bool, bool, error) {
	n, ok := f.names[id]
	return ok, n == "platform", nil
}

func (f clientFakeConnections) OpenAPIConnection(ctx context.Context, ws scope.Workspace, id string) (bool, bool, error) {
	return f.MCPInstance(ctx, ws, id)
}

func (f clientFakeConnections) OpenAPIConnectionNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	return f.MCPInstanceNames(ctx, ws, ids)
}

type clientFakePresence struct{}

func (clientFakePresence) Online(_ context.Context, ids []string) (map[string]bool, error) {
	out := map[string]bool{}
	for _, id := range ids {
		out[id] = true
	}
	return out, nil
}

func clientSetup(t *testing.T) (db.Database, *clientFakeGraph, *Service, authn.Caller) {
	t.Helper()
	d := clientOpenDB(t)
	g := &clientFakeGraph{objects: map[string]bool{}, deny: map[string]bool{}}
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	s := New(Deps{DB: d, Graph: g, Presence: clientFakePresence{}})
	return d, g, s, authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws}
}

func clientExec(t *testing.T, d db.Database, ws scope.Workspace, sql string, args ...any) {
	t.Helper()
	if err := d.Write(context.Background(), ws, func(ctx context.Context, s db.Session) error {
		_, err := s.Q().Exec(ctx, sql, args...)
		return err
	}); err != nil {
		t.Fatal(err)
	}
}

func TestClientsLifecycle(t *testing.T) {
	ctx := context.Background()
	d, g, s, c := clientSetup(t)
	mcpOwn, mcpPlatform, mcpForeign, conn := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	x := NewClients(s, ClientPorts{APIURL: "https://api.test/", MCPNames: clientFakeConnections{names: map[string]string{mcpOwn: "own", mcpPlatform: "platform", conn: "zeta"}},
		Connections: clientFakeConnections{names: map[string]string{mcpOwn: "own", mcpPlatform: "platform", conn: "zeta"}}})
	desc := "d"
	v, err := x.Create(ctx, c, "Codex", &desc, "codex")
	if err != nil {
		t.Fatal(err)
	}
	id := v.ID
	if v.EndpointURL != "https://api.test/mcp/clients/"+id.String() || !v.HasRunner || !v.Online || !v.Sandbox || len(v.Skills) != 0 {
		t.Errorf("%+v", v)
	}
	other, err := x.Create(ctx, c, "Hidden", nil, "harness")
	if err != nil {
		t.Fatal(err)
	}
	g.mu.Lock()
	delete(g.objects, other.ID.String())
	g.mu.Unlock()
	if vs, err := x.List(ctx, c, 100, 0); err != nil || len(vs) != 1 || vs[0].ID != id {
		t.Fatalf("readable only %v %v", vs, err)
	}

	model := "gpt-5"
	domains := []string{"pypi.org"}
	v, err = x.Update(ctx, c, id, ClientPatch{DefaultModel: Set[string]{Set: true, Value: &model}, AllowDomains: &domains, Sandbox: ptr(false)})
	if err != nil || *v.DefaultModel != "gpt-5" || v.Sandbox || string(v.AllowDomains) != `["pypi.org"]` || *v.Description != "d" {
		t.Fatalf("update %+v %v", v, err)
	}
	if _, err := x.Update(ctx, c, uuid.New(), ClientPatch{}); !errors.Is(err, ErrClientNotFound) {
		t.Errorf("update of nothing: %v", err)
	}

	var nf *domain.NotFoundError
	if err := x.AddSkill(ctx, c, id, uuid.NewString()); !errors.As(err, &nf) || nf.Message != "Skill not found" {
		t.Errorf("foreign skill: %v", err)
	}
	if err := x.AddSkill(ctx, c, uuid.New(), "x"); !errors.As(err, &nf) || nf.Message != "Client not found" {
		t.Errorf("unknown client first: %v", err)
	}
	if err := x.AddMCPInstance(ctx, c, id, mcpForeign, nil, nil); !errors.As(err, &nf) || nf.Message != "MCP instance not found" {
		t.Errorf("invisible instance: %v", err)
	}
	var perm *PermissionError
	if err := x.AddMCPInstance(ctx, c, id, mcpOwn, nil, nil); !errors.As(err, &perm) ||
		perm.Msg != "This MCP instance is someone else's personal connection; its owner can share it with the workspace." {
		t.Errorf("personal instance: %v", err)
	}
	for _, inst := range []string{mcpOwn, mcpPlatform} {
		clientExec(t, d, c.Workspace, `INSERT INTO mcp_server_instances (id, server_spec_id, name, workspace_id, created_by, transport) VALUES ($1, 's', 'n', $2, 'u', 'url')`, inst, c.Workspace.ID())
	}
	g.mu.Lock()
	g.objects[mcpOwn] = true
	g.mu.Unlock()
	prefix := "gh"
	if err := x.AddMCPInstance(ctx, c, id, mcpOwn, &prefix, &[]string{"a"}); err != nil {
		t.Fatal(err)
	}
	if err := x.AddMCPInstance(ctx, c, id, mcpPlatform, nil, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := x.SetToolset(ctx, c, id, "runs", &[]string{"cancel"}); err != nil {
		t.Fatal(err)
	}
	v, err = x.Get(ctx, c, id)
	if err != nil || len(v.MCPInstances) != 2 || len(v.Toolsets) != 1 || v.Toolsets[0].Toolset != "agentarea/runs" || string(v.Toolsets[0].DisabledMethods) != `["cancel"]` {
		t.Fatalf("%+v %v", v, err)
	}
	if err := x.RemoveToolset(ctx, c, id, "agentarea/runs"); err != nil {
		t.Fatal(err)
	}

	audit := &fakeAudit{}
	s.UseAudit(audit)
	agent, err := x.HarnessAgent(ctx, c, id)
	if err != nil || agent.Agent.Name != "Codex" || *agent.Agent.HarnessClientID != id.String() || agent.Client == nil || !agent.Online {
		t.Fatalf("harness agent %+v %v", agent, err)
	}
	again, err := x.HarnessAgent(ctx, c, id)
	if err != nil || again.Agent.ID != agent.Agent.ID {
		t.Errorf("made once: %v %v", again.Agent.ID, err)
	}
	if len(audit.recs) != 1 || audit.recs[0].Action != "agent.create" || audit.recs[0].ResourceID != agent.Agent.ID {
		t.Errorf("harness agent audit: %+v", audit.recs)
	}
	s.UseAudit(nil)
	var inv *domain.InvalidError
	if _, err := x.HarnessAgent(ctx, c, other.ID); !errors.As(err, &inv) || inv.Code != domain.CodeInvalidClientID {
		t.Errorf("not a runner: %v", err)
	}
	var inUse *ClientInUseError
	if err := x.Delete(ctx, c, id); !errors.As(err, &inUse) || inUse.Error() != "1 agent(s) run on this client; move them to a model or another client before deleting it" {
		t.Errorf("in use: %v", err)
	}
	if _, _, err := x.IssueRunnerKey(ctx, c, other.ID); !errors.Is(err, ErrClientNoRunner) {
		t.Errorf("no runner: %v", err)
	}
	var unwired *UnwiredError
	if _, _, err := x.IssueRunnerKey(ctx, c, id); !errors.As(err, &unwired) {
		t.Errorf("keys unwired: %v", err)
	}
	clientExec(t, d, c.Workspace, `DELETE FROM agents WHERE harness_client_id = $1`, id)
	if err := x.Delete(ctx, c, id); err != nil {
		t.Fatal(err)
	}
	if err := x.Delete(ctx, c, id); !errors.Is(err, ErrClientNotFound) {
		t.Errorf("deleted twice: %v", err)
	}
}

type taskDefFakeTriggers struct{ n int64 }

func (f taskDefFakeTriggers) CountByTaskDefinition(context.Context, scope.Workspace, string) (int64, error) {
	return f.n, nil
}

type taskDefFakeRunner struct{ got *TaskDefRun }

func (f taskDefFakeRunner) Start(_ context.Context, _ authn.Caller, run TaskDefRun) (any, error) {
	*f.got = run
	return "started", nil
}

func TestTaskDefsLifecycle(t *testing.T) {
	ctx := context.Background()
	d, g, s, c := clientSetup(t)
	agent, archived := uuid.New(), uuid.New()
	for a, st := range map[uuid.UUID]string{agent: "active", archived: "archived"} {
		clientExec(t, d, c.Workspace, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'A', $2, $3, 'u', $4)`, a, st, c.Workspace.ID(), a.String())
	}
	var run TaskDefRun
	x := NewTaskDefs(s, TaskDefPorts{Runner: taskDefFakeRunner{got: &run}})
	var inv *TaskDefInvalidError
	if _, err := x.Create(ctx, c, TaskDefCreate{Name: "n", Description: "d", AgentID: archived, Parameters: []byte(`{}`)}); !errors.As(err, &inv) ||
		inv.Msg != "Agent "+archived.String()+" is archived; restore it first" {
		t.Errorf("archived: %v", err)
	}
	if _, err := x.Create(ctx, c, TaskDefCreate{Name: "n", Description: "d", AgentID: uuid.New(), Parameters: []byte(`{}`)}); !errors.As(err, &inv) {
		t.Errorf("unknown agent: %v", err)
	}
	def, err := x.Create(ctx, c, TaskDefCreate{Name: "n", Description: "d", AgentID: agent, Parameters: []byte(`{"a": 1, "b": 2}`)})
	if err != nil || def.Name != "n" || def.CreatedAt.IsZero() {
		t.Fatalf("%+v %v", def, err)
	}
	name := "m"
	if def, err = x.Update(ctx, c, def.ID, TaskDefPatch{Name: &name, AgentID: &agent}); err != nil || def.Name != "m" {
		t.Fatalf("same agent is no change: %+v %v", def, err)
	}
	var unwired *UnwiredError
	if _, err := x.Update(ctx, c, def.ID, TaskDefPatch{AgentID: &archived}); !errors.As(err, &inv) {
		t.Errorf("agent checked first: %v", err)
	}
	other := uuid.New()
	clientExec(t, d, c.Workspace, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'B', 'active', $2, 'u', $3)`, other, c.Workspace.ID(), other.String())
	if _, err := x.Update(ctx, c, def.ID, TaskDefPatch{AgentID: &other}); !errors.As(err, &unwired) {
		t.Errorf("triggers unwired: %v", err)
	}
	if _, err := x.Run(ctx, c, def.ID, nil, "api"); !errors.Is(err, ErrDenied) {
		t.Errorf("execute on the agent: %v", err)
	}
	g.mu.Lock()
	g.objects[agent.String()] = true
	g.mu.Unlock()
	out, err := x.Run(ctx, c, def.ID, wirejson.Object{{Key: "b", Value: "x"}, {Key: "c", Value: true}}, "mcp")
	if err != nil || out != "started" || run.AgentID != agent.String() || run.CreatedVia != "mcp" {
		t.Fatalf("%v %v %+v", out, err, run)
	}
	if raw, _ := wirejson.Marshal(run.Parameters, wirejson.Compact); string(raw) != `{"a":1,"b":"x","c":true}` {
		t.Errorf("merged %s", raw)
	}
	var nf *TaskDefNotFoundError
	if _, err := x.Run(ctx, c, uuid.New(), nil, "api"); !errors.As(err, &nf) {
		t.Errorf("unknown: %v", err)
	}
	busy := NewTaskDefs(s, TaskDefPorts{Triggers: taskDefFakeTriggers{n: 2}})
	var inUse *TaskDefInUseError
	if _, err := busy.Delete(ctx, c, def.ID); !errors.As(err, &inUse) || inUse.Error() != "2 trigger(s) run this saved task; point them elsewhere before you delete it" {
		t.Errorf("in use: %v", err)
	}
	free := NewTaskDefs(s, TaskDefPorts{Triggers: taskDefFakeTriggers{}})
	if ok, err := free.Delete(ctx, c, def.ID); err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if ok, _ := free.Delete(ctx, c, def.ID); ok {
		t.Error("deleted twice")
	}
}

func TestHarnessAgentMadeOnceUnderConcurrentFirstUse(t *testing.T) {
	ctx := context.Background()
	_, _, s, c := clientSetup(t)
	x := NewClients(s, ClientPorts{APIURL: "https://api.test/"})
	v, err := x.Create(ctx, c, "Codex", nil, "codex")
	if err != nil {
		t.Fatal(err)
	}
	id := v.ID
	ids := make([]string, 4)
	errs := make([]error, 4)
	var wg sync.WaitGroup
	for i := range ids {
		wg.Go(func() {
			a, err := x.HarnessAgent(ctx, c, id)
			ids[i], errs[i] = a.Agent.ID, err
		})
	}
	wg.Wait()
	for i := range ids {
		if errs[i] != nil || ids[i] != ids[0] {
			t.Fatalf("call %d: %s %v, first %s", i, ids[i], errs[i], ids[0])
		}
	}
}
