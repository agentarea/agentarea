"""Integration tests for ADK-Temporal system."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from ..workflows.adk_agent_workflow import ADKAgentWorkflow
from ..activities.adk_agent_activities import execute_adk_agent_activity, validate_adk_agent_config
from ..services.adk_service_factory import create_adk_runner, create_default_session_data
from ..utils.agent_builder import create_simple_agent_config
from ..utils.event_serializer import EventSerializer
from ...models import AgentExecutionRequest, AgentExecutionResult
from ...ag.adk.events.event import Event
from google.genai import types


class TestADKTemporalIntegration:
    """Integration tests for the complete ADK-Temporal system."""
    
    @pytest.fixture
    def simple_task_request(self):
        """Simple task execution request."""
        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            task_query="What is 2 + 2?",
            task_parameters={},
            requires_human_approval=False,
            budget_usd=5.0
        )
    
    @pytest.fixture
    def complex_task_request(self):
        """Complex task execution request."""
        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            task_query="Please analyze the following data and provide insights: [1, 2, 3, 4, 5]",
            task_parameters={
                "analysis_type": "statistical",
                "output_format": "detailed"
            },
            requires_human_approval=False,
            budget_usd=15.0
        )
    
    def test_create_simple_agent_config_integration(self):
        """Test agent configuration creation for integration."""
        config = create_simple_agent_config(
            name="integration_test_agent",
            model="gpt-4",
            instructions="You are a helpful assistant for integration testing",
            description="Integration test agent"
        )
        
        assert config["name"] == "integration_test_agent"
        assert config["model"] == "gpt-4"
        assert "integration testing" in config["instructions"]
        assert config["description"] == "Integration test agent"
    
    def test_create_default_session_data_integration(self):
        """Test session data creation for integration."""
        session_data = create_default_session_data(
            user_id="integration_test_user",
            app_name="agentarea_test"
        )
        
        assert session_data["user_id"] == "integration_test_user"
        assert session_data["app_name"] == "agentarea_test"
        assert "session_id" in session_data
        assert "state" in session_data
        assert "created_time" in session_data
    
    @pytest.mark.asyncio
    async def test_validate_agent_config_integration(self):
        """Test agent configuration validation in integration context."""
        # Valid configuration
        valid_config = create_simple_agent_config(
            name="valid_agent",
            model="gpt-4"
        )
        
        result = await validate_adk_agent_config(valid_config)
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        
        # Invalid configuration
        invalid_config = {"model": "gpt-4"}  # Missing name
        
        result = await validate_adk_agent_config(invalid_config)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
    
    @pytest.mark.asyncio
    @patch('agentarea_execution.adk_temporal.services.adk_service_factory.build_adk_agent_from_config')
    @patch('agentarea_execution.ag.adk.runners.Runner')
    async def test_execute_adk_agent_activity_integration(self, mock_runner_class, mock_build_agent):
        """Test complete ADK agent activity execution."""
        # Setup mocks
        mock_agent = Mock()
        mock_agent.name = "test_agent"
        mock_build_agent.return_value = mock_agent
        
        mock_runner = Mock()
        mock_runner_class.return_value = mock_runner
        
        # Create realistic events
        events = [
            Event(
                author="test_agent",
                invocation_id="test_inv",
                content=types.Content(parts=[
                    types.Part(text="I understand you want to know what 2 + 2 equals.")
                ])
            ),
            Event(
                author="test_agent", 
                invocation_id="test_inv",
                content=types.Content(parts=[
                    types.Part(text="The answer is 4.")
                ])
            )
        ]
        
        # Make the last event final
        events[-1].actions.skip_summarization = True
        
        # Mock the async generator
        async def mock_run_async(*args, **kwargs):
            for event in events:
                yield event
        
        mock_runner.run_async = mock_run_async
        
        # Test data
        agent_config = create_simple_agent_config("math_agent", instructions="You are a math assistant")
        session_data = create_default_session_data("test_user")
        user_message = {"content": "What is 2 + 2?", "role": "user"}
        
        # Execute activity
        result = await execute_adk_agent_activity(
            agent_config,
            session_data,
            user_message
        )
        
        # Verify results
        assert isinstance(result, list)
        assert len(result) == 2
        
        # Verify event structure
        for event_dict in result:
            assert "author" in event_dict
            assert "invocation_id" in event_dict
            assert "content" in event_dict
            
        # Verify we can deserialize events
        deserialized_events = EventSerializer.deserialize_events(result)
        assert len(deserialized_events) == 2
        assert all(isinstance(e, Event) for e in deserialized_events)
        
        # Verify final response extraction
        final_response = None
        for event in deserialized_events:
            if event.is_final_response():
                final_response = EventSerializer.extract_final_response(event)
                break
        
        assert final_response is not None
        assert "4" in final_response
    
    @pytest.mark.asyncio
    @patch('agentarea_execution.adk_temporal.activities.adk_agent_activities.execute_adk_agent_activity')
    @patch('agentarea_execution.adk_temporal.activities.adk_agent_activities.validate_adk_agent_config')
    async def test_workflow_integration_success(self, mock_validate, mock_execute, simple_task_request):
        """Test complete workflow integration with successful execution."""
        # Mock validation
        mock_validate.return_value = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        # Mock execution with realistic events
        mock_events = [
            {
                "author": "agent",
                "invocation_id": "test_inv",
                "content": {"parts": [{"text": "Let me calculate 2 + 2 for you."}]},
                "actions": {"skip_summarization": False},
                "id": "1",
                "timestamp": 1.0
            },
            {
                "author": "agent",
                "invocation_id": "test_inv", 
                "content": {"parts": [{"text": "The answer is 4."}]},
                "actions": {"skip_summarization": True},
                "id": "2",
                "timestamp": 2.0
            }
        ]
        mock_execute.return_value = mock_events
        
        # Create and initialize workflow
        workflow = ADKAgentWorkflow()
        
        # Test workflow execution components
        await workflow._initialize_workflow(simple_task_request)
        
        # Verify initialization
        assert workflow.state.execution_id != ""
        assert workflow.state.agent_config["name"] == f"agent_{simple_task_request.agent_id}"
        assert workflow.state.user_message["content"] == "What is 2 + 2?"
        
        # Test validation
        await workflow._validate_configuration()
        
        # Test batch execution simulation
        workflow.state.events = mock_events
        final_response = workflow._extract_final_response(mock_events)
        assert final_response == "The answer is 4."
        
        workflow.state.final_response = final_response
        workflow.state.success = True
        
        # Test finalization
        result = await workflow._finalize_execution({"event_count": 2, "success": True})
        
        assert isinstance(result, AgentExecutionResult)
        assert result.success is True
        assert result.final_response == "The answer is 4."
        assert result.task_id == simple_task_request.task_id
        assert result.agent_id == simple_task_request.agent_id
    
    @pytest.mark.asyncio
    @patch('agentarea_execution.adk_temporal.activities.adk_agent_activities.validate_adk_agent_config')
    async def test_workflow_integration_validation_failure(self, mock_validate, simple_task_request):
        """Test workflow integration with validation failure."""
        # Mock validation failure
        mock_validate.return_value = {
            "valid": False,
            "errors": ["Agent name is required", "Invalid model specified"],
            "warnings": []
        }
        
        workflow = ADKAgentWorkflow()
        await workflow._initialize_workflow(simple_task_request)
        
        # Validation should raise exception
        with pytest.raises(Exception) as exc_info:
            await workflow._validate_configuration()
        
        assert "validation failed" in str(exc_info.value).lower()
    
    def test_event_serialization_round_trip_integration(self):
        """Test complete event serialization round trip in integration context."""
        # Create complex event with various content types
        original_event = Event(
            author="integration_agent",
            invocation_id="integration_test",
            content=types.Content(parts=[
                types.Part(text="Here's my analysis:"),
                types.Part(function_call=types.FunctionCall(
                    name="calculate_stats",
                    args={"data": [1, 2, 3, 4, 5]}
                ))
            ]),
            branch="main_agent.analysis_agent",
            long_running_tool_ids={"stats_tool", "viz_tool"}
        )
        
        # Serialize to dict
        event_dict = EventSerializer.event_to_dict(original_event)
        
        # Verify dict structure
        assert event_dict["author"] == "integration_agent"
        assert event_dict["invocation_id"] == "integration_test"
        assert event_dict["branch"] == "main_agent.analysis_agent"
        assert isinstance(event_dict["long_running_tool_ids"], list)
        assert set(event_dict["long_running_tool_ids"]) == {"stats_tool", "viz_tool"}
        
        # Deserialize back to event
        restored_event = EventSerializer.dict_to_event(event_dict)
        
        # Verify restoration
        assert restored_event.author == original_event.author
        assert restored_event.invocation_id == original_event.invocation_id
        assert restored_event.branch == original_event.branch
        assert restored_event.long_running_tool_ids == original_event.long_running_tool_ids
        
        # Verify function calls
        original_calls = original_event.get_function_calls()
        restored_calls = restored_event.get_function_calls()
        assert len(original_calls) == len(restored_calls)
        
        if original_calls:
            assert original_calls[0].name == restored_calls[0].name
    
    @pytest.mark.asyncio
    async def test_error_handling_integration(self):
        """Test error handling throughout the integration."""
        # Test validation error handling
        invalid_config = {}
        result = await validate_adk_agent_config(invalid_config)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        
        # Test event serialization error handling
        try:
            # This should handle gracefully
            EventSerializer.dict_to_event({"invalid": "event_data"})
        except Exception as e:
            # Should be a specific, handled exception
            assert isinstance(e, (ValueError, TypeError, KeyError))
        
        # Test workflow error handling
        workflow = ADKAgentWorkflow()
        test_error = RuntimeError("Integration test error")
        
        await workflow._handle_workflow_error(test_error)
        assert workflow.state.error_message == "Integration test error"
        assert workflow.state.success is False
    
    def test_workflow_state_queries_integration(self):
        """Test workflow state queries in integration context."""
        workflow = ADKAgentWorkflow()
        
        # Set realistic state
        workflow.state.execution_id = "integration_execution_123"
        workflow.state.agent_config = {
            "name": "integration_agent",
            "model": "gpt-4",
            "instructions": "Integration test instructions"
        }
        workflow.state.events = [
            {"event": "data1", "timestamp": 1.0},
            {"event": "data2", "timestamp": 2.0}
        ]
        workflow.state.success = True
        workflow.state.final_response = "Integration test completed successfully"
        
        # Test current state query
        state = workflow.get_current_state()
        assert state["execution_id"] == "integration_execution_123"
        assert state["agent_name"] == "integration_agent"
        assert state["event_count"] == 2
        assert state["success"] is True
        assert state["has_final_response"] is True
        
        # Test events query
        events = workflow.get_events(limit=1)
        assert len(events) == 1
        assert events[0]["event"] == "data2"  # Should get most recent
        
        # Test final response query
        response = workflow.get_final_response()
        assert response == "Integration test completed successfully"
    
    @pytest.mark.asyncio
    async def test_pause_resume_integration(self):
        """Test pause/resume functionality in integration context."""
        workflow = ADKAgentWorkflow()
        
        # Initial state
        assert not workflow.state.paused
        
        # Test pause
        await workflow.pause("Integration test pause")
        assert workflow.state.paused
        assert workflow.state.pause_reason == "Integration test pause"
        
        # Verify state query reflects pause
        state = workflow.get_current_state()
        assert state["paused"] is True
        assert state["pause_reason"] == "Integration test pause"
        
        # Test resume
        await workflow.resume("Integration test resume")
        assert not workflow.state.paused
        assert workflow.state.pause_reason == ""
        
        # Verify state query reflects resume
        state = workflow.get_current_state()
        assert state["paused"] is False
        assert state["pause_reason"] == ""