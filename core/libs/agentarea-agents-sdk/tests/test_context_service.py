from typing import Any

import pytest

from agentarea_agents_sdk.context import (
    ContextEvent,
    InMemoryContextService,
    create_context_event_listener,
    events_to_messages,
)


class TestInMemoryContextService:
    """Test the core context service functionality."""

    @pytest.fixture
    def context_service(self) -> InMemoryContextService:
        return InMemoryContextService()

    @pytest.mark.asyncio
    async def test_append_and_list_events(self, context_service: InMemoryContextService):
        """Test basic event storage and retrieval."""
        task_id = "test-task"

        event1 = ContextEvent(type="assistant_message", payload={"content": "Hello"})
        event2 = ContextEvent(
            type="tool_execution_finished", payload={"tool_name": "search", "result": "done"}
        )

        await context_service.append_event(task_id, event1)
        await context_service.append_event(task_id, event2)

        events = await context_service.list_events(task_id)
        assert len(events) == 2
        assert events[0].type == "assistant_message"
        assert events[1].type == "tool_execution_finished"

        # Events should have task_id set
        assert events[0].task_id == task_id
        assert events[1].task_id == task_id

    @pytest.mark.asyncio
    async def test_limit_events(self, context_service: InMemoryContextService):
        """Test event limit functionality."""
        task_id = "test-task"

        # Add multiple events
        for i in range(5):
            event = ContextEvent(type="test", payload={"index": i})
            await context_service.append_event(task_id, event)

        # Get limited events
        recent_events = await context_service.list_events(task_id, limit=2)
        assert len(recent_events) == 2
        assert recent_events[0].payload["index"] == 3  # Last 2 should be index 3,4
        assert recent_events[1].payload["index"] == 4

    @pytest.mark.asyncio
    async def test_state_management(self, context_service: InMemoryContextService):
        """Test per-task state management."""
        task_id = "test-task"

        await context_service.set_state(task_id, "key1", "value1")
        await context_service.set_state(task_id, "key2", {"nested": True})

        assert await context_service.get_state(task_id, "key1") == "value1"
        assert await context_service.get_state(task_id, "key2") == {"nested": True}
        assert await context_service.get_state(task_id, "missing", "default") == "default"

    @pytest.mark.asyncio
    async def test_multiple_tasks(self, context_service: InMemoryContextService):
        """Test isolation between different tasks."""
        task1 = "task-1"
        task2 = "task-2"

        await context_service.append_event(task1, ContextEvent(type="event1"))
        await context_service.append_event(task2, ContextEvent(type="event2"))

        await context_service.set_state(task1, "key", "value1")
        await context_service.set_state(task2, "key", "value2")

        # Events should be isolated
        events1 = await context_service.list_events(task1)
        events2 = await context_service.list_events(task2)

        assert len(events1) == 1
        assert len(events2) == 1
        assert events1[0].type == "event1"
        assert events2[0].type == "event2"

        # State should be isolated
        assert await context_service.get_state(task1, "key") == "value1"
        assert await context_service.get_state(task2, "key") == "value2"


class TestEventsToMessages:
    """Test event to message conversion functionality."""

    def test_assistant_message_conversion(self):
        """Test assistant message event conversion."""
        events = [ContextEvent(type="assistant_message", payload={"content": "Hello world"})]

        messages = events_to_messages(events)

        assert len(messages) == 1
        assert messages[0] == {"role": "assistant", "content": "Hello world"}

    def test_assistant_message_with_tool_calls(self):
        """Test assistant message with tool calls conversion."""
        tool_calls = [{"id": "call1", "function": {"name": "test", "arguments": "{}"}}]
        events = [
            ContextEvent(
                type="assistant_message",
                payload={"content": "Let me search", "tool_calls": tool_calls},
            )
        ]

        messages = events_to_messages(events)

        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "Let me search"
        assert messages[0]["tool_calls"] == tool_calls

    def test_tool_execution_finished_conversion(self):
        """Test tool execution finished event conversion."""
        events = [
            ContextEvent(
                type="tool_execution_finished",
                payload={
                    "tool_name": "search",
                    "tool_call_id": "call1",
                    "result": "Found information",
                },
            )
        ]

        messages = events_to_messages(events)

        assert len(messages) == 1
        assert messages[0] == {
            "role": "tool",
            "tool_call_id": "call1",
            "name": "search",
            "content": "Found information",
        }

    def test_tool_execution_error_conversion(self):
        """Test tool execution error event conversion."""
        events = [
            ContextEvent(
                type="tool_execution_error",
                payload={
                    "tool_name": "search",
                    "tool_call_id": "call1",
                    "error": "Network timeout",
                },
            )
        ]

        messages = events_to_messages(events)

        assert len(messages) == 1
        assert messages[0] == {
            "role": "tool",
            "tool_call_id": "call1",
            "name": "search",
            "content": "Error: Network timeout",
        }

    def test_pending_tool_calls_handling(self):
        """Test handling of tool calls detected without assistant message."""
        tool_calls = [{"id": "call1", "function": {"name": "test", "arguments": "{}"}}]
        events = [ContextEvent(type="llm_tool_calls_detected", payload={"tool_calls": tool_calls})]

        messages = events_to_messages(events)

        assert len(messages) == 1
        assert messages[0] == {"role": "assistant", "content": "", "tool_calls": tool_calls}

    def test_deferred_tool_calls_attachment(self):
        """Test attaching detected tool calls to subsequent assistant message."""
        tool_calls = [{"id": "call1", "function": {"name": "test", "arguments": "{}"}}]
        events = [
            ContextEvent(type="llm_tool_calls_detected", payload={"tool_calls": tool_calls}),
            ContextEvent(type="assistant_message", payload={"content": "Using tools now"}),
        ]

        messages = events_to_messages(events)

        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "Using tools now"
        assert messages[0]["tool_calls"] == tool_calls

    def test_skipped_event_types(self):
        """Test that non-message events are properly skipped."""
        events = [
            ContextEvent(type="iteration_started"),
            ContextEvent(type="llm_chunk", payload={"content": "chunk"}),
            ContextEvent(type="assistant_message", payload={"content": "Hello"}),
            ContextEvent(type="completion_signaled"),
        ]

        messages = events_to_messages(events)

        # Only assistant_message should be converted
        assert len(messages) == 1
        assert messages[0] == {"role": "assistant", "content": "Hello"}

    def test_complete_conversation_flow(self):
        """Test a complete conversation with assistant, tool calls, and results."""
        events = [
            ContextEvent(
                type="assistant_message",
                payload={
                    "content": "I'll search for that",
                    "tool_calls": [
                        {"id": "call1", "function": {"name": "search", "arguments": "{}"}}
                    ],
                },
            ),
            ContextEvent(
                type="tool_execution_finished",
                payload={"tool_name": "search", "tool_call_id": "call1", "result": "Found results"},
            ),
            ContextEvent(type="assistant_message", payload={"content": "Here are the results"}),
        ]

        messages = events_to_messages(events)

        assert len(messages) == 3
        assert messages[0]["role"] == "assistant"
        assert messages[0]["tool_calls"][0]["id"] == "call1"
        assert messages[1]["role"] == "tool"
        assert messages[1]["tool_call_id"] == "call1"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "Here are the results"


class TestContextEventListener:
    """Test the context event listener functionality."""

    @pytest.fixture
    def context_service(self) -> InMemoryContextService:
        return InMemoryContextService()

    @pytest.mark.asyncio
    async def test_listener_mirrors_events(self, context_service: InMemoryContextService):
        """Test that the listener properly mirrors agent events."""
        task_id = "test-task"
        listener = create_context_event_listener(context_service, task_id)

        # Mock an agent event
        class MockEvent:
            def __init__(self, event_type: str, payload: dict[str, Any]):
                self.type = event_type
                self.payload = payload

        event = MockEvent("assistant_message", {"content": "Hello"})
        await listener(event)

        # Check that event was stored
        stored_events = await context_service.list_events(task_id)
        assert len(stored_events) == 1
        assert stored_events[0].type == "assistant_message"
        assert stored_events[0].payload["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_listener_error_handling(self, context_service: InMemoryContextService):
        """Test that listener handles errors gracefully."""
        task_id = "test-task"
        listener = create_context_event_listener(context_service, task_id)

        # Mock an invalid event that might cause errors
        invalid_event = object()  # No type/payload attributes

        # Should not raise exception
        await listener(invalid_event)

        # Implementation stores a default 'event' with empty payload for unknown shapes
        stored_events = await context_service.list_events(task_id)
        assert len(stored_events) == 1
        assert stored_events[0].type == "event"
        assert stored_events[0].payload == {}


@pytest.mark.asyncio
class TestContextPersistenceIntegration:
    """Test context persistence across agent runs and task delegation scenarios."""

    @pytest.fixture
    def context_service(self) -> InMemoryContextService:
        return InMemoryContextService()

    async def test_context_preloading_across_runs(self, context_service: InMemoryContextService):
        """Test that context is properly preloaded in subsequent agent runs."""
        task_id = "persistent-task"

        # Simulate first agent run - store some events manually
        await context_service.append_event(
            task_id,
            ContextEvent(
                type="assistant_message", payload={"content": "Initial message from first run"}
            ),
        )
        await context_service.append_event(
            task_id,
            ContextEvent(
                type="tool_execution_finished",
                payload={
                    "tool_name": "search",
                    "tool_call_id": "call1",
                    "result": "Previous search results",
                },
            ),
        )

        # Verify we can retrieve historical context
        prior_events = await context_service.list_events(task_id)
        assert len(prior_events) == 2

        # Convert to messages for LLM context
        history_messages = events_to_messages(prior_events)
        assert len(history_messages) == 2
        assert history_messages[0]["role"] == "assistant"
        assert history_messages[1]["role"] == "tool"

    async def test_multi_agent_task_delegation(self, context_service: InMemoryContextService):
        """Test context sharing between multiple agents working on related tasks."""
        parent_task_id = "parent-task"
        subtask_id = "subtask-1"

        # Parent agent creates context
        await context_service.append_event(
            parent_task_id,
            ContextEvent(
                type="assistant_message", payload={"content": "I need to delegate this subtask"}
            ),
        )

        # Subtask agent could access parent context if needed
        await context_service.list_events(parent_task_id)

        # Subtask agent creates its own context
        await context_service.append_event(
            subtask_id,
            ContextEvent(
                type="assistant_message", payload={"content": "Working on the delegated subtask"}
            ),
        )

        # Both contexts should be independent but accessible
        parent_events = await context_service.list_events(parent_task_id)
        subtask_events = await context_service.list_events(subtask_id)

        assert len(parent_events) == 1
        assert len(subtask_events) == 1
        assert parent_events[0].payload["content"] != subtask_events[0].payload["content"]

    async def test_context_state_persistence(self, context_service: InMemoryContextService):
        """Test that task state persists across operations."""
        task_id = "stateful-task"

        # Set initial state
        await context_service.set_state(task_id, "progress", {"completed_steps": 3})
        await context_service.set_state(task_id, "user_preferences", {"format": "json"})

        # Simulate agent restart - state should persist
        progress = await context_service.get_state(task_id, "progress")
        preferences = await context_service.get_state(task_id, "user_preferences")

        assert progress["completed_steps"] == 3
        assert preferences["format"] == "json"

        # Update state
        await context_service.set_state(task_id, "progress", {"completed_steps": 5})

        # Verify update
        updated_progress = await context_service.get_state(task_id, "progress")
        assert updated_progress["completed_steps"] == 5
