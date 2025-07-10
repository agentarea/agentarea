"""
AgentArea Execution Library

Google ADK-powered Temporal workflow execution for agent tasks with TemporalFlow integration.

Core Components:
- Models: Data models for agent task execution
- Activities: Atomic agent execution activities (focused on LLM and tool execution)
- Interfaces: Service interfaces for AgentArea integration
- TemporalFlow: Custom ADK flow that routes LLM calls through Temporal activities
- TemporalLlmAgent: LlmAgent that uses TemporalFlow for execution

Features:
- Google ADK agent execution with TemporalFlow for durability
- Temporal workflow orchestration
- Proper error handling and retry mechanisms
- Integration with existing AgentArea services
- Minimal changes to existing architecture - just override the LLM flow
- Drop-in replacement for LlmAgent with Temporal benefits

Architecture:
    TemporalLlmAgent (extends LlmAgent)
        ↓ overrides _llm_flow property  
    TemporalFlow (extends BaseLlmFlow)
        ↓ overrides _call_llm_async method
    Temporal Activities (call_llm_activity, execute_mcp_tool_activity)
        ↓ uses existing AgentArea services
    AgentArea Services (LLM, MCP, Events)

Usage:
    from agentarea_execution import create_temporal_llm_agent
    
    # Create TemporalLlmAgent as drop-in replacement for LlmAgent
    temporal_agent = create_temporal_llm_agent(
        activity_services=activity_services,
        agent_id=agent_id,
        name="my_agent",
        model=model,
        instruction="You are a helpful assistant.",
        tools=[]
    )
    
    # Use exactly like standard LlmAgent - Temporal integration is transparent
"""

from .interfaces import ActivityServicesInterface
from .models import (
    AgentExecutionRequest,
    ToolExecutionRequest,
    ToolExecutionResult,
    LLMReasoningResult,
)

# Activities exports
from .activities import (
    build_agent_config_activity,
    validate_agent_configuration_activity,
    discover_available_tools_activity,
    call_llm_activity,
    execute_mcp_tool_activity,
    persist_agent_memory_activity,
    publish_task_event_activity,
)

# TemporalFlow integration exports - The key new functionality
from .temporal_flow import TemporalFlow
from .temporal_llm_agent import TemporalLlmAgent, create_temporal_llm_agent

__all__ = [
    # Interfaces
    "ActivityServicesInterface",
    
    # Models
    "AgentExecutionRequest",
    "ToolExecutionRequest", 
    "ToolExecutionResult",
    "LLMReasoningResult",
    
    # Activities (Temporal activities for LLM and tool execution)
    "build_agent_config_activity",
    "validate_agent_configuration_activity",
    "discover_available_tools_activity",
    "call_llm_activity", 
    "execute_mcp_tool_activity",
    "persist_agent_memory_activity",
    "publish_task_event_activity",
    
    # TemporalFlow Integration - The key new exports
    "TemporalFlow",
    "TemporalLlmAgent",
    "create_temporal_llm_agent",
] 