package domain_test

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

func jsonMap(t *testing.T, s string) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func TestConditionSyntaxErrorsMatchPython(t *testing.T) {
	cases := []struct {
		body string
		want []string
	}{
		{`{"type": "rule", "logic": "AND", "rules": [{"field": "a", "operator": "eq", "value": 1}]}`, nil},
		{`{"type": "rule"}`, []string{"Rule condition must have at least one rule", "Rule condition must name its 'logic' (AND or OR)"}},
		{`{"type": "rule", "logic": "XOR", "rules": [{"operator": "between"}, "x"]}`, []string{
			"Invalid logic operator: XOR. Must be one of {'AND', 'OR'}", "Rule 0 missing required 'field'",
			"Rule 0 has invalid operator: between", "Rule 0 missing required 'value' for operator between", "Rule 1 must be a dictionary"}},
		{`{"type": "rule", "logic": "or", "rules": [{"field": "a"}]}`, []string{
			"Rule 0 missing required 'operator'", "Rule 0 missing required 'value' for operator None"}},
		{`{"type": "rule", "logic": 1, "rules": [{"field": "a", "operator": "exists"}]}`, []string{
			"Validation error: 'int' object has no attribute 'upper'"}},
		{`{"description": "x", "model_id": "m", "examples": [{"input": 1}, 2]}`, []string{
			"Example 0 must have 'input' and 'expected' fields", "Example 1 must be a dictionary"}},
		{`{"type": "llm", "examples": null}`, []string{"Validation error: 'NoneType' object is not iterable"}},
		{`{"type": "combined", "logic": "AND", "conditions": [{"type": "rule"}, 3]}`, []string{
			"Sub-condition 0: Rule condition must have at least one rule",
			"Sub-condition 0: Rule condition must name its 'logic' (AND or OR)", "Sub-condition 1 must be a dictionary"}},
		{`{"type": "regex"}`, []string{"Unknown condition type: regex"}},
		{`{"type": null}`, []string{"Unknown condition type: None"}},
	}
	for _, c := range cases {
		if got := domain.ConditionSyntaxErrors(jsonMap(t, c.body)); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s\n got %q\nwant %q", c.body, got, c.want)
		}
	}
}

func TestRuleConditionsDecideAsPythonDoes(t *testing.T) {
	event := jsonMap(t, `{"n": 5, "f": 2.5, "flag": true, "s": "Hello", "tags": ["a", 1], "obj": {"k": null}, "nil": null}`)
	cases := []struct {
		rule string
		met  bool
	}{
		{`{"field": "n", "operator": "eq", "value": 5.0}`, true},
		{`{"field": "flag", "operator": "eq", "value": 1}`, true},
		{`{"field": "n", "operator": "ne", "value": "5"}`, true},
		{`{"field": "f", "operator": "lt", "value": 3}`, true},
		{`{"field": "s", "operator": "gte", "value": "Hello"}`, true},
		{`{"field": "tags", "operator": "lt", "value": ["a", 2]}`, true},
		{`{"field": "missing", "operator": "gt", "value": 1}`, false},
		{`{"field": "flag", "operator": "contains", "value": "Tru"}`, true},
		{`{"field": "tags", "operator": "contains", "value": "['a', 1]"}`, true},
		{`{"field": "obj", "operator": "contains", "value": "{'k': None}"}`, true},
		{`{"field": "n", "operator": "not_contains", "value": "6"}`, true},
		{`{"field": "missing", "operator": "not_contains", "value": "x"}`, false},
		{`{"field": "nil", "operator": "exists"}`, false},
		{`{"field": "nil", "operator": "not_exists"}`, true},
	}
	for _, c := range cases {
		cond := jsonMap(t, `{"type": "rule", "logic": "AND", "rules": [`+c.rule+`]}`)
		v, err := domain.EvaluateConditions(context.Background(), cond, event, nil)
		if err != nil || v.Met != c.met {
			t.Errorf("%s: met=%v err=%v, want %v", c.rule, v.Met, err, c.met)
		}
	}
	or := jsonMap(t, `{"type": "rule", "logic": "or", "rules": [
		{"field": "n", "operator": "eq", "value": 1}, {"field": "s", "operator": "eq", "value": "Hello"}]}`)
	if v, err := domain.EvaluateConditions(context.Background(), or, event, nil); err != nil || !v.Met || v.Reason != "rule (OR): 1 of 2 rules matched" {
		t.Fatalf("or = %+v %v", v, err)
	}
}

func TestConditionErrorsAreUndecidedWithPythonsWords(t *testing.T) {
	event := map[string]any{"n": json.Number("5")}
	cases := map[string]string{
		`{"type": "rule", "logic": "AND", "rules": [{"field": "n", "operator": "contains", "value": 5}]}`: "Trigger conditions could not be evaluated: Condition evaluation failed: 'in <string>' requires string as left operand, not int",
		`{"type": "rule", "logic": "AND", "rules": [{"field": "n", "operator": "like", "value": 5}]}`:     "Trigger conditions could not be evaluated: Unknown operator: like",
		`{"type": "rule", "logic": "XOR", "rules": [{"field": "n", "operator": "exists"}]}`:               "Trigger conditions could not be evaluated: Unknown rule logic: XOR",
		`{"type": "combined", "logic": "AND", "conditions": ["x"]}`:                                       "Trigger conditions could not be evaluated: Condition evaluation failed: 'str' object has no attribute 'get'",
		`{"type": "llm", "description": "urgent", "model_id": "4a0b2b5e8d4f4a529a433f3b1c1f2d10"}`:        "Trigger conditions could not be evaluated: LLM condition on model instance 4a0b2b5e-8d4f-4a52-9a43-3f3b1c1f2d10 cannot be evaluated: no condition model calls are wired",
		`{"field_matches": [1]}`: "Trigger conditions could not be evaluated: 'list' object has no attribute 'items'",
	}
	for body, want := range cases {
		_, err := domain.EvaluateConditions(context.Background(), jsonMap(t, body), event, nil)
		if !errors.Is(err, domain.ErrConditionUndecided) || err.Error() != want {
			t.Errorf("%s\n got %v\nwant %s", body, err, want)
		}
	}
}

func TestCombinedConditionsAndFieldMatches(t *testing.T) {
	event := jsonMap(t, `{"body": {"action": "opened", "n": 2}}`)
	and := jsonMap(t, `{"type": "combined", "logic": "and", "conditions": [
		{"type": "rule", "logic": "AND", "rules": [{"field": "body.action", "operator": "eq", "value": "opened"}]},
		{"type": "rule", "logic": "AND", "rules": [{"field": "body.n", "operator": "gt", "value": 5}]}]}`)
	v, err := domain.EvaluateConditions(context.Background(), and, event, nil)
	if err != nil || v.Met || v.Reason != "AND: rule (AND): 1 of 1 rules matched; rule (AND): 0 of 1 rules matched" {
		t.Fatalf("combined = %+v %v", v, err)
	}
	fm := jsonMap(t, `{"field_matches": {"body.action": "closed"}}`)
	v, err = domain.EvaluateConditions(context.Background(), fm, event, nil)
	if err != nil || v.Met || v.Reason != "body.action is 'opened', not 'closed'" {
		t.Fatalf("field_matches = %+v %v", v, err)
	}
	fm = jsonMap(t, `{"field_matches": {"body.action": "opened", "body.n": 2.0}}`)
	if v, err := domain.EvaluateConditions(context.Background(), fm, event, nil); err != nil || !v.Met {
		t.Fatalf("field_matches met = %+v %v", v, err)
	}
	if v, err := domain.EvaluateConditions(context.Background(), map[string]any{}, event, nil); err != nil || !v.Met {
		t.Fatalf("no conditions = %+v %v", v, err)
	}
}

func TestCheckConditionsRefusesWhatPythonRefuses(t *testing.T) {
	var inv *domain.ValidationError
	if err := domain.CheckConditions(jsonMap(t, `{"field_matches": {"a": 1}}`)); !errors.As(err, &inv) {
		t.Fatalf("field_matches is not savable in Python: %v", err)
	}
	nested := jsonMap(t, `{"type": "combined", "logic": "AND", "conditions": [{"description": "x", "model_id": "not-a-uuid"}]}`)
	if err := domain.CheckConditions(nested); !errors.As(err, &inv) || inv.Msg != "Condition model_id 'not-a-uuid' is not a model instance id" {
		t.Fatalf("nested llm = %v", err)
	}
	if err := domain.CheckConditions(map[string]any{}); err != nil {
		t.Fatal(err)
	}
}
