package workflows

import (
	"encoding/json"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// continueAsNew compacts if needed and restarts the run with fresh history,
// carrying its state.
func (r *agentRun) continueAsNew(ctx workflow.Context, _ string) error {
	if r.contextWindow > 0 {
		raw, _ := json.Marshal(r.pendingPayload())
		oversized := len(raw) > contextMaxPayload
		if oversized || r.needsCompaction() {
			if _, err := r.compact(ctx, oversized); err != nil {
				return err
			}
		}
	}
	if r.goal == nil {
		return nonRetryable("workflow goal is missing from execution state", ErrInvalidExecutionSnapshot)
	}
	runID := workflow.GetInfo(ctx).WorkflowExecution.RunID
	r.emit(ctx, domain.EventExecutionContinuedAsNew, map[string]any{
		"iteration": r.iteration, "total_cost": r.cost.String(), "conversation_entries": r.nextSeq + int64(len(r.messages)),
		"continued_from_run_id": runID, "reason": "Temporal event history size limit approaching",
	})
	if err := r.publish(ctx); err != nil {
		return err
	}
	if err := workflow.Await(ctx, func() bool { return workflow.AllHandlersFinished(ctx) }); err != nil {
		return err
	}
	state := r.continuedState(runID)
	req := AgentRunRequest{
		TaskID: r.taskID, AgentID: r.principal.AgentID, UserID: r.principal.UserID, WorkspaceID: r.principal.WorkspaceID,
		TaskQuery: r.goal.Description, Continued: &state,
	}
	return workflow.NewContinueAsNewError(ctx, api.WorkflowAgentExecution, req)
}

func (r *agentRun) continuedState(runID string) ContinuedState {
	return ContinuedState{
		ExecutionID: r.executionID, Goal: *r.goal, Config: r.cfg, Messages: r.pendingPayload(), NextSeq: r.nextSeq,
		LastPromptTokens: r.lastPromptTokens, SeenURLs: r.seenURLs, TruncatedReply: r.truncatedReply, Tools: r.tools,
		Iteration: r.iteration, ToolCallsUsed: r.toolCallsUsed, TotalCost: r.cost, DelegatedCost: r.delegatedCost,
		TokensUsed: r.tokensUsed, Budget: r.budgetLimit, ContinuedFromRunID: runID, ActivatedSkills: r.activatedSkills,
		SkillTokensUsed: r.skillTokensUsed, ChainExpiresAt: r.chainExpiresAt, RunStartedAt: r.runStartedAt,
		HistoryChunkCounter: r.historyChunks, ActivatedSources: r.activatedSources, RevealedTools: r.revealedTools,
		ServiceCostUsed: r.serviceCostUsed, LLMCostUsed: r.llmCostUsed, MessageQueue: r.messageQueue,
		Escalations: r.escalations, InputRequests: r.inputRequests, A2UIQueue: r.a2uiQueue, Interaction: r.interaction,
		A2UISurfaces: r.a2uiSurfaces, AwaitingInput: r.awaitingInput, Paused: r.paused, PauseReason: r.pauseReason,
		WorkflowMetadata: r.metadata, CompletionPublished: r.completionPublished, WaitingContinuation: r.waitingContinuation,
		ContinuationReason: r.continuationReason, ContinuationMessage: r.continuationMessage,
		ContinuationCount: r.continuationCount, Status: r.status, Success: r.success, FinalResponse: r.finalResponse,
		FailureReason: r.failureReason, ErrorMessage: r.errorMessage, BlockedReason: r.blockedReason,
		ValidationState: r.validationState, ValidationRepairs: r.validationRepairs, ValidationTerminal: r.validationTerminal,
		PendingEvents: r.pending, BudgetWarningSent: r.budgetWarningSent, Currency: r.currency,
		ContextWarningSent: r.contextWarningSent, CompactionCount: r.compactionCount, ConversationSeeded: true,
		MonthlyCapMessage: r.monthlyCapMessage, RecordedTurnCalls: r.recordedTurnCalls, RecordedTurnAnswered: r.recordedTurnAnswered,
		ModelOverride: r.modelOverride,
	}
}
