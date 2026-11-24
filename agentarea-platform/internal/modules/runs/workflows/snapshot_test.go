package workflows

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	govapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// pythonSnapshot is a governance_snapshot as task_service.py stores it.
const pythonSnapshot = `{
 "requested_policy": {"budget": {"run_budget_usd": "1.50"}},
 "requested_execution": {},
 "resolved_execution": {"max_model_turns": 25},
 "effective_policy": {
  "budget": {"monthly_spend_cap_usd": "50", "agent_monthly_spend_cap_usd": "20", "run_budget_usd": "1.50",
   "service_budget_usd": "3", "spend_caps": [{"amount_usd": "10", "own_agent": true, "category": "llm"}]},
  "tokens": {"max_tokens": 100000, "max_tokens_per_call": 8000},
  "execution": {"max_model_turns": 25, "max_tool_calls_per_turn": 10, "max_tool_calls_total": 100},
  "tools": {"denied": []},
  "approval": {"escalation_rules": [], "approvers": [], "approvers_by_tool": {}},
  "content_safety": {"prompt_injection_detection_enabled": true, "output_sanitizer_enabled": false},
  "source_policy_ids": ["p1"], "resolver_version": "policy-resolver-v1"},
 "limit_ceilings": {"budget_exceeded": "1.50"},
 "resolved_at": "2026-11-10T12:00:00.123456+00:00",
 "revision": 1
}`

func runFromSnapshot(t *testing.T, raw []byte) AgentRunRequest {
	t.Helper()
	var snap map[string]any
	if err := json.Unmarshal(raw, &snap); err != nil {
		t.Fatal(err)
	}
	req, err := RunRequestFromTask("ws", store.StoredTask{ID: "t1", Metadata: map[string]any{"governance_snapshot": snap}})
	if err != nil {
		t.Fatal(err)
	}
	return req
}

func TestRunReadsThePythonStoredSnapshot(t *testing.T) {
	p := runFromSnapshot(t, []byte(pythonSnapshot)).Policy
	b := p.Budget
	if b == nil || b.RunBudget == nil || b.RunBudget.String() != money.MustParse("1.50").String() ||
		b.MonthlySpendCap == nil || b.AgentMonthlySpendCap == nil || b.ServiceBudget == nil {
		t.Fatalf("budget %+v", b)
	}
	if len(b.SpendCaps) != 1 || b.SpendCaps[0].Amount.String() != "10" || !b.SpendCaps[0].OwnAgent || b.SpendCaps[0].Category != "llm" {
		t.Fatalf("spend caps %+v", b.SpendCaps)
	}
	if p.ContentSafety == nil || p.ContentSafety.PromptInjectionDetection == nil || !*p.ContentSafety.PromptInjectionDetection {
		t.Fatalf("content safety %+v", p.ContentSafety)
	}
	if p.Execution == nil || p.Execution.MaxModelTurns == nil || *p.Execution.MaxModelTurns != 25 {
		t.Fatalf("execution %+v", p.Execution)
	}
}

func TestRunReadsTheGoStoredSnapshot(t *testing.T) {
	run, capAmount, on := money.MustParse("2"), money.MustParse("7"), true
	turns := int64(5)
	snap := govapi.Snapshot{
		EffectivePolicy: govapi.Policy{
			Budget:        &govapi.Budget{RunBudgetUSD: &run, SpendCaps: []govapi.SpendCap{{AmountUSD: capAmount}}},
			Execution:     &govapi.Execution{MaxModelTurns: &turns},
			ContentSafety: &govapi.ContentSafety{PromptInjectionDetectionEnabled: &on},
		},
		ResolvedAt: time.Now(), Revision: 1,
	}
	raw, err := snap.MarshalJSON()
	if err != nil {
		t.Fatal(err)
	}
	req := runFromSnapshot(t, raw)
	p := req.Policy
	if p.Budget == nil || p.Budget.RunBudget == nil || p.Budget.RunBudget.String() != "2" ||
		len(p.Budget.SpendCaps) != 1 || p.Budget.SpendCaps[0].Amount.String() != "7" {
		t.Fatalf("budget %+v", p.Budget)
	}
	if p.ContentSafety == nil || p.ContentSafety.PromptInjectionDetection == nil || !*p.ContentSafety.PromptInjectionDetection {
		t.Fatalf("content safety %+v", p.ContentSafety)
	}
	again, err := json.Marshal(req.Governance)
	if err != nil {
		t.Fatal(err)
	}
	if back := runFromSnapshot(t, again).Policy; back.Budget == nil || back.Budget.RunBudget == nil || back.Budget.RunBudget.String() != "2" {
		t.Fatalf("the run's own snapshot does not read back: %s", again)
	}
}
