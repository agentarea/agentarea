package api

import (
	"fmt"
	"math/big"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

// Phase is an execution boundary the gates run at.
type Phase string

const (
	PhasePreLLMCall    Phase = "pre_llm_call"
	PhasePostLLMCall   Phase = "post_llm_call"
	PhasePreToolCall   Phase = "pre_tool_call"
	PhasePostToolCall  Phase = "post_tool_call"
	PhaseToolDiscovery Phase = "tool_discovery"
)

// Verdict types as the workflow matches them (ApplicationError type).
const (
	DeniedErrorType     = "GovernanceDeniedError"
	EscalationErrorType = "EscalationRequiredError"
)

// GateInput is the governed activity's request: the run's effective policy
// and its counters so far (to_execution_state). Currency names the billing
// currency in the cost gate's reason.
type GateInput struct {
	Phase           Phase
	Policy          *Policy
	CostUsed        *money.Decimal
	ServiceCostUsed *money.Decimal
	TokensUsed      *int64
	Currency        string
}

// Verdict is a gate's refusal. ErrorType is DeniedErrorType or
// EscalationErrorType; Details is the ApplicationError's first detail.
type Verdict struct {
	ErrorType       string
	InterceptorName string
	Reason          string
	Metadata        map[string]any
	Phase           Phase
}

// Message is the ApplicationError message: "<gate>: <reason>".
func (v Verdict) Message() string { return v.InterceptorName + ": " + v.Reason }

// Details is {interceptor_name, reason, metadata, phase}.
func (v Verdict) Details() map[string]any {
	meta := v.Metadata
	if meta == nil {
		meta = map[string]any{}
	}
	return map[string]any{"interceptor_name": v.InterceptorName, "reason": v.Reason, "metadata": meta, "phase": string(v.Phase)}
}

// CheckGates runs the open-core gates of a phase in priority order
// (factory.py): before a model call the cost budget (100) and the token
// budget (110); before a tool call the cost budget (100) and the service
// budget (105). Nil allows. The plan's entitlement gate (120) is the
// enterprise edition's and runs after these; the prompt-injection filter
// registered at 300 never sees content before a call (temporal_bridge.py
// builds the pre-phase context without it), so it never refuses; no gate runs
// after a call.
func CheckGates(in GateInput) *Verdict {
	switch in.Phase {
	case PhasePreLLMCall:
		if v := costGate(in); v != nil {
			return v
		}
		return tokenGate(in)
	case PhasePreToolCall:
		if v := costGate(in); v != nil {
			return v
		}
		return serviceGate(in)
	case PhasePostLLMCall, PhasePostToolCall, PhaseToolDiscovery:
	}
	return nil
}

func orZero(d *money.Decimal) money.Decimal {
	if d == nil {
		return money.Zero()
	}
	return *d
}

func costGate(in GateInput) *Verdict {
	if in.Policy == nil || in.Policy.Budget == nil || in.Policy.Budget.RunBudgetUSD == nil {
		return nil
	}
	budget := *in.Policy.Budget.RunBudgetUSD
	if budget.Sign() <= 0 {
		return nil
	}
	used := orZero(in.CostUsed)
	if used.Cmp(budget) < 0 {
		return nil
	}
	return &Verdict{
		ErrorType: DeniedErrorType, InterceptorName: "cost_budget_guard", Phase: in.Phase,
		Reason:   fmt.Sprintf("budget exhausted (%s/%s %s)", Fixed2(used), Fixed2(budget), in.Currency),
		Metadata: map[string]any{"cost_used": used.String(), "budget_usd": budget.String()},
	}
}

func serviceGate(in GateInput) *Verdict {
	if in.Policy == nil || in.Policy.Budget == nil || in.Policy.Budget.ServiceBudgetUSD == nil {
		return nil
	}
	budget := *in.Policy.Budget.ServiceBudgetUSD
	if budget.Sign() <= 0 {
		return nil
	}
	used := orZero(in.ServiceCostUsed)
	if used.Cmp(budget) < 0 {
		return nil
	}
	return &Verdict{
		ErrorType: DeniedErrorType, InterceptorName: "service_budget_guard", Phase: in.Phase,
		Reason:   fmt.Sprintf("service budget exhausted ($%s/$%s)", Fixed2(used), Fixed2(budget)),
		Metadata: map[string]any{"service_cost_used": used.String(), "service_budget_usd": budget.String()},
	}
}

func tokenGate(in GateInput) *Verdict {
	if in.Policy == nil || in.Policy.Tokens == nil || in.Policy.Tokens.MaxTokens == nil || *in.Policy.Tokens.MaxTokens <= 0 {
		return nil
	}
	limit := *in.Policy.Tokens.MaxTokens
	var used int64
	if in.TokensUsed != nil {
		used = *in.TokensUsed
	}
	if used < limit {
		return nil
	}
	return &Verdict{
		ErrorType: DeniedErrorType, InterceptorName: "token_budget_guard", Phase: in.Phase,
		Reason:   fmt.Sprintf("token budget exhausted (%d/%d)", used, limit),
		Metadata: map[string]any{"tokens_used": used, "max_tokens": limit},
	}
}

// Fixed2 is format(Decimal, ".2f"): two places, half to even.
func Fixed2(d money.Decimal) string {
	r, ok := new(big.Rat).SetString(d.Plain())
	if !ok {
		return d.Plain()
	}
	scaled := new(big.Rat).Mul(r, big.NewRat(100, 1))
	neg := scaled.Sign() < 0
	scaled.Abs(scaled)
	q, rem := new(big.Int).QuoRem(scaled.Num(), scaled.Denom(), new(big.Int))
	twice := new(big.Int).Mul(rem, big.NewInt(2))
	switch twice.Cmp(scaled.Denom()) {
	case 1:
		q.Add(q, big.NewInt(1))
	case 0:
		if q.Bit(0) == 1 {
			q.Add(q, big.NewInt(1))
		}
	}
	s := q.String()
	for len(s) < 3 {
		s = "0" + s
	}
	out := s[:len(s)-2] + "." + s[len(s)-2:]
	if neg {
		out = "-" + out
	}
	return out
}
