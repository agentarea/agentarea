"""Agent builder utilities for ADK-Temporal integration."""

import logging
from typing import Any, Dict, List, Optional

from ...ag.adk.agents.llm_agent import LlmAgent
from ...ag.adk.agents.base_agent import BaseAgent
from ...ag.adk.tools.base_tool import BaseTool
from ...ag.adk.tools.function_tool import FunctionTool
from ...ag.adk.models.registry import LLMRegistry
from ...ag.adk.models.lite_llm import LiteLlm

logger = logging.getLogger(__name__)


def build_adk_agent_from_config(agent_config: Dict[str, Any]) -> BaseAgent:
    """Build an ADK agent from configuration dictionary.
    
    Args:
        agent_config: Dictionary containing agent configuration including:
            - name: Agent name
            - description: Agent description (optional)
            - model: Model identifier
            - instructions: System instructions (optional)
            - tools: List of tool configurations (optional)
            
    Returns:
        ADK BaseAgent instance
    """
    logger.info(f"Building ADK agent from config: {agent_config.get('name', 'unknown')}")
    
    try:
        # Register LiteLLM for ollama_chat models if not already registered
        _ensure_ollama_models_registered()
        
        # Extract basic configuration
        name = agent_config.get("name", "default_agent")
        description = agent_config.get("description", "")
        model_name = agent_config.get("model", "gpt-4")
        instructions = agent_config.get("instructions", "")
        
        # Build tools if provided
        tools = []
        tool_configs = agent_config.get("tools", [])
        for tool_config in tool_configs:
            tool = build_tool_from_config(tool_config)
            if tool:
                tools.append(tool)
        
        # Create LlmAgent (most common ADK agent type)
        agent = LlmAgent(
            name=name,
            description=description,
            model=model_name,
            instruction=instructions,
            tools=tools,
        )
        
        logger.info(f"Successfully built ADK agent: {name} with model: {model_name}")
        return agent
        
    except Exception as e:
        logger.error(f"Failed to build ADK agent: {e}")
        raise


def _ensure_ollama_models_registered():
    """Register LiteLLM for ollama_chat models if not already registered."""
    try:
        # Check if ollama_chat pattern is already registered
        LLMRegistry.resolve("ollama_chat/test")
        logger.debug("ollama_chat models already registered")
    except ValueError:
        # Register LiteLLM for ollama_chat models
        LLMRegistry._register(r"ollama_chat/.*", LiteLlm)
        logger.info("Registered LiteLLM for ollama_chat models")


def build_tool_from_config(tool_config: Dict[str, Any]) -> Optional[BaseTool]:
    """Build an ADK tool from configuration dictionary.
    
    Args:
        tool_config: Dictionary containing tool configuration including:
            - name: Tool name
            - description: Tool description
            - function: Python function reference (optional)
            - parameters: Tool parameters schema (optional)
            
    Returns:
        ADK BaseTool instance or None if invalid
    """
    tool_name = tool_config.get("name")
    tool_description = tool_config.get("description", "")
    
    if not tool_name:
        return None
    
    # For now, create a simple function tool
    # In the future, this could be extended to support more tool types
    function_ref = tool_config.get("function")
    if function_ref and callable(function_ref):
        return FunctionTool(
            name=tool_name,
            description=tool_description,
            func=function_ref
        )
    
    # Return a placeholder tool for now
    # This would be extended to support MCP tools, etc.
    return None


def extract_agent_metadata(agent: BaseAgent) -> Dict[str, Any]:
    """Extract metadata from an ADK agent for Temporal storage.
    
    Args:
        agent: ADK BaseAgent instance
        
    Returns:
        Dictionary containing agent metadata
    """
    metadata = {
        "name": agent.name,
        "description": agent.description,
        "type": type(agent).__name__,
    }
    
    # Add model information if it's an LlmAgent
    if isinstance(agent, LlmAgent):
        metadata["model"] = getattr(agent, "model", None)
        metadata["instruction"] = getattr(agent, "instruction", None)
    
    # Add sub-agent information
    if agent.sub_agents:
        metadata["sub_agents"] = [
            extract_agent_metadata(sub_agent) 
            for sub_agent in agent.sub_agents
        ]
    
    return metadata


def validate_agent_config(agent_config: Dict[str, Any]) -> bool:
    """Validate agent configuration dictionary.
    
    Args:
        agent_config: Dictionary to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Check required fields
    if not agent_config.get("name"):
        return False
    
    # Validate tools if provided
    tools = agent_config.get("tools", [])
    if tools and not isinstance(tools, list):
        return False
    
    for tool_config in tools:
        if not isinstance(tool_config, dict) or not tool_config.get("name"):
            return False
    
    return True


def create_simple_agent_config(
    name: str,
    model: str = "gpt-4",
    instructions: str = "",
    description: str = "",
    tools: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Create a simple agent configuration dictionary.
    
    Args:
        name: Agent name
        model: Model identifier
        instructions: System instructions
        description: Agent description
        tools: List of tool configurations
        
    Returns:
        Agent configuration dictionary
    """
    config = {
        "name": name,
        "model": model,
        "instructions": instructions,
        "description": description,
    }
    
    if tools:
        config["tools"] = tools
    
    return config