"""Constants and configuration for agent execution workflows."""

from datetime import timedelta
from typing import Final

from agentarea_common.events import contract

# Warning threshold is behavior, not a resource entitlement. Resource ceilings
# live in persisted governance policy and are required at workflow start.
BUDGET_WARNING_THRESHOLD: Final[float] = 0.8  # 80% of budget

# Timeout configurations
ACTIVITY_TIMEOUT: Final[timedelta] = timedelta(minutes=5)
LLM_CALL_TIMEOUT: Final[timedelta] = timedelta(minutes=10)
# Covers the longest MCP tool call an instance may allow (agentarea_mcp.tool_timeout)
# after a container instance's cold start; the call's own timeout is the real bound.
TOOL_EXECUTION_TIMEOUT: Final[timedelta] = timedelta(minutes=40)
EVENT_PUBLISH_TIMEOUT: Final[timedelta] = timedelta(seconds=30)
# How long a run waits for its event store to come back before it gives up.
EVENT_PUBLISH_WINDOW: Final[timedelta] = timedelta(hours=1)
CONTINUATION_TIMEOUT: Final[timedelta] = timedelta(hours=24)

# Heartbeat configuration
HEARTBEAT_TIMEOUT: Final[timedelta] = timedelta(seconds=30)

# Agent delegation: the child's own turn, token and budget limits bound its work;
# this only stops a child that is stuck.
DELEGATION_TIMEOUT: Final[timedelta] = timedelta(hours=6)

# Retry policies
DEFAULT_RETRY_ATTEMPTS: Final[int] = 3
# Idempotent bookkeeping (task status, spend reads) rides out a few minutes of
# database or network trouble instead of ending the run.
BOOKKEEPING_RETRY_ATTEMPTS: Final[int] = 10
BOOKKEEPING_RETRY_MAX_INTERVAL: Final[timedelta] = timedelta(seconds=30)
# LLM calls retry transient failures (rate limit, network, 5xx) with backoff for
# about three minutes. Permanent failures (auth, quota/billing, bad model) still
# fail fast via the ApplicationError non_retryable flag (_is_non_retryable_error).
LLM_RETRY_ATTEMPTS: Final[int] = 8
LLM_RETRY_INITIAL_INTERVAL: Final[timedelta] = timedelta(seconds=2)
LLM_RETRY_MAX_INTERVAL: Final[timedelta] = timedelta(seconds=60)


# Context window management
CONTEXT_COMPACT_THRESHOLD: Final[float] = 0.75  # Compact at 75% of context window
# A compaction runs again only once the prompt grew by this share of the usable
# window since the last one; less would not free room worth a paid summary.
CONTEXT_MIN_COMPACTION_GAIN: Final[float] = 0.1
CONTEXT_WARNING_THRESHOLD: Final[float] = 0.60  # Warn at 60%
CONTEXT_RESERVE_FOR_OUTPUT: Final[float] = 0.15  # Reserve 15% for model output
MIN_RECENT_MESSAGES_TO_KEEP: Final[int] = 6  # Always keep last 6 messages (3 turns)
# The conversation travels in every model-call and continue-as-new payload, and
# Temporal rejects payloads over 2 MiB, so it is compacted well before that
# whatever the model's context window allows.
CONTEXT_MAX_PAYLOAD_BYTES: Final[int] = 1_500_000
TOKENS_PER_MESSAGE_OVERHEAD: Final[int] = 4  # ~4 tokens overhead per message

# Dynamic context discovery — output offloading
TOOL_OUTPUT_OFFLOAD_CHARS: Final[int] = 8000  # ~2000 tokens
OUTPUT_SUMMARY_HEAD_CHARS: Final[int] = 500
OUTPUT_SUMMARY_TAIL_CHARS: Final[int] = 200
READ_OUTPUT_MAX_RETURN_CHARS: Final[int] = 16000  # Safety limit for read_tool_output
HISTORY_SEARCH_MAX_RESULTS: Final[int] = 20


# Event types
class EventTypes:
    """Workflow event type constants, all from agentarea_common.events.contract."""

    WORKFLOW_STARTED: Final[str] = contract.TASK_STARTED
    WORKFLOW_COMPLETED: Final[str] = contract.TASK_COMPLETED
    WORKFLOW_FAILED: Final[str] = contract.TASK_FAILED
    WORKFLOW_CANCELLED: Final[str] = contract.TASK_CANCELLED
    EXECUTION_FINISHED: Final[str] = contract.EXECUTION_FINISHED
    WORKFLOW_AWAITING_FOLLOW_UP: Final[str] = contract.TASK_AWAITING_FOLLOW_UP
    WORKFLOW_AWAITING_CONTINUATION: Final[str] = contract.TASK_AWAITING_CONTINUATION
    WORKFLOW_CONTINUED: Final[str] = contract.TASK_CONTINUED
    WORKFLOW_RETRIED: Final[str] = contract.TASK_RETRIED
    CONTINUED_AS_NEW: Final[str] = contract.EXECUTION_CONTINUED_AS_NEW
    EXECUTION_PAUSED: Final[str] = contract.EXECUTION_PAUSED
    EXECUTION_RESUMED: Final[str] = contract.EXECUTION_RESUMED
    VALIDATION_STARTED: Final[str] = contract.ARTIFACT_VALIDATION_STARTED
    VALIDATION_COMPLETED: Final[str] = contract.ARTIFACT_VALIDATION_COMPLETED

    TURN_STARTED: Final[str] = contract.TURN_STARTED
    TURN_COMPLETED: Final[str] = contract.TURN_COMPLETED
    TURN_ABORTED: Final[str] = contract.TURN_ABORTED

    LLM_CALL_STARTED: Final[str] = contract.LLM_STARTED
    LLM_CALL_CHUNK: Final[str] = contract.LLM_CHUNK
    LLM_CALL_COMPLETED: Final[str] = contract.LLM_COMPLETED
    LLM_CALL_FAILED: Final[str] = contract.LLM_FAILED

    # Failed is a tool.result whose data carries ``error`` (no ``success``); the
    # constant names stay distinct so callers can branch pre-emit.
    TOOL_CALL_STARTED: Final[str] = contract.TOOL_CALL
    TOOL_CALL_COMPLETED: Final[str] = contract.TOOL_RESULT
    TOOL_CALL_FAILED: Final[str] = contract.TOOL_RESULT
    # Recorded by the tool activity itself while a call runs (see tool_progress).
    TOOL_PROGRESS: Final[str] = contract.TOOL_PROGRESS

    BUDGET_WARNING: Final[str] = contract.BUDGET_WARNING
    BUDGET_EXCEEDED: Final[str] = contract.BUDGET_EXCEEDED
    BUDGET_UPDATED: Final[str] = contract.BUDGET_UPDATED

    SERVICE_PAYMENT: Final[str] = contract.SERVICE_PAYMENT
    SERVICE_BUDGET_WARNING: Final[str] = contract.SERVICE_BUDGET_WARNING
    SERVICE_BUDGET_EXCEEDED: Final[str] = contract.SERVICE_BUDGET_EXCEEDED

    CONTEXT_COMPACTED: Final[str] = contract.CONTEXT_COMPACTED
    CONTEXT_WARNING: Final[str] = contract.CONTEXT_WARNING
    # The final answer's check found leaks; data says which and whether it was rewritten.
    ANSWER_CHECKED: Final[str] = contract.ANSWER_CHECKED

    DELEGATION_STARTED: Final[str] = contract.DELEGATION_STARTED
    DELEGATION_COMPLETED: Final[str] = contract.DELEGATION_COMPLETED
    DELEGATION_FAILED: Final[str] = contract.DELEGATION_FAILED

    # Approval received/denied both map to ``approval.decided`` (the decision
    # lives in the data payload).
    HUMAN_APPROVAL_REQUESTED: Final[str] = contract.APPROVAL_REQUESTED
    HUMAN_APPROVAL_RECEIVED: Final[str] = contract.APPROVAL_DECIDED
    HUMAN_APPROVAL_DENIED: Final[str] = contract.APPROVAL_DECIDED
    # Event rows of the task log (the feed shows them, the model never sees them).
    APPROVAL_REQUESTED: Final[str] = contract.APPROVAL_REQUESTED
    APPROVAL_DECIDED: Final[str] = contract.APPROVAL_DECIDED
    HUMAN_INPUT_REQUESTED: Final[str] = contract.INPUT_REQUEST
    HUMAN_INPUT_SUBMITTED: Final[str] = contract.INPUT_SUBMITTED
    HUMAN_INPUT_RECEIVED: Final[str] = contract.INPUT_RESPONSE

    MESSAGE_QUEUED: Final[str] = contract.MESSAGE_QUEUED
    MESSAGE_REMOVED: Final[str] = contract.MESSAGE_REMOVED

    MODEL_CHANGED: Final[str] = contract.MODEL_CHANGED
    MODEL_FALLBACK: Final[str] = contract.MODEL_FALLBACK
    MODEL_UNAVAILABLE: Final[str] = contract.MODEL_UNAVAILABLE
    RUNTIME_DISCOVERED: Final[str] = contract.RUNTIME_DISCOVERED
    COMMAND_RECEIVED: Final[str] = contract.COMMAND_RECEIVED
    COMMAND_REJECTED: Final[str] = contract.COMMAND_REJECTED


# Activity names
class Activities:
    """Activity function references to avoid hardcoded strings."""

    BUILD_AGENT_CONFIG: Final[str] = "build_agent_config_activity"
    DISCOVER_RUNTIME_MANIFEST: Final[str] = "discover_runtime_manifest_activity"
    VALIDATE_ARTIFACTS: Final[str] = "validate_artifacts_activity"
    DISCOVER_AVAILABLE_TOOLS: Final[str] = "discover_available_tools_activity"
    CALL_LLM: Final[str] = "call_llm_activity"
    EXECUTE_MCP_TOOL: Final[str] = "execute_mcp_tool_activity"
    CREATE_EXECUTION_PLAN: Final[str] = "create_execution_plan_activity"
    EVALUATE_GOAL_PROGRESS: Final[str] = "evaluate_goal_progress_activity"
    PUBLISH_WORKFLOW_EVENTS: Final[str] = "publish_workflow_events_activity"
    RECORD: Final[str] = "record_activity"
    COMPACT_MESSAGES: Final[str] = "compact_messages_activity"
    RESOLVE_AGENT_TOOLS: Final[str] = "resolve_agent_tools_activity"
    RECALL_HISTORY: Final[str] = "recall_history_activity"
    UPDATE_TASK_STATUS: Final[str] = "update_task_status_activity"
    UPDATE_TASK_GOVERNANCE_SNAPSHOT: Final[str] = "update_task_governance_snapshot_activity"
    CHECK_MONTHLY_SPEND_CAP: Final[str] = "check_monthly_spend_cap_activity"
    MATERIALIZE_SKILL_FILES: Final[str] = "materialize_skill_files_activity"
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
    WAITING_FOR_CONTINUATION: Final[str] = "waiting_for_continuation"
    BLOCKED: Final[str] = "blocked"
    TOOL_EXECUTION: Final[str] = "tool_execution"
    EVALUATING: Final[str] = "evaluating"
    COMPLETED: Final[str] = "completed"
    FAILED: Final[str] = "failed"
    CANCELLED: Final[str] = "cancelled"
