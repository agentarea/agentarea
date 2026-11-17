package domain

// Task event types, the closed vocabulary of agentarea_common.events.contract
// (VOCABULARY_VERSION 5). Clients read them over SSE; the names are a contract.
const (
	EventLLMStarted                = "llm.call.started"
	EventLLMCompleted              = "llm.call.completed"
	EventLLMFailed                 = "llm.call.failed"
	EventLLMChunk                  = "llm.call.chunk"
	EventToolCall                  = "tool.call"
	EventToolResult                = "tool.result"
	EventToolProgress              = "tool.progress"
	EventInputRequest              = "input.request"
	EventInputResponse             = "input.response"
	EventApprovalRequested         = "approval.requested"
	EventApprovalDecided           = "approval.decided"
	EventArtifactCreated           = "artifact.created"
	EventArtifactUpdated           = "artifact.updated"
	EventA2UICreate                = "a2ui.create"
	EventA2UIUpdateComponents      = "a2ui.update.components"
	EventA2UIUpdateData            = "a2ui.update.data"
	EventA2UIDelete                = "a2ui.delete"
	EventTaskStarted               = "task.started"
	EventTaskCompleted             = "task.completed"
	EventTaskFailed                = "task.failed"
	EventTaskCancelled             = "task.cancelled"
	EventTaskAwaitingFollowUp      = "task.awaiting_follow_up"
	EventTaskAwaitingContinuation  = "task.awaiting_continuation"
	EventTaskContinued             = "task.continued"
	EventTaskAwaitingInfra         = "task.awaiting_infrastructure"
	EventTaskInfraRecovered        = "task.infrastructure_recovered"
	EventSkillWithheld             = "skill.withheld"
	EventTaskRetried               = "task.retried"
	EventExecutionFinished         = "execution.finished"
	EventExecutionContinuedAsNew   = "execution.continued_as_new"
	EventExecutionPaused           = "execution.paused"
	EventExecutionResumed          = "execution.resumed"
	EventArtifactValidationStarted = "artifact.validation.started"
	EventArtifactValidationDone    = "artifact.validation.completed"
	EventTurnStarted               = "turn.started"
	EventTurnCompleted             = "turn.completed"
	EventTurnAborted               = "turn.aborted"
	EventBudgetWarning             = "budget.warning"
	EventBudgetExceeded            = "budget.exceeded"
	EventBudgetUpdated             = "budget.updated"
	EventServicePayment            = "service.payment"
	EventServiceBudgetWarning      = "service.budget_warning"
	EventServiceBudgetExceeded     = "service.budget_exceeded"
	EventContextCompacted          = "context.compacted"
	EventContextWarning            = "context.warning"
	EventAnswerChecked             = "answer.checked"
	EventModelChanged              = "model.changed"
	EventModelFallback             = "model.fallback"
	EventModelUnavailable          = "model.unavailable"
	EventRuntimeDiscovered         = "runtime.discovered"
	EventCommandReceived           = "command.received"
	EventCommandRejected           = "command.rejected"
	EventMessageQueued             = "message.queued"
	EventMessageReceived           = "message.received"
	EventMessageRemoved            = "message.removed"
	EventInputSubmitted            = "input.submitted"
	EventDelegationStarted         = "delegation.started"
	EventDelegationCompleted       = "delegation.completed"
	EventDelegationFailed          = "delegation.failed"
)

// KnownEventType reports whether t is in the closed vocabulary (require_known_type).
func KnownEventType(t string) bool {
	switch t {
	case EventLLMStarted, EventLLMCompleted, EventLLMFailed, EventLLMChunk, EventToolCall, EventToolResult,
		EventToolProgress, EventInputRequest, EventInputResponse, EventApprovalRequested, EventApprovalDecided,
		EventArtifactCreated, EventArtifactUpdated, EventA2UICreate, EventA2UIUpdateComponents, EventA2UIUpdateData,
		EventA2UIDelete, EventTaskStarted, EventTaskCompleted, EventTaskFailed, EventTaskCancelled,
		EventTaskAwaitingFollowUp, EventTaskAwaitingContinuation, EventTaskContinued, EventTaskAwaitingInfra,
		EventTaskInfraRecovered, EventSkillWithheld, EventTaskRetried, EventExecutionFinished,
		EventExecutionContinuedAsNew, EventExecutionPaused, EventExecutionResumed, EventArtifactValidationStarted,
		EventArtifactValidationDone, EventTurnStarted, EventTurnCompleted, EventTurnAborted, EventBudgetWarning,
		EventBudgetExceeded, EventBudgetUpdated, EventServicePayment, EventServiceBudgetWarning,
		EventServiceBudgetExceeded, EventContextCompacted, EventContextWarning, EventAnswerChecked,
		EventModelChanged, EventModelFallback, EventModelUnavailable, EventRuntimeDiscovered,
		EventCommandReceived, EventCommandRejected, EventMessageQueued, EventMessageReceived,
		EventMessageRemoved, EventInputSubmitted, EventDelegationStarted, EventDelegationCompleted,
		EventDelegationFailed:
		return true
	}
	return false
}

// LiveOnly reports the signals that matter only while the run is live:
// broadcast, never stored (LIVE_ONLY_TYPES).
func LiveOnly(t string) bool {
	return t == EventLLMStarted || t == EventLLMChunk || t == EventToolProgress
}

// Terminal task events carry a user-facing message (ensure_terminal_message).
func Terminal(t string) bool {
	return t == EventTaskCompleted || t == EventTaskFailed || t == EventTaskCancelled
}
