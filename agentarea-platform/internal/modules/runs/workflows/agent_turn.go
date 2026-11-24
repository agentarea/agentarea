package workflows

import (
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

const (
	compactionThreshold  = 0.75
	contextWarnThreshold = 0.60
	contextLimitShare    = 0.85
	minCompactionGain    = 0.10
)

// executeIteration is one turn: the model call and its response.
func (r *agentRun) executeIteration(ctx workflow.Context) error {
	iteration := r.iteration
	r.completedStatus = nil
	r.emit(ctx, domain.EventTurnStarted, map[string]any{"iteration": iteration, "budget_remaining": r.remaining().String()})
	if err := r.publish(ctx); err != nil {
		return err
	}
	var err error
	if r.runner.on {
		err = r.executeRunnerTurn(ctx)
	} else {
		err = r.traditionalIteration(ctx)
	}
	if err == nil {
		err = r.checkBudgetStatus(ctx)
	}
	if err == nil {
		r.emit(ctx, domain.EventTurnCompleted, map[string]any{"iteration": iteration, "total_cost": r.cost.String()})
		if r.awaitingInput {
			status := "waiting"
			if r.isDelegationChild() {
				status = "completed"
			}
			r.emit(ctx, domain.EventTaskCompleted, map[string]any{
				"success": true, "iterations_completed": r.iteration, "total_cost": r.cost.String(),
				"tokens_used": r.tokensUsed, "result": nullable(r.finalResponse), "validation_state": r.validationState,
				"execution_status": status,
			})
			r.completionPublished = true
		}
		if r.completedStatus != nil {
			st := *r.completedStatus
			r.completedStatus = nil
			if err := r.persistStatus(ctx, st); err != nil {
				return err
			}
		}
		return r.publish(ctx)
	}
	switch {
	case isCancellation(err) || ctx.Err() != nil:
		r.abortTurn(ctx, iteration, "cancelled")
		return err
	case runLimitReason(err) != "":
		r.abortTurn(ctx, iteration, runLimitReason(err))
		return err
	case appErrorType(err) == ErrSpendCapReached:
		r.monthlyCapMessage = causeText(err)
		r.abortTurn(ctx, iteration, "spend_cap")
		return r.publish(ctx)
	}
	workflow.GetLogger(ctx).Error("iteration failed", "iteration", iteration, "error", extractErrorDetails(err))
	if reason, msg, denied := governanceDenial(err); denied {
		r.status = StatusBlocked
		r.failureReason = reason
		r.errorMessage = msg
		r.blockedReason = msg
		r.abortTurn(ctx, iteration, "blocked")
		return r.publish(ctx)
	}
	if r.reportedLLMFailure == nil || !errors.Is(err, r.reportedLLMFailure) {
		r.emit(ctx, domain.EventLLMFailed, map[string]any{"iteration": iteration, "error": extractErrorDetails(err)})
	}
	r.abortTurn(ctx, iteration, "failed")
	return err
}

func (r *agentRun) abortTurn(ctx workflow.Context, iteration int, reason string) {
	r.emit(ctx, domain.EventTurnAborted, map[string]any{"iteration": iteration, "reason": reason})
}

func (r *agentRun) instruction() string {
	text := r.cfg.Agent.Instruction
	if len(r.cfg.Skills) > 0 {
		text += domain.SkillCatalog(r.cfg.Skills)
	}
	if r.dynamic() {
		text += domain.ToolSourceCatalog(r.cfg.ToolProviders, r.activatedSources)
	}
	if truthyAny(r.metadata["project_id"]) {
		text += "\n\nProject input files are available to shell commands in the " +
			"`inputs/` directory of the sandbox. Use ordinary file operations " +
			"such as `find inputs -maxdepth 2 -type f` to inspect them."
	}
	text += workspaceAttachmentPrompt(r.metadata["workspace_attachments"])
	if !r.dynamic() && len(r.cfg.SearchableTools) > 0 {
		var pool []api.SearchableTool
		for _, c := range r.cfg.SearchableTools {
			if !slices.Contains(r.revealedTools, c.Name) {
				pool = append(pool, c)
			}
		}
		text += domain.OpenAPICatalog(pool)
	}
	text += "\n\nInteraction contract: attempt the task autonomously with available " +
		"context and tools. Do not invent missing facts, credentials, or authorization. " +
		"Unavailable interaction alone does not block useful work. If an actual " +
		"prerequisite remains unmet after available alternatives, call completion " +
		"with outcome='blocked', explain it in result, and declare any artifacts."
	if !r.questionsAvailable() {
		text += "\nQuestions are unavailable for this run. Do not ask the user, " +
			"promise a reply channel, or call request_user_input."
	}
	if !r.interaction.AllowApprovals {
		text += "\nHuman approvals cannot be collected on this route. Protected tools " +
			"remain denied; use permitted alternatives, never bypass approval."
	}
	if r.a2uiAvailable() {
		text += "\nA2UI presentation alone is informational, not a request for input. " +
			"For required forms, emit the surface and call request_user_input " +
			"with its surface_id and questions in the same turn; do not complete " +
			"until the matching answer arrives. Button action.event.context must " +
			"map question IDs to data-model values. Secret fields MUST use the " +
			"native request_user_input form without surface_id, never A2UI."
	}
	return text
}

func workspaceAttachmentPrompt(v any) string {
	list, ok := v.([]any)
	if !ok {
		return ""
	}
	var lines []string
	for _, item := range list[:min(100, len(list))] {
		d, isMap := item.(map[string]any)
		if !isMap {
			continue
		}
		rel, _ := d["relative_path"].(string)
		filename, _ := d["filename"].(string)
		parts := strings.Split(rel, "/")
		if !strings.HasPrefix(rel, "inputs/attachments/") || len(parts) != 3 || strings.ContainsAny(rel, "\\\r\n\x00") ||
			slices.ContainsFunc(parts, func(p string) bool { return p == "" || p == "." || p == ".." }) {
			continue
		}
		if filename != parts[2] || strings.ContainsAny(filename, "\r\n\x00") {
			continue
		}
		size, isNum := d["size"].(float64)
		if !isNum || size < 0 || size != float64(int64(size)) {
			continue
		}
		ct, isStr := d["content_type"].(string)
		if !isStr || strings.ContainsAny(ct, "\r\n\x00") {
			ct = "application/octet-stream"
		}
		lines = append(lines, fmt.Sprintf("- path=%s; filename=%s; size=%d; content_type=%s",
			domain.PyDumps(rel), domain.PyDumps(filename), int64(size), domain.PyDumps(ct)))
	}
	if len(lines) == 0 {
		return ""
	}
	return "\n\nTask attachments are already available in the task workspace. " +
		"Use the exact relative paths below and do not ask the user to upload them again:\n" + strings.Join(lines, "\n")
}

func (r *agentRun) traditionalIteration(ctx workflow.Context) error {
	iteration := r.iteration
	firstMessage := iteration == 1
	goalText := r.goal.Description
	if firstMessage {
		goalText = domain.FirstMessageIsTheTask
	}
	name := r.cfg.Agent.Name
	if name == "" {
		name = "AI Agent"
	}
	prompt := domain.SystemPrompt(name, r.instruction(), goalText, r.goal.SuccessCriteria, r.a2uiAvailable(), workflow.Now(ctx))
	switch {
	case firstMessage:
		r.messages = append(r.messages, Message{Role: "system", Content: prompt}, Message{Role: "user", Content: r.goal.Description})
		r.conversationSeeded = true
		if err := r.refuseOversizedHead(prompt); err != nil {
			return err
		}
	case r.resumePromptMissing:
		r.resumePromptMissing = false
		r.messages = append(r.messages, Message{Role: "system", Content: prompt})
	}
	if iteration > 1 && r.contextWindow > 0 {
		pending := r.pendingPayload()
		r.contextUsage = r.lastPromptTokens + estimateMessages(r.messages)
		raw, _ := json.Marshal(pending)
		oversized := len(raw) > contextMaxPayload
		if oversized || r.compactionWanted() {
			if _, err := r.compact(ctx, oversized); err != nil {
				return err
			}
		} else if r.contextRatio() >= contextWarnThreshold && !r.contextWarningSent {
			r.emit(ctx, domain.EventContextWarning, map[string]any{
				"iteration": r.iteration, "usage_ratio": r.contextRatio(), "message_count": r.nextSeq + int64(len(r.messages)),
			})
			if err := r.publish(ctx); err != nil {
				return err
			}
			r.contextWarningSent = true
		}
	}
	for _, action := range r.a2uiQueue {
		ctxJSON := domain.PyDumps(orDefault(action["context"], map[string]any{}))
		r.messages = append(r.messages, Message{Role: "user", Content: fmt.Sprintf(
			"[A2UI Action] The user interacted with the UI surface '%v': action=%v, source=%v, context=%s",
			orDefault(action["surface_id"], "unknown"), orDefault(action["name"], "unknown"),
			orDefault(action["source_component_id"], "unknown"), ctxJSON)})
	}
	r.a2uiQueue = nil
	for _, q := range r.messageQueue {
		r.messages = append(r.messages, Message{Role: "user", Content: q.Content})
	}
	r.messageQueue = nil
	reply, err := r.callLLM(ctx)
	if err != nil {
		return err
	}
	return r.processResponse(ctx, reply)
}

func orDefault(v, def any) any {
	if v == nil {
		return def
	}
	return v
}

func (r *agentRun) refuseOversizedHead(prompt string) error {
	pinned := estimateMessages([]Message{{Role: "system", Content: prompt}, {Role: "user", Content: r.goal.Description}})
	limit := r.effectiveLimit()
	if pinned > int64(limit) {
		return nonRetryable(fmt.Sprintf("The run's input and system prompt take about %d tokens, more than "+
			"the %d this model's context window leaves for them. They stay in "+
			"view for the whole run, so the run cannot start: shorten the input or "+
			"use a model with a larger context window.", pinned, limit), ErrRunInputExceedsWindow)
	}
	return nil
}

func estimateMessages(ms []Message) int64 {
	var total int64
	for _, m := range ms {
		total += int64(domain.EstimateTokens(m.Content)) + 4
		for _, c := range m.ToolCalls {
			total += int64(domain.EstimateTokens(c.Name + c.Arguments))
		}
	}
	return total
}

func (r *agentRun) effectiveLimit() int { return int(float64(r.contextWindow) * contextLimitShare) }

func (r *agentRun) contextRatio() float64 {
	if r.effectiveLimit() <= 0 {
		return 0
	}
	return float64(r.contextUsage) / float64(r.effectiveLimit())
}

func (r *agentRun) needsCompaction() bool { return r.contextRatio() >= compactionThreshold }

// compactionWanted skips a compaction that would gain too little over the
// prompt measured right after the last one.
func (r *agentRun) compactionWanted() bool {
	if !r.needsCompaction() {
		return false
	}
	return r.compactionFloor == nil || float64(r.contextUsage-*r.compactionFloor) >= minCompactionGain*float64(r.effectiveLimit())
}

func (r *agentRun) contextStatus() map[string]any {
	return map[string]any{
		"context_window": r.contextWindow, "effective_limit": r.effectiveLimit(), "current_tokens": r.contextUsage,
		"usage_ratio": r.contextRatio(), "needs_compaction": r.needsCompaction(), "compaction_count": r.compactionCount,
	}
}

func (r *agentRun) pendingPayload() []Message { return slices.Clone(r.messages) }

func (r *agentRun) conversation() Conversation {
	return Conversation{TaskID: r.taskID, NextSeq: r.nextSeq}
}

// compact summarizes the logged conversation once it nears the window.
func (r *agentRun) compact(ctx workflow.Context, force bool) (bool, error) {
	var chunk *int
	if r.cfg.ContextStrategy != "static" {
		chunk = ptr(r.historyChunks)
	}
	req := CompactMessagesRequest{
		Principal: r.principal, Conversation: r.conversation(), Pending: r.pendingPayload(), HistoryChunkIndex: chunk,
		Model: r.cfg.Model, Policy: r.cfg.Policy, Counters: r.counters(),
	}
	var res CompactMessagesResult
	if err := r.modelActivity(ctx, api.ActivityCompactMessages, req, &res); err != nil {
		return false, err
	}
	if res.OriginalMessageCount == 0 {
		return false, nil
	}
	row := Message{Role: "user", Kind: "compaction", Content: domain.CompactionSummaryHeader + "\n" + res.Summary}
	if len(res.Skills) > 0 {
		row.Meta = map[string]any{"skills": res.Skills}
	}
	r.messages = append(r.messages, row)
	if err := r.accountInference(res.Cost, res.Usage.TotalTokens, "Context compaction"); err != nil {
		return false, err
	}
	if res.HistoryChunkStored {
		r.historyChunks++
	}
	r.lastPromptTokens = int64(res.ContextTokens)
	r.contextUsage = int64(res.ContextTokens)
	r.compactionCount++
	r.contextWarningSent = false
	r.compactionFloor = nil
	r.awaitingFloor = true
	r.emit(ctx, domain.EventLLMCompleted, map[string]any{
		"iteration": r.iteration, "purpose": "compaction", "model_id": nullable(r.cfg.Agent.ModelID),
		"model_name": nullable(r.cfg.Model.ModelName), "managed_by": nullable(r.cfg.Model.ManagedBy),
		"cost": res.Cost.String(), "provider_cost_usd": nil, "total_cost": r.cost.String(),
		"usage":   map[string]any{"cost": res.Cost.String(), "usage": usageValue(res.Usage)},
		"content": "", "thinking": "", "tool_calls": []any{}, "role": "assistant",
	})
	r.emit(ctx, domain.EventContextCompacted, map[string]any{
		"iteration": r.iteration, "messages_compacted": res.OriginalMessageCount, "tokens_saved": res.EstimatedTokensSaved,
		"compaction_number": r.compactionCount, "context_tokens": res.ContextTokens,
	})
	if err := r.publish(ctx); err != nil {
		return false, err
	}
	return true, r.enforceInferenceLimits("Context compaction")
}

func usageValue(u LLMUsage) map[string]any {
	out := map[string]any{
		"prompt_tokens": u.PromptTokens, "completion_tokens": u.CompletionTokens, "total_tokens": u.TotalTokens,
		"cached_prompt_tokens": u.CachedPromptTokens, "cache_creation_tokens": u.CacheCreationTokens,
	}
	if u.Billing != nil {
		out["billing"] = u.Billing
	}
	return out
}

// modelActivity runs a model-calling activity; a stop waits for it to settle
// and leaves the call to be answered as stopped.
func (r *agentRun) modelActivity(ctx workflow.Context, name string, req, out any) error {
	err := workflow.ExecuteActivity(activityCtx(ctx, name, "", 0), name, req).Get(ctx, out)
	if err != nil && (isCancellation(err) || ctx.Err() != nil) {
		r.stoppedModelCall = true
	}
	return err
}

type llmReply struct {
	role          string
	content       string
	thinking      string
	toolCalls     []ToolCall
	finishReason  string
	model         map[string]any
	answerChecked bool
}

func (r *agentRun) callLLM(ctx workflow.Context) (llmReply, error) {
	r.emit(ctx, domain.EventLLMStarted, map[string]any{"iteration": r.iteration, "message_count": r.nextSeq + int64(len(r.messages))})
	if err := r.publish(ctx); err != nil {
		return llmReply{}, err
	}
	tools := r.tools
	if !r.questionsAvailable() {
		tools = slices.DeleteFunc(slices.Clone(tools), func(t api.ToolDefinition) bool { return t.Name == domain.ToolRequestUserInput })
	}
	effort, maxTokens := reasoningSettings(r.goal.Context, r.cfg.Agent.ReasoningEffort, r.cfg.Agent.ReasoningMaxTokens)
	conv := r.conversation()
	req := LLMCallRequest{
		Principal: r.principal, TaskID: r.taskID, ExecutionID: r.executionID, Iteration: r.iteration, Purpose: "turn",
		Model: r.cfg.Model, Conversation: &conv, Messages: r.pendingPayload(), Tools: tools,
		ReasoningEffort: effort, ReasoningMaxTokens: maxTokens, StreamText: true, Policy: r.cfg.Policy, Counters: r.counters(),
	}
	var res LLMCallResult
	if err := r.modelActivity(ctx, api.ActivityCallLLM, req, &res); err != nil {
		return llmReply{}, r.reportLLMFailure(ctx, err)
	}
	if res.Currency != "" {
		r.currency = res.Currency
	}
	if err := r.accountInference(res.Cost, res.Usage.TotalTokens, "LLM call"); err != nil {
		return llmReply{}, r.reportLLMFailure(ctx, err)
	}
	if res.Usage.PromptTokens > 0 {
		r.lastPromptTokens = res.Usage.PromptTokens
		r.contextUsage = res.Usage.PromptTokens
		if r.awaitingFloor {
			r.compactionFloor = ptr(res.Usage.PromptTokens)
			r.awaitingFloor = false
		}
	}
	display := res.Content
	if r.a2uiAvailable() && strings.Contains(display, domain.A2UIDelimiter) {
		display = strings.TrimRight(strings.SplitN(display, domain.A2UIDelimiter, 2)[0], " \t\r\n")
	}
	content, answerChecked := res.Content, false
	if len(res.ToolCalls) == 0 && strings.TrimSpace(display) != "" && r.answerCheck() != nil {
		checked, err := r.checkedAnswer(ctx, strings.TrimSpace(display))
		if err != nil {
			return llmReply{}, err
		}
		content = checked + res.Content[len(display):]
		display = checked
		answerChecked = true
	}
	role := firstNonEmpty(res.Role, "assistant")
	r.emit(ctx, domain.EventLLMCompleted, map[string]any{
		"iteration": r.iteration, "model_id": nullable(r.cfg.Agent.ModelID), "model_name": nullable(r.cfg.Model.ModelName),
		"managed_by": nullable(res.ManagedBy), "cost": res.Cost.String(), "provider_cost_usd": res.ProviderCostUSD.String(),
		"total_cost": r.cost.String(), "usage": map[string]any{"cost": res.Cost.String(), "usage": usageValue(res.Usage)},
		"content": display, "thinking": res.Thinking, "tool_calls": toolCallsValue(res.ToolCalls), "role": role,
		"finish_reason": nullable(res.FinishReason),
	})
	if err := r.publish(ctx); err != nil {
		return llmReply{}, err
	}
	reply := llmReply{
		role: role, content: content, thinking: res.Thinking, toolCalls: res.ToolCalls, finishReason: res.FinishReason, answerChecked: answerChecked,
		model: map[string]any{"model_id": r.cfg.Agent.ModelID, "model_name": nullable(r.cfg.Model.ModelName)},
	}
	if err := r.enforceInferenceLimits("LLM call"); err != nil {
		r.keepReply(reply)
		return llmReply{}, err
	}
	return reply, nil
}

func (r *agentRun) reportLLMFailure(ctx workflow.Context, err error) error {
	if isCancellation(err) || ctx.Err() != nil || runLimitReason(err) == ReasonTokens || appErrorType(err) == ErrSpendCapReached {
		return err
	}
	lower := strings.ToLower(extractErrorDetails(err))
	cause := failureCause(err)
	quota := cause == "provider_out_of_credits" || (cause == "" &&
		(strings.Contains(lower, "insufficient balance") || strings.Contains(lower, "no resource package") || strings.Contains(lower, "quota exceeded")))
	userErr := userFacingError(err)
	r.emit(ctx, domain.EventLLMFailed, map[string]any{
		"iteration": r.iteration, "error": userErr, "error_type": userFacingErrorType(err),
		"failure_reason": nullable(cause), "error_detail": errorDetail(err), "model_id": nullable(r.cfg.Agent.ModelID),
	})
	r.reportedLLMFailure = err
	if quota {
		r.status = StatusBlocked
		r.blockedReason = userErr
	}
	if perr := r.publish(ctx); perr != nil {
		return perr
	}
	return err
}

func (r *agentRun) keepReply(reply llmReply) {
	if strings.TrimSpace(reply.content) == "" && len(reply.toolCalls) == 0 {
		return
	}
	r.messages = append(r.messages, Message{Role: reply.role, Content: reply.content, ToolCalls: reply.toolCalls, Meta: reply.model})
	r.turnCallIDs = callIDs(reply.toolCalls)
}

func callIDs(calls []ToolCall) []string {
	out := make([]string, 0, len(calls))
	for _, c := range calls {
		if c.ID != "" {
			out = append(out, c.ID)
		}
	}
	return out
}

// reasoningSettings is reasoning_settings: a task's own setting wins over the agent's.
func reasoningSettings(params map[string]any, effort string, maxTokens *int) (string, *int) {
	if v, ok := params["reasoning_effort"].(string); ok && v != "" {
		return v, nil
	}
	if v, ok := params["reasoning_max_tokens"].(float64); ok && v > 0 {
		return "", ptr(int(v))
	}
	return effort, maxTokens
}

func (r *agentRun) processResponse(ctx workflow.Context, reply llmReply) error {
	content := reply.content
	if r.a2uiAvailable() && content != "" && strings.Contains(content, domain.A2UIDelimiter) {
		parsed := domain.ParseA2UI(content)
		if len(parsed.Events) > 0 {
			content = parsed.Text
			for _, ev := range parsed.Events {
				r.applyA2UIEvent(ctx, ev)
			}
			if err := r.publish(ctx); err != nil {
				return err
			}
		}
		if parsed.ParseError != "" {
			workflow.GetLogger(ctx).Warn("A2UI parse error", "error", parsed.ParseError)
		}
	}
	if strings.TrimSpace(content) == "" && len(reply.toolCalls) == 0 && reply.thinking != "" {
		r.messages = append(r.messages, Message{Role: "user", Content: "Your previous reply contained only reasoning, with no answer " +
			"and no tool call. Reply with your answer or call a tool."})
	}
	if strings.TrimSpace(content) != "" || len(reply.toolCalls) > 0 {
		r.messages = append(r.messages, Message{Role: reply.role, Content: content, ToolCalls: reply.toolCalls, Meta: reply.model})
		r.turnCallIDs = callIDs(reply.toolCalls)
	}
	switch {
	case len(reply.toolCalls) > 0:
		return r.executeToolCalls(ctx, reply.toolCalls)
	case strings.TrimSpace(content) != "" && reply.finishReason == "length":
		r.truncatedReply += content
		r.messages = append(r.messages, Message{Role: "user", Content: "Your reply was cut off at the output limit. Continue exactly where " +
			"it stopped, without repeating anything already written."})
	case strings.TrimSpace(content) != "":
		args := domain.PyDumps(domain.Ordered{{Key: "result", Value: strings.TrimSpace(r.truncatedReply + content)}, {Key: "artifacts", Value: []any{}}})
		call := ToolCall{ID: r.ids.uuid(), Name: domain.ToolCompletion, Arguments: args}
		r.truncatedReply = ""
		return r.handleCompletion(ctx, call, reply.answerChecked)
	default:
		workflow.GetLogger(ctx).Error("LLM returned empty response with no tool calls", "iteration", r.iteration)
	}
	return nil
}

func (r *agentRun) applyA2UIEvent(ctx workflow.Context, ev map[string]any) {
	typ, _ := ev["type"].(string)
	surfaceID, isStr := ev["surface_id"].(string)
	if !isStr {
		return
	}
	switch typ {
	case "A2UICreateSurface":
		r.a2uiSurfaces[surfaceID] = map[string]string{}
	case "A2UIDeleteSurface":
		delete(r.a2uiSurfaces, surfaceID)
	case "A2UIUpdateComponents":
		if actions := r.a2uiSurfaces[surfaceID]; actions != nil {
			comps, _ := ev["components"].([]any)
			for _, c := range comps {
				comp, isMap := c.(map[string]any)
				if !isMap {
					continue
				}
				id, idOK := comp["id"].(string)
				action, _ := comp["action"].(map[string]any)
				event, _ := action["event"].(map[string]any)
				name, _ := event["name"].(string)
				if idOK {
					if name != "" {
						actions[id] = name
					} else {
						delete(actions, id)
					}
				}
			}
		}
	}
	data := map[string]any{}
	for k, v := range ev {
		if k != "type" {
			data[k] = v
		}
	}
	data["task_id"] = r.taskID
	canonical, _ := domain.A2UICanonical(typ)
	r.emit(ctx, canonical, data)
}
