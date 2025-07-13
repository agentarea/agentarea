"""
AgentArea Execution Library

LangGraph-based Temporal workflow execution for agent tasks.

Core Components:
- Models: Data models for agent task execution
- Activities: Atomic agent execution activities (focused on LLM and tool execution)
- Interfaces: Service interfaces for AgentArea integration
- TemporalFlow: Custom ADK flow that routes LLM calls through Temporal activities
- TemporalLlmAgent: LlmAgent that uses TemporalFlow for execution
- Workflows: LangGraph-based workflows that orchestrate activities
- LLM Integration: LiteLLM-based model calls with configurable providers

Features:
- Google ADK agent execution with TemporalFlow for durability
- LangGraph agent execution with Temporal workflow orchestration
- Temporal workflow orchestration
- Proper error handling and retry mechanisms
- Integration with existing AgentArea services
- Minimal changes to existing architecture - just override the LLM flow
- Drop-in replacement for LlmAgent with Temporal benefits
- LiteLLM integration for flexible model providers
- Activity-based architecture for durable execution

Architecture:
    AgentExecutionWorkflow (Temporal workflow)
        ↓ orchestrates activities step-by-step
    Temporal Activities (build_config, call_llm, execute_tools, check_completion)
        ↓ uses AgentArea services + LiteLLM
    AgentArea Services (Agent, MCP, Events) + LiteLLM

Usage:
    from agentarea_execution import AgentExecutionWorkflow, set_global_services
    
    # Set up services for activities
    set_global_services(activity_services)
    
    # Execute via Temporal workflow
    result = await client.execute_workflow(
        AgentExecutionWorkflow.run,
        AgentExecutionRequest(...),
        id="workflow-id",
        task_queue="agent-task-queue"
    )
"""

# Activities exports
from .activities.agent_execution_activities import (
    AgentActivities,
    set_global_services,
    build_agent_config_activity,
    discover_available_tools_activity,
    call_llm_activity,
    execute_mcp_tool_activity,
    check_task_completion_activity,
)

# Backward compatibility - ALL_ACTIVITIES list
ALL_ACTIVITIES = [
    build_agent_config_activity,
    discover_available_tools_activity,
    call_llm_activity,
    execute_mcp_tool_activity,
    check_task_completion_activity,
]

# Interfaces exports
from .interfaces import (
    ActivityServicesInterface,
    AgentServiceInterface,
    MCPServiceInterface,
    LLMServiceInterface,
    EventBrokerInterface,
)

# Models exports
from .models import (
    AgentExecutionRequest,
    ToolExecutionRequest,
    ToolExecutionResult,
    LLMReasoningResult,
)


def create_activities_for_worker(services: ActivityServicesInterface) -> list[object]:
    """Create activity instances for Temporal worker registration.
    
    Args:
        services: Injected services for activities
        
    Returns:
        List of activity methods ready for worker registration
    """
    activities = AgentActivities(services)
    return [
        activities.build_agent_config_activity,
        activities.discover_available_tools_activity,
        activities.call_llm_activity,
        activities.execute_mcp_tool_activity,
        activities.check_task_completion_activity,
    ]


# Base exports that are always available
__all__ = [
    # Interfaces
    "ActivityServicesInterface",
    "AgentServiceInterface",
    "MCPServiceInterface",
    "LLMServiceInterface",
    "EventBrokerInterface",
    
    # Models
    "AgentExecutionRequest",
    "ToolExecutionRequest", 
    "ToolExecutionResult",
    "LLMReasoningResult",
    
    # Activities (Temporal activities for LLM and tool execution)
    "AgentActivities",
    "create_activities_for_worker",
    "set_global_services",
    "build_agent_config_activity",
    "discover_available_tools_activity",
    "call_llm_activity",
    "execute_mcp_tool_activity",
    "check_task_completion_activity",
    "ALL_ACTIVITIES",
] 