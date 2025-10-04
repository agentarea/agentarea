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
LLM_CALL_TIMEOUT: Final[timedelta] = timedelta(minutes=2)
TOOL_EXECUTION_TIMEOUT: Final[timedelta] = timedelta(minutes=3)
EVENT_PUBLISH_TIMEOUT: Final[timedelta] = timedelta(seconds=5)

# Retry policies
DEFAULT_RETRY_ATTEMPTS: Final[int] = 3
EVENT_PUBLISH_RETRY_ATTEMPTS: Final[int] = 1


# Event types
class EventTypes:
    """Workflow event type constants."""

    WORKFLOW_STARTED: Final[str] = "WorkflowStarted"
    WORKFLOW_COMPLETED: Final[str] = "WorkflowCompleted"
    WORKFLOW_FAILED: Final[str] = "WorkflowFailed"
    WORKFLOW_CANCELLED: Final[str] = "WorkflowCancelled"

    ITERATION_STARTED: Final[str] = "IterationStarted"
    ITERATION_COMPLETED: Final[str] = "IterationCompleted"

    LLM_CALL_STARTED: Final[str] = "LLMCallStarted"
    LLM_CALL_CHUNK: Final[str] = "LLMCallChunk"
    LLM_CALL_COMPLETED: Final[str] = "LLMCallCompleted"
    LLM_CALL_FAILED: Final[str] = "LLMCallFailed"

    TOOL_CALL_STARTED: Final[str] = "ToolCallStarted"
    TOOL_CALL_COMPLETED: Final[str] = "ToolCallCompleted"
    TOOL_CALL_FAILED: Final[str] = "ToolCallFailed"

    BUDGET_WARNING: Final[str] = "BudgetWarning"
    BUDGET_EXCEEDED: Final[str] = "BudgetExceeded"

    HUMAN_APPROVAL_REQUESTED: Final[str] = "HumanApprovalRequested"
    HUMAN_APPROVAL_RECEIVED: Final[str] = "HumanApprovalReceived"


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


# Execution statuses
class ExecutionStatus:
    """Agent execution status constants."""

    INITIALIZING: Final[str] = "initializing"
    PLANNING: Final[str] = "planning"
    EXECUTING: Final[str] = "executing"
    WAITING_FOR_APPROVAL: Final[str] = "waiting_for_approval"
    TOOL_EXECUTION: Final[str] = "tool_execution"
    EVALUATING: Final[str] = "evaluating"
    COMPLETED: Final[str] = "completed"
    FAILED: Final[str] = "failed"
    CANCELLED: Final[str] = "cancelled"
