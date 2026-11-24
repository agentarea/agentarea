package api

import (
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// ResolverVersion is RESOLVER_VERSION, stamped on every resolved policy.
const ResolverVersion = "policy-resolver-v1"

// Policy is PolicyDocument, and EffectivePolicy when SourcePolicyIDs and
// ResolverVersion are set (domain/policies.py). A nil section is None.
type Policy struct {
	Budget        *Budget
	Tokens        *Tokens
	Execution     *Execution
	Tools         *Tools
	Approval      *Approval
	ContentSafety *ContentSafety
	// SourcePolicyIDs and ResolverVersion are EffectivePolicy's.
	SourcePolicyIDs []string
	ResolverVersion string
}

// Budget is BudgetPolicy; amounts are in the billing currency.
type Budget struct {
	MonthlySpendCapUSD      *money.Decimal
	AgentMonthlySpendCapUSD *money.Decimal
	RunBudgetUSD            *money.Decimal
	ServiceBudgetUSD        *money.Decimal
	// SpendCaps nil is None.
	SpendCaps []SpendCap
}

// SpendCap is ScopedSpendCap: a cap on part of the spend.
type SpendCap struct {
	AmountUSD    money.Decimal
	OwnAgent     bool
	ClientID     *string
	ConnectionID *string
	Tool         *string
	Currency     *string
	// Category is llm or tools; Period is run (nil: the calendar month).
	Category *string
	Period   *string
}

// Tokens is TokenPolicy.
type Tokens struct {
	MaxTokens        *int64
	MaxTokensPerCall *int64
}

// Execution is ExecutionLimitsPolicy.
type Execution struct {
	MaxModelTurns       *int64
	MaxToolCallsPerTurn *int64
	MaxToolCallsTotal   *int64
}

// Tools is ToolsPolicy: Allowed nil declares no allowlist, empty permits no tool.
type Tools struct {
	Allowed []string
	Denied  []string
}

// ToolApprovers is one entry of approvers_by_tool, in its written order.
type ToolApprovers struct {
	Tool string
	Refs []string
}

// Approval is ApprovalPolicy.
type Approval struct {
	RequiresHumanApproval *bool
	EscalationRules       []string
	Approvers             []string
	ApproversByTool       []ToolApprovers
}

// ByTool is the approvers keyed by tool, written order lost.
func (a Approval) ByTool() map[string][]string {
	out := make(map[string][]string, len(a.ApproversByTool))
	for _, e := range a.ApproversByTool {
		out[e.Tool] = e.Refs
	}
	return out
}

// ContentSafety is ContentSafetyPolicy.
type ContentSafety struct {
	PromptInjectionDetectionEnabled *bool
	AnswerCheck                     *AnswerCheck
}

// AnswerCheck is AnswerCheckPolicy.
type AnswerCheck struct {
	Enabled            bool
	Language           *string
	RewriteInstruction *string
}

// Snapshot is tasks.metadata.governance_snapshot as task_service writes it.
type Snapshot struct {
	RequestedPolicy    Policy
	RequestedExecution *Execution
	ResolvedExecution  *Execution
	EffectivePolicy    Policy
	// LimitCeilings is keyed by the failure reason a limit stops a run with.
	LimitCeilings []Ceiling
	ResolvedAt    time.Time
	Revision      int
}

// Ceiling is one entry of limit_ceilings, in Python's key order.
type Ceiling struct{ Reason, Value string }

// RuntimeContractError is RuntimePolicyContractError.
type RuntimeContractError struct{ Missing []string }

func (e *RuntimeContractError) Error() string {
	return "effective policy is missing required runtime limits: " + strings.Join(e.Missing, ", ")
}
func (e *RuntimeContractError) Is(target error) bool { return target == ErrPolicyRefused }

// ValidationError is PolicyValidationError.
type ValidationError struct{ Message string }

func (e *ValidationError) Error() string        { return e.Message }
func (e *ValidationError) Is(target error) bool { return target == ErrPolicyRefused }

// RequireRuntimeContract fails closed unless every runtime limit is set.
func (p Policy) RequireRuntimeContract() error {
	var missing []string
	if p.Budget == nil || p.Budget.RunBudgetUSD == nil {
		missing = append(missing, "budget.run_budget_usd")
	}
	if p.Tokens == nil || p.Tokens.MaxTokens == nil {
		missing = append(missing, "tokens.max_tokens")
	}
	if p.Tokens == nil || p.Tokens.MaxTokensPerCall == nil {
		missing = append(missing, "tokens.max_tokens_per_call")
	}
	if p.Execution == nil || p.Execution.MaxModelTurns == nil {
		missing = append(missing, "execution.max_model_turns")
	}
	if p.Execution == nil || p.Execution.MaxToolCallsPerTurn == nil {
		missing = append(missing, "execution.max_tool_calls_per_turn")
	}
	if p.Execution == nil || p.Execution.MaxToolCallsTotal == nil {
		missing = append(missing, "execution.max_tool_calls_total")
	}
	if len(missing) > 0 {
		return &RuntimeContractError{Missing: missing}
	}
	return nil
}

// Document is the policy without its EffectivePolicy fields.
func (p Policy) Document() Policy {
	p.SourcePolicyIDs, p.ResolverVersion = nil, ""
	return p
}

// emit builds pydantic's model_dump(mode="json"): with keepNone false it is
// exclude_none (to_json_dict), with true every field (a response model).
type emit struct{ keepNone bool }

func (e emit) put(o *wirejson.Object, key string, v any, isNone bool) {
	if isNone {
		if e.keepNone {
			*o = append(*o, wirejson.Member{Key: key, Value: nil})
		}
		return
	}
	*o = append(*o, wirejson.Member{Key: key, Value: v})
}

func (e emit) money(o *wirejson.Object, key string, d *money.Decimal) {
	if d == nil {
		e.put(o, key, nil, true)
		return
	}
	e.put(o, key, d.String(), false)
}

func (e emit) int(o *wirejson.Object, key string, n *int64) {
	if n == nil {
		e.put(o, key, nil, true)
		return
	}
	e.put(o, key, *n, false)
}

func (e emit) bool(o *wirejson.Object, key string, b *bool) {
	if b == nil {
		e.put(o, key, nil, true)
		return
	}
	e.put(o, key, *b, false)
}

func (e emit) str(o *wirejson.Object, key string, s *string) {
	if s == nil {
		e.put(o, key, nil, true)
		return
	}
	e.put(o, key, *s, false)
}

func strs(v []string) []any {
	out := make([]any, len(v))
	for i, s := range v {
		out[i] = s
	}
	return out
}

func (e emit) budget(b *Budget) wirejson.Object {
	o := wirejson.Object{}
	e.money(&o, "monthly_spend_cap_usd", b.MonthlySpendCapUSD)
	e.money(&o, "agent_monthly_spend_cap_usd", b.AgentMonthlySpendCapUSD)
	e.money(&o, "run_budget_usd", b.RunBudgetUSD)
	e.money(&o, "service_budget_usd", b.ServiceBudgetUSD)
	if b.SpendCaps == nil {
		e.put(&o, "spend_caps", nil, true)
	} else {
		caps := make([]any, len(b.SpendCaps))
		for i, c := range b.SpendCaps {
			caps[i] = e.spendCap(c)
		}
		e.put(&o, "spend_caps", caps, false)
	}
	return o
}

func (e emit) spendCap(c SpendCap) wirejson.Object {
	o := wirejson.Object{{Key: "amount_usd", Value: c.AmountUSD.String()}, {Key: "own_agent", Value: c.OwnAgent}}
	e.str(&o, "client_id", c.ClientID)
	e.str(&o, "connection_id", c.ConnectionID)
	e.str(&o, "tool", c.Tool)
	e.str(&o, "currency", c.Currency)
	e.str(&o, "category", c.Category)
	e.str(&o, "period", c.Period)
	return o
}

func (e emit) tokens(t *Tokens) wirejson.Object {
	o := wirejson.Object{}
	e.int(&o, "max_tokens", t.MaxTokens)
	e.int(&o, "max_tokens_per_call", t.MaxTokensPerCall)
	return o
}

func (e emit) execution(x *Execution) wirejson.Object {
	o := wirejson.Object{}
	e.int(&o, "max_model_turns", x.MaxModelTurns)
	e.int(&o, "max_tool_calls_per_turn", x.MaxToolCallsPerTurn)
	e.int(&o, "max_tool_calls_total", x.MaxToolCallsTotal)
	return o
}

func (e emit) tools(t *Tools) wirejson.Object {
	o := wirejson.Object{}
	if t.Allowed == nil {
		e.put(&o, "allowed", nil, true)
	} else {
		e.put(&o, "allowed", strs(t.Allowed), false)
	}
	o = append(o, wirejson.Member{Key: "denied", Value: strs(t.Denied)})
	return o
}

func (e emit) approval(a *Approval) wirejson.Object {
	o := wirejson.Object{}
	e.bool(&o, "requires_human_approval", a.RequiresHumanApproval)
	byTool := wirejson.Object{}
	for _, t := range a.ApproversByTool {
		byTool.Set(t.Tool, strs(t.Refs))
	}
	return append(o,
		wirejson.Member{Key: "escalation_rules", Value: strs(a.EscalationRules)},
		wirejson.Member{Key: "approvers", Value: strs(a.Approvers)},
		wirejson.Member{Key: "approvers_by_tool", Value: byTool},
	)
}

func (e emit) contentSafety(c *ContentSafety) wirejson.Object {
	o := wirejson.Object{}
	e.bool(&o, "prompt_injection_detection_enabled", c.PromptInjectionDetectionEnabled)
	if c.AnswerCheck == nil {
		e.put(&o, "answer_check", nil, true)
	} else {
		ac := wirejson.Object{{Key: "enabled", Value: c.AnswerCheck.Enabled}}
		e.str(&ac, "language", c.AnswerCheck.Language)
		e.str(&ac, "rewrite_instruction", c.AnswerCheck.RewriteInstruction)
		e.put(&o, "answer_check", ac, false)
	}
	return o
}

func (e emit) policy(p Policy, effective bool) wirejson.Object {
	o := wirejson.Object{}
	section := func(key string, isNil bool, f func() wirejson.Object) {
		if isNil {
			e.put(&o, key, nil, true)
			return
		}
		e.put(&o, key, f(), false)
	}
	section("budget", p.Budget == nil, func() wirejson.Object { return e.budget(p.Budget) })
	section("tokens", p.Tokens == nil, func() wirejson.Object { return e.tokens(p.Tokens) })
	section("execution", p.Execution == nil, func() wirejson.Object { return e.execution(p.Execution) })
	section("tools", p.Tools == nil, func() wirejson.Object { return e.tools(p.Tools) })
	section("approval", p.Approval == nil, func() wirejson.Object { return e.approval(p.Approval) })
	section("content_safety", p.ContentSafety == nil, func() wirejson.Object { return e.contentSafety(p.ContentSafety) })
	if effective {
		ids := p.SourcePolicyIDs
		if ids == nil {
			ids = []string{}
		}
		o = append(o, wirejson.Member{Key: "source_policy_ids", Value: strs(ids)},
			wirejson.Member{Key: "resolver_version", Value: p.ResolverVersion})
	}
	return o
}

// EffectiveJSON is an EffectivePolicy as a response model renders it, None
// fields included.
func (p Policy) EffectiveJSON() wirejson.Object { return emit{keepNone: true}.policy(p, true) }

// EffectiveStored is EffectivePolicy.to_json_dict(): what a snapshot stores.
func (p Policy) EffectiveStored() wirejson.Object { return emit{}.policy(p, true) }

// DocumentStored is PolicyDocument.to_json_dict().
func (p Policy) DocumentStored() wirejson.Object { return emit{}.policy(p, false) }

// ExecutionStored is ExecutionLimitsPolicy.model_dump(exclude_none=True), {} for none.
func ExecutionStored(x *Execution) wirejson.Object {
	if x == nil {
		return wirejson.Object{}
	}
	return emit{}.execution(x)
}

// MarshalJSON writes the stored form of an effective policy.
func (p Policy) MarshalJSON() ([]byte, error) { return p.EffectiveStored().MarshalJSON() }

// UnmarshalJSON reads an effective policy (effective_policy_from_json).
func (p *Policy) UnmarshalJSON(b []byte) error {
	v, err := wirejson.Unmarshal(b)
	if err != nil {
		return err
	}
	if v == nil {
		v = wirejson.Object{}
	}
	out, errs := ParsePolicy(v, nil, true)
	if len(errs) > 0 {
		msgs := make([]string, len(errs))
		for i, e := range errs {
			msgs[i] = e.Msg
		}
		return errors.New("invalid effective policy: " + strings.Join(msgs, "; "))
	}
	*p = out
	return nil
}

// Stored is the governance_snapshot metadata object.
func (s Snapshot) Stored() wirejson.Object {
	ceilings := wirejson.Object{}
	for _, c := range s.LimitCeilings {
		ceilings = append(ceilings, wirejson.Member{Key: c.Reason, Value: c.Value})
	}
	return wirejson.Object{
		{Key: "requested_policy", Value: s.RequestedPolicy.DocumentStored()},
		{Key: "requested_execution", Value: ExecutionStored(s.RequestedExecution)},
		{Key: "resolved_execution", Value: ExecutionStored(s.ResolvedExecution)},
		{Key: "effective_policy", Value: s.EffectivePolicy.EffectiveStored()},
		{Key: "limit_ceilings", Value: ceilings},
		{Key: "resolved_at", Value: isoformatUTC(s.ResolvedAt)},
		{Key: "revision", Value: s.Revision},
	}
}

// MarshalJSON writes the stored snapshot.
func (s Snapshot) MarshalJSON() ([]byte, error) { return s.Stored().MarshalJSON() }

// isoformatUTC is datetime.now(UTC).isoformat().
func isoformatUTC(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}

var _ json.Marshaler = Policy{}
