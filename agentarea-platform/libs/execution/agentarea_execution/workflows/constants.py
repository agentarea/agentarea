"""Constants and configuration for agent execution workflows."""

from datetime import timedelta
from typing import Final

# Execution limits
MAX_ITERATIONS: Final[int] = 50
MAX_TOOL_CALLS_PER_ITERATION: Final[int] = 10
DEFAULT_BUDGET_USD: Final[float] = 10.0
BUDGET_WARNING_THRESHOLD: Final[float] = 0.8  # 80% of budget

# Timeout configurations
ACTIVITY_TIMEOUT: Final[timedelta] = timedelta(minutes=5)
LLM_CALL_TIMEOUT: Final[timedelta] = timedelta(minutes=10)
TOOL_EXECUTION_TIMEOUT: Final[timedelta] = timedelta(minutes=35)
EVENT_PUBLISH_TIMEOUT: Final[timedelta] = timedelta(seconds=5)

# Heartbeat configuration
HEARTBEAT_TIMEOUT: Final[timedelta] = timedelta(seconds=30)

# Agent delegation
DELEGATION_TIMEOUT: Final[timedelta] = timedelta(minutes=10)  # Max time for child agent

# Retry policies
DEFAULT_RETRY_ATTEMPTS: Final[int] = 3
EVENT_PUBLISH_RETRY_ATTEMPTS: Final[int] = 1
LLM_RETRY_ATTEMPTS: Final[int] = 1


# Context window management
CONTEXT_COMPACT_THRESHOLD: Final[float] = 0.75  # Compact at 75% of context window
CONTEXT_WARNING_THRESHOLD: Final[float] = 0.60  # Warn at 60%
CONTEXT_RESERVE_FOR_OUTPUT: Final[float] = 0.15  # Reserve 15% for model output
MIN_RECENT_MESSAGES_TO_KEEP: Final[int] = 6  # Always keep last 6 messages (3 turns)
TOKENS_PER_MESSAGE_OVERHEAD: Final[int] = 4  # ~4 tokens overhead per message
DEFAULT_CONTEXT_WINDOW: Final[int] = 128000  # Fallback if not set on model

# Dynamic context discovery — output offloading
TOOL_OUTPUT_OFFLOAD_CHARS: Final[int] = 8000  # ~2000 tokens
OUTPUT_SUMMARY_HEAD_CHARS: Final[int] = 500
OUTPUT_SUMMARY_TAIL_CHARS: Final[int] = 200
READ_OUTPUT_MAX_RETURN_CHARS: Final[int] = 16000  # Safety limit for read_tool_output
HISTORY_SEARCH_MAX_RESULTS: Final[int] = 20


# Event types
class EventTypes:
    """Workflow event type constants.

    Semantic part-taxonomy events hold the canonical dotted names directly (the
    wire vocabulary — see agentarea_common.events.contract). Timeline/system
    events that are NOT part of that taxonomy keep their bare names.
    """

    # Task lifecycle (canonical dotted).
    WORKFLOW_STARTED: Final[str] = "task.started"
    WORKFLOW_COMPLETED: Final[str] = "task.completed"
    WORKFLOW_FAILED: Final[str] = "task.failed"
    WORKFLOW_CANCELLED: Final[str] = "task.cancelled"

    # Timeline/system — not in the part taxonomy, kept bare.
    ITERATION_STARTED: Final[str] = "IterationStarted"
    ITERATION_COMPLETED: Final[str] = "IterationCompleted"

    # LLM part (canonical dotted).
    LLM_CALL_STARTED: Final[str] = "llm.call.started"
    LLM_CALL_CHUNK: Final[str] = "llm.call.chunk"
    LLM_CALL_COMPLETED: Final[str] = "llm.call.completed"
    LLM_CALL_FAILED: Final[str] = "llm.call.failed"

    # Tool part (canonical dotted). Failed is a tool.result whose data carries
    # ``error`` (no ``success``); the constant names stay distinct so callers can
    # branch pre-emit, even though both collapse to the same wire type.
    TOOL_CALL_STARTED: Final[str] = "tool.call"
    TOOL_CALL_COMPLETED: Final[str] = "tool.result"
    TOOL_CALL_FAILED: Final[str] = "tool.result"

    # Timeline/system — not in the part taxonomy, kept bare.
    BUDGET_WARNING: Final[str] = "BudgetWarning"
    BUDGET_EXCEEDED: Final[str] = "BudgetExceeded"

    SERVICE_PAYMENT: Final[str] = "ServicePayment"
    SERVICE_BUDGET_WARNING: Final[str] = "ServiceBudgetWarning"
    SERVICE_BUDGET_EXCEEDED: Final[str] = "ServiceBudgetExceeded"

    CONTEXT_COMPACTED: Final[str] = "ContextCompacted"
    CONTEXT_WARNING: Final[str] = "ContextWarning"

    WORKFLOW_CONTINUED_AS_NEW: Final[str] = "WorkflowContinuedAsNew"

    AGENT_DELEGATION_STARTED: Final[str] = "AgentDelegationStarted"
    AGENT_DELEGATION_COMPLETED: Final[str] = "AgentDelegationCompleted"
    AGENT_DELEGATION_FAILED: Final[str] = "AgentDelegationFailed"

    # Human-in-the-loop parts (canonical dotted). Approval received/denied both
    # map to ``approval.response`` (the decision lives in the data payload).
    HUMAN_APPROVAL_REQUESTED: Final[str] = "approval.request"
    HUMAN_APPROVAL_RECEIVED: Final[str] = "approval.response"
    HUMAN_APPROVAL_DENIED: Final[str] = "approval.response"
    HUMAN_INPUT_REQUESTED: Final[str] = "input.request"
    HUMAN_INPUT_RECEIVED: Final[str] = "input.response"

    # Timeline/system — not in the part taxonomy, kept bare.
    MODEL_CHANGED: Final[str] = "ModelChanged"
    MODEL_RESOLUTION_FALLBACK: Final[str] = "ModelResolutionFallback"
    MODEL_UNAVAILABLE: Final[str] = "ModelUnavailable"
    WORKFLOW_COMMAND_RECEIVED: Final[str] = "WorkflowCommandReceived"


# Activity names
class Activities:
    """Activity function references to avoid hardcoded strings."""

    BUILD_AGENT_CONFIG: Final[str] = "build_agent_config_activity"
    DISCOVER_AVAILABLE_TOOLS: Final[str] = "discover_available_tools_activity"
    EXECUTE_ADK_AGENT_WITH_TEMPORAL_BACKBONE: Final[str] = (
        "execute_adk_agent_with_temporal_backbone"
    )
    CALL_LLM: Final[str] = "call_llm_activity"
    EXECUTE_MCP_TOOL: Final[str] = "execute_mcp_tool_activity"
    CREATE_EXECUTION_PLAN: Final[str] = "create_execution_plan_activity"
    EVALUATE_GOAL_PROGRESS: Final[str] = "evaluate_goal_progress_activity"
    PUBLISH_WORKFLOW_EVENTS: Final[str] = "publish_workflow_events_activity"
    COMPACT_MESSAGES: Final[str] = "compact_messages_activity"
    RESOLVE_AGENT_TOOLS: Final[str] = "resolve_agent_tools_activity"
    RECALL_HISTORY: Final[str] = "recall_history_activity"
    UPDATE_TASK_STATUS: Final[str] = "update_task_status_activity"
    MATERIALIZE_SKILL_FILES: Final[str] = "materialize_skill_files_activity"
    CLEANUP_SANDBOX_WORKFLOW: Final[str] = "cleanup_sandbox_workflow_activity"
    # Dynamic context discovery
    DISCOVER_TOOL_PROVIDERS: Final[str] = "discover_tool_providers_activity"
    STORE_CONTEXT_OUTPUT: Final[str] = "store_context_output"
    READ_CONTEXT_OUTPUT: Final[str] = "read_context_output"
    STORE_HISTORY_CHUNK: Final[str] = "store_history_chunk"
    SEARCH_HISTORY: Final[str] = "search_history"
    # Delegation
    CREATE_DELEGATION_TASK: Final[str] = "create_delegation_task_activity"
    # Model resolution
    RESOLVE_MODEL: Final[str] = "resolve_model_activity"


# Execution statuses
class ExecutionStatus:
    """Agent execution status constants."""

    INITIALIZING: Final[str] = "initializing"
    PLANNING: Final[str] = "planning"
    EXECUTING: Final[str] = "executing"
    WAITING_FOR_APPROVAL: Final[str] = "waiting_for_approval"
    WAITING_FOR_INPUT: Final[str] = "waiting_for_input"
    BLOCKED: Final[str] = "blocked"
    TOOL_EXECUTION: Final[str] = "tool_execution"
    EVALUATING: Final[str] = "evaluating"
    COMPLETED: Final[str] = "completed"
    FAILED: Final[str] = "failed"
    CANCELLED: Final[str] = "cancelled"
