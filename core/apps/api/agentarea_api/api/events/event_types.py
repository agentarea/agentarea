from enum import Enum


class EventType(Enum):
    TASK_CREATED = "TaskCreated"
    TASK_UPDATED = "TaskUpdated"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    TASK_STATUS_CHANGED = "TaskStatusChanged"
    TASK_ASSIGNED = "TaskAssigned"
    TASK_CANCELED = "TaskCanceled"
    TASK_INPUT_REQUIRED = "TaskInputRequired"
    TASK_ARTIFACT_ADDED = "TaskArtifactAdded"

    # Workflow execution events
    WORKFLOW_STARTED = "WorkflowStarted"
    WORKFLOW_STEP_STARTED = "WorkflowStepStarted"
    WORKFLOW_STEP_COMPLETED = "WorkflowStepCompleted"
    WORKFLOW_LLM_CALL_STARTED = "WorkflowLLMCallStarted"
    WORKFLOW_LLM_CALL_COMPLETED = "WorkflowLLMCallCompleted"
    WORKFLOW_TOOL_CALL_STARTED = "WorkflowToolCallStarted"
    WORKFLOW_TOOL_CALL_COMPLETED = "WorkflowToolCallCompleted"
    WORKFLOW_APPROVAL_REQUESTED = "WorkflowApprovalRequested"
    WORKFLOW_BUDGET_WARNING = "WorkflowBudgetWarning"
    WORKFLOW_BUDGET_EXCEEDED = "WorkflowBudgetExceeded"
    WORKFLOW_PAUSED = "WorkflowPaused"
    WORKFLOW_RESUMED = "WorkflowResumed"
    WORKFLOW_COMPLETED = "WorkflowCompleted"
    WORKFLOW_FAILED = "WorkflowFailed"
    WORKFLOW_PROGRESS_UPDATED = "WorkflowProgressUpdated"
    WORKFLOW_ERROR = "WorkflowError"

    # Agent-to-agent communication events
    A2A_MESSAGE_SENT = "A2AMessageSent"
    A2A_MESSAGE_RECEIVED = "A2AMessageReceived"
    A2A_COMMUNICATION_STARTED = "A2ACommunicationStarted"
