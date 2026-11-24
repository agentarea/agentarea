package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// Model kinds an LLM condition may name (CONDITION_MODEL_KINDS).
const (
	kindChat     = "chat"
	kindDecision = "decision"
)

// checkConditionModels is validate_condition_models: every LLM condition names a chat or decision
// model instance the workspace has.
func (s *Service) checkConditionModels(ctx context.Context, ws scope.Workspace, conditions map[string]any) error {
	conds := domain.LLMConditions(conditions)
	if len(conds) == 0 {
		return nil
	}
	if s.d.ModelKinds == nil {
		return errors.New("LLM conditions need the model kinds of models, which are not wired")
	}
	for _, c := range conds {
		id := fmt.Sprint(c["model_id"])
		kind, found, err := s.d.ModelKinds.ModelKind(ctx, ws, id)
		if err != nil {
			return err
		}
		if !found {
			return domain.Invalid(fmt.Sprintf("Model instance '%s' does not exist in this workspace", id))
		}
		if kind != kindChat && kind != kindDecision {
			return domain.Invalid(fmt.Sprintf("Model instance '%s' is a %s model; a condition needs a chat or decision model", id, kind))
		}
	}
	return nil
}

// judge is the LLM judge a trigger's conditions are decided with, its calls made for the trigger.
func (s *Service) judge(ws scope.Workspace, t domain.Trigger) domain.LLMJudge {
	if s.d.ModelKinds == nil || s.d.Models == nil {
		return nil
	}
	who := runsapi.ModelCallFor{UserID: t.CreatedBy, AgentID: t.AgentID, Purpose: "trigger_condition", TriggerID: t.ID}
	trigger := domain.TriggerContext(t)
	return func(ctx context.Context, q domain.LLMQuestion) (domain.ConditionVerdict, error) {
		kind, found, err := s.d.ModelKinds.ModelKind(ctx, ws, q.ModelID)
		if err != nil {
			return domain.ConditionVerdict{}, err
		}
		if !found {
			return domain.ConditionVerdict{}, domain.ConditionFailed(fmt.Sprintf("Model instance %s not found", q.ModelID))
		}
		switch kind {
		case kindDecision:
			state, questions := domain.ConditionDecision(q, trigger)
			answers, err := s.d.Models.Decide(ctx, ws, who, runsapi.DecideOnce{ModelID: q.ModelID, State: state, Questions: questions})
			if err != nil {
				return domain.ConditionVerdict{}, err
			}
			return domain.DecisionVerdict(q.ModelID, answers)
		case kindChat:
			answer, err := s.d.Models.Chat(ctx, ws, who, runsapi.ChatOnce{
				ModelID: q.ModelID, Prompt: domain.ConditionPrompt(q, trigger), MaxTokens: domain.ConditionMaxTokens, Temperature: 0.1,
			})
			if err != nil {
				return domain.ConditionVerdict{}, chatFailure(err)
			}
			return domain.ParseVerdict(answer)
		}
		return domain.ConditionVerdict{}, domain.ConditionFailed(fmt.Sprintf("Model instance %s is a %s model; a condition needs a chat or decision model", q.ModelID, kind))
	}
}

// chatFailure is _call_llm's LLMConditionEvaluationError.
func chatFailure(err error) error {
	var refused *runsapi.ModelCallRefused
	if errors.As(err, &refused) {
		return domain.ConditionFailed("model call refused: " + refused.Msg)
	}
	var failed *runsapi.ModelCallFailed
	if errors.As(err, &failed) {
		return domain.ConditionFailed("LLM call failed: " + failed.Detail)
	}
	return err
}

// evaluate is evaluate_trigger_verdict for t, its LLM conditions decided by the trigger's judge.
func (s *Service) evaluate(ctx context.Context, ws scope.Workspace, t domain.Trigger, event map[string]any) (domain.ConditionVerdict, error) {
	return domain.EvaluateConditions(ctx, t.Conditions, event, s.judge(ws, t))
}

// Evaluate is evaluate_trigger_verdict for a router that holds the trigger.
func (s *Service) Evaluate(ctx context.Context, t domain.Trigger, event map[string]any) (domain.ConditionVerdict, error) {
	ws, err := scope.NewWorkspace(t.WorkspaceID, "")
	if err != nil {
		return domain.ConditionVerdict{}, err
	}
	return s.evaluate(ctx, ws, t, event)
}

// extractParameters is the llm_parameter_extraction of _build_task_parameters: parameters the
// agent's own model reads out of the event join the task's, never over one already set. Python
// names no model for the call, so its extraction never ran; here the agent's model answers.
// A failure is logged and the task starts with the parameters it has.
func (s *Service) extractParameters(ctx context.Context, ws scope.Workspace, t domain.Trigger, asked, event, params map[string]any) {
	instruction, _ := asked["llm_parameter_extraction"].(string)
	if instruction == "" {
		return
	}
	extracted, err := s.extract(ctx, ws, t, instruction, event)
	if err != nil {
		s.log.WarnContext(ctx, "LLM parameter extraction failed", "trigger_id", t.ID, "error", err.Error())
		return
	}
	for k, v := range extracted {
		if domain.ExtractedKeyAllowed(params, k) {
			params[k] = v
		}
	}
	s.log.InfoContext(ctx, "Enhanced task parameters with LLM extraction", "trigger_id", t.ID)
}

func (s *Service) extract(ctx context.Context, ws scope.Workspace, t domain.Trigger, instruction string, event map[string]any) (map[string]any, error) {
	if s.d.Models == nil || s.d.AgentModels == nil {
		return nil, errors.New("LLM parameter extraction is not wired")
	}
	modelID, err := s.d.AgentModels.AgentModel(ctx, ws, t.AgentID)
	if err != nil {
		return nil, err
	}
	if modelID == "" {
		return nil, fmt.Errorf("agent %s has no model instance to extract parameters with", t.AgentID)
	}
	who := runsapi.ModelCallFor{UserID: t.CreatedBy, AgentID: t.AgentID, Purpose: "trigger_parameters", TriggerID: t.ID}
	answer, err := s.d.Models.Chat(ctx, ws, who, runsapi.ChatOnce{
		ModelID: modelID, Prompt: domain.ExtractionPrompt(instruction, event, domain.TriggerContext(t)), MaxTokens: domain.ConditionMaxTokens, Temperature: 0.1,
	})
	if err != nil {
		return nil, chatFailure(err)
	}
	params, ok := domain.ExtractedParameters(answer, instruction, event)
	if !ok {
		s.log.WarnContext(ctx, "LLM parameter extraction did not answer a JSON object", "trigger_id", t.ID)
	}
	return params, nil
}
