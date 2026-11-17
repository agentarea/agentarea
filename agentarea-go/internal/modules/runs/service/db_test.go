package service

import (
	"context"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func openDB(t *testing.T) db.Database {
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
	}, quiet())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

// seed makes a workspace with one running task of the principal's agent.
func seed(t *testing.T, d db.Database) (Principal, string) {
	t.Helper()
	p := Principal{WorkspaceID: uuid.NewString(), UserID: "user-1", AgentID: uuid.NewString()}
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		t.Fatal(err)
	}
	taskID := uuid.NewString()
	err = d.Write(context.Background(), ws, func(ctx context.Context, s db.Session) error {
		if _, err := s.Q().Exec(ctx, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, p.WorkspaceID, "ws-"+p.WorkspaceID[:8]); err != nil {
			return err
		}
		return store.Runs{}.CreateTask(ctx, s, store.NewTask{ID: taskID, AgentID: p.AgentID, Description: "d", Status: "running", CreatedBy: p.UserID}, time.Now())
	})
	if err != nil {
		t.Fatal(err)
	}
	return p, taskID
}

func count(t *testing.T, d db.Database, p Principal, query string, args ...any) int {
	t.Helper()
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	s, release, err := d.Read(context.Background(), ws)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	var n int
	if err := s.Q().QueryRow(context.Background(), query, args...).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func TestRecordWritesEverythingOnceAndPublishesEachRow(t *testing.T) {
	d := openDB(t)
	p, taskID := seed(t, d)
	ev, audit, b := &fakeEvents{}, &fakeAudit{}, newMemBlob()
	s := New(Deps{DB: d, Blob: b, Events: ev, Audit: audit, Pricing: eurPricing{}, Log: quiet()})
	it := 1
	big := strings.Repeat("y", domain.BodyOffloadBytes+10)
	llm := uuid.NewString()
	in := RecordInput{TaskID: taskID, ExecutionID: "e1", Rows: []domain.Entry{
		{Seq: 0, EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "user", Content: "hi"},
		{Seq: 1, EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "assistant", Content: big},
		{Seq: 2, EventID: llm, Kind: domain.KindEvent, Name: domain.EventLLMCompleted, Iteration: &it, Meta: map[string]any{
			"task_id": taskID, "agent_id": p.AgentID, "model_id": "m1", "cost": "0.25",
			"usage": map[string]any{"usage": map[string]any{"total_tokens": 10}},
		}},
		{Seq: 3, EventID: uuid.NewString(), Kind: domain.KindEvent, Name: domain.EventToolCall, Iteration: &it, Meta: map[string]any{
			"task_id": taskID, "agent_id": p.AgentID, "tool_name": "bash", "tool_call_id": "c1", "arguments": map[string]any{"cmd": "ls"},
		}},
	}, Status: &domain.StatusUpdate{Status: "completed", Response: "done"}}
	for range 2 {
		if _, err := s.Record(context.Background(), p, in); err != nil {
			t.Fatal(err)
		}
	}
	if n := count(t, d, p, `SELECT count(*) FROM task_conversation_entries WHERE task_id = $1`, taskID); n != 4 {
		t.Fatalf("%d log rows", n)
	}
	if n := count(t, d, p, `SELECT count(*) FROM cost_entries WHERE task_id = $1 AND category = 'model'`, taskID); n != 1 {
		t.Fatalf("%d model lines", n)
	}
	if n := count(t, d, p, `SELECT count(*) FROM tasks WHERE id = $1 AND status = 'completed' AND completed_at IS NOT NULL`, taskID); n != 1 {
		t.Fatal("the task was not completed")
	}
	if len(audit.lines) != 1 {
		t.Fatalf("audit %+v", audit.lines)
	}
	if len(b.m) != 1 {
		t.Fatalf("offloaded %d bodies, want the one over 64 KiB", len(b.m))
	}
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	window, err := s.window(context.Background(), ws, taskID, 4, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(window) != 2 || window[1].Content != big {
		t.Fatalf("window rows %d", len(window))
	}
	spent, err := s.DelegatedSpend(context.Background(), p, taskID)
	if err != nil || !spent.Equal(money.MustParse("0.25")) {
		t.Fatalf("spent %s %v", spent, err)
	}
	caps, err := s.CheckMonthlySpendCap(context.Background(), p, SpendCapInput{WorkspaceCap: dec("0.2"), LLMCaps: []api.SpendCap{{Amount: money.MustParse("0.25"), Category: "llm", OwnAgent: true}}})
	if err != nil || !caps.Exceeded || !strings.HasPrefix(caps.LLMCapMessage, "Agent monthly LLM spend cap reached (0.25") {
		t.Fatalf("caps %+v %v", caps, err)
	}
	if len(ev.submitted) == 0 || ev.submitted[0].Extensions["seq"] == "" {
		t.Fatalf("published %+v", ev.submitted)
	}
}

type fakeAgents map[string]agentsapi.Definition

func (f fakeAgents) Definition(_ context.Context, _ scope.Workspace, id string) (agentsapi.Definition, error) {
	a, ok := f[id]
	if !ok {
		return agentsapi.Definition{}, agentsapi.ErrNotFound
	}
	return a, nil
}

type fakePolicies struct{ governanceapi.RunPolicies }

func (fakePolicies) Delegation(_ context.Context, _ governanceapi.RunPrincipal, req governanceapi.DelegationRequest) (governanceapi.Policy, governanceapi.Snapshot, error) {
	b := req.RunBudget
	return governanceapi.Policy{Budget: &governanceapi.Budget{RunBudgetUSD: &b}}, governanceapi.Snapshot{Revision: 1}, nil
}

func TestCreateDelegationTaskStoresTheChildUnderItsParent(t *testing.T) {
	d := openDB(t)
	p, parent := seed(t, d)
	child := uuid.NewString()
	s := New(Deps{DB: d, Pricing: eurPricing{}, Policies: fakePolicies{}, Log: quiet(), Agents: fakeAgents{
		child: {Name: "helper", ModelID: "m1"},
	}})
	out, err := s.CreateDelegationTask(context.Background(), p, DelegationInput{ParentTaskID: parent, TargetAgentID: child, TargetAgentName: "helper", RunBudget: dec("1")})
	if err != nil || out.Status != "created" || out.Policy.Budget.RunBudget.String() != "1" {
		t.Fatalf("out %+v %v", out, err)
	}
	if n := count(t, d, p, `SELECT count(*) FROM tasks WHERE id = $1 AND parent_task_id = $2 AND origin_type = 'agent' AND status = 'submitted'`, out.TaskID, parent); n != 1 {
		t.Fatal("the child task is not stored under its parent")
	}
	missing, err := s.CreateDelegationTask(context.Background(), p, DelegationInput{ParentTaskID: parent, TargetAgentID: uuid.NewString(), RunBudget: dec("1")})
	if err != nil || missing.Status != "failed" {
		t.Fatalf("missing agent %+v %v", missing, err)
	}
}

func TestExecuteToolMetersItsDeclaredCostOnce(t *testing.T) {
	d := openDB(t)
	p, taskID := seed(t, d)
	tool := &fakeTool{out: ToolOutput{Success: true, Result: "ok"}}
	s := New(Deps{DB: d, Pricing: eurPricing{}, Tools: map[string]ToolCaller{"openapi": tool}, Log: quiet()})
	call := ToolCall{TaskID: taskID, ToolCallID: "c1", ToolName: "op",
		Binding: api.ToolBinding{Source: "openapi", OpenAPI: &api.OpenAPIBinding{ConnectionID: "k1", OperationID: "op"},
			Cost: &api.ToolCost{Payer: "workspace", Connector: "acme", VendorCost: money.MustParse("0.2"), VendorCurrency: "EUR"}}}
	first, err := s.ExecuteTool(context.Background(), p, call)
	if err != nil || !first.Cost.Equal(money.MustParse("0.2")) || !first.CostMetered || first.Replayed {
		t.Fatalf("first %+v %v", first, err)
	}
	second, err := s.ExecuteTool(context.Background(), p, call)
	if err != nil || !second.Replayed {
		t.Fatalf("retry %+v %v", second, err)
	}
	if n := count(t, d, p, `SELECT count(*) FROM cost_entries WHERE task_id = $1 AND category = 'service' AND subject_id = 'k1'`, taskID); n != 1 {
		t.Fatalf("%d tool lines", n)
	}
	call.Policy = api.Policy{Budget: &api.BudgetPolicy{RunBudget: dec("0.3")}}
	capped, err := s.ExecuteTool(context.Background(), p, call)
	if err != nil || capped.Out.Error != "run spend cap of 0.3 EUR would be exceeded: 0.2 EUR spent in this run, this call costs 0.2 EUR" {
		t.Fatalf("capped %+v %v", capped, err)
	}
}
