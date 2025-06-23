"""Base adapter interface for agent protocol adapters.

This module defines the common interface that all protocol adapters must implement
to enable seamless integration of different agent communication protocols.

All interactions with agents are treated as tasks - whether they're simple chat messages
or complex multi-step operations.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentTask:
    """Standard internal task format for agent communication."""

    content: str
    task_type: str = "message"  # message, action, query, etc.
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class AgentTaskResponse:
    """Standard internal task response format."""

    content: str
    artifacts: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    status: str = "completed"


# Backward compatibility aliases for chat interfaces
@dataclass
class ChatMessage:
    """Chat message format for adapter compatibility."""

    content: str
    metadata: dict[str, Any] | None = None


@dataclass
class ChatResponse:
    """Chat response format for adapter compatibility."""

    content: str
    metadata: dict[str, Any] | None = None
    status: str = "completed"


class AgentAdapter(ABC):
    """Base class for all agent protocol adapters."""

    def __init__(self, agent_config: dict[str, Any]):
        self.agent_config = agent_config
        self.agent_id = agent_config.get("id")
        self.agent_name = agent_config.get("name")
        self.endpoint = agent_config.get("endpoint")
        self.is_remote = agent_config.get("endpoint") is not None

    @abstractmethod
    async def send_task(
        self, task: AgentTask, session_id: str | None = None
    ) -> AgentTaskResponse:
        """Send a task to the agent and get response."""
        pass

    @abstractmethod
    def stream_task(
        self, task: AgentTask, session_id: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream task response from agent."""
        pass

    @abstractmethod
    async def get_capabilities(self) -> dict[str, Any]:
        """Get agent capabilities and metadata."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if agent is available."""
        pass

    @abstractmethod
    async def create_agent(self, agent_spec: dict[str, Any]) -> dict[str, Any]:
        """Create a new agent instance (for platforms that support it)."""
        pass
