package domain

import (
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

func refused(msg string) error { return &api.ValidationError{Message: msg} }

// Resolve is PolicyResolver.resolve: the layers, highest first, folded into
// one monotonic policy. A lower layer that loosens a higher one is refused.
func Resolve(layers []*api.Policy, sourceIDs []string) (api.Policy, error) {
	var current api.Policy
	for _, l := range layers {
		if l == nil {
			continue
		}
		if err := validateTightens(current, *l); err != nil {
			return api.Policy{}, err
		}
		current = merge(current, *l)
	}
	if sourceIDs == nil {
		sourceIDs = []string{}
	}
	current.SourcePolicyIDs = sourceIDs
	current.ResolverVersion = api.ResolverVersion
	return current, nil
}

func validateTightens(h, l api.Policy) error {
	if h.Budget != nil && l.Budget != nil {
		switch {
		case looserMoney(h.Budget.MonthlySpendCapUSD, l.Budget.MonthlySpendCapUSD):
			return refused("monthly_spend_cap_usd cannot loosen higher-scope ceiling")
		case looserMoney(h.Budget.AgentMonthlySpendCapUSD, l.Budget.AgentMonthlySpendCapUSD):
			return refused("agent_monthly_spend_cap_usd cannot loosen higher-scope ceiling")
		case looserMoney(h.Budget.RunBudgetUSD, l.Budget.RunBudgetUSD):
			return refused("run_budget_usd cannot loosen higher-scope ceiling")
		case looserMoney(h.Budget.ServiceBudgetUSD, l.Budget.ServiceBudgetUSD):
			return refused("service_budget_usd cannot loosen higher-scope ceiling")
		}
		if h.Budget.MonthlySpendCapUSD != nil && l.Budget.AgentMonthlySpendCapUSD != nil &&
			l.Budget.AgentMonthlySpendCapUSD.Cmp(*h.Budget.MonthlySpendCapUSD) > 0 {
			return refused("agent_monthly_spend_cap_usd cannot exceed the higher-scope monthly_spend_cap_usd")
		}
	}
	if h.Tokens != nil && l.Tokens != nil {
		if looser(h.Tokens.MaxTokens, l.Tokens.MaxTokens) {
			return refused("max_tokens cannot loosen higher-scope ceiling")
		}
		if looser(h.Tokens.MaxTokensPerCall, l.Tokens.MaxTokensPerCall) {
			return refused("max_tokens_per_call cannot loosen higher-scope ceiling")
		}
	}
	if h.Execution != nil && l.Execution != nil {
		if looser(h.Execution.MaxModelTurns, l.Execution.MaxModelTurns) {
			return refused("max_model_turns cannot loosen higher-scope ceiling")
		}
		if looser(h.Execution.MaxToolCallsPerTurn, l.Execution.MaxToolCallsPerTurn) {
			return refused("max_tool_calls_per_turn cannot loosen higher-scope ceiling")
		}
		if looser(h.Execution.MaxToolCallsTotal, l.Execution.MaxToolCallsTotal) {
			return refused("max_tool_calls_total cannot loosen higher-scope ceiling")
		}
	}
	if h.Tools != nil && l.Tools != nil && h.Tools.Allowed != nil && l.Tools.Allowed != nil {
		for _, pattern := range l.Tools.Allowed {
			within := false
			for _, parent := range h.Tools.Allowed {
				if PatternIsWithin(pattern, parent) {
					within = true
					break
				}
			}
			if !within {
				return refused("tools.allowed cannot widen higher-scope allowlist")
			}
		}
	}
	if h.Approval != nil && l.Approval != nil && isTrue(h.Approval.RequiresHumanApproval) && isFalse(l.Approval.RequiresHumanApproval) {
		return refused("requires_human_approval cannot be disabled")
	}
	if h.ContentSafety != nil && l.ContentSafety != nil &&
		isTrue(h.ContentSafety.PromptInjectionDetectionEnabled) && isFalse(l.ContentSafety.PromptInjectionDetectionEnabled) {
		return refused("prompt_injection_detection_enabled cannot be disabled")
	}
	return nil
}

func isTrue(b *bool) bool  { return b != nil && *b }
func isFalse(b *bool) bool { return b != nil && !*b }

func looser(h, l *int64) bool { return h != nil && l != nil && *l > *h }

func merge(h, l api.Policy) api.Policy {
	return api.Policy{
		Budget:        mergeBudget(h.Budget, l.Budget),
		Tokens:        mergeTokens(h.Tokens, l.Tokens),
		Execution:     mergeExecution(h.Execution, l.Execution),
		Tools:         mergeTools(h.Tools, l.Tools),
		Approval:      mergeApproval(h.Approval, l.Approval),
		ContentSafety: mergeContentSafety(h.ContentSafety, l.ContentSafety),
	}
}

func mergeBudget(h, l *api.Budget) *api.Budget {
	if h == nil {
		return l
	}
	if l == nil {
		return h
	}
	var caps []api.SpendCap
	caps = append(append(caps, h.SpendCaps...), l.SpendCaps...)
	if len(caps) == 0 {
		caps = nil
	}
	return &api.Budget{
		MonthlySpendCapUSD:      minMoney(h.MonthlySpendCapUSD, l.MonthlySpendCapUSD),
		AgentMonthlySpendCapUSD: minMoney(h.AgentMonthlySpendCapUSD, l.AgentMonthlySpendCapUSD),
		RunBudgetUSD:            minMoney(h.RunBudgetUSD, l.RunBudgetUSD),
		ServiceBudgetUSD:        minMoney(h.ServiceBudgetUSD, l.ServiceBudgetUSD),
		SpendCaps:               caps,
	}
}

func mergeTokens(h, l *api.Tokens) *api.Tokens {
	if h == nil {
		return l
	}
	if l == nil {
		return h
	}
	return &api.Tokens{MaxTokens: minInt(h.MaxTokens, l.MaxTokens), MaxTokensPerCall: minInt(h.MaxTokensPerCall, l.MaxTokensPerCall)}
}

func mergeExecution(h, l *api.Execution) *api.Execution {
	if h == nil {
		return l
	}
	if l == nil {
		return h
	}
	return &api.Execution{
		MaxModelTurns:       minInt(h.MaxModelTurns, l.MaxModelTurns),
		MaxToolCallsPerTurn: minInt(h.MaxToolCallsPerTurn, l.MaxToolCallsPerTurn),
		MaxToolCallsTotal:   minInt(h.MaxToolCallsTotal, l.MaxToolCallsTotal),
	}
}

func mergeTools(h, l *api.Tools) *api.Tools {
	if h == nil {
		return l
	}
	if l == nil {
		return h
	}
	allowed := h.Allowed
	if l.Allowed != nil {
		allowed = l.Allowed
	}
	return &api.Tools{Allowed: allowed, Denied: Dedupe(append(append([]string{}, h.Denied...), l.Denied...))}
}

func mergeApproval(h, l *api.Approval) *api.Approval {
	if h == nil {
		return l
	}
	if l == nil {
		return h
	}
	required := isTrue(h.RequiresHumanApproval) || isTrue(l.RequiresHumanApproval)
	return &api.Approval{
		RequiresHumanApproval: &required,
		EscalationRules:       Dedupe(append(append([]string{}, h.EscalationRules...), l.EscalationRules...)),
		Approvers:             Dedupe(append(append([]string{}, h.Approvers...), l.Approvers...)),
		ApproversByTool:       mergeApproversByTool(h.ApproversByTool, l.ApproversByTool),
	}
}

func mergeApproversByTool(h, l []api.ToolApprovers) []api.ToolApprovers {
	out := make([]api.ToolApprovers, 0, len(h)+len(l))
	for _, e := range h {
		out = append(out, api.ToolApprovers{Tool: e.Tool, Refs: append([]string{}, e.Refs...)})
	}
	for _, e := range l {
		i := slices.IndexFunc(out, func(x api.ToolApprovers) bool { return x.Tool == e.Tool })
		if i < 0 {
			out = append(out, api.ToolApprovers{Tool: e.Tool, Refs: Dedupe(append([]string{}, e.Refs...))})
			continue
		}
		out[i].Refs = Dedupe(append(out[i].Refs, e.Refs...))
	}
	return out
}

func mergeContentSafety(h, l *api.ContentSafety) *api.ContentSafety {
	if h == nil {
		return l
	}
	if l == nil {
		return h
	}
	on := isTrue(h.PromptInjectionDetectionEnabled) || isTrue(l.PromptInjectionDetectionEnabled)
	check := l.AnswerCheck
	if check == nil {
		check = h.AnswerCheck
	}
	return &api.ContentSafety{PromptInjectionDetectionEnabled: &on, AnswerCheck: check}
}

// Dedupe keeps the first of each value, in order (dict.fromkeys).
func Dedupe(values []string) []string {
	out := make([]string, 0, len(values))
	for _, v := range values {
		if !slices.Contains(out, v) {
			out = append(out, v)
		}
	}
	return out
}

type ordered[T any] interface{ Cmp(T) int }

func looserMoney[T ordered[T]](h, l *T) bool { return h != nil && l != nil && (*l).Cmp(*h) > 0 }

func minMoney[T ordered[T]](a, b *T) *T {
	if a == nil {
		return b
	}
	if b == nil {
		return a
	}
	if (*b).Cmp(*a) < 0 {
		return b
	}
	return a
}

func itoa(n int64) string { return strconv.FormatInt(n, 10) }

func minInt(a, b *int64) *int64 {
	if a == nil {
		return b
	}
	if b == nil {
		return a
	}
	if *b < *a {
		return b
	}
	return a
}

// PatternIsWithin is _pattern_is_within: a lower scope's allowlist pattern
// admitted by a higher one's.
func PatternIsWithin(child, parent string) bool {
	if child == parent || parent == "*" {
		return true
	}
	if !strings.ContainsAny(child, "*?") {
		return api.Fnmatch(child, parent)
	}
	if strings.HasSuffix(parent, "*") && !strings.ContainsAny(parent[:len(parent)-1], "*?") {
		return strings.HasPrefix(child, parent[:len(parent)-1])
	}
	return false
}

// ValidateCallerApprovers refuses a caller layer naming an approver the
// ceiling does not admit: every named approver must be in each non-empty
// ceiling set.
func ValidateCallerApprovers(ceiling, caller api.Policy) error {
	if caller.Approval == nil || ceiling.Approval == nil {
		return nil
	}
	var sets [][]string
	if len(ceiling.Approval.Approvers) > 0 {
		sets = append(sets, ceiling.Approval.Approvers)
	}
	for _, e := range ceiling.Approval.ApproversByTool {
		if len(e.Refs) > 0 {
			sets = append(sets, e.Refs)
		}
	}
	if len(sets) == 0 {
		return nil
	}
	admitted := func(ref string) bool {
		for _, s := range sets {
			if !slices.Contains(s, ref) {
				return false
			}
		}
		return true
	}
	named := append([]string{}, caller.Approval.Approvers...)
	for _, e := range caller.Approval.ApproversByTool {
		named = append(named, e.Refs...)
	}
	var added []string
	for _, r := range named {
		if !admitted(r) && !slices.Contains(added, r) {
			added = append(added, r)
		}
	}
	if len(added) == 0 {
		return nil
	}
	sort.Strings(added)
	return refused("task policy cannot add approvers beyond the workspace policy: " + strings.Join(added, ", "))
}

// LimitCeilings is _limit_ceilings: what the policy allows for each limit a
// continuation grant raises, keyed by the failure reason; unbounded ones are left out.
func LimitCeilings(p api.Policy) []api.Ceiling {
	var out []api.Ceiling
	if p.Execution != nil && p.Execution.MaxModelTurns != nil {
		out = append(out, api.Ceiling{Reason: "iteration_limit", Value: itoa(*p.Execution.MaxModelTurns)})
	}
	if p.Execution != nil && p.Execution.MaxToolCallsTotal != nil {
		out = append(out, api.Ceiling{Reason: "tool_call_limit", Value: itoa(*p.Execution.MaxToolCallsTotal)})
	}
	if p.Tokens != nil && p.Tokens.MaxTokens != nil {
		out = append(out, api.Ceiling{Reason: "token_limit", Value: itoa(*p.Tokens.MaxTokens)})
	}
	if p.Budget != nil && p.Budget.RunBudgetUSD != nil {
		out = append(out, api.Ceiling{Reason: "budget_exceeded", Value: p.Budget.RunBudgetUSD.String()})
	}
	return out
}
