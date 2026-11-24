package workflows

import (
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

const (
	skillContextShare       = 0.1
	legacySkillsWindowShare = 0.3
	skillMinTokens          = 256
	finalizeMargin          = 10 * time.Minute
	inputSkipped            = "Skipped because the workflow requested user input. Call this tool again after the user reply if it is still needed."
)

func parseArgs(call ToolCall) map[string]any {
	var args map[string]any
	if json.Unmarshal([]byte(call.Arguments), &args) != nil || args == nil {
		return map[string]any{}
	}
	return args
}

func (r *agentRun) toolMessage(call ToolCall, content string) {
	r.messages = append(r.messages, Message{Role: "tool", Content: content, ToolCallID: call.ID, Name: call.Name})
}

// executeToolCalls runs a turn's calls: context tools, delegations to local
// and remote agents in parallel, regular tools in order, completion last.
func (r *agentRun) executeToolCalls(ctx workflow.Context, calls []ToolCall) error {
	exec := policyExec(r.cfg.Policy)
	perTurn, ok := intLimit(exec.MaxToolCallsPerTurn)
	if !ok || perTurn <= 0 {
		return nonRetryable("effective policy is missing execution.max_tool_calls_per_turn", ErrInvalidExecutionSnapshot)
	}
	total, ok := intLimit(exec.MaxToolCallsTotal)
	if !ok || total <= 0 {
		return nonRetryable("effective policy is missing execution.max_tool_calls_total", ErrInvalidExecutionSnapshot)
	}
	names := make([]string, 0, len(calls))
	for _, c := range calls {
		names = append(names, c.Name)
	}
	metered := domain.MeteredToolCallCount(names)
	if metered > perTurn {
		refusal := fmt.Sprintf("Not executed: this turn requested %d tool calls and the policy allows %d per turn. Request at most %d at once.", metered, perTurn, perTurn)
		for _, c := range calls {
			r.toolMessage(c, refusal)
			r.announce(ctx, c)
			r.emit(ctx, domain.EventToolResult, map[string]any{"tool_name": c.Name, "tool_call_id": c.ID, "success": false, "error": refusal, "iteration": r.iteration})
		}
		return r.publish(ctx)
	}
	attempted := r.toolCallsUsed + metered
	if attempted > total {
		return nonRetryable(fmt.Sprintf("tool-call budget exceeded: %d/%d", attempted, total), ErrToolCallLimitExceeded)
	}
	r.toolCallsUsed = attempted

	var completion, delegations, regular, recall, skills, readOutput, sources, loads, inputs []ToolCall
	for _, c := range calls {
		switch c.Name {
		case domain.ToolCompletion, domain.ToolTaskComplete:
			completion = append(completion, c)
		case domain.ToolRequestUserInput:
			inputs = append(inputs, c)
		case domain.ToolRecallHistory:
			recall = append(recall, c)
		case domain.ToolReadToolOutput:
			readOutput = append(readOutput, c)
		case domain.ToolActivateToolSource:
			sources = append(sources, c)
		case domain.ToolLoadTools:
			loads = append(loads, c)
		case domain.ToolActivateSkill:
			skills = append(skills, c)
		default:
			if r.delegates(c) {
				delegations = append(delegations, c)
			} else {
				regular = append(regular, c)
			}
		}
	}
	if len(completion) > 1 {
		for _, c := range completion {
			r.rejectCompletion(c, "exactly one completion call may be made per turn")
		}
		completion = nil
	}
	if len(inputs) > 0 {
		if err := r.requestUserInput(ctx, inputs[0]); err != nil {
			return err
		}
		skipped := slices.Concat(inputs[1:], recall, readOutput, sources, loads, skills, delegations, regular, completion)
		for _, c := range skipped {
			r.toolMessage(c, inputSkipped)
		}
		return nil
	}
	steps := []struct {
		calls []ToolCall
		run   func(workflow.Context, ToolCall) error
	}{
		{recall, r.recallHistory}, {readOutput, r.readToolOutput}, {sources, r.activateToolSource},
		{loads, r.loadTools}, {skills, r.activateSkill},
	}
	for _, s := range steps {
		for _, c := range s.calls {
			if err := s.run(ctx, c); err != nil {
				return err
			}
		}
	}
	if len(delegations) > 0 {
		if err := r.delegateAll(ctx, delegations); err != nil {
			return err
		}
	}
	for _, c := range regular {
		var err error
		if c.Name == domain.ToolWait {
			err = r.wait(ctx, c)
		} else {
			err = r.executeTool(ctx, c)
		}
		if err != nil {
			return err
		}
	}
	if len(completion) == 1 {
		return r.handleCompletion(ctx, completion[0], false)
	}
	return nil
}

func (r *agentRun) announce(ctx workflow.Context, c ToolCall) {
	raw := c.Arguments
	if raw == "" {
		raw = "{}"
	}
	var args any
	if json.Unmarshal([]byte(raw), &args) != nil {
		args = map[string]any{}
	}
	r.emit(ctx, domain.EventToolCall, map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "iteration": r.iteration, "arguments": domain.SanitizeToolEventValue(args, ""),
	})
}

func (r *agentRun) deny(ctx workflow.Context, c ToolCall, reason string, ran, announced bool) {
	if !announced {
		r.announce(ctx, c)
	}
	msg := "Tool call denied by policy: " + reason
	if ran {
		msg = "Tool call ran, but its result was withheld by policy: " + reason
	}
	r.toolMessage(c, msg)
	r.emit(ctx, domain.EventToolResult, map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "success": false, "iteration": r.iteration, "error": msg, "denied_by_policy": true,
	})
}

// gate decides a call: allowed, and whether a human approved it.
func (r *agentRun) gate(ctx workflow.Context, c ToolCall) (bool, bool, error) {
	args := parseArgs(c)
	if r.monthlyCapMessage != "" {
		r.deny(ctx, c, r.monthlyCapMessage, false, false)
		return false, false, nil
	}
	if !r.offered(c.Name) {
		r.deny(ctx, c, "tool is not available to this agent", false, false)
		return false, false, nil
	}
	if b, bound := r.cfg.Bindings[c.Name]; !bound || b.MCP == nil {
		if url, isFetch := webFetchURL(c.Name, args); isFetch && !r.linkReachedTask(url) {
			r.deny(ctx, c, "a page can be fetched only from a link that already appeared in this "+
				"task: the request, search results or a page fetched earlier", false, false)
			return false, false, nil
		}
	}
	action, _ := domain.DecideToolPolicy(r.cfg.Policy, c.Name, domain.NamesFor(&r.cfg, c.Name))
	switch action {
	case domain.ToolDeny:
		r.deny(ctx, c, "not permitted by policy", false, false)
		return false, false, nil
	case domain.ToolRequireApproval:
		approved, err := r.requireApproval(ctx, c, args, "")
		return approved, approved, err
	case domain.ToolAllow:
	}
	return true, false, nil
}

func webFetchURL(tool string, args map[string]any) (string, bool) {
	var url any
	switch tool {
	case "web_fetch_webpage":
		url = args["url"]
	case "web":
		action, _ := args["action"].(string)
		if action != "fetch_webpage" {
			if action != "" || args["action"] != nil && args["action"] != "" {
				return "", false
			}
			if !slices.ContainsFunc(sortedKeys(args), func(k string) bool { return strings.HasPrefix(k, "fetch_webpage_") }) {
				return "", false
			}
		}
		url = args["fetch_webpage_url"]
	default:
		return "", false
	}
	s, _ := url.(string)
	return s, true
}

func (r *agentRun) linkReachedTask(url string) bool {
	target, ok := domain.ComparableURL(url)
	if !ok {
		return false
	}
	if slices.Contains(r.seenURLs, target) {
		return true
	}
	entries := make([]domain.Entry, 0, len(r.messages))
	for _, m := range r.messages {
		entries = append(entries, domain.Entry{Role: m.Role, Content: m.Content})
	}
	return slices.Contains(domain.ExternalURLs(entries), target)
}

// requireApproval waits for a person to decide a call; true when approved.
func (r *agentRun) requireApproval(ctx workflow.Context, c ToolCall, args map[string]any, reason string) (bool, error) {
	if !r.interaction.AllowApprovals {
		r.deny(ctx, c, "Required human approval is unavailable on this return route. The operation "+
			"was not executed. Use permitted alternatives; if approval is indispensable, "+
			"complete with outcome='blocked' and explain the missing authorization.", false, false)
		return false, nil
	}
	id := r.ids.uuid()
	names := domain.NamesFor(&r.cfg, c.Name)
	esc := &Escalation{
		EscalationID: id, ToolCallID: c.ID, ToolName: c.Name, ToolArgs: args,
		Approvers: domain.ApproversForTool(r.cfg.Policy, c.Name, slices.Concat(names.Aliases, names.Restricting)),
	}
	r.escalations[id] = esc
	r.escalationOrder = append(r.escalationOrder, id)
	r.status = StatusWaitingForApproval
	if err := r.persistStatus(ctx, r.statusOnly("waiting_for_approval")); err != nil {
		return false, err
	}
	msg := "Tool '" + c.Name + "' requires human approval"
	if reason != "" {
		msg += ": " + reason
	}
	r.emit(ctx, domain.EventApprovalRequested, map[string]any{
		"escalation_id": id, "tool_name": c.Name, "tool_call_id": c.ID, "iteration": r.iteration,
		"arguments": domain.SanitizeToolEventValue(args, ""), "approvers": orEmpty(esc.Approvers), "message": msg,
	})
	if err := r.publish(ctx); err != nil {
		return false, err
	}
	if err := workflow.Await(ctx, func() bool { return esc.Resolved }); err != nil {
		return false, err
	}
	if esc.Approved {
		if err := r.checkMonthlySpendCap(ctx); err != nil {
			return false, err
		}
	}
	r.emit(ctx, domain.EventApprovalDecided, map[string]any{
		"escalation_id": id, "tool_name": c.Name, "tool_call_id": c.ID, "iteration": r.iteration,
		"approved": esc.Approved, "approved_by": nullable(esc.ApprovedBy), "comment": nullable(esc.Comment),
	})
	if !esc.Approved {
		denyMsg := firstNonEmpty(esc.DenyComment, "Denied by user")
		r.emit(ctx, domain.EventToolResult, map[string]any{
			"tool_name": c.Name, "tool_call_id": c.ID, "success": false, "iteration": r.iteration,
			"error": "Denied by human operator: " + denyMsg, "denied_by_human": true,
		})
		if err := r.publish(ctx); err != nil {
			return false, err
		}
		r.toolMessage(c, "Tool call denied by human operator: "+denyMsg)
	} else if err := r.publish(ctx); err != nil {
		return false, err
	}
	delete(r.escalations, id)
	r.escalationOrder = slices.DeleteFunc(r.escalationOrder, func(s string) bool { return s == id })
	if len(r.escalations) == 0 {
		r.status = StatusExecuting
		if err := r.persistStatus(ctx, r.statusOnly("running")); err != nil {
			return false, err
		}
	}
	if esc.Approved && r.monthlyCapMessage != "" {
		r.deny(ctx, c, r.monthlyCapMessage, false, false)
		return false, nil
	}
	return esc.Approved, nil
}

func orEmpty(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

// toolActivity runs a tool's activity; a stop waits for it and leaves the
// call to be answered as stopped while running.
func (r *agentRun) toolActivity(ctx workflow.Context, c ToolCall, req ToolCallRequest) (ToolCallResult, error) {
	var res ToolCallResult
	err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityExecuteTool, "", 0), api.ActivityExecuteTool, req).Get(ctx, &res)
	if err != nil && (isCancellation(err) || ctx.Err() != nil) {
		r.stoppedToolCalls = append(r.stoppedToolCalls, c)
	}
	return res, err
}

// governanceVerdict is a governance gate's refusal of a tool activity: type, reason, ran.
func governanceVerdict(err error) (string, string, bool, bool) {
	a := appErr(err)
	if a == nil || (a.Type() != ErrGovernanceDenied && a.Type() != ErrEscalationRequired) {
		return "", "", false, false
	}
	details := errorDetails(err)
	if len(details) == 0 {
		return a.Type(), a.Message(), false, true
	}
	v := details[0]
	phase, _ := v["phase"].(string)
	return a.Type(), fmt.Sprintf("%v: %v", v["interceptor_name"], v["reason"]), strings.HasPrefix(phase, "post_"), true
}

func (r *agentRun) governedTool(ctx workflow.Context, c ToolCall, args map[string]any, req ToolCallRequest) (*ToolCallResult, error) {
	res, err := r.toolActivity(ctx, c, req)
	if err == nil {
		return &res, nil
	}
	if isCancellation(err) || ctx.Err() != nil {
		return nil, err
	}
	typ, reason, ran, ok := governanceVerdict(err)
	if !ok || (typ == ErrEscalationRequired && req.EscalationApproved) {
		return nil, err
	}
	if typ == ErrGovernanceDenied {
		r.deny(ctx, c, reason, ran, true)
		return nil, r.publish(ctx)
	}
	approved, aerr := r.requireApproval(ctx, c, args, reason)
	if aerr != nil {
		return nil, aerr
	}
	if !approved {
		return nil, r.publish(ctx)
	}
	req.EscalationApproved = true
	return r.governedTool(ctx, c, args, req)
}

// failureText is what Python's str() of a failed activity reads.
func failureText(err error) string {
	if _, ok := errors.AsType[*temporal.ActivityError](err); ok {
		return "Activity task failed"
	}
	if _, ok := errors.AsType[*temporal.ChildWorkflowExecutionError](err); ok {
		return "Child Workflow execution failed"
	}
	if a := appErr(err); a != nil {
		return a.Message()
	}
	return err.Error()
}

// executeTool runs a capability tool through its activity.
func (r *agentRun) executeTool(ctx workflow.Context, c ToolCall) error {
	args := parseArgs(c)
	allowed, granted, err := r.gate(ctx, c)
	if err != nil || !allowed {
		return err
	}
	r.emit(ctx, domain.EventToolCall, map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "iteration": r.iteration, "arguments": domain.SanitizeToolEventValue(args, ""),
	})
	if err := r.publish(ctx); err != nil {
		return err
	}
	req := ToolCallRequest{
		Principal: r.principal, TaskID: r.taskID, ExecutionID: r.executionID, ToolCallID: c.ID, ToolName: c.Name,
		Args: args, Binding: r.cfg.Bindings[c.Name], Policy: r.cfg.Policy, Counters: r.counters(),
		RunMetadata: r.metadata, PolicyApprovalGranted: granted,
	}
	started := workflow.Now(ctx).UTC()
	res, err := r.governedTool(ctx, c, args, req)
	if err != nil {
		if isCancellation(err) || ctx.Err() != nil {
			return err
		}
		r.toolMessage(c, "Tool execution failed: "+failureText(err))
		r.emit(ctx, domain.EventToolResult, map[string]any{
			"tool_name": c.Name, "tool_call_id": c.ID, "iteration": r.iteration,
			"error": domain.SanitizeToolEventValue(failureText(err), "result"),
		})
		return r.publish(ctx)
	}
	if res == nil {
		return nil
	}
	return r.recordToolResult(ctx, c, args, *res, started)
}

func (r *agentRun) recordToolResult(ctx workflow.Context, c ToolCall, args map[string]any, res ToolCallResult, started time.Time) error {
	execTime := res.Duration.Seconds()
	paths := res.ArtifactPaths
	if paths == nil {
		paths = []string{}
	}
	var exitCode any
	if res.ExitCode != nil {
		exitCode = *res.ExitCode
	}
	meta := map[string]any{
		"exit_code": exitCode, "duration": execTime, "server": nullable(firstNonEmpty(res.ServerName, res.ServerInstanceID)),
		"started_at": started.Format("2006-01-02T15:04:05.999999-07:00"), "artifact_paths": paths,
	}
	priced := map[string]any{}
	if res.ModelCost.Sign() > 0 {
		priced["model_cost"] = res.ModelCost.String()
	}
	if res.ModelBilling != nil {
		priced["model_billing"] = res.ModelBilling
	}
	if res.CostUnknown {
		priced["cost_unknown"] = true
	}
	replay := map[string]any{}
	if res.Replayed {
		replay["replayed"] = true
	}
	if res.Attempt != nil && *res.Attempt != 0 {
		replay["attempt"] = *res.Attempt
	}
	server := map[string]any{
		"source": nullable(res.Source), "server_instance_id": nullable(res.ServerInstanceID),
		"server_name": nullable(res.ServerName), "server_icon": nullable(res.ServerIcon),
	}
	r.chargeTool(res)
	if !res.Success {
		msg := firstNonEmpty(res.Error, res.Result, "Tool execution failed")
		r.messages = append(r.messages, Message{Role: "tool", Content: "Tool failed: " + msg, ToolCallID: c.ID, Name: c.Name, Meta: meta})
		data := map[string]any{
			"tool_name": c.Name, "tool_call_id": c.ID, "success": false,
			"error": domain.SanitizeToolEventValue(msg, "result"), "exit_code": exitCode, "artifact_paths": paths,
			"arguments": domain.SanitizeToolEventValue(args, ""), "execution_time": execTime, "iteration": r.iteration,
		}
		mergeInto(data, server, priced, replay)
		r.emit(ctx, domain.EventToolResult, data)
		return r.publish(ctx)
	}
	if res.ServiceCost.Sign() > 0 {
		r.serviceCostUsed = r.serviceCostUsed.Add(res.ServiceCost)
		r.enforceAgentSpendCap()
	}
	text, err := r.maybeOffload(ctx, res.Result, c.ID)
	if err != nil {
		return err
	}
	r.messages = append(r.messages, Message{Role: "tool", Content: text, ToolCallID: c.ID, Name: c.Name, Attachments: res.Images, Meta: meta})
	data := map[string]any{
		"tool_name": c.Name, "tool_call_id": c.ID, "success": true, "exit_code": exitCode, "artifact_paths": paths,
		"iteration": r.iteration, "result": domain.SanitizeToolEventValue(text, "result"),
		"arguments": domain.SanitizeToolEventValue(args, ""), "execution_time": execTime,
		"service_cost": res.ServiceCost.String(), "payment": paymentValue(res.Payments),
	}
	paid := map[string]any{}
	if res.Cost.Sign() > 0 {
		paid["cost"] = res.Cost.String()
	}
	if res.Payer != "" {
		paid["payer"] = res.Payer
	}
	if res.CostMetered {
		paid["cost_metered"] = true
	}
	extra := map[string]any{}
	switch {
	case res.StructuredContent != nil:
		extra["structured_content"] = res.StructuredContent
	case res.StructuredContentDropped:
		extra["structured_content_dropped"] = true
	}
	if res.MCPAppTool != "" {
		extra["mcp_app_tool"] = res.MCPAppTool
	}
	if len(res.Images) > 0 {
		extra["images"] = res.Images
	}
	mergeInto(data, priced, paid, replay, extra, server)
	r.emit(ctx, domain.EventToolResult, data)
	return r.publish(ctx)
}

// chargeTool adds what a call cost the run: its model and connector cost.
func (r *agentRun) chargeTool(res ToolCallResult) {
	if spent := res.ModelCost.Add(res.Cost); spent.Sign() > 0 {
		r.cost = r.cost.Add(spent)
		r.llmCostUsed = r.llmCostUsed.Add(res.ModelCost)
		r.enforceAgentSpendCap()
	}
}

func paymentValue(ps []Payment) any {
	if len(ps) == 0 {
		return nil
	}
	p := ps[len(ps)-1]
	return map[string]any{
		"protocol": p.Protocol, "amount": p.Amount.String(), "currency": p.Currency,
		"network": nullable(p.Network), "reference": nullable(p.Reference), "settled": p.Settled,
	}
}

func mergeInto(dst map[string]any, srcs ...map[string]any) {
	for _, s := range srcs {
		for k, v := range s {
			dst[k] = v
		}
	}
}

func (r *agentRun) offloads() bool { return r.cfg.ContextStrategy == "hybrid" || r.dynamic() }

// maybeOffload stores a large output and hands the model a summary instead.
func (r *agentRun) maybeOffload(ctx workflow.Context, content, outputID string) (string, error) {
	if !r.offloads() || len([]rune(content)) <= outputOffloadChars {
		return content, nil
	}
	req := StoreOutputRequest{Principal: r.principal, TaskID: r.taskID, OutputID: outputID, Content: content}
	var res ContextResult
	err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityStoreContextOutput, "", 0), api.ActivityStoreContextOutput, req).Get(ctx, &res)
	if err != nil {
		if isCancellation(err) || ctx.Err() != nil {
			return "", err
		}
		workflow.GetLogger(ctx).Warn("storing a large tool output failed; keeping it inline", "output_id", outputID, "error", err)
		return content, nil
	}
	if res.Success {
		return domain.OutputSummary(content, outputID), nil
	}
	return content, nil
}

func (r *agentRun) recallHistory(ctx workflow.Context, c ToolCall) error {
	args := parseArgs(c)
	grep, _ := args["grep"].(string)
	toolName, _ := args["tool_name"].(string)
	if (grep != "" || toolName != "") && r.offloads() && r.historyChunks > 0 {
		req := SearchHistoryRequest{Principal: r.principal, TaskID: r.taskID, Grep: grep, ToolName: toolName}
		var res ContextResult
		err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivitySearchHistory, "", 0), api.ActivitySearchHistory, req).Get(ctx, &res)
		switch {
		case err != nil && (isCancellation(err) || ctx.Err() != nil):
			return err
		case err != nil:
			workflow.GetLogger(ctx).Warn("history search failed, falling back to the task log", "error", err)
		case res.Success && res.Content != "":
			r.toolMessage(c, "[History search results]\n"+res.Content)
			return nil
		}
	}
	limit := 20
	if v, ok := args["limit"].(float64); ok {
		limit = int(v)
	}
	var types []string
	if list, ok := args["event_types"].([]any); ok {
		for _, t := range list {
			if s, isStr := t.(string); isStr {
				types = append(types, s)
			}
		}
	}
	query, _ := args["query"].(string)
	req := RecallHistoryRequest{Principal: r.principal, TaskID: r.taskID, Query: query, EventTypes: types, Limit: limit}
	var res RecallHistoryResult
	if err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityRecallHistory, "", 0), api.ActivityRecallHistory, req).Get(ctx, &res); err != nil {
		if isCancellation(err) || ctx.Err() != nil {
			return err
		}
		r.toolMessage(c, "Failed to recall history: "+failureText(err))
		return nil
	}
	if len(res.Events) == 0 {
		r.toolMessage(c, "No events found for this task.")
		return nil
	}
	parts := []string{res.Summary, ""}
	for _, e := range res.Events {
		data := truncateRunes(domain.PyDumps(e.Data), 500)
		parts = append(parts, fmt.Sprintf("[%s] %s: %s", e.Timestamp.Format("2006-01-02T15:04:05.999999-07:00"), e.Type, data))
	}
	r.toolMessage(c, strings.Join(parts, "\n"))
	return nil
}

func optionalInt(v any) *int {
	if f, ok := v.(float64); ok {
		return ptr(int(f))
	}
	return nil
}

func (r *agentRun) readToolOutput(ctx workflow.Context, c ToolCall) error {
	args := parseArgs(c)
	id, _ := args["output_id"].(string)
	if id == "" {
		r.toolMessage(c, "Error: output_id is required.")
		return nil
	}
	grep, _ := args["grep"].(string)
	req := ReadOutputRequest{Principal: r.principal, TaskID: r.taskID, FilesTaskID: r.sharedFilesTask(), OutputID: id, Grep: grep, Head: optionalInt(args["head"]), Tail: optionalInt(args["tail"])}
	var res ContextResult
	var content string
	err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityReadContextOutput, "", 0), api.ActivityReadContextOutput, req).Get(ctx, &res)
	switch {
	case err != nil && (isCancellation(err) || ctx.Err() != nil):
		return err
	case err != nil:
		content = fmt.Sprintf("Failed to read output '%s': %s", id, failureText(err))
	case res.Success:
		content = res.Content
	default:
		content = "Error reading output: " + res.Error
	}
	r.toolMessage(c, content)
	return nil
}

func (r *agentRun) activateToolSource(ctx workflow.Context, c ToolCall) error {
	source, _ := parseArgs(c)["source_name"].(string)
	if !r.dynamic() {
		r.toolMessage(c, "Error: tool catalog not available (not in dynamic mode).")
		return nil
	}
	var found []api.ToolDefinition
	for _, p := range r.cfg.ToolProviders {
		if p.Name == source {
			found = append(found, p.Tools...)
		}
	}
	added := domain.DisclosedTools(&r.cfg, found)
	text := fmt.Sprintf("Tool source '%s' not found or has no tools.", source)
	if len(added) > 0 {
		r.tools = append(r.tools, added...)
		if !slices.Contains(r.activatedSources, source) {
			r.activatedSources = append(r.activatedSources, source)
		}
		names := make([]string, 0, len(added))
		for _, t := range added {
			names = append(names, t.Name)
		}
		text = fmt.Sprintf("Activated '%s' with %d tools: %s", source, len(added), strings.Join(names, ", "))
	}
	r.toolMessage(c, text)
	r.emit(ctx, domain.EventToolResult, map[string]any{
		"tool_name": domain.ToolActivateToolSource, "tool_call_id": c.ID, "source_name": source, "tools_loaded": len(added), "iteration": r.iteration,
	})
	return nil
}

func (r *agentRun) loadTools(ctx workflow.Context, c ToolCall) error {
	var requested []string
	if list, ok := parseArgs(c)["tool_names"].([]any); ok {
		for _, n := range list {
			if s := fmt.Sprint(n); n != nil && s != "" {
				requested = append(requested, s)
			}
		}
	}
	if len(r.cfg.SearchableTools) == 0 {
		r.toolMessage(c, "Error: no searchable OpenAPI pool available.")
		return nil
	}
	res := domain.RevealTools(requested, r.cfg.SearchableTools)
	for _, name := range res.Matched {
		for _, cand := range r.cfg.SearchableTools {
			if cand.Name == name && !r.offered(name) {
				r.tools = append(r.tools, searchableDefinition(cand))
			}
		}
	}
	for _, name := range res.Matched {
		if !slices.Contains(r.revealedTools, name) {
			r.revealedTools = append(r.revealedTools, name)
		}
	}
	r.toolMessage(c, firstNonEmpty(res.Message, fmt.Sprintf("Loaded %d OpenAPI operations.", len(res.Matched))))
	r.emit(ctx, domain.EventToolResult, map[string]any{
		"tool_name": domain.ToolLoadTools, "tool_call_id": c.ID, "matched_names": orEmpty(res.Matched),
		"unknown_names": orEmpty(res.Unknown), "iteration": r.iteration,
	})
	return nil
}

func (r *agentRun) answerSkill(ctx workflow.Context, c ToolCall, name, text string, success bool) {
	r.toolMessage(c, text)
	data := map[string]any{"tool_name": domain.ToolActivateSkill, "tool_call_id": c.ID, "skill_name": name, "success": success, "iteration": r.iteration}
	if success {
		data["result"] = text
	} else {
		data["error"] = text
	}
	r.emit(ctx, domain.EventToolResult, data)
}

func (r *agentRun) skillRefusal(name string) string {
	if slices.Contains(r.activatedSkills, name) {
		return fmt.Sprintf("Skill '%s' is already active in this session.", name)
	}
	names := make([]string, 0, len(r.cfg.Skills))
	for _, s := range r.cfg.Skills {
		if s.Name == name {
			return ""
		}
		names = append(names, s.Name)
	}
	return fmt.Sprintf("Unknown skill '%s'. Available: %s", name, strings.Join(names, ", "))
}

// activateSkill hands the model a skill through its activity; the body never
// enters workflow history.
func (r *agentRun) activateSkill(ctx workflow.Context, c ToolCall) error {
	allowed, _, err := r.gate(ctx, c)
	if err != nil || !allowed {
		return err
	}
	name, _ := parseArgs(c)["skill_name"].(string)
	if len(r.cfg.Skills) == 0 {
		r.answerSkill(ctx, c, name, "No skills available.", true)
		return nil
	}
	if refusal := r.skillRefusal(name); refusal != "" {
		r.answerSkill(ctx, c, name, refusal, true)
		return nil
	}
	var skill api.Skill
	for _, s := range r.cfg.Skills {
		if s.Name == name {
			skill = s
			break
		}
	}
	share := r.cfg.SkillsWindowShare
	if share == 0 {
		share = legacySkillsWindowShare
	}
	left := int(float64(r.contextWindow)*share) - r.skillTokensUsed
	maxTokens := min(int(float64(r.contextWindow)*skillContextShare), left)
	if maxTokens < skillMinTokens {
		r.answerSkill(ctx, c, name, fmt.Sprintf("Skill '%s' was not loaded: the skills already active take the "+
			"%s of the context window this run's skills may use.", name, percent(share)), false)
		return nil
	}
	if err := r.publish(ctx); err != nil {
		return err
	}
	seq := r.nextSeq
	r.nextSeq++
	eventID := r.ids.uuid()
	req := ActivateSkillRequest{
		Principal: r.principal, TaskID: r.taskID, FilesTaskID: r.sharedFilesTask(), ExecutionID: r.executionID, ToolCallID: c.ID, Skill: skill,
		Seq: seq, EventID: eventID, Iteration: ptr(r.iteration), MaxTokens: maxTokens,
	}
	var res ActivateSkillResult
	if err := r.executeThroughOutage(ctx, api.ActivityActivateSkill, req, &res, fmt.Sprintf("activating skill '%s'", name), spec(api.ActivityActivateSkill).Heartbeat); err != nil {
		if isCancellation(err) || ctx.Err() != nil {
			return err
		}
		if _, ok := errors.AsType[*temporal.ActivityError](err); !ok {
			return err
		}
		text := causeText(err)
		if rerr := r.recordAt(ctx, seq, eventID, Message{Role: "tool", Content: "Tool failed: " + text, ToolCallID: c.ID, Name: domain.ToolActivateSkill}); rerr != nil {
			return rerr
		}
		r.emit(ctx, domain.EventToolResult, map[string]any{
			"tool_name": domain.ToolActivateSkill, "tool_call_id": c.ID, "skill_name": name, "success": false, "error": text, "iteration": r.iteration,
		})
		return nil
	}
	r.activatedSkills = append(r.activatedSkills, name)
	r.recordedTurnAnswered = append(r.recordedTurnAnswered, c.ID)
	r.skillTokensUsed += res.EstTokens
	r.lastPromptTokens += int64(res.EstTokens)
	for _, u := range res.URLs {
		if !slices.Contains(r.seenURLs, u) {
			r.seenURLs = append(r.seenURLs, u)
		}
	}
	if len(r.seenURLs) > seenURLsLimit {
		r.seenURLs = r.seenURLs[len(r.seenURLs)-seenURLsLimit:]
	}
	r.emit(ctx, domain.EventToolResult, map[string]any{
		"tool_name": domain.ToolActivateSkill, "tool_call_id": c.ID, "skill_name": name, "success": true,
		"result": fmt.Sprintf("Loaded skill '%s' (%d characters)", name, res.Chars), "summarized": res.Summarized, "iteration": r.iteration,
	})
	return nil
}

func percent(f float64) string { return fmt.Sprintf("%.0f%%", f*100) }

// recordAt writes one row at a position reserved earlier.
func (r *agentRun) recordAt(ctx workflow.Context, seq int64, eventID string, m Message) error {
	row := LogRow{
		Seq: seq, EventID: eventID, Kind: kindOf(m), Role: m.Role, Content: m.Content, ToolCallID: m.ToolCallID,
		Name: m.Name, Iteration: ptr(r.iteration),
	}
	req := RecordRequest{Principal: r.principal, TaskID: r.taskID, ExecutionID: r.executionID, Rows: []LogRow{row}}
	if err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityRecord, "", 0), api.ActivityRecord, req).Get(ctx, nil); err != nil {
		return err
	}
	r.recordedTurnAnswered = append(r.recordedTurnAnswered, m.ToolCallID)
	return nil
}

// hardCap is the last moment the run can still record its own end.
func (r *agentRun) hardCap(ctx workflow.Context) *time.Time {
	info := workflow.GetInfo(ctx)
	var ends []time.Time
	switch {
	case r.chainExpiresAt != nil:
		ends = append(ends, *r.chainExpiresAt)
	case info.WorkflowExecutionTimeout > 0:
		ends = append(ends, info.WorkflowStartTime.Add(info.WorkflowExecutionTimeout))
	}
	if info.WorkflowRunTimeout > 0 {
		ends = append(ends, info.WorkflowStartTime.Add(info.WorkflowRunTimeout))
	}
	if len(ends) == 0 {
		return nil
	}
	return ptr(slices.MinFunc(ends, func(a, b time.Time) int { return a.Compare(b) }).Add(-finalizeMargin))
}

func (r *agentRun) waitInterruption() string {
	if r.paused {
		return "pause"
	}
	if len(r.messageQueue) > 0 || len(r.a2uiQueue) > 0 {
		return "user_message"
	}
	return ""
}

func (r *agentRun) rejectWait(ctx workflow.Context, c ToolCall, reason string) error {
	r.toolMessage(c, domain.PyDumpsCompact(domain.Ordered{
		{Key: "status", Value: "invalid_wait_arguments"}, {Key: "error", Value: reason},
		{Key: "instruction", Value: fmt.Sprintf("Call wait again with an integer seconds of at least %d that ends before the run does, and a non-empty reason.", domain.WaitMinSeconds)},
	}))
	r.emit(ctx, domain.EventToolResult, map[string]any{"tool_name": domain.ToolWait, "tool_call_id": c.ID, "success": false, "error": reason, "iteration": r.iteration})
	return r.publish(ctx)
}

// wait idles on a durable timer; a message or a pause ends it early.
func (r *agentRun) wait(ctx workflow.Context, c ToolCall) error {
	var args any
	if err := json.Unmarshal([]byte(c.Arguments), &args); err != nil {
		return r.rejectWait(ctx, c, "arguments must be valid JSON: "+err.Error())
	}
	m, ok := args.(map[string]any)
	if !ok {
		return r.rejectWait(ctx, c, "arguments must be a JSON object")
	}
	f, isNum := m["seconds"].(float64)
	if !isNum || f != float64(int64(f)) || f < domain.WaitMinSeconds {
		return r.rejectWait(ctx, c, fmt.Sprintf("seconds must be an integer of at least %d", domain.WaitMinSeconds))
	}
	seconds := int64(f)
	now := workflow.Now(ctx)
	if hc := r.hardCap(ctx); hc != nil && now.Add(time.Duration(seconds)*time.Second).After(*hc) {
		remaining := max(int64(hc.Sub(now).Seconds()), 0)
		return r.rejectWait(ctx, c, fmt.Sprintf("this run ends in %d s, so it cannot wait %d s", remaining, seconds))
	}
	reason, _ := m["reason"].(string)
	reason = strings.TrimSpace(reason)
	if reason == "" {
		return r.rejectWait(ctx, c, "reason must be a non-empty string")
	}
	arguments := map[string]any{"seconds": seconds, "reason": reason}
	r.emit(ctx, domain.EventToolCall, map[string]any{"tool_name": domain.ToolWait, "tool_call_id": c.ID, "iteration": r.iteration, "arguments": arguments})
	if err := r.publish(ctx); err != nil {
		return err
	}
	_, err := workflow.AwaitWithTimeout(ctx, time.Duration(seconds)*time.Second, func() bool { return r.waitInterruption() != "" })
	if err != nil {
		r.emit(ctx, domain.EventToolResult, map[string]any{
			"tool_name": domain.ToolWait, "tool_call_id": c.ID, "success": false, "error": "The task was cancelled during the wait.", "iteration": r.iteration,
		})
		return err
	}
	woken := r.waitInterruption()
	waited := int64(workflow.Now(ctx).Sub(now).Seconds())
	content := fmt.Sprintf("Waited %d s for '%s'.", waited, reason)
	switch woken {
	case "user_message":
		content = fmt.Sprintf("Wait for '%s' ended after %d of %d s: a user message arrived. Read it before waiting again.", reason, waited, seconds)
	case "pause":
		content = fmt.Sprintf("Wait for '%s' ended after %d of %d s: the task was paused.", reason, waited, seconds)
	}
	r.toolMessage(c, content)
	r.emit(ctx, domain.EventToolResult, map[string]any{
		"tool_name": domain.ToolWait, "tool_call_id": c.ID, "success": true, "iteration": r.iteration, "arguments": arguments,
		"result": content, "execution_time": waited, "waited_seconds": waited, "woken_by": nullable(woken),
	})
	return r.publish(ctx)
}

// requestUserInput asks the user and waits for this request's validated answer.
func (r *agentRun) requestUserInput(ctx workflow.Context, c ToolCall) error {
	if !r.questionsAvailable() {
		r.deny(ctx, c, "Questions are unavailable on this route or denied by policy. Continue "+
			"autonomously using available context and tools without inventing facts. "+
			"Only if an actual prerequisite remains unmet, complete with outcome='blocked'.", false, false)
		return nil
	}
	var raw any
	if json.Unmarshal([]byte(c.Arguments), &raw) != nil {
		raw = map[string]any{}
	}
	args, ok := raw.(map[string]any)
	if !ok {
		r.deny(ctx, c, "arguments must be an object", false, false)
		return nil
	}
	if len(r.inputRequests) > 0 {
		r.deny(ctx, c, "A required input request is already pending.", false, false)
		return nil
	}
	questions := normalizeQuestions(args)
	question := strings.TrimSpace(pyStr(args["question"]))
	if question == "" {
		question, _ = questions[0]["question"].(string)
	}
	allowCustom := true
	if v, has := args["allow_custom_response"]; has {
		allowCustom = truthyAny(v)
	}
	surfaceRaw, hasSurface := args["surface_id"]
	surfaceID, _ := surfaceRaw.(string)
	if hasSurface && surfaceRaw != nil {
		_, isStr := surfaceRaw.(string)
		if !isStr || !r.a2uiAvailable() || len(r.a2uiSurfaces[surfaceID]) == 0 ||
			slices.ContainsFunc(questions, func(q map[string]any) bool { return q["type"] == "secret" }) {
			r.deny(ctx, c, "surface_id must identify an emitted A2UI surface with an action. "+
				"Secret questions must use the native input form without surface_id.", false, false)
			return nil
		}
	}
	id := r.ids.uuid()
	pending := &InputRequest{Questions: questions, SurfaceID: surfaceID, AllowCustomResponse: allowCustom}
	r.inputRequests[id] = pending
	r.inputOrder = append(r.inputOrder, id)
	r.status = StatusWaitingForInput
	if err := r.persistStatus(ctx, r.statusOnly("waiting_for_input")); err != nil {
		return err
	}
	mode, _ := questions[0]["type"].(string)
	if len(questions) > 1 {
		mode = "form"
	}
	data := map[string]any{
		"input_request_id": id, "tool_call_id": c.ID, "iteration": r.iteration, "question": question,
		"questions": questions, "allow_custom_response": allowCustom, "input_mode": mode,
	}
	if surfaceID != "" {
		data["surface_id"] = surfaceID
	}
	r.emit(ctx, domain.EventInputRequest, data)
	if err := r.publish(ctx); err != nil {
		return err
	}
	drop := func() {
		delete(r.inputRequests, id)
		r.inputOrder = slices.DeleteFunc(r.inputOrder, func(s string) bool { return s == id })
	}
	got, err := workflow.AwaitWithTimeout(ctx, inputRequestTimeout, func() bool { return pending.Resolved })
	if err != nil {
		drop()
		return err
	}
	if !got {
		r.toolMessage(c, "No user response was received before the input request timed out.")
		drop()
		r.success = false
		r.status = StatusBlocked
		r.failureReason = "input_timeout"
		r.blockedReason = "Required user input was not received within 30 minutes."
		r.errorMessage = r.blockedReason
		r.awaitingInput = false
		return nil
	}
	answers, _ := pending.Submission["answers"].(map[string]any)
	refs, _ := pending.Submission["secret_refs"].(map[string]any)
	if surfaceID != "" {
		delete(r.a2uiSurfaces, surfaceID)
	}
	resp := map[string]any{
		"input_request_id": id, "tool_call_id": c.ID, "answer_keys": sortedKeys(answers),
		"secret_keys": sortedKeys(refs), "iteration": r.iteration,
	}
	if surfaceID != "" {
		resp["surface_id"] = surfaceID
	}
	r.emit(ctx, domain.EventInputResponse, resp)
	if err := r.publish(ctx); err != nil {
		return err
	}
	r.status = StatusExecuting
	if err := r.persistStatus(ctx, r.statusOnly("running")); err != nil {
		return err
	}
	if answers == nil {
		answers = map[string]any{}
	}
	if refs == nil {
		refs = map[string]any{}
	}
	r.toolMessage(c, domain.PyDumps(domain.Ordered{{Key: "input_request_id", Value: id}, {Key: "answers", Value: answers}, {Key: "secret_refs", Value: refs}}))
	drop()
	return nil
}

func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return ""
	case float64:
		if x == 0 {
			return ""
		}
		if x == float64(int64(x)) {
			return fmt.Sprint(int64(x))
		}
	}
	return fmt.Sprint(v)
}

func questionType(t string) bool {
	switch t {
	case "text", "textarea", "select", "multiselect", "boolean", "number", "secret":
		return true
	}
	return false
}

// normalizeQuestions turns the simple question/options form and rich
// questions[] into form fields.
func normalizeQuestions(args map[string]any) []map[string]any {
	if raw, ok := args["questions"].([]any); ok && len(raw) > 0 {
		var out []map[string]any
		for i, item := range raw {
			q, isMap := item.(map[string]any)
			if !isMap {
				continue
			}
			id := strings.TrimSpace(firstNonEmpty(pyStr(q["id"]), fmt.Sprintf("field_%d", i+1)))
			label := strings.TrimSpace(firstNonEmpty(pyStr(q["question"]), pyStr(q["label"]), id))
			typ := strings.ToLower(strings.TrimSpace(firstNonEmpty(pyStr(q["type"]), "text")))
			if !questionType(typ) {
				typ = "text"
			}
			required := true
			if v, has := q["required"]; has {
				required = truthyAny(v)
			}
			field := map[string]any{"id": id, "question": label, "type": typ, "required": required}
			if opts := optionStrings(q["options"]); len(opts) > 0 {
				field["options"] = opts
			}
			if typ == "secret" && truthyAny(q["secret_name"]) {
				field["secret_name"] = pyStr(q["secret_name"])
			}
			out = append(out, field)
		}
		if len(out) > 0 {
			return out
		}
	}
	question := strings.TrimSpace(pyStr(args["question"]))
	if question == "" {
		question = "Please provide the missing information so I can continue."
	}
	field := map[string]any{"id": "answer", "question": question, "type": "text", "required": true}
	if opts := optionStrings(args["options"]); len(opts) > 0 {
		field["type"] = "select"
		field["options"] = opts
	}
	return []map[string]any{field}
}

func optionStrings(v any) []any {
	list, _ := v.([]any)
	var out []any
	for _, o := range list {
		s := fmt.Sprint(o)
		if o == nil {
			s = "None"
		}
		if strings.TrimSpace(s) != "" {
			out = append(out, s)
		}
	}
	return out
}
