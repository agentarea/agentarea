"""Tests for ADK Temporal activities."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from google.genai import types

from ..activities.adk_agent_activities import (
    execute_adk_agent_activity,
    validate_adk_agent_config,
    _dict_to_adk_content
)
from ..utils.event_serializer import EventSerializer
from ...ag.adk.events.event import Event


class TestADKActivities:
    """Test suite for ADK Temporal activities."""
    
    @pytest.fixture
    def sample_agent_config(self):
        """Sample agent configuration for testing."""
        return {
            "name": "test_agent",
            "model": "gpt-4",
            "instructions": "You are a helpful test assistant",
            "description": "Test agent for unit tests"
        }
    
    @pytest.fixture
    def sample_session_data(self):
        """Sample session data for testing."""
        return {
            "user_id": "test_user",
            "session_id": "test_session",
            "app_name": "agentarea",
            "state": {}
        }
    
    @pytest.fixture
    def sample_user_message(self):
        """Sample user message for testing."""
        return {
            "content": "Hello, please help me with a test task",
            "role": "user"
        }
    
    def test_dict_to_adk_content_string(self):
        """Test converting string content to ADK Content."""
        message_dict = {"content": "Hello, world!"}
        
        content = _dict_to_adk_content(message_dict)
        
        assert isinstance(content, types.Content)
        assert len(content.parts) == 1
        assert content.parts[0].text == "Hello, world!"
    
    def test_dict_to_adk_content_dict(self):
        """Test converting structured content to ADK Content."""
        message_dict = {
            "content": {
                "parts": [{"text": "Structured content"}]
            }
        }
        
        content = _dict_to_adk_content(message_dict)
        
        assert isinstance(content, types.Content)
        # Note: This test may need adjustment based on actual deserialization behavior
    
    def test_dict_to_adk_content_fallback(self):
        """Test fallback behavior for unexpected content types."""
        message_dict = {"content": 123}  # Numeric content
        
        content = _dict_to_adk_content(message_dict)
        
        assert isinstance(content, types.Content)
        assert len(content.parts) == 1
        assert content.parts[0].text == "123"
    
    @pytest.mark.asyncio
    async def test_validate_adk_agent_config_valid(self, sample_agent_config):
        """Test validation of valid agent configuration."""
        result = await validate_adk_agent_config(sample_agent_config)
        
        assert isinstance(result, dict)
        assert result["valid"] is True
        assert isinstance(result["errors"], list)
        assert isinstance(result["warnings"], list)
        assert len(result["errors"]) == 0
    
    @pytest.mark.asyncio
    async def test_validate_adk_agent_config_invalid_no_name(self):
        """Test validation of invalid agent configuration (no name)."""
        invalid_config = {"model": "gpt-4"}
        
        result = await validate_adk_agent_config(invalid_config)
        
        assert isinstance(result, dict)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any("name" in error.lower() for error in result["errors"])
    
    @pytest.mark.asyncio
    async def test_validate_adk_agent_config_invalid_tools(self):
        """Test validation of invalid agent configuration (bad tools)."""
        invalid_config = {
            "name": "test_agent",
            "tools": "not_a_list"  # Should be a list
        }
        
        result = await validate_adk_agent_config(invalid_config)
        
        assert isinstance(result, dict)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
    
    @pytest.mark.asyncio
    async def test_validate_adk_agent_config_warnings(self):
        """Test validation warnings for missing optional fields."""
        config_without_model = {"name": "test_agent"}
        
        result = await validate_adk_agent_config(config_without_model)
        
        assert isinstance(result, dict)
        # Should be valid but may have warnings
        assert result["valid"] is True
        # Warnings depend on implementation details
    
    @pytest.mark.asyncio
    @patch('agentarea_execution.adk_temporal.services.adk_service_factory.create_adk_runner')
    async def test_execute_adk_agent_activity_success(
        self,
        mock_create_runner,
        sample_agent_config,
        sample_session_data,
        sample_user_message
    ):
        """Test successful ADK agent activity execution."""
        # Mock the runner and its execution
        mock_runner = Mock()
        mock_create_runner.return_value = mock_runner
        
        # Create sample events that the agent would generate
        sample_events = [
            Event(
                author="test_agent",
                invocation_id="test_inv",
                content=types.Content(parts=[
                    types.Part(text="I'm processing your request...")
                ])
            ),
            Event(
                author="test_agent", 
                invocation_id="test_inv",
                content=types.Content(parts=[
                    types.Part(text="Here's my final response")
                ])
            )
        ]
        
        # Make the second event a final response
        sample_events[1].actions.skip_summarization = True
        
        # Mock the async generator
        async def mock_run_async(*args, **kwargs):
            for event in sample_events:
                yield event
        
        mock_runner.run_async = mock_run_async
        
        # Execute the activity
        result = await execute_adk_agent_activity(
            sample_agent_config,
            sample_session_data,
            sample_user_message
        )
        
        # Verify results
        assert isinstance(result, list)
        assert len(result) == 2
        
        # Verify events were serialized
        for event_dict in result:
            assert isinstance(event_dict, dict)
            assert "author" in event_dict
            assert "invocation_id" in event_dict
            assert "content" in event_dict
    
    @pytest.mark.asyncio
    async def test_execute_adk_agent_activity_invalid_config(
        self,
        sample_session_data,
        sample_user_message
    ):
        """Test ADK agent activity with invalid configuration."""
        invalid_config = {}  # Missing required name field
        
        result = await execute_adk_agent_activity(
            invalid_config,
            sample_session_data,
            sample_user_message
        )
        
        # Should return error event
        assert isinstance(result, list)
        assert len(result) == 1
        
        error_event_dict = result[0]
        assert "author" in error_event_dict
        
        # Convert back to event to check content
        error_event = EventSerializer.dict_to_event(error_event_dict)
        error_text = EventSerializer.extract_final_response(error_event)
        assert error_text is not None
        assert "failed" in error_text.lower()
    
    @pytest.mark.asyncio
    async def test_execute_adk_agent_activity_no_message_content(
        self,
        sample_agent_config,
        sample_session_data
    ):
        """Test ADK agent activity with no message content."""
        empty_message = {"role": "user"}  # Missing content
        
        result = await execute_adk_agent_activity(
            sample_agent_config,
            sample_session_data,
            empty_message
        )
        
        # Should return error event
        assert isinstance(result, list)
        assert len(result) == 1
        
        error_event_dict = result[0]
        error_event = EventSerializer.dict_to_event(error_event_dict)
        error_text = EventSerializer.extract_final_response(error_event)
        assert error_text is not None
        assert "content is required" in error_text.lower()
    
    @pytest.mark.asyncio
    @patch('agentarea_execution.adk_temporal.services.adk_service_factory.create_adk_runner')
    async def test_execute_adk_agent_activity_runner_exception(
        self,
        mock_create_runner,
        sample_agent_config,
        sample_session_data,
        sample_user_message
    ):
        """Test ADK agent activity when runner raises exception."""
        # Mock runner to raise exception
        mock_runner = Mock()
        mock_create_runner.return_value = mock_runner
        
        async def mock_run_async_error(*args, **kwargs):
            raise RuntimeError("Test runner error")
        
        mock_runner.run_async = mock_run_async_error
        
        result = await execute_adk_agent_activity(
            sample_agent_config,
            sample_session_data,
            sample_user_message
        )
        
        # Should return error event
        assert isinstance(result, list)
        assert len(result) == 1
        
        error_event_dict = result[0]
        error_event = EventSerializer.dict_to_event(error_event_dict)
        error_text = EventSerializer.extract_final_response(error_event)
        assert error_text is not None
        assert "Test runner error" in error_text
    
    @pytest.mark.asyncio
    @patch('agentarea_execution.adk_temporal.services.adk_service_factory.create_adk_runner')
    async def test_execute_adk_agent_activity_event_counting(
        self,
        mock_create_runner,
        sample_agent_config,
        sample_session_data,
        sample_user_message
    ):
        """Test that activity properly counts and processes events."""
        mock_runner = Mock()
        mock_create_runner.return_value = mock_runner
        
        # Create many events to test counting logic
        sample_events = []
        for i in range(15):  # More than the logging threshold of 10
            event = Event(
                author="test_agent",
                invocation_id="test_inv",
                content=types.Content(parts=[
                    types.Part(text=f"Event {i}")
                ])
            )
            sample_events.append(event)
        
        # Make the last event final
        sample_events[-1].actions.skip_summarization = True
        
        async def mock_run_async(*args, **kwargs):
            for event in sample_events:
                yield event
        
        mock_runner.run_async = mock_run_async
        
        result = await execute_adk_agent_activity(
            sample_agent_config,
            sample_session_data,
            sample_user_message
        )
        
        # Should have all events
        assert len(result) == 15
        
        # Verify content of events
        for i, event_dict in enumerate(result):
            event = EventSerializer.dict_to_event(event_dict)
            response_text = EventSerializer.extract_final_response(event)
            assert f"Event {i}" in response_text