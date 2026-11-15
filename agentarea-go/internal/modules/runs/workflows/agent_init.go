package workflows

import (
	"maps"
	"slices"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

func (r *agentRun) initialize(ctx workflow.Context, req AgentRunRequest) error {
	if req.Continued != nil {
		return r.restore(ctx, req, req.Continued)
	}
	info := workflow.GetInfo(ctx)
	started := info.WorkflowStartTime.UTC()
	r.runStartedAt = &started
	if info.WorkflowExecutionTimeout > 0 {
		r.chainExpiresAt = ptr(started.Add(info.WorkflowExecutionTimeout))
	}
	r.executionID = info.WorkflowExecution.ID
	r.taskID = req.TaskID
	r.principal = Principal{WorkspaceID: req.WorkspaceID, UserID: req.UserID, AgentID: req.AgentID}
	r.cfg.Policy = req.Policy
	r.cfg.Governance = req.Governance
	maxTurns, ok := intLimit(policyExec(req.Policy).MaxModelTurns)
	if !ok {
		return nonRetryable("effective policy is missing required runtime limit execution.max_model_turns", ErrInvalidExecutionSnapshot)
	}
	params := req.TaskParameters
	if params == nil {
		params = map[string]any{}
	}
	var criteria []string
	if list, isList := params["success_criteria"].([]any); isList {
		for _, c := range list {
			if s, isStr := c.(string); isStr {
				criteria = append(criteria, s)
			}
		}
	}
	r.goal = &Goal{ID: req.TaskID, Description: req.TaskQuery, SuccessCriteria: criteria, MaxIterations: maxTurns,
		RequiresHumanApproval: req.RequiresHumanApproval, Context: params}
	r.status = StatusInitializing
	budget, err := resolveBudget(req.Budget, req.Policy)
	if err != nil {
		return err
	}
	r.budgetLimit = budget
	r.metadata = maps.Clone(req.WorkflowMetadata)
	if r.metadata == nil {
		r.metadata = map[string]any{}
	}
	r.adoptRunner()
	r.emit(ctx, domain.EventTaskStarted, map[string]any{
		"goal_description": r.goal.Description, "max_iterations": r.goal.MaxIterations, "budget_limit": r.budgetLimit.String(),
	})
	if req.Resume != nil {
		r.adoptResume(ctx, req.Resume)
	}
	if err := r.publish(ctx); err != nil {
		return err
	}
	if req.Resume == nil && (truthyAny(r.metadata["scheduled_at"]) || r.isDelegationChild()) {
		if err := r.persistStatus(ctx, r.statusOnly("running")); err != nil {
			return err
		}
	}
	if r.runner.on {
		return nil
	}
	return r.configure(ctx, req.Selections)
}

func truthyAny(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case bool:
		return x
	}
	return true
}

func resolveBudget(request *money.Decimal, p api.Policy) (money.Decimal, error) {
	var candidates []money.Decimal
	if request != nil {
		candidates = append(candidates, *request)
	}
	if p.Budget != nil && p.Budget.RunBudget != nil {
		candidates = append(candidates, *p.Budget.RunBudget)
	}
	if len(candidates) == 0 {
		return money.Zero(), nonRetryable("effective policy is missing required runtime limit budget.run_budget_usd", ErrInvalidExecutionSnapshot)
	}
	b := candidates[0]
	for _, c := range candidates[1:] {
		b = minDec(b, c)
	}
	if b.Sign() <= 0 {
		return money.Zero(), nonRetryable("budget_usd must be greater than zero", ErrInvalidExecutionSnapshot)
	}
	return b, nil
}

func (r *agentRun) adoptResume(ctx workflow.Context, resume *RunResume) {
	s := resume.Snapshot
	r.nextSeq = s.NextSeq
	r.iteration = s.CurrentIteration
	r.toolCallsUsed = s.ToolCallsUsed
	r.tokensUsed = s.TokensUsed
	r.lastPromptTokens = s.LastPromptTokens
	r.cost = r.cost.Add(resume.TotalCost)
	r.llmCostUsed = resume.LLMCost
	if resume.OwnCost != nil {
		r.delegatedCost = maxDec(resume.TotalCost.Sub(*resume.OwnCost), money.Zero())
	}
	r.resumePromptMissing = resume.SystemPromptMissing
	if resume.Retry && r.runner.on && r.goal != nil {
		msg := runnerRetryMessage
		if s.CurrentIteration <= 1 {
			msg = r.goal.Description
		}
		r.runner.retryMessage = &msg
	}
	if resume.Retry {
		r.emit(ctx, domain.EventTaskRetried, map[string]any{"iteration": s.CurrentIteration + 1})
	}
}

// configure resolves the run's configuration once and builds the tool list.
func (r *agentRun) configure(ctx workflow.Context, selections RunSelections) error {
	req := ResolveRunConfigRequest{Principal: r.principal, TaskID: r.taskID, Selections: selections, Policy: r.cfg.Policy, Governance: r.cfg.Governance}
	var cfg api.RunConfig
	if err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityResolveRunConfig, "", 0), api.ActivityResolveRunConfig, req).Get(ctx, &cfg); err != nil {
		return err
	}
	cfg.Policy, cfg.Governance = r.cfg.Policy, r.cfg.Governance
	r.cfg = cfg
	r.configured = true
	for _, w := range cfg.WithheldSkills {
		r.emit(ctx, domain.EventSkillWithheld, map[string]any{"skill_id": w.ID, "skill_name": w.Name, "reason": w.Reason})
	}
	var params map[string]any
	if r.goal != nil {
		params = r.goal.Context
	}
	r.interaction = domain.ResolveInteraction(params, r.metadata, cfg.Agent.A2UIEnabled)
	r.emit(ctx, domain.EventRuntimeDiscovered, runtimeEventData(&cfg))
	if err := r.publish(ctx); err != nil {
		return err
	}
	if cfg.Model.ContextWindow <= 0 {
		return nonRetryable("agent configuration has no valid ModelSpec context_window", ErrInvalidExecutionSnapshot)
	}
	r.contextWindow = cfg.Model.ContextWindow
	tools, err := r.buildTools()
	if err != nil {
		return err
	}
	r.tools = tools
	return nil
}

func runtimeEventData(cfg *api.RunConfig) map[string]any {
	if cfg.Runtime == nil {
		if cfg.RuntimeError != "" {
			return map[string]any{"error": cfg.RuntimeError}
		}
		return map[string]any{}
	}
	m := cfg.Runtime
	return map[string]any{
		"schema_version": m.SchemaVersion, "image_version": m.ImageVersion, "managed_environment": m.ManagedEnvironment,
		"python_version": m.PythonVersion, "node_version": m.NodeVersion, "tools": m.Tools, "packages": m.Packages,
		"browser": m.Browser, "environment_mutable": m.EnvironmentMutable, "arbitrary_code": m.ArbitraryCode,
	}
}

func (r *agentRun) dynamic() bool { return r.cfg.ContextStrategy == "dynamic" }

// buildTools is the model-facing tool list: built-ins first, then the agent's, then disclosure.
func (r *agentRun) buildTools() ([]api.ToolDefinition, error) {
	var tools []api.ToolDefinition
	if r.dynamic() {
		for _, p := range r.cfg.ToolProviders {
			if p.ProviderType == "builtin" || slices.Contains(r.activatedSources, p.Name) {
				tools = append(tools, p.Tools...)
			}
		}
		tools = append(tools, domain.ActivateToolSourceTool(r.cfg.ToolProviders, r.activatedSources))
	} else {
		tools = append(tools, r.cfg.Tools...)
		if len(r.cfg.SearchableTools) > 0 {
			tools = append(tools, domain.LoadToolsTool())
		}
	}
	tools = slices.DeleteFunc(tools, func(t api.ToolDefinition) bool {
		return t.Name == domain.ToolCompletion || t.Name == domain.ToolTaskComplete
	})
	tools = append([]api.ToolDefinition{domain.CompletionTool(), domain.RequestUserInputTool()}, tools...)
	if !r.questionsAvailable() {
		tools = slices.DeleteFunc(tools, func(t api.ToolDefinition) bool { return t.Name == domain.ToolRequestUserInput })
	}
	tools = append(tools, domain.RecallHistoryTool(), domain.ReadToolOutputTool())
	for _, t := range tools {
		if t.Name == domain.ToolWait {
			return nil, nonRetryable("tool name 'wait' is reserved for the workflow's built-in wait; rename the agent tool that uses it", ErrReservedToolName)
		}
	}
	tools = append(tools, domain.WaitTool())
	if len(r.cfg.Skills) > 0 {
		tools = append(tools, domain.ActivateSkillTool(r.cfg.Skills))
	}
	for _, name := range r.revealedTools {
		for _, c := range r.cfg.SearchableTools {
			if c.Name == name {
				tools = append(tools, searchableDefinition(c))
			}
		}
	}
	return domain.DisclosedTools(&r.cfg, tools), nil
}

func searchableDefinition(c api.SearchableTool) api.ToolDefinition {
	def := api.ToolDefinition{Name: c.Name, Description: c.Description, Parameters: c.Schema}
	if fn, ok := c.Schema["function"].(map[string]any); ok {
		def.Description, _ = fn["description"].(string)
		def.Parameters, _ = fn["parameters"].(map[string]any)
	}
	return def
}

// restore continues a run from the state its previous run carried over.
func (r *agentRun) restore(ctx workflow.Context, req AgentRunRequest, s *ContinuedState) error {
	r.executionID = s.ExecutionID
	r.taskID = req.TaskID
	r.principal = Principal{WorkspaceID: req.WorkspaceID, UserID: req.UserID, AgentID: req.AgentID}
	goal := s.Goal
	r.goal = &goal
	r.cfg = s.Config
	r.configured = true
	r.messages = s.Messages
	r.nextSeq = s.NextSeq
	r.lastPromptTokens = s.LastPromptTokens
	r.seenURLs = s.SeenURLs
	r.truncatedReply = s.TruncatedReply
	r.tools = s.Tools
	r.iteration = s.Iteration
	r.toolCallsUsed = s.ToolCallsUsed
	r.cost = s.TotalCost
	r.delegatedCost = s.DelegatedCost
	r.tokensUsed = s.TokensUsed
	r.budgetLimit = s.Budget
	r.continuedFromRunID = s.ContinuedFromRunID
	r.activatedSkills = s.ActivatedSkills
	r.skillTokensUsed = s.SkillTokensUsed
	r.chainExpiresAt = s.ChainExpiresAt
	r.runStartedAt = s.RunStartedAt
	r.historyChunks = s.HistoryChunkCounter
	r.activatedSources = s.ActivatedSources
	r.revealedTools = s.RevealedTools
	r.serviceCostUsed = s.ServiceCostUsed
	r.llmCostUsed = s.LLMCostUsed
	r.messageQueue = s.MessageQueue
	if s.Escalations != nil {
		r.escalations = s.Escalations
		r.escalationOrder = sortedKeys(s.Escalations)
	}
	if s.InputRequests != nil {
		r.inputRequests = s.InputRequests
		r.inputOrder = sortedKeys(s.InputRequests)
	}
	r.a2uiQueue = s.A2UIQueue
	r.interaction = s.Interaction
	if s.A2UISurfaces != nil {
		r.a2uiSurfaces = s.A2UISurfaces
	}
	r.awaitingInput = s.AwaitingInput
	r.paused = s.Paused
	r.pauseReason = s.PauseReason
	r.metadata = s.WorkflowMetadata
	if r.metadata == nil {
		r.metadata = map[string]any{}
	}
	r.completionPublished = s.CompletionPublished
	r.waitingContinuation = s.WaitingContinuation
	r.continuationReason = s.ContinuationReason
	r.continuationMessage = s.ContinuationMessage
	r.continuationCount = s.ContinuationCount
	r.status = s.Status
	r.success = s.Success
	r.finalResponse = s.FinalResponse
	r.failureReason = s.FailureReason
	r.errorMessage = s.ErrorMessage
	r.blockedReason = s.BlockedReason
	r.validationState = s.ValidationState
	r.validationRepairs = s.ValidationRepairs
	r.validationTerminal = s.ValidationTerminal
	r.pending = s.PendingEvents
	r.budgetWarningSent = s.BudgetWarningSent
	r.currency = s.Currency
	r.contextWarningSent = s.ContextWarningSent
	r.compactionCount = s.CompactionCount
	r.conversationSeeded = true
	r.monthlyCapMessage = s.MonthlyCapMessage
	r.recordedTurnCalls = s.RecordedTurnCalls
	r.recordedTurnAnswered = s.RecordedTurnAnswered
	r.adoptRunner()
	r.contextWindow = r.cfg.Model.ContextWindow
	if r.contextWindow <= 0 && !r.runner.on {
		return nonRetryable("continued state has no ModelSpec context_window", ErrInvalidExecutionSnapshot)
	}
	return r.publish(ctx)
}
