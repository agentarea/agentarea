package service_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
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

type modelKinds map[string]string

func (m modelKinds) ModelKind(_ context.Context, _ scope.Workspace, id string) (string, bool, error) {
	k, ok := m[id]
	return k, ok, nil
}

type oneShot struct {
	answer  string
	choice  string
	prompts []string
	who     []runsapi.ModelCallFor
}

func (o *oneShot) Chat(_ context.Context, _ scope.Workspace, who runsapi.ModelCallFor, in runsapi.ChatOnce) (string, error) {
	o.prompts, o.who = append(o.prompts, in.Prompt), append(o.who, who)
	return o.answer, nil
}

func (o *oneShot) Decide(_ context.Context, _ scope.Workspace, who runsapi.ModelCallFor, _ runsapi.DecideOnce) (map[string]map[string]any, error) {
	o.who = append(o.who, who)
	return map[string]map[string]any{domain.ConditionQuestion: {"type": "choice", "choice": o.choice}}, nil
}

type agentModel string

func (a agentModel) AgentModel(context.Context, scope.Workspace, string) (string, error) {
	return string(a), nil
}

const (
	chatModel     = "4a0b2b5e-8d4f-4a52-9a43-3f3b1c1f2d10"
	decisionModel = "5b1c3c6f-9e50-4b63-8b54-4f4c2d203e21"
	imageModel    = "6c2d4d70-af61-4c74-9c65-505d3e314f32"
)

func newJudgedRig(t *testing.T, models *oneShot) *fireRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	g := &fireRig{ctx: ctx, ws: ws, tasks: &storetest.Tasks{}, firing: &storetest.FiringTasks{}, agent: uuid.NewString()}
	g.known = map[string]bool{g.agent: true}
	g.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true}, Agents: storetest.Agents{Known: g.known},
		Schedules: &storetest.Schedules{}, TriggerQueue: "trigger-schedules", Tasks: g.tasks, FiringTasks: g.firing,
		Broker: &storetest.Broker{}, Settings: service.DefaultSettings(),
		ModelKinds: modelKinds{chatModel: "chat", decisionModel: "decision", imageModel: "image"}, Models: models, AgentModels: agentModel(chatModel),
	})
	return g
}

func TestAnLLMConditionIsDecidedByTheModelItNames(t *testing.T) {
	models := &oneShot{answer: `{"verdict": "not_met", "score": 0.2, "reason": "routine"}`, choice: "true"}
	g := newJudgedRig(t, models)
	n := cronNew(g.agent, true)
	n.Conditions = map[string]any{"type": "llm", "description": "urgent", "model_id": chatModel}
	tr, err := g.svc.Create(g.ctx, n)
	if err != nil {
		t.Fatal(err)
	}
	f, err := g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, Data: map[string]any{"level": "low"}})
	if err != nil || f.Outcome != service.OutcomeSkipped || f.Reason != "routine" || *f.Score != 0.2 {
		t.Fatalf("chat verdict = %+v %v", f, err)
	}
	if len(models.prompts) != 1 || !strings.Contains(models.prompts[0], "CONDITION TO EVALUATE: urgent") ||
		models.who[0] != (runsapi.ModelCallFor{UserID: "u1", AgentID: g.agent, Purpose: "trigger_condition", TriggerID: tr.ID}) {
		t.Fatalf("asked %q as %+v", models.prompts, models.who)
	}

	n.Conditions = map[string]any{"type": "combined", "logic": "and", "conditions": []any{
		map[string]any{"description": "urgent", "model_id": decisionModel},
	}}
	n.TaskParameters = map[string]any{"text": "summarise", "llm_parameter_extraction": "pick the user"}
	models.answer = `{"user_id": "u-7", "mcps": ["x"], "trigger_id": "forged"}`
	tr, err = g.svc.Create(g.ctx, n)
	if err != nil {
		t.Fatal(err)
	}
	f, err = g.svc.Fire(g.ctx, g.ws, service.FireRequest{TriggerID: tr.ID, Data: map[string]any{"level": "high"}})
	reqs := g.tasks.Submitted()
	if err != nil || f.Outcome != service.OutcomeReacted || len(reqs) != 1 {
		t.Fatalf("decision verdict = %+v %v", f, err)
	}
	p := reqs[0].Parameters
	if p["user_id"] != "u-7" || p["mcps"] != nil || p["trigger_id"] != tr.ID {
		t.Fatalf("extracted parameters %v", p)
	}
}

func TestAnLLMConditionMustNameAChatOrDecisionModel(t *testing.T) {
	g := newJudgedRig(t, &oneShot{})
	n := cronNew(g.agent, true)
	var inv *domain.ValidationError
	for model, want := range map[string]string{
		imageModel:                             "Model instance '" + imageModel + "' is a image model; a condition needs a chat or decision model",
		"7d3e5e81-b072-4d85-ad76-616e4f425043": "Model instance '7d3e5e81-b072-4d85-ad76-616e4f425043' does not exist in this workspace",
	} {
		n.Conditions = map[string]any{"type": "llm", "description": "urgent", "model_id": model}
		if _, err := g.svc.Create(g.ctx, n); !errors.As(err, &inv) || inv.Msg != want {
			t.Fatalf("%s = %v", model, err)
		}
	}
	n.Conditions = map[string]any{"type": "llm", "description": "urgent"}
	if _, err := g.svc.Create(g.ctx, n); !errors.As(err, &inv) ||
		inv.Msg != "An LLM condition needs a model_id: the chat or decision model instance that evaluates it" {
		t.Fatalf("no model = %v", err)
	}
}
