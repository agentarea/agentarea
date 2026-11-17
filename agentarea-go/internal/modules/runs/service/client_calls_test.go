package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
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
