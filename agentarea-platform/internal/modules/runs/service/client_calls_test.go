package service

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

type fixedCosts struct {
	cost *api.ToolCost
	err  error
}

func (f fixedCosts) ToolCost(context.Context, scope.Workspace, api.ToolBinding) (*api.ToolCost, error) {
	return f.cost, f.err
}

type fixedBudget struct{ b *governanceapi.Budget }

func (f fixedBudget) CurrentBudget(context.Context, governanceapi.RunPrincipal) (*governanceapi.Budget, error) {
	return f.b, nil
}

func TestAClientCallIsMeteredToItsClientAndCappedByIt(t *testing.T) {
	d := openDB(t)
	p, _ := seed(t, d)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	client, connection := uuid.NewString(), uuid.NewString()
	cap := money.MustParse("0.5")
	s := New(Deps{DB: d, Pricing: eurPricing{}, Log: quiet(),
		ToolCosts: fixedCosts{cost: &api.ToolCost{Payer: "workspace", Connector: "acme",
			Declaration: map[string]any{"source": "rate", "rate": map[string]any{"amount": "0.3", "currency": "EUR"}}}},
		Caps: fixedBudget{b: &governanceapi.Budget{SpendCaps: []governanceapi.SpendCap{{AmountUSD: cap, ClientID: &client}}}}})
	call := api.ClientToolCall{UserID: p.UserID, ClientID: client, ToolName: "acme__search", Args: map[string]any{"q": "x"},
		Binding: api.ToolBinding{Source: "mcp", MCP: &api.MCPBinding{InstanceID: connection, RawName: "search"}}}
	var audited []string
	ran := 0
	hooks := api.ClientCallHooks{
		Audit: func(_ context.Context, refusal string) error { audited = append(audited, refusal); return nil },
		Invoke: func(context.Context) (api.ClientToolAnswer, error) {
			ran++
			return api.ClientToolAnswer{Success: true}, nil
		},
	}
	if refusal, err := s.RunClientCall(context.Background(), ws, call, hooks); err != nil || refusal != "" {
		t.Fatalf("first %q %v", refusal, err)
	}
	if n := count(t, d, p, `SELECT count(*) FROM cost_entries WHERE client_id = $1 AND task_id IS NULL AND subject_id = $2 AND amount = 0.3`, client, connection); n != 1 {
		t.Fatalf("%d client lines", n)
	}
	refusal, err := s.RunClientCall(context.Background(), ws, call, hooks)
	if err != nil || refusal != "client spend cap of 0.5 EUR would be exceeded: 0.3 EUR spent this month, this call costs 0.3 EUR" {
		t.Fatalf("capped %q %v", refusal, err)
	}
	if ran != 1 || len(audited) != 2 || audited[0] != "" || audited[1] != refusal {
		t.Fatalf("ran %d audited %q", ran, audited)
	}
	other := call
	other.ClientID = uuid.NewString()
	if refusal, err := s.RunClientCall(context.Background(), ws, other, hooks); err != nil || refusal != "" {
		t.Fatalf("another client's call was capped: %q %v", refusal, err)
	}

	s.d.ToolCosts = fixedCosts{err: &api.CostDeclarationError{Msg: "acme does not allow calls paid by the workspace"}}
	if refusal, err := s.RunClientCall(context.Background(), ws, call, hooks); err != nil ||
		refusal != "the cost of this call cannot be known: acme does not allow calls paid by the workspace" {
		t.Fatalf("unpriced %q %v", refusal, err)
	}
	s.d.ToolCosts = fixedCosts{err: errors.New("db down")}
	if _, err := s.RunClientCall(context.Background(), ws, call, hooks); err == nil {
		t.Fatal("a failed price lookup ran the call")
	}
}

// runnerTask stores a task a runner's turn acts in, run under policy.
func runnerTask(t *testing.T, s *Service, p Principal, client string, policy api.Policy) string {
	t.Helper()
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	snap, err := json.Marshal(api.GovernanceSnapshot{Revision: 1, EffectivePolicy: policy})
	if err != nil {
		t.Fatal(err)
	}
	var stored map[string]any
	if err := json.Unmarshal(snap, &stored); err != nil {
		t.Fatal(err)
	}
	id := uuid.NewString()
	if err := s.d.DB.Write(context.Background(), ws, func(ctx context.Context, tx db.Session) error {
		return store.Runs{}.CreateTask(ctx, tx, store.NewTask{ID: id, AgentID: p.AgentID, Description: "d", Status: "running", CreatedBy: p.UserID,
			Metadata: map[string]any{"runner_client_id": client, "governance_snapshot": stored}}, time.Now())
	}); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestARunnerTurnsCallIsHeldToItsRunsPolicyAndBudget(t *testing.T) {
	d := openDB(t)
	p, _ := seed(t, d)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	client, connection := uuid.NewString(), uuid.NewString()
	s := New(Deps{DB: d, Pricing: eurPricing{}, Log: quiet(),
		ToolCosts: fixedCosts{cost: &api.ToolCost{Payer: "workspace", Connector: "acme",
			Declaration: map[string]any{"source": "rate", "rate": map[string]any{"amount": "0.3", "currency": "EUR"}}}}})
	task := runnerTask(t, s, p, client, api.Policy{
		Budget:   &api.BudgetPolicy{RunBudget: dec("0.5")},
		Tools:    &api.ToolsPolicy{Denied: []string{"mcp:" + connection + ":delete"}},
		Approval: &api.ApprovalPolicy{EscalationRules: []string{"mcp:" + connection + ":send"}},
	})
	call := func(raw string) api.ClientToolCall {
		return api.ClientToolCall{UserID: p.UserID, ClientID: client, TaskID: task, ToolName: "acme__" + raw, Args: map[string]any{"q": "x"},
			Binding: api.ToolBinding{Source: "mcp", PolicyNames: []string{"mcp:" + connection + ":" + raw}, MCP: &api.MCPBinding{InstanceID: connection, RawName: raw}}}
	}
	var audited []string
	ran := 0
	hooks := api.ClientCallHooks{
		Audit: func(_ context.Context, refusal string) error { audited = append(audited, refusal); return nil },
		Invoke: func(context.Context) (api.ClientToolAnswer, error) {
			ran++
			return api.ClientToolAnswer{Success: true}, nil
		},
	}
	ctx := context.Background()

	if refusal, err := s.RunClientCall(ctx, ws, call("delete"), hooks); err != nil || refusal != "tool 'acme__delete' is denied by policy" {
		t.Fatalf("denied %q %v", refusal, err)
	}
	if refusal, err := s.RunClientCall(ctx, ws, call("send"), hooks); err != nil || !strings.HasPrefix(refusal, "tool 'acme__send' requires approval") {
		t.Fatalf("unapproved %q %v", refusal, err)
	}
	if ran != 0 || len(audited) != 2 || audited[0] == "" || audited[1] == "" {
		t.Fatalf("a refused call ran %d, audited %q", ran, audited)
	}
	approved := call("send")
	approved.Approved = true
	if refusal, err := s.RunClientCall(ctx, ws, approved, hooks); err != nil || refusal != "" {
		t.Fatalf("approved %q %v", refusal, err)
	}
	if n := count(t, d, p, `SELECT count(*) FROM cost_entries WHERE task_id = $1 AND client_id = $2 AND amount = 0.3`, task, client); n != 1 {
		t.Fatalf("%d lines on the run", n)
	}
	refusal, err := s.RunClientCall(ctx, ws, call("search"), hooks)
	if err != nil || !strings.HasPrefix(refusal, "run spend cap of 0.5 EUR would be exceeded") {
		t.Fatalf("over budget %q %v", refusal, err)
	}
	if ran != 1 {
		t.Fatalf("ran %d", ran)
	}

	outside := call("search")
	outside.TaskID = ""
	if refusal, err := s.RunClientCall(ctx, ws, outside, hooks); err != nil || refusal != "" {
		t.Fatalf("a call outside a run was held to a run's budget: %q %v", refusal, err)
	}
	unknown := call("search")
	unknown.TaskID = uuid.NewString()
	if refusal, err := s.RunClientCall(ctx, ws, unknown, hooks); err != nil || refusal == "" {
		t.Fatalf("a call in an unknown run ran: %q %v", refusal, err)
	}
}
