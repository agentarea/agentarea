package workflows

import (
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"slices"
	"strings"
	"unicode/utf8"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

// ChangeModelPayload is the change_model command: the resolved model and who changed it.
type ChangeModelPayload struct {
	Model     api.ResolvedModel `json:"model"`
	ChangedBy map[string]any    `json:"changed_by"`
}

func decodePayload(payload map[string]any, out any) error {
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return json.Unmarshal(raw, out)
}

func (r *agentRun) onCommand(ctx workflow.Context, s api.WorkflowCommandSignal) {
	var err error
	switch s.Command {
	case api.CommandChangeModel:
		err = r.changeModel(ctx, s.Payload)
	case api.CommandUpdateBudget:
		err = r.updateBudget(ctx, s.Payload)
	case api.CommandContinueExecution:
		workflow.GetLogger(ctx).Warn("continue_execution signal ignored; use the validated workflow update")
	case api.CommandQueueMessage:
		err = r.queueMessage(ctx, s.Payload)
	case api.CommandSubmitUserInput:
		r.submitUserInput(ctx, s.Payload)
	case api.CommandRemoveMessage:
		err = r.removeMessage(ctx, s.Payload)
	default:
		workflow.GetLogger(ctx).Warn("unknown workflow command", "command", s.Command)
		return
	}
	if r.taskID == "" {
		return
	}
	if err != nil {
		workflow.GetLogger(ctx).Warn("rejected malformed workflow command", "command", s.Command, "error", err)
		r.emit(ctx, domain.EventCommandRejected, map[string]any{"command": s.Command, "reason": err.Error(), "iteration": r.iteration})
		return
	}
	r.emit(ctx, domain.EventCommandReceived, map[string]any{"command": s.Command, "iteration": r.iteration})
}

func (r *agentRun) changeModel(ctx workflow.Context, payload map[string]any) error {
	var p ChangeModelPayload
	if err := decodePayload(payload, &p); err != nil {
		return err
	}
	if p.Model.ModelID == "" {
		return errors.New("model.model_id: Field required")
	}
	if p.Model.ContextWindow <= 0 {
		return errors.New("model.context_window: Input should be greater than 0")
	}
	old := r.cfg.Model
	previousID := r.cfg.Agent.ModelID
	r.cfg.Model = p.Model
	r.cfg.Agent.ModelID = p.Model.ModelID
	if p.Model.ContextWindow != r.contextWindow {
		r.contextWindow = p.Model.ContextWindow
		r.contextUsage = 0
		r.contextWarningSent = false
	}
	if r.taskID == "" {
		return nil
	}
	oldName := nullable(old.ModelName)
	r.emit(ctx, domain.EventModelChanged, map[string]any{
		"old_model": oldName, "new_model": p.Model.ModelName, "new_model_id": p.Model.ModelID,
		"from": map[string]any{"model_id": nullable(previousID), "model_name": oldName},
		"to":   map[string]any{"model_id": p.Model.ModelID, "model_name": p.Model.ModelName},
		"by":   p.ChangedBy,
	})
	return nil
}

func (r *agentRun) updateBudget(ctx workflow.Context, payload map[string]any) error {
	var p struct {
		Budget *money.Decimal `json:"budget_usd"`
	}
	if err := decodePayload(payload, &p); err != nil {
		return err
	}
	if p.Budget == nil || p.Budget.Sign() <= 0 {
		return errors.New("budget_usd: Input should be greater than 0")
	}
	if p.Budget.Cmp(r.cost) < 0 {
		return errors.New("budget_usd cannot be lower than accumulated cost")
	}
	if r.cfg.Policy.Budget == nil || r.cfg.Policy.Budget.RunBudget == nil {
		return errors.New("effective policy is missing budget.run_budget_usd")
	}
	if p.Budget.Cmp(*r.cfg.Policy.Budget.RunBudget) > 0 {
		return errors.New("budget increases require a re-resolved governance snapshot")
	}
	old := r.budgetLimit
	r.budgetLimit = *p.Budget
	r.budgetWarningSent = false
	if r.taskID != "" {
		r.emit(ctx, domain.EventBudgetUpdated, map[string]any{"old_limit": old.String(), "new_limit": r.budgetLimit.String()})
	}
	return nil
}

func (r *agentRun) queueMessage(ctx workflow.Context, payload map[string]any) error {
	id := r.ids.uuid()
	raw, ok := payload["message"]
	if s, isStr := raw.(string); !ok || (isStr && s == "") {
		raw = payload["content"]
	}
	if raw == nil {
		raw = ""
	}
	text, isStr := raw.(string)
	if !isStr {
		return errors.New("message must be a string")
	}
	if text == "" {
		return nil
	}
	q := QueuedMessage{ID: id, Content: text}
	if sender, has := payload["sender"]; has && sender != nil {
		m, isMap := sender.(map[string]any)
		if !isMap || (m["type"] != "user" && m["type"] != "agent") {
			return errors.New("sender must name a user or an agent")
		}
		q.Sender = map[string]string{"type": m["type"].(string), "id": fmt.Sprint(m["id"])}
	}
	r.messageQueue = append(r.messageQueue, q)
	r.wakeWait = true
	if r.taskID != "" {
		r.emit(ctx, domain.EventMessageQueued, map[string]any{"message_id": id, "content_length": utf8.RuneCountInString(text)})
	}
	return nil
}

func (r *agentRun) removeMessage(ctx workflow.Context, payload map[string]any) error {
	raw, ok := payload["message_id"]
	if !ok {
		return errors.New("'message_id'")
	}
	id := fmt.Sprint(raw)
	r.messageQueue = slices.DeleteFunc(r.messageQueue, func(m QueuedMessage) bool { return m.ID == id })
	if r.taskID != "" {
		r.emit(ctx, domain.EventMessageRemoved, map[string]any{"message_id": raw})
	}
	return nil
}

// submitUserInput resolves a pending request_user_input form when the answers fit it.
func (r *agentRun) submitUserInput(ctx workflow.Context, payload map[string]any) {
	id := ""
	if v := payload["input_request_id"]; v != nil {
		id = fmt.Sprint(v)
	}
	pending := r.inputRequests[id]
	if pending == nil || pending.Resolved {
		return
	}
	answers, okA := orEmptyMap(payload["answers"])
	refs, okR := orEmptyMap(payload["secret_refs"])
	if !okA || !okR || !validSubmission(pending, answers, refs) {
		return
	}
	pending.Resolved = true
	pending.Submission = map[string]any{"answers": answers, "secret_refs": refs}
	if r.taskID != "" {
		r.emit(ctx, domain.EventInputSubmitted, map[string]any{
			"input_request_id": id, "answer_keys": sortedKeys(answers), "secret_keys": sortedKeys(refs),
		})
	}
}

func orEmptyMap(v any) (map[string]any, bool) {
	if v == nil {
		return map[string]any{}, true
	}
	m, ok := v.(map[string]any)
	return m, ok
}

func validSubmission(p *InputRequest, answers, refs map[string]any) bool {
	fields := map[string]map[string]any{}
	var order []string
	for _, q := range p.Questions {
		qid, _ := q["id"].(string)
		fields[qid] = q
		order = append(order, qid)
	}
	for k := range answers {
		if _, ok := fields[k]; !ok {
			return false
		}
	}
	for k := range refs {
		if _, ok := fields[k]; !ok {
			return false
		}
	}
	for _, id := range order {
		f := fields[id]
		required := true
		if b, ok := f["required"].(bool); ok {
			required = b
		}
		if f["type"] == "secret" {
			if _, has := answers[id]; has {
				return false
			}
			ref, has := refs[id]
			if has && ref != nil {
				m, isMap := ref.(map[string]any)
				s, isStr := m["secret_ref"].(string)
				if !isMap || !isStr || !strings.HasPrefix(s, "secret:") {
					return false
				}
			}
			if required && !truthyAny(ref) {
				return false
			}
			continue
		}
		if _, has := refs[id]; has {
			return false
		}
		value := answers[id]
		if value == nil || value == "" || reflect.DeepEqual(value, []any{}) {
			if required {
				return false
			}
			continue
		}
		typ, _ := f["type"].(string)
		if typ == "" {
			typ = "text"
		}
		switch typ {
		case "boolean":
			if _, ok := value.(bool); !ok {
				return false
			}
		case "number":
			if _, ok := value.(float64); !ok {
				return false
			}
		case "text", "textarea", "select":
			if _, ok := value.(string); !ok {
				return false
			}
		case "multiselect":
			list, ok := value.([]any)
			if !ok {
				return false
			}
			for _, item := range list {
				if _, isStr := item.(string); !isStr {
					return false
				}
			}
		}
		options, _ := f["options"].([]any)
		if len(options) > 0 && !p.AllowCustomResponse {
			values, isList := value.([]any)
			if !isList {
				values = []any{value}
			}
			for _, v := range values {
				if !slices.Contains(options, v) {
					return false
				}
			}
		}
	}
	return true
}

// onContinueExecution persists and applies a re-resolved policy revision.
func (r *agentRun) onContinueExecution(ctx workflow.Context, grant api.ContinueExecution) (api.ContinueExecutionResult, error) {
	if r.continuationInFlight {
		return api.ContinueExecutionResult{Reason: "not_waiting_for_continuation"}, nil
	}
	if reason := r.prepareContinuation(grant); reason != "" {
		return api.ContinueExecutionResult{Reason: reason}, nil
	}
	r.continuationInFlight = true
	req := UpdateGovernanceSnapshotRequest{Principal: r.principal, TaskID: r.taskID, Snapshot: *grant.Governance}
	err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityUpdateGovernanceSnapshot, "", 0), api.ActivityUpdateGovernanceSnapshot, req).Get(ctx, nil)
	r.continuationInFlight = false
	if err != nil {
		return api.ContinueExecutionResult{}, nonRetryable(err.Error(), ErrGovernanceSnapshotPersist)
	}
	return r.commitContinuation(grant), nil
}

func (r *agentRun) prepareContinuation(g api.ContinueExecution) string {
	if !r.waitingContinuation {
		return "not_waiting_for_continuation"
	}
	if g.AdditionalIterations == 0 && g.AdditionalBudget == nil && g.AdditionalTokens == 0 && g.AdditionalToolCalls == 0 {
		return "no_resources_granted"
	}
	switch {
	case r.continuationReason == ReasonIteration && g.AdditionalIterations == 0:
		return "additional_iterations_required"
	case r.continuationReason == ReasonBudget && g.AdditionalBudget == nil:
		return "additional_budget_required"
	case r.continuationReason == ReasonTokens && g.AdditionalTokens == 0:
		return "additional_tokens_required"
	case r.continuationReason == ReasonToolCalls && g.AdditionalToolCalls == 0:
		return "additional_tool_calls_required"
	}
	if r.goal == nil {
		return "goal_not_initialized"
	}
	if g.Policy == nil || g.Governance == nil {
		return "governance_snapshot_required"
	}
	next := *g.Policy
	if !reflect.DeepEqual(canonical(g.Governance.EffectivePolicy), canonical(next)) || g.Governance.Revision < 2 {
		return "invalid_governance_snapshot"
	}
	curExec, nextExec := policyExec(r.cfg.Policy), policyExec(next)
	if v, ok := intLimit(nextExec.MaxModelTurns); !ok || v != r.goal.MaxIterations+g.AdditionalIterations {
		return "policy_revision_mismatch"
	}
	expected := r.budgetLimit
	if g.AdditionalBudget != nil {
		expected = expected.Add(*g.AdditionalBudget)
	}
	if next.Budget == nil || next.Budget.RunBudget == nil || next.Budget.RunBudget.Cmp(expected) != 0 {
		return "policy_revision_mismatch"
	}
	curTokens, _ := policyMaxTokens(r.cfg.Policy)
	if nextTokens, _ := policyMaxTokens(next); nextTokens != curTokens+g.AdditionalTokens {
		return "policy_revision_mismatch"
	}
	curCalls, _ := intLimit(curExec.MaxToolCallsTotal)
	if nextCalls, _ := intLimit(nextExec.MaxToolCallsTotal); nextCalls != curCalls+g.AdditionalToolCalls {
		return "policy_revision_mismatch"
	}
	if !reflect.DeepEqual(withoutLimits(r.cfg.Policy), withoutLimits(next)) {
		return "unexpected_policy_dimension_change"
	}
	return ""
}

func canonical(v any) any {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	var out any
	if json.Unmarshal(raw, &out) != nil {
		return nil
	}
	return out
}

// withoutLimits is a policy minus the dimensions a continuation may change.
func withoutLimits(p api.Policy) any {
	m, _ := canonical(p).(map[string]any)
	delete(m, "source_policy_ids")
	delete(m, "resolver_version")
	for section, keys := range map[string][]string{
		"budget":    {"run_budget_usd", "monthly_spend_cap_usd", "agent_monthly_spend_cap_usd"},
		"execution": {"max_model_turns", "max_tool_calls_total"},
		"tokens":    {"max_tokens"},
	} {
		if s, ok := m[section].(map[string]any); ok {
			for _, k := range keys {
				delete(s, k)
			}
		}
	}
	return m
}

func (r *agentRun) commitContinuation(g api.ContinueExecution) api.ContinueExecutionResult {
	next := *g.Policy
	turns, _ := intLimit(policyExec(next).MaxModelTurns)
	r.goal.MaxIterations = turns
	r.budgetLimit = *next.Budget.RunBudget
	r.budgetWarningSent = false
	r.cfg.Policy = next
	r.cfg.Governance = *g.Governance
	r.continuationCount++
	r.waitingContinuation = false
	r.status = StatusExecuting
	r.failureReason = ""
	r.errorMessage = ""
	return api.ContinueExecutionResult{Accepted: true, ContinuationCount: r.continuationCount, MaxIterations: r.goal.MaxIterations, Budget: r.budgetLimit.String()}
}
