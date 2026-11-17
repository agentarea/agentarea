package workflows

import (
	"strings"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

const answerCheckMaxTokens = 4000

func (r *agentRun) answerCheck() *api.AnswerCheck {
	return domain.AnswerCheckConfig(r.cfg.Policy, r.cfg.Agent.AnswerCheck)
}

// checkedAnswer is the final answer after the answer check (_checked_answer):
// as is, rewritten once by a silent call to the agent's own model, or with
// CJK characters stripped when those were the leak and the rewrite failed.
func (r *agentRun) checkedAnswer(ctx workflow.Context, text string) (string, error) {
	config := r.answerCheck()
	if config == nil {
		return text, nil
	}
	leaks := domain.FindLeaks(text, domain.ToolNamesOf(r.tools), config.Language)
	if len(leaks) == 0 {
		return text, nil
	}
	stripCJK := false
	for _, l := range leaks {
		if l.Kind == "cjk" {
			stripCJK = true
		}
	}
	checked := text
	if stripCJK {
		checked = domain.StripUnreadable(text)
	}
	system, user := domain.RewriteMessages(text, leaks, config.Language, config.RewriteInstruction)
	req := LLMCallRequest{
		Principal: r.principal, ExecutionID: r.executionID, Iteration: r.iteration, Purpose: "answer_check",
		Model: r.cfg.Model, Messages: []Message{{Role: "system", Content: system}, {Role: "user", Content: user}},
		Temperature: ptr(0.0), MaxTokens: ptr(answerCheckMaxTokens), Policy: r.cfg.Policy, Counters: r.counters(),
	}
	var res LLMCallResult
	var rewrite *domain.Rewrite
	err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityCallLLM, "", 0), api.ActivityCallLLM, req).Get(ctx, &res)
	switch {
	case err != nil && (isCancellation(err) || ctx.Err() != nil):
		return "", err
	case err != nil:
		workflow.GetLogger(ctx).Warn("answer check rewrite failed, keeping the answer", "error", err)
	default:
		if aerr := r.accountInference(res.Cost, res.Usage.TotalTokens, "answer check"); aerr != nil {
			return "", aerr
		}
		rewrite = domain.AcceptRewrite(text, res.Content, stripCJK)
		if rewrite == nil {
			workflow.GetLogger(ctx).Warn("answer check rewrite was unusable, keeping the answer")
		} else {
			checked = rewrite.Answer
		}
		r.emit(ctx, domain.EventLLMCompleted, map[string]any{
			"iteration": r.iteration, "purpose": "answer_check", "model_id": nullable(r.cfg.Agent.ModelID),
			"model_name": nullable(r.cfg.Model.ModelName), "managed_by": nullable(r.cfg.Model.ManagedBy),
			"cost": res.Cost.String(), "provider_cost_usd": res.ProviderCostUSD.String(), "total_cost": r.cost.String(),
			"usage":   map[string]any{"cost": res.Cost.String(), "usage": usageValue(res.Usage)},
			"content": checked, "thinking": "", "tool_calls": []any{}, "role": "assistant",
		})
	}
	data := map[string]any{"iteration": r.iteration, "leaks": leakValues(leaks), "rewritten": rewrite != nil, "changes": nil}
	if rewrite != nil {
		data["changes"] = rewrite.Changes
	}
	r.emit(ctx, domain.EventAnswerChecked, data)
	if err := r.publish(ctx); err != nil {
		return "", err
	}
	return checked, nil
}

func leakValues(leaks []domain.Leak) []any {
	out := make([]any, len(leaks))
	for i, l := range leaks {
		out[i] = map[string]any{"kind": l.Kind, "sample": l.Sample}
	}
	return out
}

// replaceAnswer gives the follow-up turns the answer the person saw.
func (r *agentRun) replaceAnswer(original, checked string) {
	for i := len(r.messages) - 1; i >= 0; i-- {
		if m := r.messages[i]; m.Role == "assistant" && strings.TrimSpace(m.Content) == original {
			r.messages[i].Content = checked
			return
		}
	}
}
