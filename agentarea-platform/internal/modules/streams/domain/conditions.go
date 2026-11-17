package domain

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"math/big"
	"sort"
	"strconv"
	"strings"
)

// Condition types (ConditionType); an untyped condition is an LLM condition.
const (
	ConditionLLM      = "llm"
	ConditionRule     = "rule"
	ConditionCombined = "combined"
)

// ErrConditionUndecided is TriggerConditionError: the conditions could not be evaluated, so the
// trigger must not fire. A condition nobody could check is not a condition that passed.
var ErrConditionUndecided = errors.New("trigger conditions could not be evaluated")

// ConditionVerdict is what a condition decided about one event, and why.
type ConditionVerdict struct {
	Met    bool
	Score  *float64
	Reason string
}

type conditionError struct{ msg string }

func (e *conditionError) Error() string { return e.msg }

type undecided struct{ msg string }

func (e *undecided) Error() string        { return e.msg }
func (e *undecided) Is(target error) bool { return target == ErrConditionUndecided }

type pyTypeError struct{ msg string }

func (e *pyTypeError) Error() string { return e.msg }

func condErr(format string, a ...any) error { return &conditionError{fmt.Sprintf(format, a...)} }

func validLogic() string { return "{'AND', 'OR'}" }

func validOperator(op string) bool {
	switch op {
	case "eq", "ne", "gt", "lt", "gte", "lte", "contains", "not_contains", "exists", "not_exists":
		return true
	}
	return false
}

// conditionType is _condition_type: "" when the condition names no known type.
func conditionType(c map[string]any) string {
	t, ok := c["type"]
	if !ok {
		return ConditionLLM
	}
	s, _ := t.(string)
	switch s {
	case ConditionLLM, ConditionRule, ConditionCombined:
		return s
	}
	return ""
}

// ConditionSyntaxErrors is condition_syntax_errors: the syntax errors of a condition body.
func ConditionSyntaxErrors(c map[string]any) []string {
	var (
		errs []string
		err  error
	)
	switch conditionType(c) {
	case "":
		return []string{"Unknown condition type: " + pyStr(c["type"])}
	case ConditionRule:
		errs, err = ruleConditionErrors(c)
	case ConditionLLM:
		errs, err = llmConditionErrors(c)
	default:
		errs, err = combinedConditionErrors(c)
	}
	if err != nil {
		return []string{"Validation error: " + err.Error()}
	}
	return errs
}

func logicErrors(c map[string]any, missing string) ([]string, error) {
	logic := c["logic"]
	if !pyTruthy(logic) {
		return []string{missing}, nil
	}
	s, ok := logic.(string)
	if !ok {
		return nil, noAttribute(logic, "upper")
	}
	if u := strings.ToUpper(s); u != "AND" && u != "OR" {
		return []string{fmt.Sprintf("Invalid logic operator: %s. Must be one of %s", s, validLogic())}, nil
	}
	return nil, nil
}

func ruleConditionErrors(c map[string]any) ([]string, error) {
	var errs []string
	rules := getOr(c, "rules", []any{})
	if !pyTruthy(rules) {
		errs = append(errs, "Rule condition must have at least one rule")
	}
	le, err := logicErrors(c, "Rule condition must name its 'logic' (AND or OR)")
	if err != nil {
		return nil, err
	}
	errs = append(errs, le...)
	items, err := pyIter(rules)
	if err != nil {
		return nil, err
	}
	for i, item := range items {
		rule, ok := item.(map[string]any)
		if !ok {
			errs = append(errs, fmt.Sprintf("Rule %d must be a dictionary", i))
			continue
		}
		if _, ok := rule["field"]; !ok {
			errs = append(errs, fmt.Sprintf("Rule %d missing required 'field'", i))
		}
		op := rule["operator"]
		if !pyTruthy(op) {
			errs = append(errs, fmt.Sprintf("Rule %d missing required 'operator'", i))
		} else if !hashable(op) {
			return nil, &pyTypeError{fmt.Sprintf("unhashable type: '%s'", pyType(op))}
		} else if s, _ := op.(string); !validOperator(s) {
			errs = append(errs, fmt.Sprintf("Rule %d has invalid operator: %s", i, pyStr(op)))
		}
		if !hashable(op) {
			return nil, &pyTypeError{fmt.Sprintf("unhashable type: '%s'", pyType(op))}
		}
		s, _ := op.(string)
		if _, has := rule["value"]; s != "exists" && s != "not_exists" && !has {
			errs = append(errs, fmt.Sprintf("Rule %d missing required 'value' for operator %s", i, pyStr(op)))
		}
	}
	return errs, nil
}

func llmConditionErrors(c map[string]any) ([]string, error) {
	var errs []string
	if !pyTruthy(c["description"]) {
		errs = append(errs, "LLM condition must have a 'description'")
	}
	if !pyTruthy(c["model_id"]) {
		errs = append(errs, "LLM condition must name its 'model_id'")
	}
	if fields := getOr(c, "context_fields", []any{}); pyTruthy(fields) {
		if _, ok := fields.([]any); !ok {
			errs = append(errs, "context_fields must be a list")
		}
	}
	examples := getOr(c, "examples", []any{})
	if _, ok := examples.([]any); pyTruthy(examples) && !ok {
		errs = append(errs, "examples must be a list")
	}
	items, err := pyIter(examples)
	if err != nil {
		return nil, err
	}
	for i, item := range items {
		ex, ok := item.(map[string]any)
		if !ok {
			errs = append(errs, fmt.Sprintf("Example %d must be a dictionary", i))
			continue
		}
		_, in := ex["input"]
		_, exp := ex["expected"]
		if !in || !exp {
			errs = append(errs, fmt.Sprintf("Example %d must have 'input' and 'expected' fields", i))
		}
	}
	return errs, nil
}

func combinedConditionErrors(c map[string]any) ([]string, error) {
	var errs []string
	conds := getOr(c, "conditions", []any{})
	if !pyTruthy(conds) {
		errs = append(errs, "Combined condition must have at least one sub-condition")
	}
	le, err := logicErrors(c, "Combined condition must name its 'logic' (AND or OR)")
	if err != nil {
		return nil, err
	}
	errs = append(errs, le...)
	items, err := pyIter(conds)
	if err != nil {
		return nil, err
	}
	for i, item := range items {
		sub, ok := item.(map[string]any)
		if !ok {
			errs = append(errs, fmt.Sprintf("Sub-condition %d must be a dictionary", i))
			continue
		}
		for _, e := range ConditionSyntaxErrors(sub) {
			errs = append(errs, fmt.Sprintf("Sub-condition %d: %s", i, e))
		}
	}
	return errs, nil
}

// isLLMCondition is is_llm_condition: an explicit llm condition, or an untyped one with a description.
func isLLMCondition(c map[string]any) bool {
	t := c["type"]
	if t == nil {
		_, has := c["description"]
		return has
	}
	return t == ConditionLLM
}

// LLMConditions is llm_conditions: every LLM condition, through nested combined conditions.
func LLMConditions(c any) []map[string]any {
	m, ok := c.(map[string]any)
	if !ok {
		return nil
	}
	if m["type"] == ConditionCombined {
		subs := m["conditions"]
		if !pyTruthy(subs) {
			return nil
		}
		items, err := pyIter(subs)
		if err != nil {
			return nil
		}
		var out []map[string]any
		for _, sub := range items {
			out = append(out, LLMConditions(sub)...)
		}
		return out
	}
	if isLLMCondition(m) {
		return []map[string]any{m}
	}
	return nil
}

// CheckConditionModels is validate_condition_models up to what needs no store: an LLM condition
// must name a model instance id. The service then checks the instance's kind (ModelsOfConditions).
func CheckConditionModels(c map[string]any) error {
	for _, cond := range LLMConditions(c) {
		id := cond["model_id"]
		if !pyTruthy(id) {
			return Invalid("An LLM condition needs a model_id: the chat or decision model instance that evaluates it")
		}
		if !pyUUID(pyStr(id)) {
			return Invalid(fmt.Sprintf("Condition model_id '%s' is not a model instance id", pyStr(id)))
		}
	}
	return nil
}

// CheckConditions is the conditions part of validate_trigger_configuration (and of update).
func CheckConditions(c map[string]any) error {
	if err := CheckConditionModels(c); err != nil {
		return err
	}
	if len(c) == 0 {
		return nil
	}
	if errs := ConditionSyntaxErrors(c); len(errs) > 0 {
		return Invalid(strings.Join(errs, "; "))
	}
	return nil
}

// EvaluateConditions is evaluate_trigger_verdict: a trigger without conditions passes; an error is
// ErrConditionUndecided. Only a body of nothing but field_matches falls back to the rule check.
func EvaluateConditions(ctx context.Context, conditions, event map[string]any, judge LLMJudge) (ConditionVerdict, error) {
	if len(conditions) == 0 {
		return ConditionVerdict{Met: true, Reason: "trigger has no conditions"}, nil
	}
	v, err := evaluateStructured(ctx, conditions, event, judge)
	if err == nil {
		return v, nil
	}
	if !onlyFieldMatches(conditions) {
		return ConditionVerdict{}, &undecided{"Trigger conditions could not be evaluated: " + err.Error()}
	}
	v, ferr := fieldMatches(conditions, event)
	if ferr != nil {
		return ConditionVerdict{}, &undecided{"Trigger conditions could not be evaluated: " + ferr.Error()}
	}
	return v, nil
}

func onlyFieldMatches(c map[string]any) bool {
	_, ok := c["field_matches"]
	return ok && len(c) == 1
}

func fieldMatches(c, event map[string]any) (ConditionVerdict, error) {
	fm, ok := c["field_matches"].(map[string]any)
	if !ok {
		return ConditionVerdict{}, noAttribute(c["field_matches"], "items")
	}
	for _, path := range sortedKeys(fm) {
		actual, _ := ValueAt(event, path)
		if !pyEqual(actual, fm[path]) {
			return ConditionVerdict{Reason: fmt.Sprintf("%s is %s, not %s", path, pyReprValue(actual), pyReprValue(fm[path]))}, nil
		}
	}
	return ConditionVerdict{Met: true, Reason: "every field_matches entry matched"}, nil
}

// evaluateStructured is LLMConditionEvaluator.evaluate_structured: a failure is a *conditionError.
func evaluateStructured(ctx context.Context, c any, event map[string]any, judge LLMJudge) (ConditionVerdict, error) {
	m, ok := c.(map[string]any)
	if !ok {
		return ConditionVerdict{}, condErr("Condition evaluation failed: %s", noAttribute(c, "get"))
	}
	var (
		v   ConditionVerdict
		err error
	)
	switch conditionType(m) {
	case "":
		return ConditionVerdict{}, condErr("Unknown condition type: %s", pyStr(m["type"]))
	case ConditionRule:
		v, err = evaluateRule(m, event)
	case ConditionLLM:
		v, err = evaluateLLM(ctx, m, event, judge)
	default:
		v, err = evaluateCombined(ctx, m, event, judge)
	}
	var ce *conditionError
	if err != nil && !errors.As(err, &ce) {
		return ConditionVerdict{}, condErr("Condition evaluation failed: %s", err)
	}
	return v, err
}

func upperLogic(logic any) (string, error) {
	s, ok := logic.(string)
	if !ok {
		return "", noAttribute(logic, "upper")
	}
	return strings.ToUpper(s), nil
}

func evaluateRule(c, event map[string]any) (ConditionVerdict, error) {
	rules := c["rules"]
	if !pyTruthy(rules) {
		return ConditionVerdict{}, condErr("Rule condition needs at least one rule")
	}
	if !pyTruthy(c["logic"]) {
		return ConditionVerdict{}, condErr("Rule condition needs its 'logic' (AND or OR)")
	}
	logic, err := upperLogic(c["logic"])
	if err != nil {
		return ConditionVerdict{}, err
	}
	items, err := pyIter(rules)
	if err != nil {
		return ConditionVerdict{}, err
	}
	matched := 0
	results := make([]bool, 0, len(items))
	for _, item := range items {
		rule, ok := item.(map[string]any)
		if !ok {
			return ConditionVerdict{}, noAttribute(item, "get")
		}
		field := rule["field"]
		if !pyTruthy(field) {
			return ConditionVerdict{}, condErr("Rule is missing its 'field'")
		}
		op := rule["operator"]
		if !pyTruthy(op) {
			return ConditionVerdict{}, condErr("Rule is missing its 'operator'")
		}
		path, ok := field.(string)
		if !ok {
			return ConditionVerdict{}, noAttribute(field, "split")
		}
		actual, _ := ValueAt(event, path)
		r, err := applyOperator(op, actual, rule["value"])
		if err != nil {
			return ConditionVerdict{}, err
		}
		results = append(results, r)
		if r {
			matched++
		}
	}
	var met bool
	switch logic {
	case "AND":
		met = matched == len(results)
	case "OR":
		met = matched > 0
	default:
		return ConditionVerdict{}, condErr("Unknown rule logic: %s", logic)
	}
	return ConditionVerdict{Met: met, Reason: fmt.Sprintf("rule (%s): %d of %d rules matched", logic, matched, len(results))}, nil
}

func applyOperator(op, actual, expected any) (bool, error) {
	name, _ := op.(string)
	switch name {
	case "eq":
		return pyEqual(actual, expected), nil
	case "ne":
		return !pyEqual(actual, expected), nil
	case "gt", "lt", "gte", "lte":
		if actual == nil {
			return false, nil
		}
		return pyCompare(actual, expected, map[string]string{"gt": ">", "lt": "<", "gte": ">=", "lte": "<="}[name])
	case "contains", "not_contains":
		if actual == nil {
			return false, nil
		}
		s, ok := expected.(string)
		if !ok {
			return false, &pyTypeError{fmt.Sprintf("'in <string>' requires string as left operand, not %s", pyType(expected))}
		}
		in := strings.Contains(pyStr(actual), s)
		if name == "contains" {
			return in, nil
		}
		return !in, nil
	case "exists":
		return actual != nil, nil
	case "not_exists":
		return actual == nil, nil
	}
	return false, condErr("Unknown operator: %s", pyStr(op))
}

func evaluateLLM(ctx context.Context, c, event map[string]any, judge LLMJudge) (ConditionVerdict, error) {
	description := getOr(c, "description", "")
	if !pyTruthy(description) {
		return ConditionVerdict{}, condErr("LLM condition description is required")
	}
	q := LLMQuestion{Description: pyStr(description), Event: event}
	if fields, err := pyIter(getOr(c, "context_fields", []any{})); err != nil {
		return ConditionVerdict{}, err
	} else if len(fields) > 0 {
		q.Context = map[string]any{}
		for _, f := range fields {
			key := pyStr(f)
			q.Context[key], _ = ValueAt(event, key)
		}
	}
	examples, err := pyIter(getOr(c, "examples", []any{}))
	if err != nil {
		return ConditionVerdict{}, err
	}
	q.Examples = examples
	raw := c["model_id"]
	if !pyTruthy(raw) {
		return ConditionVerdict{}, condErr("LLM condition has no model_id")
	}
	if !pyUUID(pyStr(raw)) {
		return ConditionVerdict{}, condErr("LLM condition model_id '%s' is not a model instance id", pyStr(raw))
	}
	q.ModelID = pyUUIDString(pyStr(raw))
	if judge == nil {
		return ConditionVerdict{}, condErr("LLM condition on model instance %s cannot be evaluated: no condition model calls are wired", q.ModelID)
	}
	return judge(ctx, q)
}

func evaluateCombined(ctx context.Context, c, event map[string]any, judge LLMJudge) (ConditionVerdict, error) {
	conds := c["conditions"]
	if !pyTruthy(conds) {
		return ConditionVerdict{}, condErr("Combined condition needs at least one sub-condition")
	}
	if !pyTruthy(c["logic"]) {
		return ConditionVerdict{}, condErr("Combined condition needs its 'logic' (AND or OR)")
	}
	logic, err := upperLogic(c["logic"])
	if err != nil {
		return ConditionVerdict{}, err
	}
	items, err := pyIter(conds)
	if err != nil {
		return ConditionVerdict{}, err
	}
	verdicts := make([]ConditionVerdict, 0, len(items))
	for _, sub := range items {
		v, err := evaluateStructured(ctx, sub, event, judge)
		if err != nil {
			return ConditionVerdict{}, err
		}
		verdicts = append(verdicts, v)
	}
	allMet, anyMet := true, false
	var score *float64
	reasons := make([]string, 0, len(verdicts))
	for _, v := range verdicts {
		allMet = allMet && v.Met
		anyMet = anyMet || v.Met
		reasons = append(reasons, v.Reason)
		if v.Score == nil {
			continue
		}
		s := *v.Score
		if score == nil || (logic == "AND" && s < *score) || (logic != "AND" && s > *score) {
			score = &s
		}
	}
	var met bool
	switch logic {
	case "AND":
		met = allMet
	case "OR":
		met = anyMet
	default:
		return ConditionVerdict{}, condErr("Unknown combined logic: %s", logic)
	}
	return ConditionVerdict{Met: met, Score: score, Reason: logic + ": " + strings.Join(reasons, "; ")}, nil
}

func getOr(m map[string]any, key string, def any) any {
	if v, ok := m[key]; ok {
		return v
	}
	return def
}

func sortedKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func noAttribute(v any, attr string) error {
	return &pyTypeError{fmt.Sprintf("'%s' object has no attribute '%s'", pyType(v), attr)}
}

// pyNum is a JSON number as Python holds it: an int (exact) or a float.
type pyNum struct {
	i     *big.Int
	f     float64
	isInt bool
}

func numOf(v any) (pyNum, bool) {
	switch x := v.(type) {
	case bool:
		if x {
			return pyNum{i: big.NewInt(1), isInt: true}, true
		}
		return pyNum{i: big.NewInt(0), isInt: true}, true
	case int:
		return pyNum{i: big.NewInt(int64(x)), isInt: true}, true
	case int64:
		return pyNum{i: big.NewInt(x), isInt: true}, true
	case float64:
		return pyNum{f: x}, true
	case json.Number:
		s := string(x)
		if !strings.ContainsAny(s, ".eE") {
			if i, ok := new(big.Int).SetString(s, 10); ok {
				return pyNum{i: i, isInt: true}, true
			}
		}
		f, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return pyNum{}, false
		}
		return pyNum{f: f}, true
	}
	return pyNum{}, false
}

func (n pyNum) cmp(o pyNum) (int, bool) {
	if n.isInt && o.isInt {
		return n.i.Cmp(o.i), true
	}
	a, b := n.float(), o.float()
	if math.IsNaN(a) || math.IsNaN(b) {
		return 0, false
	}
	if n.isInt && !math.IsInf(b, 0) {
		return new(big.Float).SetInt(n.i).Cmp(big.NewFloat(b)), true
	}
	if o.isInt && !math.IsInf(a, 0) {
		return big.NewFloat(a).Cmp(new(big.Float).SetInt(o.i)), true
	}
	switch {
	case a < b:
		return -1, true
	case a > b:
		return 1, true
	}
	return 0, true
}

func (n pyNum) float() float64 {
	if n.isInt {
		f, _ := new(big.Float).SetInt(n.i).Float64()
		return f
	}
	return n.f
}

// pyEqual is Python's == over JSON values (True == 1, 1 == 1.0).
func pyEqual(a, b any) bool {
	if na, ok := numOf(a); ok {
		nb, ok := numOf(b)
		if !ok {
			return false
		}
		c, ok := na.cmp(nb)
		return ok && c == 0
	}
	switch x := a.(type) {
	case nil:
		return b == nil
	case string:
		y, ok := b.(string)
		return ok && x == y
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !pyEqual(x[i], y[i]) {
				return false
			}
		}
		return true
	case map[string]any:
		y, ok := b.(map[string]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for k, v := range x {
			w, ok := y[k]
			if !ok || !pyEqual(v, w) {
				return false
			}
		}
		return true
	}
	return false
}

// pyCompare is Python's a <op> b for an ordering op; a TypeError between unorderable types.
func pyCompare(a, b any, op string) (bool, error) {
	c, err := pyOrder(a, b, op)
	if err != nil {
		return false, err
	}
	switch op {
	case "<":
		return c < 0, nil
	case "<=":
		return c <= 0, nil
	case ">":
		return c > 0, nil
	}
	return c >= 0, nil
}

// pyOrder orders a and b; 2 marks an incomparable pair (NaN), which no op holds for.
func pyOrder(a, b any, op string) (int, error) {
	unorderable := &pyTypeError{fmt.Sprintf("'%s' not supported between instances of '%s' and '%s'", op, pyType(a), pyType(b))}
	if na, ok := numOf(a); ok {
		nb, ok := numOf(b)
		if !ok {
			return 0, unorderable
		}
		c, ok := na.cmp(nb)
		if !ok {
			return nanOrder(op), nil
		}
		return c, nil
	}
	switch x := a.(type) {
	case string:
		y, ok := b.(string)
		if !ok {
			return 0, unorderable
		}
		return strings.Compare(x, y), nil
	case []any:
		y, ok := b.([]any)
		if !ok {
			return 0, unorderable
		}
		for i := 0; i < len(x) && i < len(y); i++ {
			if !pyEqual(x[i], y[i]) {
				return pyOrder(x[i], y[i], op)
			}
		}
		switch {
		case len(x) < len(y):
			return -1, nil
		case len(x) > len(y):
			return 1, nil
		}
		return 0, nil
	}
	return 0, unorderable
}

// nanOrder is an order no op holds for, as every comparison with NaN is False.
func nanOrder(op string) int {
	switch op {
	case "<", "<=":
		return 1
	}
	return -1
}

func pyType(v any) string {
	switch x := v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case string:
		return "str"
	case []any:
		return "list"
	case map[string]any:
		return "dict"
	case int, int64:
		return "int"
	case float64:
		if x == math.Trunc(x) && math.Abs(x) < 1e16 {
			return "int"
		}
		return "float"
	case json.Number:
		if n, ok := numOf(x); ok && n.isInt {
			return "int"
		}
		return "float"
	}
	return fmt.Sprintf("%T", v)
}

func pyTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	if n, ok := numOf(v); ok {
		if n.isInt {
			return n.i.Sign() != 0
		}
		return n.f != 0
	}
	return true
}

func hashable(v any) bool {
	switch v.(type) {
	case []any, map[string]any:
		return false
	}
	return true
}

// pyIter is iter(v) as a for loop sees it: a str yields its characters, a dict its keys.
func pyIter(v any) ([]any, error) {
	switch x := v.(type) {
	case []any:
		return x, nil
	case string:
		out := make([]any, 0, len(x))
		for _, r := range x {
			out = append(out, string(r))
		}
		return out, nil
	case map[string]any:
		out := make([]any, 0, len(x))
		for _, k := range sortedKeys(x) {
			out = append(out, k)
		}
		return out, nil
	}
	return nil, &pyTypeError{fmt.Sprintf("'%s' object is not iterable", pyType(v))}
}

// pyStr is str() of a JSON value.
func pyStr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return pyReprValue(v)
}

// pyReprValue is repr() of a JSON value; a dict's keys in sorted order.
func pyReprValue(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return PyRepr(x)
	case json.Number:
		return pyNumber(string(x))
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		if x == math.Trunc(x) && math.Abs(x) < 1e16 {
			return strconv.FormatFloat(x, 'f', 0, 64)
		}
		return PyFloat(x)
	case []any:
		parts := make([]string, len(x))
		for i, e := range x {
			parts[i] = pyReprValue(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		parts := make([]string, 0, len(x))
		for _, k := range sortedKeys(x) {
			parts = append(parts, PyRepr(k)+": "+pyReprValue(x[k]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return fmt.Sprint(v)
}

// pyUUID is whether UUID(s) parses: hex digits, with optional braces, hyphens and urn:uuid: prefix.
// pyUUIDString is str(UUID(s)) of an id pyUUID accepts.
func pyUUIDString(s string) string {
	h := strings.ToLower(strings.ReplaceAll(strings.ReplaceAll(s, "urn:", ""), "uuid:", ""))
	h = strings.ReplaceAll(strings.Trim(h, "{}"), "-", "")
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32]
}

func pyUUID(s string) bool {
	h := strings.ReplaceAll(strings.ReplaceAll(s, "urn:", ""), "uuid:", "")
	h = strings.ReplaceAll(strings.Trim(h, "{}"), "-", "")
	if len(h) != 32 {
		return false
	}
	_, ok := new(big.Int).SetString(h, 16)
	return ok
}
