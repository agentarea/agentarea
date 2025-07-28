"""Tests for ADK Temporal workflow."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from datetime import timedelta

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from ..workflows.adk_agent_workflow import ADKAgentWorkflow, ADKAgentState
from ..activities.adk_agent_activities import (
    execute_adk_agent_activity,
    validate_adk_agent_config
)
from ...models import AgentExecutionRequest, AgentExecutionResult


class TestADKAgentWorkflow:
    """Test suite for ADK Agent Workflow."""
    
    @pytest.fixture
    def sample_execution_request(self):
        """Sample execution request for testing."""
        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(), 
            task_query="Please help me test the ADK integration",
            task_parameters={},
            requires_human_approval=False,
            budget_usd=10.0
        )
    
    def test_adk_agent_state_initialization(self):
        """Test ADK agent state initialization."""
        state = ADKAgentState()
        
        assert state.execution_id == ""
        assert state.agent_config == {}
        assert state.session_data == {}
        assert state.user_message == {}
        assert state.events == []
        assert state.final_response is None
        assert state.success is False
        assert state.error_message is None
        assert state.paused is False
        assert state.pause_reason == ""
    
    @pytest.mark.asyncio
    async def test_workflow_initialization(self, sample_execution_request):
        """Test workflow initialization with execution request."""
        async with WorkflowEnvironment() as env:
            # Create workflow instance
            workflow = ADKAgentWorkflow()
            
            # Test initialization method
            await workflow._initialize_workflow(sample_execution_request)
            
            # Verify state was initialized
            assert workflow.state.agent_config["name"] == f"agent_{sample_execution_request.agent_id}"
            assert workflow.state.session_data["user_id"] == str(sample_execution_request.task_id)
            assert workflow.state.session_data["app_name"] == "agentarea"
            assert workflow.state.user_message["content"] == sample_execution_request.task_query
            assert workflow.state.user_message["role"] == "user"
    
    @pytest.mark.asyncio
    async def test_build_agent_config(self, sample_execution_request):
        """Test building agent configuration from request."""
        workflow = ADKAgentWorkflow()
        
        config = await workflow._build_agent_config(sample_execution_request)
        
        assert isinstance(config, dict)
        assert config["name"] == f"agent_{sample_execution_request.agent_id}"
        assert config["model"] == "gpt-4"
        assert "instructions" in config
        assert sample_execution_request.task_query in config["instructions"]
        assert config["description"] == "AgentArea AI assistant"
    
    @pytest.mark.asyncio
    async def test_extract_final_response_from_events(self):
        """Test extracting final response from event list."""
        workflow = ADKAgentWorkflow()
        
        # Create sample events
        events = [
            {
                "author": "agent",
                "invocation_id": "inv1",
                "content": {"parts": [{"text": "Intermediate message"}]},
                "actions": {"skip_summarization": False},
                "id": "1",
                "timestamp": 1.0
            },
            {
                "author": "agent", 
                "invocation_id": "inv1",
                "content": {"parts": [{"text": "Final response"}]},
                "actions": {"skip_summarization": True},  # This makes it final
                "id": "2",
                "timestamp": 2.0
            }
        ]
        
        final_response = workflow._extract_final_response(events)
        
        assert final_response == "Final response"
    
    @pytest.mark.asyncio
    async def test_extract_final_response_no_final_event(self):
        """Test extracting final response when no final event exists."""
        workflow = ADKAgentWorkflow()
        
        # Create events without final response
        events = [
            {
                "author": "agent",
                "invocation_id": "inv1", 
                "content": {"parts": [{"text": "Just a message"}]},
                "actions": {"skip_summarization": False},
                "id": "1",
                "timestamp": 1.0
            }
        ]
        
        final_response = workflow._extract_final_response(events)
        
        assert final_response is None
    
    @pytest.mark.asyncio
    async def test_extract_final_response_empty_events(self):
        """Test extracting final response from empty event list."""
        workflow = ADKAgentWorkflow()
        
        final_response = workflow._extract_final_response([])
        
        assert final_response is None
    
    @pytest.mark.asyncio
    async def test_is_final_event_true(self):
        """Test detecting final events."""
        workflow = ADKAgentWorkflow()
        
        final_event_dict = {
            "author": "agent",
            "invocation_id": "inv1",
            "content": {"parts": [{"text": "Final message"}]},
            "actions": {"skip_summarization": True},
            "id": "1",
            "timestamp": 1.0
        }
        
        assert workflow._is_final_event(final_event_dict) is True
    
    @pytest.mark.asyncio
    async def test_is_final_event_false(self):
        """Test detecting non-final events."""
        workflow = ADKAgentWorkflow()
        
        non_final_event_dict = {
            "author": "agent",
            "invocation_id": "inv1",
            "content": {"parts": [{"text": "Regular message"}]},
            "actions": {"skip_summarization": False},
            "id": "1",
            "timestamp": 1.0
        }
        
        assert workflow._is_final_event(non_final_event_dict) is False
    
    @pytest.mark.asyncio
    async def test_finalize_execution_success(self, sample_execution_request):
        """Test successful workflow finalization."""
        workflow = ADKAgentWorkflow()
        
        # Initialize state
        await workflow._initialize_workflow(sample_execution_request)
        
        # Set success state
        workflow.state.success = True
        workflow.state.final_response = "Task completed successfully"
        workflow.state.events = [
            {
                "author": "agent",
                "content": {"parts": [{"text": "Hello"}]},
                "timestamp": 1.0
            }
        ]
        
        result_dict = {"event_count": 1, "success": True}
        
        execution_result = await workflow._finalize_execution(result_dict)
        
        assert isinstance(execution_result, AgentExecutionResult)
        assert execution_result.success is True
        assert execution_result.final_response == "Task completed successfully"
        assert execution_result.task_id == sample_execution_request.task_id
        assert execution_result.agent_id == sample_execution_request.agent_id
        assert execution_result.reasoning_iterations_used == 1
        assert len(execution_result.conversation_history) >= 0
    
    @pytest.mark.asyncio
    async def test_finalize_execution_failure(self, sample_execution_request):
        """Test workflow finalization with failure."""
        workflow = ADKAgentWorkflow()
        
        # Initialize state
        await workflow._initialize_workflow(sample_execution_request)
        
        # Set failure state
        workflow.state.success = False
        workflow.state.error_message = "Test error"
        workflow.state.events = []
        
        result_dict = {"event_count": 0, "success": False}
        
        execution_result = await workflow._finalize_execution(result_dict)
        
        assert isinstance(execution_result, AgentExecutionResult)
        assert execution_result.success is False
        assert execution_result.final_response == "No final response generated"
        assert execution_result.reasoning_iterations_used == 0
    
    @pytest.mark.asyncio
    async def test_handle_workflow_error(self):
        """Test workflow error handling."""
        workflow = ADKAgentWorkflow()
        
        test_error = RuntimeError("Test workflow error")
        
        await workflow._handle_workflow_error(test_error)
        
        assert workflow.state.error_message == "Test workflow error"
        assert workflow.state.success is False
    
    def test_get_current_state_query(self, sample_execution_request):
        """Test workflow state query method."""
        workflow = ADKAgentWorkflow()
        
        # Set some state
        workflow.state.execution_id = "test_execution"
        workflow.state.agent_config = {"name": "test_agent"}
        workflow.state.events = [{"event": "data"}]
        workflow.state.success = True
        workflow.state.paused = False
        workflow.state.final_response = "Done"
        
        state = workflow.get_current_state()
        
        assert isinstance(state, dict)
        assert state["execution_id"] == "test_execution"
        assert state["agent_name"] == "test_agent"
        assert state["event_count"] == 1
        assert state["success"] is True
        assert state["paused"] is False
        assert state["has_final_response"] is True
        assert state["error_message"] is None
    
    def test_get_events_query(self):
        """Test workflow events query method."""
        workflow = ADKAgentWorkflow()
        
        # Set events
        events = [{"event": i} for i in range(20)]
        workflow.state.events = events
        
        # Test with limit
        limited_events = workflow.get_events(limit=5)
        assert len(limited_events) == 5
        assert limited_events == events[-5:]  # Should get last 5
        
        # Test without limit
        all_events = workflow.get_events(limit=0)
        assert len(all_events) == 20
        assert all_events == events
        
        # Test with limit larger than available
        more_events = workflow.get_events(limit=50)
        assert len(more_events) == 20
        assert more_events == events
    
    def test_get_final_response_query(self):
        """Test workflow final response query method."""
        workflow = ADKAgentWorkflow()
        
        # Test with no response
        assert workflow.get_final_response() is None
        
        # Test with response
        workflow.state.final_response = "Test response"
        assert workflow.get_final_response() == "Test response"
    
    @pytest.mark.asyncio
    async def test_pause_resume_signals(self):
        """Test workflow pause and resume signals."""
        workflow = ADKAgentWorkflow()
        
        # Initial state - not paused
        assert workflow.state.paused is False
        assert workflow.state.pause_reason == ""
        
        # Test pause
        await workflow.pause("Test pause")
        assert workflow.state.paused is True
        assert workflow.state.pause_reason == "Test pause"
        
        # Test resume
        await workflow.resume("Test resume")
        assert workflow.state.paused is False
        assert workflow.state.pause_reason == ""
    
    def test_should_use_streaming(self):
        """Test streaming decision logic."""
        workflow = ADKAgentWorkflow()
        
        # Currently always returns False for simplicity
        assert workflow._should_use_streaming() is False
    
    @pytest.mark.asyncio
    async def test_batch_execution_result_processing(self):
        """Test processing of batch execution results."""
        workflow = ADKAgentWorkflow()
        
        # Mock events with final response
        mock_events = [
            {
                "author": "agent",
                "content": {"parts": [{"text": "Processing..."}]},
                "actions": {"skip_summarization": False},
                "id": "1",
                "timestamp": 1.0
            },
            {
                "author": "agent",
                "content": {"parts": [{"text": "Task completed"}]},
                "actions": {"skip_summarization": True},
                "id": "2", 
                "timestamp": 2.0
            }
        ]
        
        # Set events and process
        workflow.state.events = mock_events
        
        final_response = workflow._extract_final_response(mock_events)
        assert final_response == "Task completed"
        
        # Verify state updates
        if final_response:
            workflow.state.final_response = final_response
            workflow.state.success = True
        
        assert workflow.state.success is True
        assert workflow.state.final_response == "Task completed"