package service

import (
	"context"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

type describedModels map[string]modelsapi.ResolvedModel

func (d describedModels) Describe(_ context.Context, _ modelsapi.Principal, id, kind string) (modelsapi.ResolvedModel, error) {
	m, ok := d[id]
	if !ok {
		return modelsapi.ResolvedModel{}, modelsapi.ErrNotFound
	}
	if kind != m.DisplayName {
		return modelsapi.ResolvedModel{}, modelsapi.ErrKindMismatch
	}
	return m, nil
}

type fakeDecider struct{ reply modelsapi.DecisionReply }

func (f fakeDecider) Decide(context.Context, modelsapi.Principal, modelsapi.Decision) (modelsapi.DecisionReply, error) {
	return f.reply, nil
}

func TestAModelCallOutsideARunIsHeldChargedAndLedgeredForItsAgent(t *testing.T) {
	d := openDB(t)
	p, _ := seed(t, d)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	price := money.MustParse("0.001")
	held := money.MustParse("2")
	charged := money.MustParse("0.4")
	bill := &fakeBilling{hold: money.HoldDecision{Allowed: true, HoldID: "h1", Amount: &held, Currency: "EUR"}, quote: &charged}
	models := &fakeModels{reply: modelsapi.Reply{Content: "  {\"verdict\": \"met\", \"reason\": \"x\"}  ", Usage: modelsapi.Usage{Total: 10}, ProviderCostUSD: money.MustParse("0.3")}}
	described := describedModels{
		"chat":     {ModelID: "chat", ModelName: "gpt", DisplayName: modelsapi.KindChat, ManagedBy: "platform", Prices: modelsapi.ModelPrices{Input: &price, Output: &price}},
		"decision": {ModelID: "decision", ModelName: "s1", DisplayName: modelsapi.KindDecision},
	}
	s := New(Deps{DB: d, Pricing: eurPricing{}, Billing: bill, Models: models, Describer: described, Log: quiet(),
		Decider: fakeDecider{reply: modelsapi.DecisionReply{Answers: map[string]map[string]any{"q": {"type": "choice", "choice": "true"}}}},
		Caps:    fixedBudget{b: &governanceapi.Budget{}}})
	who := api.ModelCallFor{UserID: p.UserID, AgentID: p.AgentID, Purpose: "trigger_condition", TriggerID: "t1"}

	answer, err := s.Chat(context.Background(), ws, who, api.ChatOnce{ModelID: "chat", Prompt: "is it urgent?", MaxTokens: 1000, Temperature: 0.1})
	if err != nil || answer != `{"verdict": "met", "reason": "x"}` || !models.calls[0].Funded || *models.calls[0].Temperature != 0.1 {
		t.Fatalf("chat %q %v", answer, err)
	}
	if n := count(t, d, p, `SELECT count(*) FROM cost_entries WHERE task_id IS NULL AND agent_id = $1 AND subject_id = 'chat'
		AND amount = 0.4 AND payer = 'platform' AND evidence->>'purpose' = 'trigger_condition' AND evidence->>'trigger_id' = 't1' AND evidence->>'hold_id' = 'h1'`, p.AgentID); n != 1 {
		t.Fatalf("%d chat lines", n)
	}

	answers, err := s.Decide(context.Background(), ws, who, api.DecideOnce{ModelID: "decision", State: map[string]any{}, Questions: map[string]any{"q": map[string]any{}}})
	if err != nil || answers["q"]["choice"] != "true" {
		t.Fatalf("decide %v %v", answers, err)
	}
	if n := count(t, d, p, `SELECT count(*) FROM cost_entries WHERE subject_id = 'decision' AND agent_id = $1 AND amount = 0 AND (evidence->>'cost_unknown')::bool`, p.AgentID); n != 1 {
		t.Fatalf("%d unknown-cost lines", n)
	}

	_, err = s.Chat(context.Background(), ws, who, api.ChatOnce{ModelID: "decision", Prompt: "x", MaxTokens: 10})
	var failed *api.ModelCallFailed
	if !errors.As(err, &failed) {
		t.Fatalf("wrong kind = %v", err)
	}

	cap := money.MustParse("0.1")
	s.d.Caps = fixedBudget{b: &governanceapi.Budget{MonthlySpendCapUSD: &cap}}
	_, err = s.Chat(context.Background(), ws, who, api.ChatOnce{ModelID: "chat", Prompt: "x", MaxTokens: 10})
	var refused *api.ModelCallRefused
	if !errors.As(err, &refused) || refused.Msg != "Workspace monthly spend cap reached (0.400000000000 EUR/0.1 EUR)" || len(models.calls) != 1 {
		t.Fatalf("capped = %v", err)
	}
}
