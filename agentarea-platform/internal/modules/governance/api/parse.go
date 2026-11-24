package api

import (
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// Checker validates a decoded JSON value (wirejson.Unmarshal) the way
// pydantic 2 does in lax mode, collecting pydantic's errors.
type Checker struct{ Errs []httpx.FieldError }

func at(loc []any, k ...any) []any {
	out := make([]any, 0, len(loc)+len(k))
	return append(append(out, loc...), k...)
}

func (c *Checker) add(e httpx.FieldError) { c.Errs = append(c.Errs, e) }

// Model checks v is an object of class; nil when it is not (error added).
func (c *Checker) Model(v any, class string, loc []any) (wirejson.Object, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		c.add(httpx.FieldError{Type: "model_type", Loc: loc,
			Msg: "Input should be a valid dictionary or instance of " + class,
			Ctx: wirejson.Object{{Key: "class_name", Value: class}}})
		return nil, false
	}
	return o, true
}

// Extra reports keys outside fields (extra="forbid").
func (c *Checker) Extra(o wirejson.Object, fields []string, loc []any) {
	for _, m := range o {
		known := false
		for _, f := range fields {
			if f == m.Key {
				known = true
				break
			}
		}
		if !known {
			c.add(httpx.ExtraForbidden(at(loc, m.Key)...))
		}
	}
}

// Int is an int field; isNil when the value is None. gt0 adds Field(gt=0).
func (c *Checker) Int(v any, loc []any, gt0 bool) (n int64, ok bool) {
	switch x := v.(type) {
	case bool:
		if x {
			n = 1
		}
	case json.Number:
		i, err := strconv.ParseInt(string(x), 10, 64)
		if err != nil {
			if strings.HasPrefix(string(x), "-") {
				i = math.MinInt64
			} else {
				i = math.MaxInt64
			}
		}
		n = i
	case wirejson.Float:
		f := float64(x)
		if f != math.Trunc(f) {
			c.add(httpx.IntFromFloat(loc...))
			return 0, false
		}
		n = int64(f)
	case string:
		p, good := httpx.ParseInt(x)
		if !good {
			c.add(httpx.IntParsing(loc...))
			return 0, false
		}
		n = p.Value
	default:
		c.add(httpx.IntType(loc...))
		return 0, false
	}
	if gt0 && n <= 0 {
		c.add(httpx.GreaterThan(0, loc...))
		return 0, false
	}
	return n, true
}

// OptInt is int | None.
func (c *Checker) OptInt(v any, present bool, loc []any, gt0 bool) *int64 {
	if !present || v == nil {
		return nil
	}
	n, ok := c.Int(v, loc, gt0)
	if !ok {
		return nil
	}
	return &n
}

// Bool is a bool field.
func (c *Checker) Bool(v any, loc []any) (bool, bool) {
	switch x := v.(type) {
	case bool:
		return x, true
	case json.Number:
		switch string(x) {
		case "0":
			return false, true
		case "1":
			return true, true
		}
		c.add(httpx.BoolParsing(loc...))
	case wirejson.Float:
		switch float64(x) {
		case 0:
			return false, true
		case 1:
			return true, true
		}
		c.add(httpx.BoolParsing(loc...))
	case string:
		b, ok := httpx.ParseBool(x)
		if ok {
			return b, true
		}
		c.add(httpx.BoolParsing(loc...))
	default:
		c.add(httpx.BoolType(loc...))
	}
	return false, false
}

// OptBool is bool | None.
func (c *Checker) OptBool(v any, present bool, loc []any) *bool {
	if !present || v == nil {
		return nil
	}
	b, ok := c.Bool(v, loc)
	if !ok {
		return nil
	}
	return &b
}

// Str is a str field with optional length bounds (0: none).
func (c *Checker) Str(v any, loc []any, minLen, maxLen int) (string, bool) {
	s, ok := v.(string)
	if !ok {
		c.add(httpx.StringType(loc...))
		return "", false
	}
	n := utf8.RuneCountInString(s)
	if minLen > 0 && n < minLen {
		c.add(httpx.StringTooShort(minLen, loc...))
		return "", false
	}
	if maxLen > 0 && n > maxLen {
		c.add(httpx.StringTooLong(maxLen, loc...))
		return "", false
	}
	return s, true
}

// OptStr is str | None.
func (c *Checker) OptStr(v any, present bool, loc []any, minLen, maxLen int) *string {
	if !present || v == nil {
		return nil
	}
	s, ok := c.Str(v, loc, minLen, maxLen)
	if !ok {
		return nil
	}
	return &s
}

// Strs is list[str].
func (c *Checker) Strs(v any, loc []any) ([]string, bool) {
	arr, ok := v.([]any)
	if !ok {
		c.add(httpx.ListType(loc...))
		return nil, false
	}
	out := make([]string, 0, len(arr))
	good := true
	for i, item := range arr {
		s, ok := c.Str(item, at(loc, i), 0, 0)
		if !ok {
			good = false
			continue
		}
		out = append(out, s)
	}
	return out, good
}

// Literal is a Literal of string choices.
func (c *Checker) Literal(v any, loc []any, choices ...string) (string, bool) {
	if s, ok := v.(string); ok {
		for _, ch := range choices {
			if s == ch {
				return s, true
			}
		}
	}
	c.add(httpx.LiteralError(choices, loc...))
	return "", false
}

// PyRepr is Python's repr() of a decoded JSON value.
func PyRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return pyStrRepr(x)
	case json.Number:
		return string(x)
	case wirejson.Float:
		return wirejson.FormatFloat(float64(x))
	case []any:
		parts := make([]string, len(x))
		for i, e := range x {
			parts[i] = PyRepr(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case wirejson.Object:
		parts := make([]string, len(x))
		for i, m := range x {
			parts[i] = pyStrRepr(m.Key) + ": " + PyRepr(m.Value)
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return fmt.Sprint(v)
}

func pyStrRepr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case r == rune(quote):
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// moneyText is str(value) for the values money._parse_money reads.
func moneyText(v any) (string, bool) {
	switch x := v.(type) {
	case string:
		return x, true
	case json.Number:
		return string(x), true
	case wirejson.Float:
		return wirejson.FormatFloat(float64(x)), true
	}
	return "", false
}

var asciiDecimal = regexp.MustCompile(`^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$`)

// Money is the Money type (BeforeValidator _parse_money) with ge or gt 0.
func (c *Checker) Money(v any, loc []any, strictlyPositive bool) (money.Decimal, bool) {
	text, ok := moneyText(v)
	text = strings.TrimSpace(text)
	if !ok || !asciiDecimal.MatchString(text) {
		c.add(httpx.ValueError(PyRepr(v)+" is not a money amount", loc...))
		return money.Decimal{}, false
	}
	d, err := money.Parse(text)
	if err != nil {
		c.add(httpx.ValueError(PyRepr(v)+" is not a money amount", loc...))
		return money.Decimal{}, false
	}
	return d, c.positive(d, loc, strictlyPositive)
}

func (c *Checker) positive(d money.Decimal, loc []any, strict bool) bool {
	if strict && d.Sign() <= 0 {
		c.add(httpx.GreaterThan(0, loc...))
		return false
	}
	if !strict && d.Sign() < 0 {
		c.add(httpx.GreaterThanEqual(0, loc...))
		return false
	}
	return true
}

// OptMoney is Money | None.
func (c *Checker) OptMoney(v any, present bool, loc []any, strictlyPositive bool) *money.Decimal {
	if !present || v == nil {
		return nil
	}
	d, ok := c.Money(v, loc, strictlyPositive)
	if !ok {
		return nil
	}
	return &d
}

// Decimal is a plain decimal.Decimal field with ge or gt 0.
func (c *Checker) Decimal(v any, loc []any, strictlyPositive bool) (money.Decimal, bool) {
	var text string
	switch x := v.(type) {
	case string:
		text = strings.TrimSpace(x)
	case json.Number:
		text = string(x)
	case wirejson.Float:
		text = wirejson.FormatFloat(float64(x))
	default:
		c.add(httpx.FieldError{Type: "decimal_type", Loc: loc, Msg: "Decimal input should be an integer, float, string or Decimal object"})
		return money.Decimal{}, false
	}
	d, err := money.Parse(text)
	if err != nil {
		c.add(httpx.FieldError{Type: "decimal_parsing", Loc: loc, Msg: "Input should be a valid decimal"})
		return money.Decimal{}, false
	}
	return d, c.positive(d, loc, strictlyPositive)
}

// ParseSubject is parse_subject: "type:id" or "type:id#relation".
func ParseSubject(ref string) (typ, id, relation string, hasRelation bool, err error) {
	t, rest, ok := strings.Cut(ref, ":")
	if !ok {
		return "", "", "", false, fmt.Errorf("invalid subject ref %s: expected 'type:id' or 'type:id#relation'", pyStrRepr(ref))
	}
	id = rest
	if i := strings.Index(rest, "#"); i >= 0 {
		id, relation, hasRelation = rest[:i], rest[i+1:], true
	}
	if t == "" || id == "" || (hasRelation && relation == "") {
		return "", "", "", false, fmt.Errorf("invalid subject ref %s: empty component", pyStrRepr(ref))
	}
	return t, id, relation, hasRelation, nil
}

func (c *Checker) subjects(refs []string, loc []any) {
	for _, r := range refs {
		if _, _, _, _, err := ParseSubject(r); err != nil {
			c.add(httpx.ValueError(err.Error(), loc...))
			return
		}
	}
}

func get(o wirejson.Object, key string) (any, bool) { return o.Get(key) }

// ParsePolicy validates v as PolicyDocument at loc, or as EffectivePolicy
// when effective (which admits source_policy_ids and resolver_version).
func ParsePolicy(v any, loc []any, effective bool) (Policy, []httpx.FieldError) {
	var c Checker
	p := c.Policy(v, loc, effective)
	return p, c.Errs
}

// Policy is ParsePolicy on this checker.
func (c *Checker) Policy(v any, loc []any, effective bool) Policy {
	class := "PolicyDocument"
	if effective {
		class = "EffectivePolicy"
	}
	o, ok := c.Model(v, class, loc)
	if !ok {
		return Policy{}
	}
	var p Policy
	if x, ok := get(o, "budget"); ok && x != nil {
		p.Budget = c.budget(x, at(loc, "budget"))
	}
	if x, ok := get(o, "tokens"); ok && x != nil {
		if m, ok := c.Model(x, "TokenPolicy", at(loc, "tokens")); ok {
			t := Tokens{}
			v1, p1 := get(m, "max_tokens")
			t.MaxTokens = c.OptInt(v1, p1, at(loc, "tokens", "max_tokens"), true)
			v2, p2 := get(m, "max_tokens_per_call")
			t.MaxTokensPerCall = c.OptInt(v2, p2, at(loc, "tokens", "max_tokens_per_call"), true)
			c.Extra(m, []string{"max_tokens", "max_tokens_per_call"}, at(loc, "tokens"))
			p.Tokens = &t
		}
	}
	if x, ok := get(o, "execution"); ok && x != nil {
		p.Execution = c.execution(x, at(loc, "execution"))
	}
	if x, ok := get(o, "tools"); ok && x != nil {
		p.Tools = c.tools(x, at(loc, "tools"))
	}
	if x, ok := get(o, "approval"); ok && x != nil {
		p.Approval = c.approval(x, at(loc, "approval"))
	}
	if x, ok := get(o, "content_safety"); ok && x != nil {
		p.ContentSafety = c.contentSafety(x, at(loc, "content_safety"))
	}
	fields := []string{"budget", "tokens", "execution", "tools", "approval", "content_safety"}
	if effective {
		p.SourcePolicyIDs = []string{}
		if x, ok := get(o, "source_policy_ids"); ok {
			if ids, ok := c.Strs(x, at(loc, "source_policy_ids")); ok {
				p.SourcePolicyIDs = ids
			}
		}
		p.ResolverVersion = ResolverVersion
		if x, ok := get(o, "resolver_version"); ok {
			if s, ok := c.Str(x, at(loc, "resolver_version"), 0, 0); ok {
				p.ResolverVersion = s
			}
		}
		fields = append(fields, "source_policy_ids", "resolver_version")
	}
	c.Extra(o, fields, loc)
	return p
}

func (c *Checker) budget(v any, loc []any) *Budget {
	m, ok := c.Model(v, "BudgetPolicy", loc)
	if !ok {
		return nil
	}
	var b Budget
	x, pr := get(m, "monthly_spend_cap_usd")
	b.MonthlySpendCapUSD = c.OptMoney(x, pr, at(loc, "monthly_spend_cap_usd"), false)
	x, pr = get(m, "agent_monthly_spend_cap_usd")
	b.AgentMonthlySpendCapUSD = c.OptMoney(x, pr, at(loc, "agent_monthly_spend_cap_usd"), false)
	x, pr = get(m, "run_budget_usd")
	b.RunBudgetUSD = c.OptMoney(x, pr, at(loc, "run_budget_usd"), true)
	x, pr = get(m, "service_budget_usd")
	b.ServiceBudgetUSD = c.OptMoney(x, pr, at(loc, "service_budget_usd"), true)
	if x, pr := get(m, "spend_caps"); pr && x != nil {
		arr, ok := x.([]any)
		if !ok {
			c.add(httpx.ListType(at(loc, "spend_caps")...))
		} else {
			b.SpendCaps = []SpendCap{}
			for i, item := range arr {
				if sc, ok := c.spendCap(item, at(loc, "spend_caps", i)); ok {
					b.SpendCaps = append(b.SpendCaps, sc)
				}
			}
		}
	}
	c.Extra(m, []string{"monthly_spend_cap_usd", "agent_monthly_spend_cap_usd", "run_budget_usd", "service_budget_usd", "spend_caps"}, loc)
	return &b
}

func (c *Checker) spendCap(v any, loc []any) (SpendCap, bool) {
	m, ok := c.Model(v, "ScopedSpendCap", loc)
	if !ok {
		return SpendCap{}, false
	}
	before := len(c.Errs)
	var sc SpendCap
	if x, pr := get(m, "amount_usd"); !pr {
		c.add(httpx.Missing(at(loc, "amount_usd")...))
	} else {
		sc.AmountUSD, _ = c.Money(x, at(loc, "amount_usd"), false)
	}
	if x, pr := get(m, "own_agent"); pr {
		sc.OwnAgent, _ = c.Bool(x, at(loc, "own_agent"))
	}
	for _, f := range []struct {
		key string
		dst **string
	}{{"client_id", &sc.ClientID}, {"connection_id", &sc.ConnectionID}, {"tool", &sc.Tool}, {"currency", &sc.Currency}} {
		x, pr := get(m, f.key)
		*f.dst = c.OptStr(x, pr, at(loc, f.key), 0, 0)
	}
	if x, pr := get(m, "category"); pr && x != nil {
		if s, ok := c.Literal(x, at(loc, "category"), "llm", "tools"); ok {
			sc.Category = &s
		}
	}
	if x, pr := get(m, "period"); pr && x != nil {
		if s, ok := c.Literal(x, at(loc, "period"), "run"); ok {
			sc.Period = &s
		}
	}
	c.Extra(m, []string{"amount_usd", "own_agent", "client_id", "connection_id", "tool", "currency", "category", "period"}, loc)
	return sc, len(c.Errs) == before
}

func (c *Checker) execution(v any, loc []any) *Execution {
	m, ok := c.Model(v, "ExecutionLimitsPolicy", loc)
	if !ok {
		return nil
	}
	var x Execution
	a, pa := get(m, "max_model_turns")
	x.MaxModelTurns = c.OptInt(a, pa, at(loc, "max_model_turns"), true)
	b, pb := get(m, "max_tool_calls_per_turn")
	x.MaxToolCallsPerTurn = c.OptInt(b, pb, at(loc, "max_tool_calls_per_turn"), true)
	d, pd := get(m, "max_tool_calls_total")
	x.MaxToolCallsTotal = c.OptInt(d, pd, at(loc, "max_tool_calls_total"), true)
	c.Extra(m, []string{"max_model_turns", "max_tool_calls_per_turn", "max_tool_calls_total"}, loc)
	return &x
}

func (c *Checker) tools(v any, loc []any) *Tools {
	m, ok := c.Model(v, "ToolsPolicy", loc)
	if !ok {
		return nil
	}
	t := Tools{Denied: []string{}}
	if x, pr := get(m, "allowed"); pr && x != nil {
		if s, ok := c.Strs(x, at(loc, "allowed")); ok {
			t.Allowed = s
		}
	}
	if x, pr := get(m, "denied"); pr {
		if s, ok := c.Strs(x, at(loc, "denied")); ok {
			t.Denied = s
		}
	}
	c.Extra(m, []string{"allowed", "denied"}, loc)
	return &t
}

func (c *Checker) approval(v any, loc []any) *Approval {
	m, ok := c.Model(v, "ApprovalPolicy", loc)
	if !ok {
		return nil
	}
	a := Approval{EscalationRules: []string{}, Approvers: []string{}, ApproversByTool: []ToolApprovers{}}
	x, pr := get(m, "requires_human_approval")
	a.RequiresHumanApproval = c.OptBool(x, pr, at(loc, "requires_human_approval"))
	if x, pr := get(m, "escalation_rules"); pr {
		if s, ok := c.Strs(x, at(loc, "escalation_rules")); ok {
			a.EscalationRules = s
		}
	}
	if x, pr := get(m, "approvers"); pr {
		if s, ok := c.Strs(x, at(loc, "approvers")); ok {
			c.subjects(s, at(loc, "approvers"))
			a.Approvers = s
		}
	}
	if x, pr := get(m, "approvers_by_tool"); pr {
		obj, ok := x.(wirejson.Object)
		if !ok {
			c.add(httpx.DictType(at(loc, "approvers_by_tool")...))
		} else {
			before := len(c.Errs)
			for _, e := range obj {
				if s, ok := c.Strs(e.Value, at(loc, "approvers_by_tool", e.Key)); ok {
					a.ApproversByTool = append(a.ApproversByTool, ToolApprovers{Tool: e.Key, Refs: s})
				}
			}
			if len(c.Errs) == before {
				for _, t := range a.ApproversByTool {
					before := len(c.Errs)
					c.subjects(t.Refs, at(loc, "approvers_by_tool"))
					if len(c.Errs) > before {
						break
					}
				}
			}
		}
	}
	c.Extra(m, []string{"requires_human_approval", "escalation_rules", "approvers", "approvers_by_tool"}, loc)
	return &a
}

func (c *Checker) contentSafety(v any, loc []any) *ContentSafety {
	m, ok := c.Model(v, "ContentSafetyPolicy", loc)
	if !ok {
		return nil
	}
	var cs ContentSafety
	x, pr := get(m, "prompt_injection_detection_enabled")
	cs.PromptInjectionDetectionEnabled = c.OptBool(x, pr, at(loc, "prompt_injection_detection_enabled"))
	if x, pr := get(m, "answer_check"); pr && x != nil {
		cs.AnswerCheck = c.AnswerCheck(x, at(loc, "answer_check"))
	}
	x, pr = get(m, "fetch_seen_links_only")
	cs.FetchSeenLinksOnly = c.OptBool(x, pr, at(loc, "fetch_seen_links_only"))
	c.Extra(m, []string{"prompt_injection_detection_enabled", "answer_check", "output_sanitizer_enabled", "fetch_seen_links_only"}, loc)
	return &cs
}

// AnswerCheck is AnswerCheckPolicy.
func (c *Checker) AnswerCheck(v any, loc []any) *AnswerCheck {
	m, ok := c.Model(v, "AnswerCheckPolicy", loc)
	if !ok {
		return nil
	}
	ac := AnswerCheck{Enabled: true}
	if x, pr := get(m, "enabled"); pr {
		ac.Enabled, _ = c.Bool(x, at(loc, "enabled"))
	}
	x, pr := get(m, "language")
	ac.Language = c.OptStr(x, pr, at(loc, "language"), 2, 8)
	x, pr = get(m, "rewrite_instruction")
	ac.RewriteInstruction = c.OptStr(x, pr, at(loc, "rewrite_instruction"), 1, 4000)
	c.Extra(m, []string{"enabled", "language", "rewrite_instruction"}, loc)
	return &ac
}

// Field is a key of a decoded JSON object; false when v is not an object or lacks it.
func Field(v any, key string) (any, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		return nil, false
	}
	return o.Get(key)
}

// IsObject reports a decoded JSON object.
func IsObject(v any) bool {
	_, ok := v.(wirejson.Object)
	return ok
}

// Without is the object without key (a model's mode="before" drop).
func Without(v any, key string) any {
	o, ok := v.(wirejson.Object)
	if !ok {
		return v
	}
	out := make(wirejson.Object, 0, len(o))
	for _, m := range o {
		if m.Key != key {
			out = append(out, m)
		}
	}
	return out
}

// EmptyObject is {}.
func EmptyObject() any { return wirejson.Object{} }

// Truthy is Python's bool() of a decoded JSON value.
func Truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case json.Number:
		f, err := strconv.ParseFloat(string(x), 64)
		return err != nil || f != 0
	case wirejson.Float:
		return x != 0
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case wirejson.Object:
		return len(x) > 0
	}
	return true
}

// ToMoney is to_money: Decimal(str(value)), zero when that is not a number.
func ToMoney(v any) money.Decimal {
	if v == nil {
		return money.Zero()
	}
	var text string
	switch x := v.(type) {
	case string:
		text = strings.TrimSpace(x)
	case json.Number:
		text = string(x)
	case wirejson.Float:
		text = wirejson.FormatFloat(float64(x))
	default:
		return money.Zero()
	}
	d, err := money.Parse(text)
	if err != nil {
		return money.Zero()
	}
	return d
}

// LocText is '.'.join(str(loc)), "params" when empty.
func LocText(loc []any) string {
	parts := make([]string, len(loc))
	for i, p := range loc {
		parts[i] = fmt.Sprint(p)
	}
	if len(parts) == 0 {
		return "params"
	}
	return strings.Join(parts, ".")
}

// Pattern is a str field matching a regular expression (pattern=).
func (c *Checker) Pattern(v any, present bool, loc []any, pattern string) *string {
	s := c.OptStr(v, present, loc, 0, 0)
	if s == nil {
		return nil
	}
	if !regexp.MustCompile(pattern).MatchString(*s) {
		c.add(httpx.StringPatternMismatch(pattern, loc...))
		return nil
	}
	return s
}

// Fail adds a model validator's ValueError at loc.
func (c *Checker) Fail(msg string, loc []any) { c.add(httpx.ValueError(msg, loc...)) }

// Count is the number of errors so far.
func (c *Checker) Count() int { return len(c.Errs) }

// FieldError is one pydantic error.
type FieldError = httpx.FieldError

// MissingField is "Field required" at a model's own field.
func MissingField(field string) FieldError { return httpx.Missing(field) }
