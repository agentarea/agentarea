"""
Interfaces for temporal activity dependency injection.

These interfaces define the contracts for injecting AgentArea services
into temporal activities, matching the existing AgentArea architecture.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .models import LLMReasoningResult


class AgentServiceInterface(ABC):
    """Interface for agent-related operations."""
    
    @abstractmethod
    async def build_agent_config(self, agent_id: UUID) -> Dict[str, Any] | None:
        """Build complete agent configuration from database data."""
        pass
    
    @abstractmethod
    async def update_agent_memory(
        self, 
        agent_id: UUID,
        task_id: UUID,
        conversation_history: List[Dict[str, Any]],
        task_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update agent memory with conversation history and task results."""
        pass


class MCPServiceInterface(ABC):
    """Interface for MCP server operations."""
    
    @abstractmethod
    async def get_server_instance(self, server_id: UUID) -> Any:
        """Get MCP server instance by ID."""
        pass
    
    @abstractmethod
    async def get_server_tools(self, server_id: UUID) -> List[Dict[str, Any]]:
        """Get available tools from an MCP server instance."""
        pass
    
    @abstractmethod
    async def execute_tool(
        self,
        server_instance_id: UUID,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout_seconds: int = 60,
    ) -> Dict[str, Any]:
        """Execute a tool via MCP server instance."""
        pass
    
    @abstractmethod
    async def find_alternative_tools(
        self,
        tool_name: str,
        exclude_server_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Find alternative tools that provide similar functionality."""
        pass
    
    @abstractmethod
    async def find_tools_by_capability(
        self,
        capability: str,
    ) -> List[Dict[str, Any]]:
        """Find tools that provide a specific capability."""
        pass
    
    @abstractmethod
    async def find_tools_with_permissions(
        self,
        required_permissions: List[str],
    ) -> List[Dict[str, Any]]:
        """Find tools that have required permissions."""
        pass
    
    @abstractmethod
    async def find_tools_by_category(
        self,
        category: str,
    ) -> List[Dict[str, Any]]:
        """Find tools by category (e.g., 'network', 'filesystem', 'database')."""
        pass


class LLMServiceInterface(ABC):
    """Interface for LLM reasoning operations."""
    
    @abstractmethod
    async def execute_reasoning(
        self,
        agent_config: Dict[str, Any],
        conversation_history: List[Dict[str, Any]],
        current_goal: str,
        available_tools: List[Dict[str, Any]],
        max_tool_calls: int = 5,
        include_thinking: bool = True,
    ) -> "LLMReasoningResult":
        """Execute LLM reasoning and tool selection."""
        pass


class EventBrokerInterface(ABC):
    """Interface for event publishing operations."""
    
    @abstractmethod
    async def publish_event(self, event_type: str, event_data: Dict[str, Any]) -> None:
        """Publish an event to the event broker."""
        pass


class ActivityServicesInterface:
    """Container for all services needed by temporal activities."""
    
    def __init__(self, agent_service: Any, llm_service: Any, mcp_service: Any, event_broker: Optional[Any] = None):
        self.agent_service = agent_service
        self.llm_service = llm_service
        self.mcp_service = mcp_service
        self.event_broker = event_broker 