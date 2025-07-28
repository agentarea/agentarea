"""Tests for ADK Event serialization utilities."""

import pytest
from google.genai import types

from ..utils.event_serializer import EventSerializer
from ...ag.adk.events.event import Event
from ...ag.adk.events.event_actions import EventActions


class TestEventSerializer:
    """Test suite for EventSerializer utility class."""
    
    def test_event_to_dict_basic(self):
        """Test basic event to dict conversion."""
        # Create a simple event
        event = Event(
            author="test_agent",
            invocation_id="test_invocation",
            content=types.Content(parts=[
                types.Part(text="Hello, world!")
            ])
        )
        
        # Convert to dict
        event_dict = EventSerializer.event_to_dict(event)
        
        # Verify structure
        assert isinstance(event_dict, dict)
        assert event_dict["author"] == "test_agent"
        assert event_dict["invocation_id"] == "test_invocation"
        assert "content" in event_dict
        assert "id" in event_dict
        assert "timestamp" in event_dict
    
    def test_dict_to_event_basic(self):
        """Test basic dict to event conversion."""
        # Create event dict
        event_dict = {
            "author": "test_agent",
            "invocation_id": "test_invocation",
            "content": {
                "parts": [{"text": "Hello, world!"}]
            },
            "id": "test_id",
            "timestamp": 1234567890.0,
            "actions": {}
        }
        
        # Convert to event
        event = EventSerializer.dict_to_event(event_dict)
        
        # Verify structure
        assert isinstance(event, Event)
        assert event.author == "test_agent"
        assert event.invocation_id == "test_invocation"
        assert event.id == "test_id"
        assert event.timestamp == 1234567890.0
    
    def test_round_trip_conversion(self):
        """Test that event -> dict -> event preserves data."""
        # Create original event
        original = Event(
            author="test_agent",
            invocation_id="test_invocation",
            content=types.Content(parts=[
                types.Part(text="Test message"),
                types.Part(text="Another part")
            ]),
            branch="agent_1.agent_2"
        )
        
        # Convert to dict and back
        event_dict = EventSerializer.event_to_dict(original)
        restored = EventSerializer.dict_to_event(event_dict)
        
        # Verify key fields are preserved
        assert restored.author == original.author
        assert restored.invocation_id == original.invocation_id
        assert restored.branch == original.branch
        assert restored.id == original.id
    
    def test_long_running_tool_ids_serialization(self):
        """Test serialization of long running tool IDs (set -> list -> set)."""
        # Create event with long running tool IDs
        event = Event(
            author="test_agent",
            invocation_id="test_invocation",
            long_running_tool_ids={"tool1", "tool2", "tool3"}
        )
        
        # Convert to dict
        event_dict = EventSerializer.event_to_dict(event)
        
        # Should be converted to list for JSON serialization
        assert isinstance(event_dict["long_running_tool_ids"], list)
        assert set(event_dict["long_running_tool_ids"]) == {"tool1", "tool2", "tool3"}
        
        # Convert back to event
        restored = EventSerializer.dict_to_event(event_dict)
        
        # Should be restored as set
        assert isinstance(restored.long_running_tool_ids, set)
        assert restored.long_running_tool_ids == {"tool1", "tool2", "tool3"}
    
    def test_serialize_events_list(self):
        """Test serializing a list of events."""
        events = [
            Event(author="agent1", invocation_id="inv1"),
            Event(author="agent2", invocation_id="inv2"),
            Event(author="agent3", invocation_id="inv3")
        ]
        
        # Serialize list
        events_data = EventSerializer.serialize_events(events)
        
        # Verify structure
        assert isinstance(events_data, list)
        assert len(events_data) == 3
        assert all(isinstance(event_dict, dict) for event_dict in events_data)
        assert [e["author"] for e in events_data] == ["agent1", "agent2", "agent3"]
    
    def test_deserialize_events_list(self):
        """Test deserializing a list of events."""
        events_data = [
            {"author": "agent1", "invocation_id": "inv1", "actions": {}, "id": "1", "timestamp": 1.0},
            {"author": "agent2", "invocation_id": "inv2", "actions": {}, "id": "2", "timestamp": 2.0},
            {"author": "agent3", "invocation_id": "inv3", "actions": {}, "id": "3", "timestamp": 3.0}
        ]
        
        # Deserialize list
        events = EventSerializer.deserialize_events(events_data)
        
        # Verify structure
        assert isinstance(events, list)
        assert len(events) == 3
        assert all(isinstance(event, Event) for event in events)
        assert [e.author for e in events] == ["agent1", "agent2", "agent3"]
    
    def test_extract_final_response(self):
        """Test extracting final response text from events."""
        # Event with text content
        event_with_text = Event(
            author="agent",
            invocation_id="inv",
            content=types.Content(parts=[
                types.Part(text="This is the final response")
            ])
        )
        
        response = EventSerializer.extract_final_response(event_with_text)
        assert response == "This is the final response"
        
        # Event with multiple text parts
        event_multi_text = Event(
            author="agent",
            invocation_id="inv",
            content=types.Content(parts=[
                types.Part(text="Part 1"),
                types.Part(text="Part 2")
            ])
        )
        
        response = EventSerializer.extract_final_response(event_multi_text)
        assert response == "Part 1\nPart 2"
        
        # Event with no content
        event_no_content = Event(
            author="agent",
            invocation_id="inv"
        )
        
        response = EventSerializer.extract_final_response(event_no_content)
        assert response is None
    
    def test_is_streaming_event(self):
        """Test detecting streaming/partial events."""
        # Non-streaming event
        normal_event = Event(
            author="agent",
            invocation_id="inv"
        )
        assert not EventSerializer.is_streaming_event(normal_event)
        
        # Streaming event (assuming partial attribute exists)
        streaming_event = Event(
            author="agent",
            invocation_id="inv"
        )
        streaming_event.partial = True
        assert EventSerializer.is_streaming_event(streaming_event)
    
    def test_has_function_calls(self):
        """Test detecting events with function calls."""
        # Event without function calls
        normal_event = Event(
            author="agent",
            invocation_id="inv",
            content=types.Content(parts=[
                types.Part(text="Normal message")
            ])
        )
        assert not EventSerializer.has_function_calls(normal_event)
        
        # Event with function call
        function_call_event = Event(
            author="agent",
            invocation_id="inv",
            content=types.Content(parts=[
                types.Part(function_call=types.FunctionCall(
                    name="test_function",
                    args={"arg1": "value1"}
                ))
            ])
        )
        assert EventSerializer.has_function_calls(function_call_event)
    
    def test_has_function_responses(self):
        """Test detecting events with function responses."""
        # Event without function responses
        normal_event = Event(
            author="agent",
            invocation_id="inv",
            content=types.Content(parts=[
                types.Part(text="Normal message")
            ])
        )
        assert not EventSerializer.has_function_responses(normal_event)
        
        # Event with function response
        function_response_event = Event(
            author="agent",
            invocation_id="inv",
            content=types.Content(parts=[
                types.Part(function_response=types.FunctionResponse(
                    name="test_function",
                    response={"result": "Function result"}
                ))
            ])
        )
        assert EventSerializer.has_function_responses(function_response_event)
    
    def test_serialize_content(self):
        """Test content serialization."""
        # Test with content
        content = types.Content(parts=[
            types.Part(text="Test content")
        ])
        
        content_dict = EventSerializer.serialize_content(content)
        assert isinstance(content_dict, dict)
        assert "parts" in content_dict
        
        # Test with None
        content_dict = EventSerializer.serialize_content(None)
        assert content_dict is None
    
    def test_deserialize_content(self):
        """Test content deserialization."""
        # Test with content dict
        content_dict = {
            "parts": [{"text": "Test content"}]
        }
        
        content = EventSerializer.deserialize_content(content_dict)
        assert isinstance(content, types.Content)
        assert len(content.parts) == 1
        assert content.parts[0].text == "Test content"
        
        # Test with None
        content = EventSerializer.deserialize_content(None)
        assert content is None