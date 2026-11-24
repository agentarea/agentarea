// Package domain holds governance's rules: the policy rule model, its
// enforceability check, the compiler from rules to a policy document and the
// monotonic resolver (agentarea_governance/domain).
package domain

import (
	"errors"
	"fmt"
	"log/slog"
	"regexp"
	"slices"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// Effects a rule may have (PolicyEffect), in declaration order.
func Effects() []string { return []string{"allow", "deny", "cap", "approval", "safety", "egress"} }

// SubjectTypes a rule binds to (PolicySubjectType), in declaration order.
func SubjectTypes() []string { return []string{"workspace", "agent", "user", "group"} }

// ManagedByAgentTools is managed_by of a rule the agent editor's approval toggle wrote.
const ManagedByAgentTools = "agent_tools"

// Rule is PolicyRule: one governance intent for one subject. Params is a
// decoded JSON object.
type Rule struct {
	ID          string
	Enabled     bool
	Priority    int64
	SubjectType string
	SubjectID   string
	Target      string
	Effect      string
	Params      any
	Condition   *string
	ManagedBy   *string
	// TargetNull is a PATCH that set target to null: the check reads None.
	TargetNull bool
}

// Known reports an effect and subject type the schema knows (_safe_to_rule).
func (r Rule) Known() bool {
	return slices.Contains(Effects(), r.Effect) && slices.Contains(SubjectTypes(), r.SubjectType)
}

func targetKinds() []string {
	return []string{
		"tool", "mcp", "model", "skill", "collection", "spend", "service", "tokens",
		"execution", "content", "registry", "registry_trust", "all",
	}
}

// ParseTarget is parse_target: "tool:x" is ("tool", "x", true), "spend" is
// ("spend", "", false), "*" is ("all", "", false).
func ParseTarget(selector string) (kind, value string, hasValue bool, err error) {
	if selector == "" {
		return "", "", false, fmt.Errorf("invalid target selector %s: must be a non-empty string", api.PyRepr(selector))
	}
	if selector == "*" {
		return "all", "", false, nil
	}
	if k, v, ok := strings.Cut(selector, ":"); ok {
		if k == "" || v == "" {
			return "", "", false, fmt.Errorf("invalid target selector %s: empty component", api.PyRepr(selector))
		}
		kind, value, hasValue = k, v, true
	} else {
		kind = selector
	}
	if !slices.Contains(targetKinds(), kind) {
		return "", "", false, fmt.Errorf("invalid target selector %s: unknown kind %s", api.PyRepr(selector), api.PyRepr(kind))
	}
	return kind, value, hasValue, nil
}

// ErrNotEnforceable marks a rule assert_enforceable refuses (a 422).
var ErrNotEnforceable = errors.New("not enforceable")

type enforceError struct{ msg string }

func (e *enforceError) Error() string        { return e.msg }
func (e *enforceError) Is(target error) bool { return target == ErrNotEnforceable }

func refuse(format string, a ...any) error { return &enforceError{fmt.Sprintf(format, a...)} }

// AssertEnforceable rejects a rule the engine would silently ignore at
// runtime; the message is the 422 detail.
func AssertEnforceable(r Rule) error {
	if r.SubjectType == "group" {
		return refuse("group subjects are not resolved yet (issue #198); bind the rule to a workspace, agent, or user")
	}
	if r.Condition != nil {
		return refuse("conditions (CEL) are not evaluated yet; omit 'condition'")
	}
	if r.TargetNull {
		return refuse("invalid target selector None: must be a non-empty string")
	}
	kind, value, hasValue, err := ParseTarget(r.Target)
	if err != nil {
		return &enforceError{err.Error()}
	}
	target := api.PyRepr(r.Target)
	switch {
	case r.Effect == "cap":
		check, ok := capParams(kind)
		if !ok {
			return refuse("cap on %s is not enforceable; caps apply to spend, service, tokens, or execution", target)
		}
		return validateParams(r, check)
	case kind == "registry" || kind == "registry_trust":
		return assertInstallRule(r, kind, value)
	case r.Effect == "deny" || r.Effect == "allow":
		if kind != "tool" {
			return refuse("%s is only enforceable on a tool target (tool:<name>), not %s", r.Effect, target)
		}
		if !hasValue || value == "*" {
			return refuse("%s requires a specific tool (tool:<name>), not a wildcard %s", r.Effect, target)
		}
		return nil
	case r.Effect == "approval":
		if kind != "all" && (kind != "tool" || !hasValue) {
			return refuse("approval is enforceable on '*' (all tools) or tool:<name>, not %s", target)
		}
		return validateParams(r, approvalParams)
	case r.Effect == "safety":
		if kind != "content" {
			return refuse("safety is only enforceable on a content target, not %s", target)
		}
		return validateParams(r, safetyParams)
	case r.Effect == "egress":
		return nil
	case r.Effect == "":
		return errors.New("a policy rule with effect None reached the enforceability check")
	}
	return refuse("effect %s on %s is not enforceable", api.PyRepr(r.Effect), target)
}

func assertInstallRule(r Rule, kind, value string) error {
	target := api.PyRepr(r.Target)
	if r.Effect != "allow" && r.Effect != "deny" {
		return refuse("only allow or deny apply to %s", target)
	}
	if r.SubjectType != "workspace" && r.SubjectType != "user" {
		return refuse("%s decides installs, so it binds to the workspace or a user", target)
	}
	if kind == "registry" {
		if value == "github" || isUUID(value) {
			return nil
		}
		return refuse("registry:<id> needs a registry id or 'github', not %s", target)
	}
	if !slices.Contains(trustLevels(), value) {
		return refuse("registry_trust:<level> needs one of %s, not %s", strings.Join(trustLevels(), ", "), target)
	}
	return nil
}

func trustLevels() []string { return []string{"official", "verified", "community", "private"} }

var uuidForms = regexp.MustCompile(`^(?i)(urn:uuid:)?\{?[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\}?$`)

// isUUID is uuid.UUID(str(value)) accepting it: hyphens, braces and a urn
// prefix are optional.
func isUUID(s string) bool {
	if !uuidForms.MatchString(s) {
		return false
	}
	hex := strings.NewReplacer("urn:uuid:", "", "URN:UUID:", "", "{", "", "}", "", "-", "").Replace(s)
	return len(hex) == 32
}

type paramsCheck func(c *api.Checker, params any)

func capParams(kind string) (paramsCheck, bool) {
	switch kind {
	case "spend":
		return spendCapParams, true
	case "service":
		return serviceCapParams, true
	case "tokens":
		return tokenCapParams, true
	case "execution":
		return executionCapParams, true
	}
	return nil, false
}

// validateParams is _validate_params: the params model's errors in one line.
func validateParams(r Rule, check paramsCheck) error {
	params := r.Params
	if params == nil {
		params = api.EmptyObject()
	}
	var c api.Checker
	check(&c, params)
	if len(c.Errs) == 0 {
		return nil
	}
	problems := make([]string, len(c.Errs))
	for i, e := range c.Errs {
		problems[i] = api.LocText(e.Loc) + ": " + e.Msg
	}
	return refuse("invalid params for %s on %s: %s", r.Effect, api.PyRepr(r.Target), strings.Join(problems, "; "))
}

func loc(k ...any) []any { return k }

func spendCapParams(c *api.Checker, p any) {
	o, ok := c.Model(p, "SpendCapParams", nil)
	if !ok {
		return
	}
	before := c.Count()
	amountZero := false
	if v, pr := api.Field(o, "amount_usd"); !pr {
		c.Errs = append(c.Errs, missing("amount_usd"))
	} else if d, ok := c.Decimal(v, loc("amount_usd"), false); ok {
		amountZero = d.IsZero()
	}
	period := "month"
	if v, pr := api.Field(o, "period"); pr {
		period, _ = c.Literal(v, loc("period"), "month", "run")
	}
	var category string
	if v, pr := api.Field(o, "category"); pr && v != nil {
		category, _ = c.Literal(v, loc("category"), "llm", "tools")
	}
	v, pr := api.Field(o, "client_id")
	client := c.OptStr(v, pr, loc("client_id"), 0, 0)
	v, pr = api.Field(o, "connection_id")
	connection := c.OptStr(v, pr, loc("connection_id"), 0, 0)
	v, pr = api.Field(o, "tool")
	tool := c.OptStr(v, pr, loc("tool"), 0, 0)
	v, pr = api.Field(o, "currency")
	currency := c.Pattern(v, pr, loc("currency"), `^[A-Z]{3}$`)
	c.Extra(o, []string{"amount_usd", "period", "category", "client_id", "connection_id", "tool", "currency"}, nil)
	if c.Count() > before {
		return
	}
	set := func(s *string) bool { return s != nil && *s != "" }
	switch {
	case period == "run" && amountZero:
		c.Fail("a per-run spend cap must be greater than 0", nil)
	case period != "month" && (set(client) || set(currency)):
		c.Fail("a client or currency spend cap is per month", nil)
	case category == "llm" && (set(client) || set(connection) || set(tool)):
		c.Fail("a client, connection or tool cap counts tool spend; it cannot be an llm cap", nil)
	case set(tool) && !set(connection):
		c.Fail("a tool spend cap names the connection_id the tool belongs to", nil)
	}
}

func serviceCapParams(c *api.Checker, p any) {
	o, ok := c.Model(p, "ServiceCapParams", nil)
	if !ok {
		return
	}
	if v, pr := api.Field(o, "amount_usd"); !pr {
		c.Errs = append(c.Errs, missing("amount_usd"))
	} else {
		c.Decimal(v, loc("amount_usd"), true)
	}
	c.Extra(o, []string{"amount_usd"}, nil)
}

func tokenCapParams(c *api.Checker, p any) {
	o, ok := c.Model(p, "TokenCapParams", nil)
	if !ok {
		return
	}
	before := c.Count()
	v, pr := api.Field(o, "max_tokens")
	a := c.OptInt(v, pr, loc("max_tokens"), true)
	v, pr = api.Field(o, "max_tokens_per_call")
	b := c.OptInt(v, pr, loc("max_tokens_per_call"), true)
	c.Extra(o, []string{"max_tokens", "max_tokens_per_call"}, nil)
	if c.Count() == before && a == nil && b == nil {
		c.Fail("token cap requires 'max_tokens' or 'max_tokens_per_call'", nil)
	}
}

func executionCapParams(c *api.Checker, p any) {
	o, ok := c.Model(p, "ExecutionCapParams", nil)
	if !ok {
		return
	}
	before := c.Count()
	v, pr := api.Field(o, "max_model_turns")
	a := c.OptInt(v, pr, loc("max_model_turns"), true)
	v, pr = api.Field(o, "max_tool_calls_per_turn")
	b := c.OptInt(v, pr, loc("max_tool_calls_per_turn"), true)
	v, pr = api.Field(o, "max_tool_calls_total")
	d := c.OptInt(v, pr, loc("max_tool_calls_total"), true)
	c.Extra(o, []string{"max_model_turns", "max_tool_calls_per_turn", "max_tool_calls_total"}, nil)
	if c.Count() == before && a == nil && b == nil && d == nil {
		c.Fail("execution cap requires 'max_model_turns', 'max_tool_calls_per_turn', or 'max_tool_calls_total'", nil)
	}
}

func approvalParams(c *api.Checker, p any) {
	o, ok := c.Model(p, "ApprovalParams", nil)
	if !ok {
		return
	}
	if v, pr := api.Field(o, "approvers"); pr {
		if refs, ok := c.Strs(v, loc("approvers")); ok {
			for _, ref := range refs {
				typ, _, _, hasRelation, err := api.ParseSubject(ref)
				if err != nil {
					c.Fail(err.Error(), loc("approvers"))
					break
				}
				if typ != "user" || hasRelation {
					c.Fail(fmt.Sprintf("approver %s is not resolved yet (issue #198); approvers must be workspace users ('user:<id>')", api.PyRepr(ref)), loc("approvers"))
					break
				}
			}
		}
	}
	c.Extra(o, []string{"approvers"}, nil)
}

func safetyParams(c *api.Checker, p any) {
	p = api.Without(p, "output_sanitizer")
	o, ok := c.Model(p, "SafetyParams", nil)
	if !ok {
		return
	}
	before := c.Count()
	v, pr := api.Field(o, "prompt_injection")
	injection := c.OptBool(v, pr, loc("prompt_injection"))
	var check *api.AnswerCheck
	if v, pr := api.Field(o, "answer_check"); pr && v != nil {
		check = c.AnswerCheck(v, loc("answer_check"))
	}
	v, pr = api.Field(o, "fetch_seen_links_only")
	seenLinks := c.OptBool(v, pr, loc("fetch_seen_links_only"))
	c.Extra(o, []string{"prompt_injection", "answer_check", "fetch_seen_links_only"}, nil)
	if c.Count() == before && injection == nil && check == nil && seenLinks == nil {
		c.Fail("safety on content requires 'prompt_injection', 'answer_check' or 'fetch_seen_links_only'", nil)
	}
}

// RulesToDocument is rules_to_document: one subject layer's enabled rules
// compiled into a policy document. Rules the compiler does not recognise are
// skipped; a recognised rule whose stored params do not build the document
// fails, as pydantic raises there.
func RulesToDocument(rules []Rule, log *slog.Logger) (api.Policy, error) {
	acc := accumulator{log: log}
	for _, r := range rules {
		if !r.Enabled {
			continue
		}
		kind, value, hasValue, err := ParseTarget(r.Target)
		if err != nil {
			log.Debug("skipping rule: unparseable target", "rule_id", r.ID, "target", r.Target)
			continue
		}
		if err := acc.apply(r, kind, value, hasValue); err != nil {
			return api.Policy{}, err
		}
	}
	return acc.document()
}

type accumulator struct {
	log               *slog.Logger
	budget            *api.Budget
	tokens            *api.Tokens
	tokenKeys         int
	execution         *api.Execution
	executionKeys     int
	allowed, denied   []string
	approvalRequired  bool
	escalationRules   []string
	approvers         []string
	approversByTool   []api.ToolApprovers
	contentSafety     *api.ContentSafety
	contentSafetyKeys int
	errs              []string
}

func (a *accumulator) b() *api.Budget {
	if a.budget == nil {
		a.budget = &api.Budget{}
	}
	return a.budget
}

func (a *accumulator) apply(r Rule, kind, value string, hasValue bool) error {
	params := r.Params
	if params == nil || !api.IsObject(params) {
		params = api.EmptyObject()
	}
	switch {
	case r.Effect == "cap":
		return a.applyCap(r, kind, params)
	case r.Effect == "deny" && kind == "tool":
		if !hasValue || value == "*" {
			a.log.Debug("skipping deny rule: wildcard tool target", "rule_id", r.ID)
			return nil
		}
		a.denied = append(a.denied, value)
	case r.Effect == "allow" && kind == "tool":
		if !hasValue || value == "*" {
			a.log.Debug("skipping allow rule: wildcard tool target", "rule_id", r.ID)
			return nil
		}
		a.allowed = append(a.allowed, value)
	case r.Effect == "approval":
		return a.applyApproval(r, kind, value, params)
	case r.Effect == "safety" && kind == "content":
		return a.applySafety(params)
	case r.Effect == "egress":
	default:
		a.log.Debug("skipping rule: unsupported effect/target", "rule_id", r.ID, "effect", r.Effect, "target", r.Target)
	}
	return nil
}

func spendScopeKeys() []string {
	return []string{"client_id", "connection_id", "tool", "currency", "category"}
}

func (a *accumulator) applyCap(r Rule, kind string, params any) error {
	switch kind {
	case "spend":
		amount, _ := api.Field(params, "amount_usd")
		if amount == nil {
			a.log.Debug("skipping cap rule: spend cap missing amount_usd", "rule_id", r.ID)
			return nil
		}
		period := any("month")
		if v, ok := api.Field(params, "period"); ok {
			period = v
		}
		category, _ := api.Field(params, "category")
		scoped := false
		for _, k := range spendScopeKeys() {
			if v, _ := api.Field(params, k); api.Truthy(v) {
				scoped = true
			}
		}
		switch {
		case period != "month" && period != "run":
			a.log.Debug("skipping cap rule: unknown spend period", "rule_id", r.ID)
		case api.Truthy(category) && category != "llm" && category != "tools":
			a.log.Debug("skipping cap rule: unknown spend category", "rule_id", r.ID)
		case scoped:
			return a.addSpendCap(r, amount, period == "run", params)
		case period == "month" && r.SubjectType == "agent":
			m := api.ToMoney(amount)
			a.b().AgentMonthlySpendCapUSD = &m
		case period == "month":
			m := api.ToMoney(amount)
			a.b().MonthlySpendCapUSD = &m
		default:
			m := api.ToMoney(amount)
			a.b().RunBudgetUSD = &m
		}
	case "service":
		amount, _ := api.Field(params, "amount_usd")
		if amount == nil {
			a.log.Debug("skipping cap rule: service cap missing amount_usd", "rule_id", r.ID)
			return nil
		}
		m := api.ToMoney(amount)
		a.b().ServiceBudgetUSD = &m
	case "tokens":
		if a.tokens == nil {
			a.tokens = &api.Tokens{}
		}
		var c api.Checker
		if v, ok := api.Field(params, "max_tokens"); ok {
			a.tokens.MaxTokens = c.OptInt(v, true, loc("max_tokens"), true)
			a.tokenKeys++
		}
		if v, ok := api.Field(params, "max_tokens_per_call"); ok {
			a.tokens.MaxTokensPerCall = c.OptInt(v, true, loc("max_tokens_per_call"), true)
			a.tokenKeys++
		}
		a.collect("TokenPolicy", c)
	case "execution":
		if a.execution == nil {
			a.execution = &api.Execution{}
		}
		var c api.Checker
		for _, f := range []struct {
			key string
			dst **int64
		}{
			{"max_model_turns", &a.execution.MaxModelTurns},
			{"max_tool_calls_per_turn", &a.execution.MaxToolCallsPerTurn},
			{"max_tool_calls_total", &a.execution.MaxToolCallsTotal},
		} {
			if v, ok := api.Field(params, f.key); ok {
				*f.dst = c.OptInt(v, true, loc(f.key), true)
				a.executionKeys++
			}
		}
		a.collect("ExecutionLimitsPolicy", c)
	default:
		a.log.Debug("skipping cap rule: unsupported cap target", "rule_id", r.ID, "target", r.Target)
	}
	return nil
}

func (a *accumulator) collect(model string, c api.Checker) {
	for _, e := range c.Errs {
		a.errs = append(a.errs, model+": "+api.LocText(e.Loc)+": "+e.Msg)
	}
}

func (a *accumulator) addSpendCap(r Rule, amount any, run bool, params any) error {
	sc := api.SpendCap{AmountUSD: api.ToMoney(amount), OwnAgent: r.SubjectType == "agent"}
	var c api.Checker
	for _, f := range []struct {
		key string
		dst **string
	}{{"client_id", &sc.ClientID}, {"connection_id", &sc.ConnectionID}, {"tool", &sc.Tool}, {"currency", &sc.Currency}, {"category", &sc.Category}} {
		if v, _ := api.Field(params, f.key); api.Truthy(v) {
			*f.dst = c.OptStr(v, true, loc("spend_caps", f.key), 0, 0)
		}
	}
	if run {
		p := "run"
		sc.Period = &p
	}
	if sc.AmountUSD.Sign() < 0 {
		a.errs = append(a.errs, "ScopedSpendCap: amount_usd: Input should be greater than or equal to 0")
	}
	a.collect("BudgetPolicy", c)
	a.b().SpendCaps = append(a.b().SpendCaps, sc)
	return nil
}

func (a *accumulator) applyApproval(r Rule, kind, value string, params any) error {
	var approvers []string
	if v, _ := api.Field(params, "approvers"); api.Truthy(v) {
		var c api.Checker
		refs, ok := c.Strs(v, loc("approvers"))
		if !ok {
			a.collect("ApprovalPolicy", c)
			return nil
		}
		approvers = refs
	}
	switch {
	case kind == "all" || (kind == "tool" && value == "*"):
		a.approvalRequired = true
		a.approvers = append(a.approvers, approvers...)
	case kind == "tool" && value != "":
		a.escalationRules = append(a.escalationRules, value)
		if len(approvers) > 0 {
			i := slices.IndexFunc(a.approversByTool, func(t api.ToolApprovers) bool { return t.Tool == value })
			if i < 0 {
				a.approversByTool = append(a.approversByTool, api.ToolApprovers{Tool: value})
				i = len(a.approversByTool) - 1
			}
			a.approversByTool[i].Refs = append(a.approversByTool[i].Refs, approvers...)
		}
	default:
		a.log.Debug("skipping approval rule: unsupported target", "rule_id", r.ID, "target", r.Target)
	}
	return nil
}

func (a *accumulator) applySafety(params any) error {
	if a.contentSafety == nil {
		a.contentSafety = &api.ContentSafety{}
	}
	if v, ok := api.Field(params, "prompt_injection"); ok {
		on := api.Truthy(v)
		a.contentSafety.PromptInjectionDetectionEnabled = &on
		a.contentSafetyKeys++
	}
	if v, _ := api.Field(params, "answer_check"); api.IsObject(v) {
		var c api.Checker
		check := c.AnswerCheck(v, loc("answer_check"))
		if len(c.Errs) > 0 {
			return fmt.Errorf("invalid answer_check in a stored safety rule: %s", c.Errs[0].Msg)
		}
		a.contentSafety.AnswerCheck = check
		a.contentSafetyKeys++
	}
	if v, ok := api.Field(params, "fetch_seen_links_only"); ok {
		on := api.Truthy(v)
		a.contentSafety.FetchSeenLinksOnly = &on
		a.contentSafetyKeys++
	}
	return nil
}

func (a *accumulator) document() (api.Policy, error) {
	if len(a.errs) > 0 {
		return api.Policy{}, fmt.Errorf("stored policy rules do not compile: %s", strings.Join(a.errs, "; "))
	}
	var p api.Policy
	if b := a.budget; b != nil {
		for _, pair := range []struct {
			name   string
			strict bool
			set    bool
			sign   int
		}{
			{"monthly_spend_cap_usd", false, b.MonthlySpendCapUSD != nil, signOf(b.MonthlySpendCapUSD)},
			{"agent_monthly_spend_cap_usd", false, b.AgentMonthlySpendCapUSD != nil, signOf(b.AgentMonthlySpendCapUSD)},
			{"run_budget_usd", true, b.RunBudgetUSD != nil, signOf(b.RunBudgetUSD)},
			{"service_budget_usd", true, b.ServiceBudgetUSD != nil, signOf(b.ServiceBudgetUSD)},
		} {
			if pair.set && (pair.sign < 0 || (pair.strict && pair.sign == 0)) {
				return api.Policy{}, fmt.Errorf("stored policy rules do not compile: BudgetPolicy: %s is out of range", pair.name)
			}
		}
		p.Budget = b
	}
	if a.tokenKeys > 0 {
		p.Tokens = a.tokens
	}
	if a.executionKeys > 0 {
		p.Execution = a.execution
	}
	if len(a.allowed) > 0 || len(a.denied) > 0 {
		t := &api.Tools{Denied: Dedupe(a.denied)}
		if allowed := Dedupe(a.allowed); len(allowed) > 0 {
			t.Allowed = allowed
		}
		p.Tools = t
	}
	if a.approvalRequired || len(a.escalationRules) > 0 || len(a.approvers) > 0 || len(a.approversByTool) > 0 {
		ap := &api.Approval{
			EscalationRules: Dedupe(a.escalationRules),
			Approvers:       Dedupe(a.approvers),
			ApproversByTool: make([]api.ToolApprovers, 0, len(a.approversByTool)),
		}
		if a.approvalRequired {
			t := true
			ap.RequiresHumanApproval = &t
		}
		for _, e := range a.approversByTool {
			ap.ApproversByTool = append(ap.ApproversByTool, api.ToolApprovers{Tool: e.Tool, Refs: Dedupe(e.Refs)})
		}
		for _, refs := range append([][]string{ap.Approvers}, byToolRefs(ap.ApproversByTool)...) {
			for _, ref := range refs {
				if _, _, _, _, err := api.ParseSubject(ref); err != nil {
					return api.Policy{}, fmt.Errorf("stored policy rules do not compile: ApprovalPolicy: %w", err)
				}
			}
		}
		p.Approval = ap
	}
	if a.contentSafetyKeys > 0 {
		p.ContentSafety = a.contentSafety
	}
	return p, nil
}

func byToolRefs(t []api.ToolApprovers) [][]string {
	out := make([][]string, len(t))
	for i, e := range t {
		out[i] = e.Refs
	}
	return out
}

type signed interface{ Sign() int }

func signOf[T signed](d *T) int {
	if d == nil {
		return 0
	}
	return (*d).Sign()
}

func missing(field string) api.FieldError { return api.MissingField(field) }
