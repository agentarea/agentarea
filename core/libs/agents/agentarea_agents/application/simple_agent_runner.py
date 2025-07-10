"""
Simple Agent Runner Service

Focused service for basic agent execution:
- Create agent → Send message → Get response
- No complex temporal flows or dynamic configuration
- Direct LLM integration for immediate results
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from agentarea_common.events.models import Event
from agentarea_llm.application.llm_service import LLMService
from agentarea_mcp.application.mcp_service import MCPService
from .agent_service import AgentService

logger = logging.getLogger(__name__)


class SimpleAgentRunner:
    """Simplified agent runner for basic chat functionality."""
    
    def __init__(
        self, 
        agent_service: AgentService,
        llm_service: LLMService, 
        mcp_service: MCPService
    ):
        self.agent_service = agent_service
        self.llm_service = llm_service
        self.mcp_service = mcp_service
    
    async def send_message(
        self, 
        agent_id: UUID, 
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a message to an agent and get a response.
        
        Simple flow:
        1. Get agent config
        2. Get available tools
        3. Send to LLM
        4. Return response
        """
        try:
            logger.info(f"Processing message for agent {agent_id}: {message[:50]}...")
            
            # Get agent configuration
            agent_config = await self.agent_service.build_agent_config(agent_id)
            if not agent_config:
                raise ValueError(f"Agent {agent_id} not found")
            
            # Get available tools
            available_tools = await self._get_available_tools(agent_config)
            
            # Prepare conversation history (simple format)
            conversation_history = [
                {"role": "user", "content": message}
            ]
            
            # Execute LLM reasoning
            reasoning_result = await self.llm_service.execute_reasoning(
                agent_config=agent_config,
                conversation_history=conversation_history,
                current_goal="Respond to the user's message",
                available_tools=available_tools,
                max_tool_calls=3,
                include_thinking=False,
            )
            
            # Handle tool calls if any
            final_response = reasoning_result.reasoning_text
            if reasoning_result.tool_calls:
                tool_results = await self._execute_tool_calls(
                    reasoning_result.tool_calls, 
                    available_tools
                )
                
                # Add tool results to conversation and get final response
                if tool_results:
                    conversation_history.extend([
                        {"role": "assistant", "content": final_response},
                        {"role": "system", "content": f"Tool results: {tool_results}"}
                    ])
                    
                    # Get final response after tool execution
                    final_reasoning = await self.llm_service.execute_reasoning(
                        agent_config=agent_config,
                        conversation_history=conversation_history,
                        current_goal="Provide final response incorporating tool results",
                        available_tools=[],  # No more tools needed
                        max_tool_calls=0,
                        include_thinking=False,
                    )
                    final_response = final_reasoning.reasoning_text
            
            return {
                "success": True,
                "response": final_response,
                "agent_id": str(agent_id),
                "session_id": session_id,
                "model_used": reasoning_result.model_used,
                "reasoning_time": reasoning_result.reasoning_time_seconds,
                "tool_calls_made": len(reasoning_result.tool_calls) if reasoning_result.tool_calls else 0,
            }
            
        except Exception as e:
            logger.error(f"Failed to process message for agent {agent_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": f"I apologize, but I encountered an error while processing your message: {e}",
                "agent_id": str(agent_id),
                "session_id": session_id,
            }
    
    async def _get_available_tools(self, agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get available tools for the agent."""
        tools = []
        
        try:
            tools_config = agent_config.get("tools_config", {})
            mcp_servers = tools_config.get("mcp_servers", [])
            
            for mcp_server in mcp_servers:
                if mcp_server.get("enabled", False):
                    server_id = mcp_server.get("id")
                    
                    try:
                        server_tools = await self.mcp_service.get_server_tools(server_id)
                        
                        for tool in server_tools:
                            tools.append({
                                "name": tool.get("name"),
                                "description": tool.get("description", ""),
                                "parameters": tool.get("parameters", {}),
                                "mcp_server_id": server_id,
                            })
                    except Exception as e:
                        logger.warning(f"Failed to get tools from MCP server {server_id}: {e}")
                        
        except Exception as e:
            logger.warning(f"Failed to get available tools: {e}")
        
        return tools
    
    async def _execute_tool_calls(
        self, 
        tool_calls: List[Dict[str, Any]], 
        available_tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Execute tool calls and return results."""
        results = []
        
        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("arguments", {})
            
            # Find the tool in available tools
            tool_info = None
            for tool in available_tools:
                if tool["name"] == tool_name:
                    tool_info = tool
                    break
            
            if not tool_info:
                logger.warning(f"Tool {tool_name} not found in available tools")
                results.append({
                    "tool_name": tool_name,
                    "success": False,
                    "error": f"Tool {tool_name} not available"
                })
                continue
            
            try:
                # Execute the tool via MCP service
                result = await self.mcp_service.execute_tool(
                    tool_name=tool_name,
                    arguments=tool_args,
                    server_instance_id=UUID(tool_info["mcp_server_id"])
                )
                
                results.append({
                    "tool_name": tool_name,
                    "success": True,
                    "result": result.get("output", str(result))
                })
                
            except Exception as e:
                logger.error(f"Failed to execute tool {tool_name}: {e}")
                results.append({
                    "tool_name": tool_name,
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    async def get_agent_info(self, agent_id: UUID) -> Optional[Dict[str, Any]]:
        """Get basic agent information."""
        try:
            agent = await self.agent_service.get(agent_id)
            if not agent:
                return None
            
            return {
                "id": str(agent.id),
                "name": agent.name,
                "description": agent.description,
                "status": "active",  # Simple status
            }
        except Exception as e:
            logger.error(f"Failed to get agent info for {agent_id}: {e}")
            return None
    
    async def list_available_agents(self) -> List[Dict[str, Any]]:
        """List all available agents."""
        try:
            agents = await self.agent_service.list_agents()
            return [
                {
                    "id": str(agent.id),
                    "name": agent.name,
                    "description": agent.description,
                    "status": "active",
                }
                for agent in agents
            ]
        except Exception as e:
            logger.error(f"Failed to list agents: {e}")
            return [] 