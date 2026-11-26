package service

import (
	"encoding/json"
	"errors"
	"log/slog"
	"strconv"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	. "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

func mkRule(target, effect string, params ...wirejson.Member) Rule {
	return Rule{SubjectType: "workspace", SubjectID: "ws-a", Target: target, Effect: effect, Enabled: true, Params: wirejson.Object(params)}
}

func param(k string, v any) wirejson.Member { return wirejson.Member{Key: k, Value: v} }

func TestParseTarget(t *testing.T) {
	for in, want := range map[string][3]string{"tool:send_email": {"tool", "send_email", "y"}, "tool:*": {"tool", "*", "y"}, "spend": {"spend", "", ""}, "*": {"all", "", ""}, "content": {"content", "", ""}} {
		kind, value, has, err := ParseTarget(in)
		if err != nil || kind != want[0] || value != want[1] || has != (want[2] == "y") {
			t.Errorf("ParseTarget(%q) = %q %q %v %v", in, kind, value, has, err)
		}
	}
	for _, bad := range []string{"", "garbage", "bogus:thing", ":x", "tool:"} {
		if _, _, _, err := ParseTarget(bad); err == nil {
			t.Errorf("ParseTarget(%q) accepted", bad)
		}
	}
}

func TestAssertEnforceable(t *testing.T) {
	ok := []Rule{
		mkRule("spend", "cap", param("amount_usd", "500.00"), param("period", "month")),
		mkRule("*", "approval", param("approvers", []any{"user:alice"})),
		mkRule("tool:send_email", "deny"),
		mkRule("content", "safety", param("prompt_injection", true)),
	}
	for _, r := range ok {
		if err := AssertEnforceable(r); err != nil {
			t.Errorf("%s/%s refused: %v", r.Target, r.Effect, err)
		}
	}
	bad := map[string]Rule{
		"#198":                          mkRule("tool:send_email", "approval", param("approvers", []any{"role:admin"})),
		"spend":                         mkRule("spend", "cap", param("amount_usd", "abc")),
		"not a wildcard 'tool:*'":       mkRule("tool:*", "deny"),
		"conditions (CEL)":              func() Rule { r := mkRule("tool:x", "deny"); c := "true"; r.Condition = &c; return r }(),
		"group subjects":                func() Rule { r := mkRule("tool:x", "deny"); r.SubjectType = "group"; return r }(),
		"caps apply to spend":           mkRule("tool:x", "cap"),
		"approval is enforceable on":    mkRule("tool", "approval"),
		"only enforceable on a content": mkRule("tool:x", "safety"),
	}
	for want, r := range bad {
		err := AssertEnforceable(r)
		if !errors.Is(err, ErrNotEnforceable) || !strings.Contains(err.Error(), want) {
			t.Errorf("%s: got %v", want, err)
		}
	}
	r := mkRule("tool:x", "deny")
	r.TargetNull = true
	if err := AssertEnforceable(r); !errors.Is(err, ErrNotEnforceable) {
		t.Errorf("null target: %v", err)
	}
	r = mkRule("tool:x", "")
	if err := AssertEnforceable(r); err == nil || errors.Is(err, ErrNotEnforceable) {
		t.Errorf("null effect must fail as a server error, got %v", err)
	}
}

func TestModelAndLLMToolSpendCaps(t *testing.T) {
	for _, r := range []Rule{
		mkRule("spend", "cap", param("amount_usd", "5"), param("model", "gemini-4-argon")),
		mkRule("spend", "cap", param("amount_usd", "1"), param("period", "run"), param("model", "gemini-4-argon")),
		mkRule("spend", "cap", param("amount_usd", "2"), param("tool", "llm_call")),
		mkRule("spend", "cap", param("amount_usd", "2"), param("period", "run"), param("tool", "llm_decide")),
	} {
		if err := AssertEnforceable(r); err != nil {
			t.Errorf("%v refused: %v", r.Params, err)
		}
	}
	for _, c := range []struct {
		want string
		r    Rule
	}{
		{"a model spend cap", mkRule("spend", "cap", param("amount_usd", "5"), param("model", "m"), param("category", "llm"))},
		{"a model spend cap", mkRule("spend", "cap", param("amount_usd", "5"), param("model", "m"), param("tool", "llm_call"))},
		{"names the connection_id", mkRule("spend", "cap", param("amount_usd", "5"), param("tool", "search"))},
	} {
		if err := AssertEnforceable(c.r); !errors.Is(err, ErrNotEnforceable) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%v: got %v", c.r.Params, err)
		}
	}
	doc, err := RulesToDocument([]Rule{mkRule("spend", "cap", param("amount_usd", "5"), param("model", "gemini-4-argon"))}, slog.Default())
	if err != nil || doc.Budget.MonthlySpendCapUSD != nil || len(doc.Budget.SpendCaps) != 1 || *doc.Budget.SpendCaps[0].Model != "gemini-4-argon" {
		t.Fatalf("budget %+v %v", doc.Budget, err)
	}
}

func TestRulesToDocument(t *testing.T) {
	doc, err := RulesToDocument([]Rule{
		mkRule("spend", "cap", param("amount_usd", "10.00"), param("period", "month")),
		mkRule("spend", "cap", param("amount_usd", "2"), param("period", "run")),
		mkRule("tokens", "cap", param("max_tokens", num(1000))),
		mkRule("tool:rm", "deny"),
		mkRule("tool:deploy", "approval", param("approvers", []any{"user:b"})),
		func() Rule { r := mkRule("tool:x", "deny"); r.Enabled = false; return r }(),
	}, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	if doc.Budget == nil || doc.Budget.MonthlySpendCapUSD.String() != "10.00" || doc.Budget.RunBudgetUSD.Cmp(mustMoney(t, "2")) != 0 {
		t.Fatalf("budget %+v", doc.Budget)
	}
	if doc.Tokens == nil || *doc.Tokens.MaxTokens != 1000 {
		t.Fatalf("tokens %+v", doc.Tokens)
	}
	if doc.Tools == nil || len(doc.Tools.Denied) != 1 || doc.Tools.Denied[0] != "rm" {
		t.Fatalf("tools %+v", doc.Tools)
	}
	if doc.Approval == nil || len(doc.Approval.EscalationRules) != 1 || doc.Approval.EscalationRules[0] != "deploy" {
		t.Fatalf("approval %+v", doc.Approval)
	}
}

func num(n int) any { return json.Number(strconv.Itoa(n)) }

func mustMoney(t *testing.T, s string) money.Decimal {
	t.Helper()
	d, err := money.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func TestResolveRefusesLoosening(t *testing.T) {
	hi, lo := mustMoney(t, "10"), mustMoney(t, "20")
	_, err := Resolve([]*api.Policy{{Budget: &api.Budget{RunBudgetUSD: &hi}}, {Budget: &api.Budget{RunBudgetUSD: &lo}}}, nil)
	if !errors.Is(err, api.ErrPolicyRefused) || err.Error() != "run_budget_usd cannot loosen higher-scope ceiling" {
		t.Fatalf("got %v", err)
	}
	got, err := Resolve([]*api.Policy{{Budget: &api.Budget{RunBudgetUSD: &lo}}, nil, {Budget: &api.Budget{RunBudgetUSD: &hi}}}, []string{"a"})
	if err != nil || got.Budget.RunBudgetUSD.Cmp(hi) != 0 || got.SourcePolicyIDs[0] != "a" || got.ResolverVersion != api.ResolverVersion {
		t.Fatalf("got %+v %v", got, err)
	}
	_, err = Resolve([]*api.Policy{{Tools: &api.Tools{Allowed: []string{"read_*"}}}, {Tools: &api.Tools{Allowed: []string{"write"}}}}, nil)
	if err == nil || err.Error() != "tools.allowed cannot widen higher-scope allowlist" {
		t.Fatalf("got %v", err)
	}
}

func TestPatternIsWithin(t *testing.T) {
	for _, c := range []struct {
		child, parent string
		want          bool
	}{{"read_file", "read_*", true}, {"read_*", "read_*", true}, {"read_a*", "read_*", true}, {"write", "read_*", false}, {"*", "read_*", false}, {"x", "*", true}} {
		if got := PatternIsWithin(c.child, c.parent); got != c.want {
			t.Errorf("PatternIsWithin(%q, %q) = %v", c.child, c.parent, got)
		}
	}
}

func TestFetchSeenLinksOnlyIsAnOptInSafetyRule(t *testing.T) {
	ws, err := RulesToDocument([]Rule{mkRule("content", "safety", param("prompt_injection", true))}, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	off, err := Resolve([]*api.Policy{&ws}, nil)
	if err != nil || off.ContentSafety.FetchSeenLinksOnly != nil {
		t.Fatalf("no rule turned it on, got %+v %v", off.ContentSafety, err)
	}
	rule := mkRule("content", "safety", param("fetch_seen_links_only", true))
	rule.SubjectType, rule.SubjectID = "agent", "a1"
	if err := AssertEnforceable(rule); err != nil {
		t.Fatal(err)
	}
	agent, err := RulesToDocument([]Rule{rule}, slog.Default())
	if err != nil {
		t.Fatal(err)
	}
	on, err := Resolve([]*api.Policy{&ws, &agent}, nil)
	if err != nil || on.ContentSafety.FetchSeenLinksOnly == nil || !*on.ContentSafety.FetchSeenLinksOnly {
		t.Fatalf("agent opt-in lost, got %+v %v", on.ContentSafety, err)
	}
	no := false
	_, err = Resolve([]*api.Policy{&agent, {ContentSafety: &api.ContentSafety{FetchSeenLinksOnly: &no}}}, nil)
	if !errors.Is(err, api.ErrPolicyRefused) {
		t.Fatalf("a lower layer turned the opt-in off: %v", err)
	}
}
