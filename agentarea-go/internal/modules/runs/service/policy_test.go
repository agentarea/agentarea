package service

import (
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

func TestPolicyConvertsEveryFieldBothWays(t *testing.T) {
	d := func(s string) *money.Decimal { v := money.MustParse(s); return &v }
	s := func(v string) *string { return &v }
	i64 := func(v int64) *int64 { return &v }
	in := func(v int) *int { return &v }
	yes, no := true, false
	cases := []struct {
		name string
		gov  governanceapi.Policy
		run  api.Policy
	}{
		{name: "empty"},
		{
			name: "every field",
			gov: governanceapi.Policy{
				Budget: &governanceapi.Budget{
					MonthlySpendCapUSD: d("10"), AgentMonthlySpendCapUSD: d("5"), RunBudgetUSD: d("1.5"), ServiceBudgetUSD: d("0.5"),
					SpendCaps: []governanceapi.SpendCap{{
						AmountUSD: money.MustParse("2"), OwnAgent: true, ClientID: s("c1"), ConnectionID: s("i1"),
						Tool: s("search"), Currency: s("EUR"), Category: s("tools"), Period: s("run"),
					}, {AmountUSD: money.MustParse("3")}},
				},
				Tokens:    &governanceapi.Tokens{MaxTokens: i64(1000), MaxTokensPerCall: i64(200)},
				Execution: &governanceapi.Execution{MaxModelTurns: i64(7), MaxToolCallsPerTurn: i64(3), MaxToolCallsTotal: i64(20)},
				Tools:     &governanceapi.Tools{Allowed: []string{"a*"}, Denied: []string{}},
				Approval: &governanceapi.Approval{
					RequiresHumanApproval: &yes, EscalationRules: []string{"r"}, Approvers: []string{"user:u1"},
					ApproversByTool: []governanceapi.ToolApprovers{{Tool: "a", Refs: []string{"user:u2"}}, {Tool: "b", Refs: []string{"user:u3"}}},
				},
				ContentSafety: &governanceapi.ContentSafety{
					PromptInjectionDetectionEnabled: &no,
					AnswerCheck:                     &governanceapi.AnswerCheck{Enabled: true, Language: s("en"), RewriteInstruction: s("shorter")},
				},
				SourcePolicyIDs: []string{"p1", "p2"},
				ResolverVersion: "v3",
			},
			run: api.Policy{
				Budget: &api.BudgetPolicy{
					MonthlySpendCap: d("10"), AgentMonthlySpendCap: d("5"), RunBudget: d("1.5"), ServiceBudget: d("0.5"),
					SpendCaps: []api.SpendCap{{
						Amount: money.MustParse("2"), OwnAgent: true, ClientID: "c1", ConnectionID: "i1",
						Tool: "search", Currency: "EUR", Category: "tools", Period: "run",
					}, {Amount: money.MustParse("3")}},
				},
				Tokens:    &api.TokenPolicy{MaxTokens: in(1000), MaxTokensPerCall: in(200)},
				Execution: &api.ExecutionPolicy{MaxModelTurns: in(7), MaxToolCallsPerTurn: in(3), MaxToolCallsTotal: in(20)},
				Tools:     &api.ToolsPolicy{Allowed: []string{"a*"}, Denied: []string{}},
				Approval: &api.ApprovalPolicy{
					RequiresHumanApproval: &yes, EscalationRules: []string{"r"}, Approvers: []string{"user:u1"},
					ApproversByTool: map[string][]string{"a": {"user:u2"}, "b": {"user:u3"}},
				},
				ContentSafety: &api.ContentSafetyPolicy{
					PromptInjectionDetection: &no,
					AnswerCheck:              &api.AnswerCheck{Enabled: true, Language: "en", RewriteInstruction: "shorter"},
				},
				SourcePolicyIDs: []string{"p1", "p2"},
				ResolverVersion: "v3",
			},
		},
		{
			name: "sections without their optional parts",
			gov: governanceapi.Policy{
				Budget:        &governanceapi.Budget{},
				Tokens:        &governanceapi.Tokens{},
				Execution:     &governanceapi.Execution{},
				Tools:         &governanceapi.Tools{},
				Approval:      &governanceapi.Approval{},
				ContentSafety: &governanceapi.ContentSafety{AnswerCheck: &governanceapi.AnswerCheck{}},
			},
			run: api.Policy{
				Budget:        &api.BudgetPolicy{},
				Tokens:        &api.TokenPolicy{},
				Execution:     &api.ExecutionPolicy{},
				Tools:         &api.ToolsPolicy{},
				Approval:      &api.ApprovalPolicy{},
				ContentSafety: &api.ContentSafetyPolicy{AnswerCheck: &api.AnswerCheck{}},
			},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := toRunPolicy(c.gov); !reflect.DeepEqual(got, c.run) {
				t.Fatalf("toRunPolicy\n got %+v\nwant %+v", got, c.run)
			}
			if got := fromRunPolicy(c.run); !reflect.DeepEqual(got, c.gov) {
				t.Fatalf("fromRunPolicy\n got %+v\nwant %+v", got, c.gov)
			}
		})
	}
	if toRunBudget(nil) != nil {
		t.Fatal("no budget is no budget")
	}
}
