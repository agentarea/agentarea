package api

import (
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

func dec(t *testing.T, s string) *money.Decimal {
	t.Helper()
	d, err := money.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return &d
}

func yes() *bool { b := true; return &b }

func TestDecideToolPolicyDefaultAllows(t *testing.T) {
	for _, p := range []*Policy{nil, {}} {
		d := DecideToolPolicy(p, "send_email", ToolNames{NameAllows: true})
		if !d.Allowed() || d.Reason != "allowed by task policy" {
			t.Fatalf("got %+v", d)
		}
	}
}

func TestDecideToolPolicyDenyBeatsAllowAndApproval(t *testing.T) {
	p := &Policy{Tools: &Tools{Allowed: []string{"*"}, Denied: []string{"send_*"}}, Approval: &Approval{RequiresHumanApproval: yes()}}
	d := DecideToolPolicy(p, "send_email", ToolNames{NameAllows: true})
	if d.Action != ToolDeny || d.Reason != "tool 'send_email' is denied by policy" {
		t.Fatalf("got %+v", d)
	}
}

func TestDecideToolPolicyDenyMatchesAliasesAndRestrictingNames(t *testing.T) {
	p := &Policy{Tools: &Tools{Denied: []string{"mcp__gmail__*"}}}
	if d := DecideToolPolicy(p, "send", ToolNames{Restricting: []string{"mcp__gmail__send"}}); d.Action != ToolDeny {
		t.Fatalf("restricting name not denied: %+v", d)
	}
	if d := DecideToolPolicy(p, "send", ToolNames{Aliases: []string{"mcp__gmail__send"}}); d.Action != ToolDeny {
		t.Fatalf("alias not denied: %+v", d)
	}
}

func TestDecideToolPolicyAllowlist(t *testing.T) {
	p := &Policy{Tools: &Tools{Allowed: []string{"read_*"}}}
	if d := DecideToolPolicy(p, "read_file", ToolNames{NameAllows: true}); !d.Allowed() {
		t.Fatalf("got %+v", d)
	}
	d := DecideToolPolicy(p, "write_file", ToolNames{NameAllows: true})
	if d.Action != ToolDeny || d.Reason != "tool 'write_file' is not permitted by the policy allowlist" {
		t.Fatalf("got %+v", d)
	}
	// A bare name that does not grant (NameAllows false) needs an alias on the list.
	if d := DecideToolPolicy(p, "read_file", ToolNames{}); d.Action != ToolDeny {
		t.Fatalf("got %+v", d)
	}
	// An empty allowlist allows nothing; nil allows everything.
	if d := DecideToolPolicy(&Policy{Tools: &Tools{Allowed: []string{}}}, "x", ToolNames{NameAllows: true}); d.Action != ToolDeny {
		t.Fatalf("got %+v", d)
	}
}

func TestDecideToolPolicyApproval(t *testing.T) {
	p := &Policy{Approval: &Approval{EscalationRules: []string{"deploy_*"}}}
	d := DecideToolPolicy(p, "deploy_prod", ToolNames{NameAllows: true})
	if d.Action != ToolRequireApproval || d.Reason != "tool 'deploy_prod' requires approval" {
		t.Fatalf("got %+v", d)
	}
	if d := DecideToolPolicy(p, "read", ToolNames{NameAllows: true}); !d.Allowed() {
		t.Fatalf("got %+v", d)
	}
	all := &Policy{Approval: &Approval{RequiresHumanApproval: yes()}}
	if d := DecideToolPolicy(all, "read", ToolNames{NameAllows: true}); d.Action != ToolRequireApproval {
		t.Fatalf("got %+v", d)
	}
}

func TestFnmatch(t *testing.T) {
	for _, c := range []struct {
		name, pat string
		want      bool
	}{
		{"send_email", "send_*", true},
		{"send_email", "send_?mail", true},
		{"send_email", "Send_*", false},
		{"a.b", "a.b", true},
		{"axb", "a.b", false},
		{"tool[1]", "tool[[]1]", true},
		{"b", "[a-c]", true},
		{"d", "[!a-c]", true},
		{"a", "[!a-c]", false},
		{"x\ny", "x*", true},
	} {
		if got := Fnmatch(c.name, c.pat); got != c.want {
			t.Errorf("Fnmatch(%q, %q) = %v", c.name, c.pat, got)
		}
	}
}

func TestCallerCanApproveOnlyUserRefs(t *testing.T) {
	if !CallerCanApprove(nil, "alice") {
		t.Fatal("no approvers: anyone with run authority approves")
	}
	if !CallerCanApprove([]string{"user:alice"}, "alice") {
		t.Fatal("named user refused")
	}
	if CallerCanApprove([]string{"user:alice"}, "bob") || CallerCanApprove([]string{"role:admin"}, "bob") {
		t.Fatal("unnamed caller admitted")
	}
}

func TestApproversForToolNarrowsByTool(t *testing.T) {
	p := &Policy{Approval: &Approval{Approvers: []string{"user:a"}, ApproversByTool: []ToolApprovers{{Tool: "deploy_*", Refs: []string{"user:b"}}}}}
	if got := ApproversForTool(p, "deploy_prod", nil); len(got) != 1 || got[0] != "user:b" {
		t.Fatalf("got %v", got)
	}
	if got := ApproversForTool(p, "read", nil); len(got) != 1 || got[0] != "user:a" {
		t.Fatalf("got %v", got)
	}
}

func TestCheckGates(t *testing.T) {
	p := &Policy{Budget: &Budget{RunBudgetUSD: dec(t, "1.00"), ServiceBudgetUSD: dec(t, "0.50")}, Tokens: &Tokens{MaxTokens: ptr64(100)}}
	if v := CheckGates(GateInput{Phase: PhasePreLLMCall, Policy: p, CostUsed: dec(t, "0.99"), TokensUsed: ptr64(99), Currency: "USD"}); v != nil {
		t.Fatalf("under budget refused: %+v", v)
	}
	v := CheckGates(GateInput{Phase: PhasePreLLMCall, Policy: p, CostUsed: dec(t, "1.005"), Currency: "USD"})
	if v == nil || v.InterceptorName != "cost_budget_guard" || v.Reason != "budget exhausted (1.00/1.00 USD)" || v.ErrorType != DeniedErrorType {
		t.Fatalf("got %+v", v)
	}
	v = CheckGates(GateInput{Phase: PhasePreLLMCall, Policy: p, TokensUsed: ptr64(100)})
	if v == nil || v.Reason != "token budget exhausted (100/100)" {
		t.Fatalf("got %+v", v)
	}
	v = CheckGates(GateInput{Phase: PhasePreToolCall, Policy: p, ServiceCostUsed: dec(t, "0.5")})
	if v == nil || v.InterceptorName != "service_budget_guard" || v.Message() != "service_budget_guard: service budget exhausted ($0.50/$0.50)" {
		t.Fatalf("got %+v", v)
	}
	if v := CheckGates(GateInput{Phase: PhasePostToolCall, Policy: p, CostUsed: dec(t, "9")}); v != nil {
		t.Fatalf("post phase gated: %+v", v)
	}
	zero := &Policy{Budget: &Budget{RunBudgetUSD: dec(t, "0")}}
	if v := CheckGates(GateInput{Phase: PhasePreLLMCall, Policy: zero, CostUsed: dec(t, "5")}); v != nil {
		t.Fatalf("a zero budget is no budget: %+v", v)
	}
}

func ptr64(n int64) *int64 { return &n }

func TestFixed2HalfEven(t *testing.T) {
	for in, want := range map[string]string{"1.005": "1.00", "1.015": "1.02", "0.5": "0.50", "-1.235": "-1.24", "12": "12.00", "0.001": "0.00"} {
		if got := Fixed2(*dec(t, in)); got != want {
			t.Errorf("Fixed2(%s) = %s, want %s", in, got, want)
		}
	}
}

func TestParsePolicyRoundTripsEffective(t *testing.T) {
	raw := `{"budget":{"run_budget_usd":"5.00","monthly_spend_cap_usd":"100"},"tools":{"allowed":["a*"],"denied":["b"]},"approval":{"approvers":["user:x"]}}`
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	p, errs := ParsePolicy(v, []any{"body"}, false)
	if len(errs) != 0 {
		t.Fatalf("errs %+v", errs)
	}
	if p.Budget == nil || p.Budget.RunBudgetUSD.String() != "5.00" || len(p.Tools.Allowed) != 1 || p.Approval.Approvers[0] != "user:x" {
		t.Fatalf("got %+v", p)
	}
	b, err := p.MarshalJSON()
	if err != nil {
		t.Fatal(err)
	}
	var back Policy
	if err := back.UnmarshalJSON(b); err != nil {
		t.Fatal(err)
	}
	if back.Budget.RunBudgetUSD.Cmp(*p.Budget.RunBudgetUSD) != 0 || back.Tools.Denied[0] != "b" {
		t.Fatalf("round trip lost fields: %s", b)
	}
}

func TestParsePolicyReportsEveryError(t *testing.T) {
	v, _ := wirejson.Unmarshal([]byte(`{"budget":{"run_budget_usd":"-1"},"bogus":1,"approval":{"approvers":["alice"]}}`))
	_, errs := ParsePolicy(v, []any{"body", "task_policy"}, false)
	if len(errs) < 3 {
		t.Fatalf("want an error per bad field, got %+v", errs)
	}
}

func TestRuntimeContractRefusal(t *testing.T) {
	err := Policy{Tokens: &Tokens{MaxTokens: ptr64(1)}}.RequireRuntimeContract()
	if !errors.Is(err, ErrPolicyRefused) || err.Error() != "effective policy is missing required runtime limits: budget.run_budget_usd, tokens.max_tokens_per_call, execution.max_model_turns, execution.max_tool_calls_per_turn, execution.max_tool_calls_total" {
		t.Fatalf("got %v", err)
	}
	full := Policy{Budget: &Budget{RunBudgetUSD: dec(t, "1")}, Tokens: &Tokens{MaxTokens: ptr64(1), MaxTokensPerCall: ptr64(1)},
		Execution: &Execution{MaxModelTurns: ptr64(1), MaxToolCallsPerTurn: ptr64(1), MaxToolCallsTotal: ptr64(1)}}
	if err := full.RequireRuntimeContract(); err != nil {
		t.Fatal(err)
	}
}
