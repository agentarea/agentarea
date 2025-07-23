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

# Message templates
class MessageTemplates:
    """Common message templates to avoid duplication."""
    
    SYSTEM_PROMPT: Final[str] = """You are an AI agent working on a specific task. 

Your goal: {goal_description}

Success criteria:
{success_criteria}

Available tools:
{available_tools}

Instructions:
1. Work systematically towards the goal
2. Use available tools when needed
3. Provide clear, actionable responses
4. Ask for clarification if the goal is unclear
5. Stop when you've successfully completed the task

Current iteration: {current_iteration}/{max_iterations}
Budget remaining: ${budget_remaining:.2f}
"""

    BUDGET_WARNING: Final[str] = "Warning: Budget usage at {percentage:.1f}% (${used:.2f}/${total:.2f})"
    BUDGET_EXCEEDED: Final[str] = "Budget exceeded: ${used:.2f}/${total:.2f}. Stopping execution."
    
    TOOL_CALL_SUMMARY: Final[str] = "Called {tool_name} with result: {result}"
    ITERATION_SUMMARY: Final[str] = "Iteration {iteration}: {tool_calls} tool calls, ${cost:.4f} spent"