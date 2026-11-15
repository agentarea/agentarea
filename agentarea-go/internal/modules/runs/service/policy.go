package service

import (
	"sort"

	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// governance's policy and runs' workflow payload differ in shape only: the
// payload keeps its snake_case JSON in workflow history, so it is converted
// here, never aliased.

func toRunPolicy(p governanceapi.Policy) api.Policy {
	out := api.Policy{
		Budget:          toRunBudget(p.Budget),
		SourcePolicyIDs: p.SourcePolicyIDs,
		ResolverVersion: p.ResolverVersion,
	}
	if t := p.Tokens; t != nil {
		out.Tokens = &api.TokenPolicy{MaxTokens: toInt(t.MaxTokens), MaxTokensPerCall: toInt(t.MaxTokensPerCall)}
	}
	if x := p.Execution; x != nil {
		out.Execution = &api.ExecutionPolicy{MaxModelTurns: toInt(x.MaxModelTurns), MaxToolCallsPerTurn: toInt(x.MaxToolCallsPerTurn), MaxToolCallsTotal: toInt(x.MaxToolCallsTotal)}
	}
	if t := p.Tools; t != nil {
		out.Tools = &api.ToolsPolicy{Allowed: t.Allowed, Denied: t.Denied}
	}
	if a := p.Approval; a != nil {
		ap := &api.ApprovalPolicy{RequiresHumanApproval: a.RequiresHumanApproval, EscalationRules: a.EscalationRules, Approvers: a.Approvers}
		if a.ApproversByTool != nil {
			ap.ApproversByTool = a.ByTool()
		}
		out.Approval = ap
	}
	if c := p.ContentSafety; c != nil {
		cs := &api.ContentSafetyPolicy{PromptInjectionDetection: c.PromptInjectionDetectionEnabled}
		if c.AnswerCheck != nil {
			cs.AnswerCheck = &api.AnswerCheck{Enabled: c.AnswerCheck.Enabled, Language: deref(c.AnswerCheck.Language), RewriteInstruction: deref(c.AnswerCheck.RewriteInstruction)}
		}
		out.ContentSafety = cs
	}
	return out
}

func toRunBudget(b *governanceapi.Budget) *api.BudgetPolicy {
	if b == nil {
		return nil
	}
	out := &api.BudgetPolicy{
		MonthlySpendCap: b.MonthlySpendCapUSD, AgentMonthlySpendCap: b.AgentMonthlySpendCapUSD,
		RunBudget: b.RunBudgetUSD, ServiceBudget: b.ServiceBudgetUSD,
	}
	if b.SpendCaps != nil {
		out.SpendCaps = make([]api.SpendCap, len(b.SpendCaps))
		for i, c := range b.SpendCaps {
			out.SpendCaps[i] = api.SpendCap{
				Amount: c.AmountUSD, OwnAgent: c.OwnAgent, ClientID: deref(c.ClientID), ConnectionID: deref(c.ConnectionID),
				Tool: deref(c.Tool), Currency: deref(c.Currency), Category: deref(c.Category), Period: deref(c.Period),
			}
		}
	}
	return out
}

// fromRunPolicy is the payload policy as governance takes it; approvers_by_tool
// comes back in sorted tool order, the payload's map having none.
func fromRunPolicy(p api.Policy) governanceapi.Policy {
	out := governanceapi.Policy{SourcePolicyIDs: p.SourcePolicyIDs, ResolverVersion: p.ResolverVersion}
	if b := p.Budget; b != nil {
		gb := &governanceapi.Budget{
			MonthlySpendCapUSD: b.MonthlySpendCap, AgentMonthlySpendCapUSD: b.AgentMonthlySpendCap,
			RunBudgetUSD: b.RunBudget, ServiceBudgetUSD: b.ServiceBudget,
		}
		if b.SpendCaps != nil {
			gb.SpendCaps = make([]governanceapi.SpendCap, len(b.SpendCaps))
			for i, c := range b.SpendCaps {
				gb.SpendCaps[i] = governanceapi.SpendCap{
					AmountUSD: c.Amount, OwnAgent: c.OwnAgent, ClientID: ref(c.ClientID), ConnectionID: ref(c.ConnectionID),
					Tool: ref(c.Tool), Currency: ref(c.Currency), Category: ref(c.Category), Period: ref(c.Period),
				}
			}
		}
		out.Budget = gb
	}
	if t := p.Tokens; t != nil {
		out.Tokens = &governanceapi.Tokens{MaxTokens: toInt64(t.MaxTokens), MaxTokensPerCall: toInt64(t.MaxTokensPerCall)}
	}
	if x := p.Execution; x != nil {
		out.Execution = &governanceapi.Execution{MaxModelTurns: toInt64(x.MaxModelTurns), MaxToolCallsPerTurn: toInt64(x.MaxToolCallsPerTurn), MaxToolCallsTotal: toInt64(x.MaxToolCallsTotal)}
	}
	if t := p.Tools; t != nil {
		out.Tools = &governanceapi.Tools{Allowed: t.Allowed, Denied: t.Denied}
	}
	if a := p.Approval; a != nil {
		ga := &governanceapi.Approval{RequiresHumanApproval: a.RequiresHumanApproval, EscalationRules: a.EscalationRules, Approvers: a.Approvers}
		if a.ApproversByTool != nil {
			tools := make([]string, 0, len(a.ApproversByTool))
			for t := range a.ApproversByTool {
				tools = append(tools, t)
			}
			sort.Strings(tools)
			ga.ApproversByTool = make([]governanceapi.ToolApprovers, len(tools))
			for i, t := range tools {
				ga.ApproversByTool[i] = governanceapi.ToolApprovers{Tool: t, Refs: a.ApproversByTool[t]}
			}
		}
		out.Approval = ga
	}
	if c := p.ContentSafety; c != nil {
		gc := &governanceapi.ContentSafety{PromptInjectionDetectionEnabled: c.PromptInjectionDetection}
		if c.AnswerCheck != nil {
			gc.AnswerCheck = &governanceapi.AnswerCheck{Enabled: c.AnswerCheck.Enabled, Language: ref(c.AnswerCheck.Language), RewriteInstruction: ref(c.AnswerCheck.RewriteInstruction)}
		}
		out.ContentSafety = gc
	}
	return out
}

func toInt(n *int64) *int {
	if n == nil {
		return nil
	}
	v := int(*n)
	return &v
}

func toInt64(n *int) *int64 {
	if n == nil {
		return nil
	}
	v := int64(*n)
	return &v
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func ref(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
