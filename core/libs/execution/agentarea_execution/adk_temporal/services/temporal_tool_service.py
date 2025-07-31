"""Temporal-backed tool service for ADK integration.

This service intercepts ADK tool calls and routes them through Temporal activities,
making Temporal the backbone for tool execution while keeping ADK untouched.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from google.genai import types
from temporalio import workflow

from ...ag.adk.tools.base_tool import BaseTool
from ...ag.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


class TemporalTool(BaseTool):
    """Tool that routes execution through Temporal activities.
    
    This tool acts as a bridge between ADK's tool interface and Temporal
    workflow activities, enabling workflow orchestration of tool calls.
    """
    
    def __init__(
        self, 
        name: str, 
        description: str, 
        function_declaration: Optional[types.FunctionDeclaration] = None,
        server_instance_id: Optional[UUID] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        session_data: Optional[Dict[str, Any]] = None,
        is_long_running: bool = False
    ):
        """Initialize the Temporal tool.
        
        Args:
            name: Tool name
            description: Tool description
            function_declaration: OpenAPI function declaration
            server_instance_id: MCP server instance ID for this tool
            agent_config: Agent configuration for context
            session_data: Session data for context
            is_long_running: Whether this is a long-running tool
        """
        super().__init__(
            name=name, 
            description=description, 
            is_long_running=is_long_running
        )
        self.function_declaration = function_declaration
        self.server_instance_id = server_instance_id
        self.agent_config = agent_config or {}
        self.session_data = session_data or {}
    
    def _get_declaration(self) -> Optional[types.FunctionDeclaration]:
        """Get the function declaration for this tool.
        
        Returns:
            Function declaration if available
        """
        return self.function_declaration
    
    async def run_async(
        self, *, args: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Execute tool via Temporal activity.
        
        Args:
            args: Tool arguments from LLM
            tool_context: Tool execution context
            
        Returns:
            Tool execution result
        """
        try:
            logger.info(f"Routing tool call through Temporal: {self.name}")
            
            # Execute via Temporal activity
            from ...activities.agent_execution_activities import execute_mcp_tool_activity
            
            result = await workflow.execute_activity(
                execute_mcp_tool_activity,
                args=[self.name, args, self.server_instance_id],
                start_to_close_timeout=300,  # 5 minutes timeout
                heartbeat_timeout=30,  # 30 seconds heartbeat
            )
            
            # Handle the result
            if isinstance(result, dict):
                if result.get("success", True):
                    return result.get("result", "Tool executed successfully")
                else:
                    raise Exception(result.get("result", "Tool execution failed"))
            
            return result
            
        except Exception as e:
            logger.error(f"Temporal tool call failed for {self.name}: {e}")
            raise


class TemporalToolFactory:
    """Factory for creating Temporal-backed tools."""
    
    def __init__(self, agent_config: Dict[str, Any], session_data: Dict[str, Any]):
        """Initialize the tool factory.
        
        Args:
            agent_config: Agent configuration for context
            session_data: Session data for context
        """
        self.agent_config = agent_config
        self.session_data = session_data
    
    def create_tool_from_declaration(
        self, 
        func_decl: types.FunctionDeclaration,
        server_instance_id: Optional[UUID] = None
    ) -> TemporalTool:
        """Create a Temporal tool from a function declaration.
        
        Args:
            func_decl: Function declaration
            server_instance_id: Optional MCP server instance ID
            
        Returns:
            Configured TemporalTool
        """
        return TemporalTool(
            name=func_decl.name,
            description=func_decl.description or "",
            function_declaration=func_decl,
            server_instance_id=server_instance_id,
            agent_config=self.agent_config,
            session_data=self.session_data
        )
    
    def create_tool_from_config(
        self, 
        tool_config: Dict[str, Any]
    ) -> TemporalTool:
        """Create a Temporal tool from configuration.
        
        Args:
            tool_config: Tool configuration dictionary
            
        Returns:
            Configured TemporalTool
        """
        # Extract basic info
        name = tool_config.get("name", "unknown_tool")
        description = tool_config.get("description", "")
        is_long_running = tool_config.get("is_long_running", False)
        
        # Extract server instance ID if available
        server_instance_id = None
        if "server_instance_id" in tool_config:
            try:
                server_instance_id = UUID(str(tool_config["server_instance_id"]))
            except (ValueError, TypeError):
                logger.warning(f"Invalid server_instance_id for tool {name}")
        
        # Create function declaration if parameters are provided
        function_declaration = None
        if "parameters" in tool_config:
            function_declaration = types.FunctionDeclaration(
                name=name,
                description=description,
                parameters=tool_config["parameters"]
            )
        
        return TemporalTool(
            name=name,
            description=description,
            function_declaration=function_declaration,
            server_instance_id=server_instance_id,
            agent_config=self.agent_config,
            session_data=self.session_data,
            is_long_running=is_long_running
        )
    
    async def discover_tools_from_agent_config(self) -> List[TemporalTool]:
        """Discover tools from agent configuration.
        
        Returns:
            List of discovered Temporal tools
        """
        tools = []
        
        try:
            # Get agent ID for tool discovery
            agent_id_str = self.agent_config.get("id")
            if not agent_id_str:
                logger.warning("No agent ID in config for tool discovery")
                return tools
            
            agent_id = UUID(agent_id_str)
            
            # Execute tool discovery via Temporal activity
            from ...activities.agent_execution_activities import discover_available_tools_activity
            
            available_tools = await workflow.execute_activity(
                discover_available_tools_activity,
                args=[agent_id],
                start_to_close_timeout=60,  # 1 minute timeout
                heartbeat_timeout=10,  # 10 seconds heartbeat
            )
            
            # Convert discovered tools to TemporalTool instances
            for tool_config in available_tools:
                try:
                    tool = self.create_tool_from_config(tool_config)
                    tools.append(tool)
                except Exception as e:
                    logger.error(f"Failed to create tool from config {tool_config}: {e}")
            
            logger.info(f"Discovered {len(tools)} tools for agent")
            
        except Exception as e:
            logger.error(f"Tool discovery failed: {e}")
        
        return tools


class TemporalToolRegistry:
    """Registry for managing Temporal tools within an agent context."""
    
    def __init__(self, agent_config: Dict[str, Any], session_data: Dict[str, Any]):
        """Initialize the tool registry.
        
        Args:
            agent_config: Agent configuration
            session_data: Session data
        """
        self.agent_config = agent_config
        self.session_data = session_data
        self.factory = TemporalToolFactory(agent_config, session_data)
        self._tools: Dict[str, TemporalTool] = {}
    
    async def initialize_tools(self) -> None:
        """Initialize tools from agent configuration."""
        try:
            # Discover tools from agent config
            discovered_tools = await self.factory.discover_tools_from_agent_config()
            
            # Register discovered tools
            for tool in discovered_tools:
                self._tools[tool.name] = tool
            
            logger.info(f"Initialized {len(self._tools)} tools in registry")
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
    
    def get_tool(self, name: str) -> Optional[TemporalTool]:
        """Get a tool by name.
        
        Args:
            name: Tool name
            
        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[TemporalTool]:
        """Get all registered tools.
        
        Returns:
            List of all tools
        """
        return list(self._tools.values())
    
    def register_tool(self, tool: TemporalTool) -> None:
        """Register a tool.
        
        Args:
            tool: Tool to register
        """
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")
    
    def get_function_declarations(self) -> List[types.FunctionDeclaration]:
        """Get function declarations for all tools.
        
        Returns:
            List of function declarations
        """
        declarations = []
        for tool in self._tools.values():
            if tool.function_declaration:
                declarations.append(tool.function_declaration)
        return declarations