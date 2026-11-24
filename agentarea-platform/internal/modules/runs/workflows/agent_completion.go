package workflows

import (
	"encoding/json"
	"strings"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

const maxDeclaredArtifacts = 1000

// handleCompletion gates completion on validation of the files it delivers.
// answerChecked: the result is a reply the answer check already saw.
func (r *agentRun) handleCompletion(ctx workflow.Context, c ToolCall, answerChecked bool) error {
	if len(r.inputRequests) > 0 {
		r.rejectCompletion(c, "required input is still pending; await its matching submission")
		return nil
	}
	var raw any
	if err := json.Unmarshal([]byte(c.Arguments), &raw); err != nil {
		r.rejectCompletion(c, "arguments must be valid JSON: "+err.Error())
		return nil
	}
	args, ok := raw.(map[string]any)
	if !ok {
		r.rejectCompletion(c, "arguments must be a JSON object")
		return nil
	}
	result, isStr := args["result"].(string)
	if !isStr || strings.TrimSpace(result) == "" {
		r.rejectCompletion(c, "result must be a non-empty string")
		return nil
	}
	rawPaths, has := args["artifacts"]
	if !has {
		rawPaths = []any{}
	}
	list, isList := rawPaths.([]any)
	if !isList {
		r.rejectCompletion(c, "artifacts must be an array of workspace-relative paths")
		return nil
	}
	paths := make([]string, 0, len(list))
	seen := map[string]bool{}
	for _, p := range list {
		s, ok := p.(string)
		if !ok || strings.TrimSpace(s) == "" || len(list) > maxDeclaredArtifacts {
			r.rejectCompletion(c, "artifacts must contain at most 1000 non-empty workspace-relative paths")
			return nil
		}
		paths = append(paths, s)
	}
	for _, p := range paths {
		if seen[p] {
			r.rejectCompletion(c, "artifacts must not contain duplicates")
			return nil
		}
		seen[p] = true
	}
	text := strings.TrimSpace(result)
	outcome := "completed"
	if v, has := args["outcome"]; has {
		s, _ := v.(string)
		outcome = s
		if s != "completed" && s != "blocked" {
			r.rejectCompletion(c, "outcome must be completed or blocked")
			return nil
		}
	}
	validation, err := r.validateArtifacts(ctx, paths)
	if err != nil {
		return err
	}
	if validation.State != "passed" {
		r.success = false
		r.finalResponse = ""
		r.awaitingInput = false
		if validation.State == "unavailable" {
			capability := "artifact_validator"
			if validation.CapabilityUnavailable != nil {
				capability = validation.CapabilityUnavailable.Capability
			}
			r.status = StatusBlocked
			r.failureReason = "capability_unavailable"
			r.blockedReason = "Artifact validation capability is unavailable: " + capability
			r.errorMessage = r.blockedReason
			r.validationTerminal = true
			return nil
		}
		if r.validationRepairs >= 2 {
			r.status = StatusFailed
			r.failureReason = "validation_failed"
			r.errorMessage = "Artifact validation failed after two repair attempts"
			r.validationTerminal = true
			return nil
		}
		r.validationRepairs++
		r.validationFeedback(c, validation)
		return nil
	}
	if outcome == "completed" && !answerChecked {
		checked, err := r.checkedAnswer(ctx, text)
		if err != nil {
			return err
		}
		if checked != text {
			r.replaceAnswer(text, checked)
		}
		text = checked
	}
	if r.callInHistory(c.ID) {
		r.messages = append(r.messages, Message{Role: "tool", Name: domain.ToolCompletion, ToolCallID: c.ID, Content: domain.PyDumpsCompact(domain.Ordered{
			{Key: "status", Value: outcome}, {Key: "result", Value: text}, {Key: "artifacts", Value: stringsAny(paths)},
		})})
	}
	if outcome == "blocked" {
		r.success = false
		r.status = StatusBlocked
		r.failureReason = "unmet_prerequisite"
		r.blockedReason = text
		r.errorMessage = text
		r.finalResponse = text
		r.awaitingInput = false
		return nil
	}
	r.success = true
	r.finalResponse = text
	r.status = StatusCompleted
	r.failureReason = ""
	r.errorMessage = ""
	r.blockedReason = ""
	r.validationTerminal = false
	r.awaitingInput = true
	evidence := make([]string, 0, len(validation.Evidence))
	for _, e := range validation.Evidence {
		evidence = append(evidence, e.Path)
	}
	total, own, tokens := r.cost, r.ownCost(), r.tokensUsed
	r.completedStatus = &TaskStatus{
		Status: "completed", Response: text, Artifacts: evidence, ValidationState: r.validationState,
		TotalCost: &total, OwnCost: &own, TokensUsed: &tokens,
	}
	window, ok := r.followUpWindow()
	if !ok {
		r.awaitingInput = false
		return nil
	}
	r.emit(ctx, domain.EventTaskAwaitingFollowUp, map[string]any{
		"state": "awaiting_follow_up", "timeout_seconds": int(window.Seconds()), "final_response": text,
	})
	return r.publish(ctx)
}

func stringsAny(s []string) []any {
	out := make([]any, 0, len(s))
	for _, v := range s {
		out = append(out, v)
	}
	return out
}

func (r *agentRun) pairCompletionCall(c ToolCall) {
	if !r.callInHistory(c.ID) {
		r.messages = append(r.messages, Message{Role: "assistant", ToolCalls: []ToolCall{c}})
	}
}

// rejectCompletion answers a malformed completion with the contract error.
func (r *agentRun) rejectCompletion(c ToolCall, reason string) {
	r.success = false
	r.finalResponse = ""
	r.awaitingInput = false
	r.pairCompletionCall(c)
	r.messages = append(r.messages, Message{Role: "tool", Name: domain.ToolCompletion, ToolCallID: c.ID, Content: domain.PyDumpsCompact(domain.Ordered{
		{Key: "status", Value: "invalid_completion_arguments"}, {Key: "error", Value: reason},
		{Key: "instruction", Value: "Call completion again with a non-empty result. Files in " +
			"outputs/ are delivered on their own; artifacts, when given, is an " +
			"array of other workspace-relative paths."},
	})})
}

func issueValues(issues []ArtifactIssue) []any {
	out := make([]any, 0, len(issues))
	for _, i := range issues {
		out = append(out, domain.Ordered{{Key: "path", Value: i.Path}, {Key: "validator", Value: i.Validator}, {Key: "code", Value: i.Code}, {Key: "message", Value: i.Message}})
	}
	return out
}

func (r *agentRun) validateArtifacts(ctx workflow.Context, paths []string) (ArtifactValidationResult, error) {
	r.validationState = "running"
	r.emit(ctx, domain.EventArtifactValidationStarted, map[string]any{
		"validation_state": "running", "repair_attempt": r.validationRepairs, "declared_artifact_count": len(paths),
	})
	if err := r.publish(ctx); err != nil {
		return ArtifactValidationResult{}, err
	}
	req := ArtifactValidationRequest{Principal: r.principal, TaskID: r.filesTask(), ExecutionID: r.executionID, DeclaredPaths: paths}
	var res ArtifactValidationResult
	if err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityValidateArtifacts, "", 0), api.ActivityValidateArtifacts, req).Get(ctx, &res); err != nil {
		if isCancellation(err) || ctx.Err() != nil {
			return res, err
		}
		workflow.GetLogger(ctx).Error("artifact validation activity failed", "error", err)
		res = ArtifactValidationResult{
			State: "unavailable", CapabilityUnavailable: &CapabilityUnavailable{Capability: "artifact_validator"},
			Issues: []ArtifactIssue{{Validator: "artifact_validator", Code: "capability_unavailable", Message: "Artifact validation activity could not run"}},
		}
	}
	r.validationState = res.State
	evidence := make([]any, 0, len(res.Evidence))
	for _, e := range res.Evidence {
		evidence = append(evidence, map[string]any{"path": e.Path, "validator": e.Validator, "sha256": e.SHA256, "size": e.Size})
	}
	var unavailable any
	if cu := res.CapabilityUnavailable; cu != nil {
		unavailable = map[string]any{"capability": cu.Capability, "runtime_version": nullable(cu.RuntimeVersion)}
	}
	issues := make([]any, 0, len(res.Issues))
	for _, i := range res.Issues {
		issues = append(issues, map[string]any{"path": i.Path, "validator": i.Validator, "code": i.Code, "message": i.Message})
	}
	r.emit(ctx, domain.EventArtifactValidationDone, map[string]any{
		"validation_state": res.State, "generation": res.Generation, "repair_attempt": r.validationRepairs,
		"evidence": evidence, "issues": issues, "capability_unavailable": unavailable,
	})
	return res, r.publish(ctx)
}

func (r *agentRun) validationFeedback(c ToolCall, res ArtifactValidationResult) {
	r.pairCompletionCall(c)
	r.messages = append(r.messages, Message{Role: "tool", Name: domain.ToolCompletion, ToolCallID: c.ID, Content: domain.PyDumpsCompact(domain.Ordered{
		{Key: "status", Value: "validation_failed"}, {Key: "validation_state", Value: res.State},
		{Key: "repair_attempt", Value: r.validationRepairs}, {Key: "repair_attempts_remaining", Value: 2 - r.validationRepairs},
		{Key: "generation", Value: res.Generation}, {Key: "issues", Value: issueValues(res.Issues)},
		{Key: "instruction", Value: "Repair or create the missing output in outputs/, or drop the path " +
			"from artifacts, then call completion again. Do not claim success until " +
			"validation passes."},
	})})
}
