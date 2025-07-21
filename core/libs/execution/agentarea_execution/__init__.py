"""
AgentArea Execution Library

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

from agentarea_execution.interfaces import ActivityDependencies, ActivityServicesInterface
from agentarea_execution.models import (
    AgentExecutionRequest,
    AgentExecutionResult,
    ToolExecutionRequest,
    ToolExecutionResult,
    LLMReasoningRequest,
    LLMReasoningResult,
)

# Import activities creation function for worker setup
def create_activities_for_worker(dependencies: ActivityDependencies):
    """Create activities instances for the Temporal worker.
    
    Args:
        dependencies: Basic dependencies needed to create services within activities
        
    Returns:
        List of activity functions ready for worker registration
    """
    from agentarea_execution.activities.agent_execution_activities import make_agent_activities
    
    # Create activities using the factory pattern
    return make_agent_activities(dependencies)


__all__ = [
    "ActivityDependencies",
    "ActivityServicesInterface",  # Keep for backward compatibility
    "AgentExecutionRequest",
    "AgentExecutionResult", 
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "LLMReasoningRequest",
    "LLMReasoningResult",
    "create_activities_for_worker",
] 