#!/usr/bin/env python3
"""Test script to demonstrate the improved message hierarchy.

This shows how the new message types provide better structure and extensibility
while maintaining backward compatibility.
"""

import sys

sys.path.append('core/libs/execution')

from agentarea_execution.message_types.messages import (
    AssistantMessage,
    BaseMessage,
    Message,
    create_assistant_message,
    create_system_message,
    create_tool_message,
    create_user_message,
)


def test_message_hierarchy():
    """Test the new message hierarchy."""
    print("=== Testing Message Hierarchy ===\n")

    # Create different types of messages
    messages = []

    # 1. System message
    system_msg = create_system_message(
        "You are a helpful AI assistant that follows the ReAct framework.",
        metadata={"prompt_version": "2.0"}
    )
    messages.append(system_msg)
    print(f"✅ SystemMessage: {system_msg.role} - {len(system_msg.content)} chars")

    # 2. User message
    user_msg = create_user_message(
        "Please analyze the sales data and find trends.",
        metadata={"user_id": "user123"}
    )
    messages.append(user_msg)
    print(f"✅ UserMessage: {user_msg.role} - {user_msg.content}")

    # 3. Assistant message with ReAct reasoning (just regular content)
    react_content = """**Thought:** I need to analyze the sales data to find trends.
**Observation:** I don't have access to the sales data yet.
**Action:** I'll use the load_data tool to get the sales data first."""

    react_msg = create_assistant_message(react_content)
    messages.append(react_msg)
    print(f"✅ AssistantMessage with ReAct reasoning: {react_msg.role}")
    print(f"   - Content includes structured reasoning: {len(react_content)} chars")

    # 4. Tool message
    tool_msg = create_tool_message(
        content="Successfully loaded 1000 rows of sales data",
        tool_call_id="call_123",
        tool_name="load_data",
        success=True,
        metadata={"rows_loaded": 1000}
    )
    messages.append(tool_msg)
    print(f"✅ ToolMessage: {tool_msg.tool_name} - Success: {tool_msg.success}")

    # 5. Status update (just regular user message - status belongs in events, not conversation)
    status_msg = create_user_message("Iteration 2/10 | Budget remaining: $4.50")
    messages.append(status_msg)
    print(f"✅ UserMessage for status: {status_msg.role} - Status updates in conversation context")

    # 6. Regular assistant message
    assistant_msg = create_assistant_message(
        "Based on the data analysis, I found 3 key trends...",
        tool_calls=[{
            "id": "call_456",
            "type": "function",
            "function": {"name": "generate_report", "arguments": "{}"}
        }]
    )
    messages.append(assistant_msg)
    print(f"✅ AssistantMessage: {len(assistant_msg.content)} chars, {len(assistant_msg.tool_calls or [])} tool calls")

    return messages


def test_backward_compatibility():
    """Test backward compatibility with legacy Message class."""
    print("\n=== Testing Backward Compatibility ===\n")

    # Create a new message type
    system_msg = create_system_message("You are a helpful assistant.")

    # Convert to legacy format
    legacy_msg = Message.from_base_message(system_msg)
    print(f"✅ Legacy conversion: {legacy_msg.role} - {legacy_msg.content}")

    # Convert back to specialized type
    specialized_msg = legacy_msg.to_specialized_message()
    print(f"✅ Specialized conversion: {type(specialized_msg).__name__} - {specialized_msg.role}")

    # Test that it works with existing workflow code
    legacy_messages = [
        Message(role="system", content="System prompt"),
        Message(role="user", content="User query"),
        Message(role="assistant", content="Assistant response", tool_calls=[]),
        Message(role="tool", content="Tool result", tool_call_id="call_123", name="test_tool")
    ]

    print(f"✅ Legacy messages work: {len(legacy_messages)} messages created")

    # Convert all to specialized types
    specialized_messages = [msg.to_specialized_message() for msg in legacy_messages]
    message_types = [type(msg).__name__ for msg in specialized_messages]
    print(f"✅ Converted to: {', '.join(message_types)}")

    print("\n✅ Core conversation types only:")
    print("   - SystemMessage: Instructions and context")
    print("   - UserMessage: User input and status updates")
    print("   - AssistantMessage: Agent responses (including ReAct reasoning)")
    print("   - ToolMessage: Tool execution results")
    print("   - No specialized ReAct or Status messages - they don't belong in conversation history")


def test_extensibility():
    """Test how easy it is to extend the message hierarchy."""
    print("\n=== Testing Extensibility ===\n")

    # Example: Create a custom message type for debugging
    from dataclasses import dataclass, field

    @dataclass
    class DebugMessage(BaseMessage):
        """Custom message type for debugging information."""
        role: str = field(default="debug", init=False)
        debug_level: str = "info"
        execution_time: float | None = None
        memory_usage: int | None = None

    # Create a debug message
    debug_msg = DebugMessage(
        content="LLM call completed successfully",
        debug_level="info",
        execution_time=1.23,
        memory_usage=512,
        metadata={"model": "gpt-4", "tokens": 150}
    )

    print(f"✅ Custom DebugMessage: {debug_msg.debug_level} - {debug_msg.execution_time}s")
    print(f"   Content: {debug_msg.content}")
    print(f"   Memory: {debug_msg.memory_usage}MB")

    # Example: Extend AssistantMessage for domain-specific reasoning
    from typing import Any

    @dataclass
    class DataAnalysisMessage(AssistantMessage):
        """Specialized assistant message for data analysis tasks."""
        dataset_info: dict[str, Any] = field(default_factory=dict)
        analysis_type: str = "exploratory"
        confidence_score: float | None = None

    analysis_msg = DataAnalysisMessage(
        content="**Thought:** The data shows seasonal patterns...",
        dataset_info={"rows": 1000, "columns": 15},
        analysis_type="trend_analysis",
        confidence_score=0.85
    )

    print(f"✅ Custom DataAnalysisMessage: {analysis_msg.analysis_type}")
    print(f"   Dataset: {analysis_msg.dataset_info}")
    print(f"   Confidence: {analysis_msg.confidence_score}")
    print(f"   Role: {analysis_msg.role} (extends AssistantMessage)")

    print("\n✅ Clean Architecture Principles:")
    print("   - Conversation history contains only actual conversation")
    print("   - ReAct reasoning is just structured content in AssistantMessage")
    print("   - Status/iteration info belongs in event sourcing, not conversation")
    print("   - Easy to extend core message types for specific domains")


def main():
    """Run all tests."""
    print("Testing Enhanced Message Hierarchy\n")

    messages = test_message_hierarchy()
    test_backward_compatibility()
    test_extensibility()

    print("\n" + "="*50)
    print("BENEFITS OF NEW MESSAGE HIERARCHY")
    print("="*50)

    print("✅ Type Safety: Each message type has specific fields")
    print("✅ Clean Architecture: Only core conversation types in history")
    print("✅ Structure: Clear separation of concerns")
    print("✅ Metadata: Rich metadata support for all messages")
    print("✅ Backward Compatibility: Legacy Message class still works")
    print("✅ Factory Functions: Easy message creation")
    print("✅ Proper Separation: ReAct reasoning in content, status in events")
    print("✅ Validation: Type-specific validation possible")

    print(f"\nCreated {len(messages)} different message types successfully!")


if __name__ == "__main__":
    main()
