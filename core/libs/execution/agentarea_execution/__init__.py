"""AgentArea Execution Library

LangGraph-based Temporal workflow execution for agent tasks.

Core Components:
- Models: Data models for agent task execution
- Activities: Atomic agent execution activities (focused on LLM and tool execution)
- Interfaces: Service container for AgentArea service injection
- TemporalFlow: Custom ADK flow that routes LLM calls through Temporal activities
- TemporalLlmAgent: LlmAgent that uses TemporalFlow for execution
- Workflows: LangGraph-based workflows that orchestrate activities
- LLM Integration: Direct LiteLLM integration for model execution
- MCP Integration: Tool execution via MCP server instances
- Agent Management: Agent configuration and state management

The library provides a clean separation between:
- Workflows (orchestration logic)
- Activities (atomic operations)
- Services (business logic from other libraries)

This architecture allows for:
- Easy testing and mocking
- Clean dependency injection
- Scalable workflow execution
- Integration with existing AgentArea services
"""

from .interfaces import ActivityDependencies, ActivityServicesInterface
from .models import (
    AgentExecutionRequest,
    AgentExecutionResult,
    LLMReasoningRequest,
    LLMReasoningResult,
    ToolExecutionRequest,
    ToolExecutionResult,
)

# Avoid SDK imports in execution module to prevent Temporal sandbox issues
# Import Message from workflow models instead
from .workflows.models import Message

# Note: Agentic runners are not imported here to avoid Temporal sandbox issues
# Import them directly from .agentic when needed outside of workflows


# Import activities creation function for worker setup
def create_activities_for_worker(dependencies: ActivityDependencies):
    """Create activities instances for the Temporal worker.

    Args:
        dependencies: Basic dependencies needed to create services within activities

    Returns:
        List of activity functions ready for worker registration
    """
    from .activities.agent_execution_activities import make_agent_activities
    from .activities.trigger_execution_activities import make_trigger_activities

    # Create activities using the factory pattern
    agent_activities = make_agent_activities(dependencies)
    trigger_activities = make_trigger_activities(dependencies)

    # Return combined list of all activities
    return agent_activities + trigger_activities


__all__ = [
    "ActivityDependencies",
    "ActivityServicesInterface",  # Keep for backward compatibility
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "LLMReasoningRequest",
    "LLMReasoningResult",
    "Message",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "create_activities_for_worker",
]
