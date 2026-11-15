package service_test

import (
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

func ruleOn(field, op string, value any) map[string]any {
	return map[string]any{"type": "rule", "logic": "and", "rules": []any{
		map[string]any{"field": field, "operator": op, "value": value},
	}}
}

func TestATriggerFiresOnlyWhenItsConditionsAreMet(t *testing.T) {
	g := newFireRig(t)
	n := cronNew(g.agent, true)
	n.Conditions = ruleOn("level", "gte", 3)
	tr, err := g.svc.Create(g.ctx, n)
	if err != nil {
		t.Fatal(err)
	}
	if got, err := g.svc.Trigger(g.ctx, g.ws, tr.ID); err != nil || got.Conditions["type"] != "rule" {
		t.Fatalf("stored conditions = %v %v", got.Conditions, err)
	}
	f, err := g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, Data: map[string]any{"level": 2.0}})
	if err != nil {
		t.Fatal(err)
	}
	if f.Outcome != service.OutcomeSkipped || f.Reason != "rule (AND): 0 of 1 rules matched" || !f.Verdict ||
		f.Execution == nil || f.Execution.Status != service.ExecSkipped || len(g.tasks.Submitted()) != 0 {
		t.Fatalf("unmet = %+v", f)
	}
	f, err = g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, Data: map[string]any{"level": 3.0}})
	if err != nil || f.Outcome != service.OutcomeReacted || !f.Verdict || len(g.tasks.Submitted()) != 1 {
		t.Fatalf("met = %+v %v", f, err)
	}
}

func TestConditionsThatCannotBeEvaluatedFailTheFiring(t *testing.T) {
	g := newFireRig(t)
	n := cronNew(g.agent, true)
	n.Conditions = ruleOn("level", "gt", 3)
	tr, err := g.svc.Create(g.ctx, n)
	if err != nil {
		t.Fatal(err)
	}
	f, err := g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, Data: map[string]any{"level": "high"}})
	want := "Trigger conditions could not be evaluated: Condition evaluation failed: '>' not supported between instances of 'str' and 'int'"
	if err != nil || f.Outcome != service.OutcomeError || f.Reason != want || len(g.tasks.Submitted()) != 0 {
		t.Fatalf("undecided = %+v %v", f, err)
	}
	f, err = g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, Data: map[string]any{"level": "high"}, RaiseRetryable: true})
	if err != nil || f.Outcome != service.OutcomeError {
		t.Fatalf("an undecided condition was retried: %+v %v", f, err)
	}
	met, err := g.svc.Scheduling().EvaluateConditions(g.ctx, tr.ID, map[string]any{"level": "high"})
	if met || !errors.Is(err, domain.ErrConditionUndecided) {
		t.Fatalf("scheduling = %v %v", met, err)
	}
}

func TestLLMConditionsAreRefusedAtSave(t *testing.T) {
	g := newFireRig(t)
	n := cronNew(g.agent, true)
	n.Conditions = map[string]any{"type": "llm", "description": "urgent", "model_id": "4a0b2b5e-8d4f-4a52-9a43-3f3b1c1f2d10"}
	if _, err := g.svc.Create(g.ctx, n); !errors.Is(err, domain.ErrConditionsNotPorted) {
		t.Fatalf("llm condition = %v", err)
	}
	n.Conditions = map[string]any{"type": "llm", "description": "urgent"}
	var inv *domain.ValidationError
	if _, err := g.svc.Create(g.ctx, n); !errors.As(err, &inv) ||
		inv.Msg != "An LLM condition needs a model_id: the chat or decision model instance that evaluates it" {
		t.Fatalf("no model = %v", err)
	}
}
