"""
Temporal LLM Agent

Minimal implementation that extends LlmAgent to use TemporalFlow for execution.
This provides Temporal durability while preserving all ADK functionality.
"""

import logging
from typing import Any, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Handle Google ADK imports gracefully
try:
    from google.adk.agents import LlmAgent
    from google.adk.flows.llm_flows.base_llm_flow import BaseLlmFlow
    ADK_AVAILABLE = True
except ImportError:
    logger.warning("Google ADK not available - using stubs")
    class LlmAgent:
        def __init__(self, **kwargs): pass
    class BaseLlmFlow: pass
    ADK_AVAILABLE = False

from .interfaces import ActivityServicesInterface
from .temporal_flow import TemporalFlow


class TemporalLlmAgent(LlmAgent):
    """
    LlmAgent that uses TemporalFlow for execution.
    
    This is a drop-in replacement for LlmAgent that routes LLM calls
    through Temporal activities for durability and observability.
    """

    def __init__(
        self,
        activity_services: ActivityServicesInterface,
        agent_id: UUID,
        **kwargs: Any
    ):
        """
        Initialize TemporalLlmAgent.
        
        Args:
            activity_services: Interface to AgentArea services
            agent_id: AgentArea agent ID
            **kwargs: All other LlmAgent parameters (name, model, instruction, etc.)
        """
        super().__init__(**kwargs)
        self.activity_services = activity_services
        self.agent_id = agent_id
        logger.info(f"TemporalLlmAgent initialized: {getattr(self, 'name', 'unnamed')} (ID: {agent_id})")

    @property
    def _llm_flow(self) -> BaseLlmFlow:
        """
        This is the key override - return TemporalFlow instead of SingleFlow/AutoFlow.
        
        This routes all ADK execution through our Temporal activities while
        preserving ADK's sophisticated reasoning patterns.
        """
        return TemporalFlow(self.activity_services, self.agent_id)


def create_temporal_llm_agent(
    activity_services: ActivityServicesInterface,
    agent_id: UUID,
    name: str,
    model: Any,
    instruction: str,
    tools: Optional[List[Any]] = None,
    **kwargs: Any
) -> TemporalLlmAgent:
    """
    Factory function to create a TemporalLlmAgent.
    
    This is a drop-in replacement for creating LlmAgent - same parameters,
    but with Temporal durability added.
    
    Args:
        activity_services: Interface to AgentArea services
        agent_id: AgentArea agent ID
        name: Agent name
        model: LLM model (ADK format)
        instruction: Agent instructions
        tools: List of tools (ADK format)
        **kwargs: Additional LlmAgent parameters
    
    Returns:
        Configured TemporalLlmAgent ready for use
    """
    return TemporalLlmAgent(
        activity_services=activity_services,
        agent_id=agent_id,
        name=name,
        model=model,
        instruction=instruction,
        tools=tools or [],
        **kwargs
    ) 