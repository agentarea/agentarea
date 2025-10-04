"""Message models for agent conversations.

This module provides a hierarchy of message types for structured conversation history,
using composition to avoid dataclass field ordering issues while maintaining clean structure.

Moved from execution library to consolidate agent-related components in the SDK.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseMessage:
    """Base message class with common fields for all message types."""

    role: str
    content: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserMessage:
    """Message from user/human."""

    content: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    role: str = field(default="user", init=False)


@dataclass
class SystemMessage:
    """System message with instructions or context."""

    content: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    role: str = field(default="system", init=False)


@dataclass
class AssistantMessage:
    """Message from AI assistant/agent."""

    content: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] | None = None
    role: str = field(default="assistant", init=False)


@dataclass
class ToolMessage:
    """Message containing tool execution results."""

    content: str
    tool_call_id: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    success: bool = True
    error: str | None = None
    role: str = field(default="tool", init=False)


# Legacy compatibility - maps to the original Message class
@dataclass
class Message:
    """Legacy message class for backward compatibility.

    This maintains the original interface while providing the new structure.
    """

    role: str
    content: str
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


# Factory functions for easy message creation
def create_system_message(content: str, **kwargs) -> SystemMessage:
    """Create a system message."""
    return SystemMessage(content=content, **kwargs)


def create_user_message(content: str, **kwargs) -> UserMessage:
    """Create a user message."""
    return UserMessage(content=content, **kwargs)


def create_assistant_message(
    content: str, tool_calls: list[dict] | None = None, **kwargs
) -> AssistantMessage:
    """Create an assistant message."""
    return AssistantMessage(content=content, tool_calls=tool_calls, **kwargs)


def create_tool_message(
    content: str, tool_call_id: str, tool_name: str | None = None, success: bool = True, **kwargs
) -> ToolMessage:
    """Create a tool message."""
    return ToolMessage(
        content=content, tool_call_id=tool_call_id, tool_name=tool_name, success=success, **kwargs
    )


class Messages:
    """Clean API for creating message instances.

    Provides a simple interface for creating different message types:
    - Messages.SystemMessage("content")
    - Messages.UserMessage("content")
    - Messages.AssistantMessage("content", tool_calls=None)
    - Messages.ToolMessage("content", tool_call_id="id", tool_name="name")
    """

    @staticmethod
    def SystemMessage(content: str, **kwargs) -> SystemMessage:  # noqa: N802
        """Create a system message."""
        return create_system_message(content, **kwargs)

    @staticmethod
    def UserMessage(content: str, **kwargs) -> UserMessage:  # noqa: N802
        """Create a user message."""
        return create_user_message(content, **kwargs)

    @staticmethod
    def AssistantMessage(  # noqa: N802
        content: str, tool_calls: list[dict] | None = None, **kwargs
    ) -> AssistantMessage:
        """Create an assistant message."""
        return create_assistant_message(content, tool_calls=tool_calls, **kwargs)

    @staticmethod
    def ToolMessage(  # noqa: N802
        content: str,
        tool_call_id: str,
        tool_name: str | None = None,
        success: bool = True,
        **kwargs,
    ) -> ToolMessage:
        """Create a tool message."""
        return create_tool_message(
            content, tool_call_id, tool_name=tool_name, success=success, **kwargs
        )
